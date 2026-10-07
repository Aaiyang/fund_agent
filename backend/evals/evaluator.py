"""LLM 评测执行器：取 trace、按指标打分并回写 Langfuse."""

import os
import sys
import time
from datetime import (
    datetime,
    timedelta,
)
from time import sleep

import openai
from langfuse import Langfuse
from langfuse.api.resources.commons.types.trace_with_details import TraceWithDetails
from tqdm import tqdm

# 修正 app 包的导入路径（把 backend/ 目录加进 sys.path）
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings
from app.core.logging import logger
from evals.helpers import (
    calculate_avg_scores,
    generate_report,
    get_input_output,
    initialize_metrics_summary,
    initialize_report,
    process_trace_results,
    update_failure_metrics,
    update_success_metrics,
)
from evals.metrics import metrics
from evals.schemas import ScoreSchema


class Evaluator:
    """用预定义指标给模型输出打分的评测器.

    负责从 Langfuse 拉取 trace、逐条按各指标评测，再把评分回写到 Langfuse。

    Attributes:
        client: 调用评分模型用的 OpenAI 客户端。
        langfuse: 管理 trace 与评分回写的 Langfuse 客户端。
    """

    def __init__(self):
        """用 OpenAI 与 Langfuse 客户端初始化评测器."""
        self.client = openai.AsyncOpenAI(api_key=settings.EVALUATION_API_KEY, base_url=settings.EVALUATION_BASE_URL)
        self.langfuse = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            timeout=60,  # 单位：秒
        )
        # 初始化报告的数据结构
        self.report = initialize_report(settings.EVALUATION_LLM)
        initialize_metrics_summary(self.report, metrics)

    async def run(self, generate_report_file=True):
        """主流程：取 trace、按指标评测并汇总结果.

        从 Langfuse 取出待评 trace，对每条依次套用全部指标，再把评分回写到 Langfuse。

        Args:
            generate_report_file: 评测结束后是否生成 JSON 报告文件，默认 True。
        """
        start_time = time.time()
        traces = self.__fetch_traces()
        self.report["total_traces"] = len(traces)

        trace_results = {}

        for trace in tqdm(traces, desc="Evaluating traces"):
            trace_id = trace.id
            trace_results[trace_id] = {
                "success": False,
                "metrics_evaluated": 0,
                "metrics_succeeded": 0,
                "metrics_results": {},
            }

            for metric in tqdm(metrics, desc=f"Applying metrics to trace {trace_id[:8]}...", leave=False):
                metric_name = metric["name"]
                input, output = get_input_output(trace)
                if input is None or output is None:
                    update_failure_metrics(self.report, trace_id, metric_name, trace_results)
                    trace_results[trace_id]["metrics_evaluated"] += 1
                    continue
                score = await self._run_metric_evaluation(metric, input, output)

                if score:
                    self._push_to_langfuse(trace, score, metric)
                    update_success_metrics(self.report, trace_id, metric_name, score, trace_results)
                else:
                    update_failure_metrics(self.report, trace_id, metric_name, trace_results)

                trace_results[trace_id]["metrics_evaluated"] += 1

            process_trace_results(self.report, trace_id, trace_results, len(metrics))
            sleep(settings.EVALUATION_SLEEP_TIME)

        self.report["duration_seconds"] = round(time.time() - start_time, 2)
        calculate_avg_scores(self.report)

        if generate_report_file:
            generate_report(self.report)

        logger.info(
            "evaluation_completed",
            total_traces=self.report["total_traces"],
            successful_traces=self.report["successful_traces"],
            failed_traces=self.report["failed_traces"],
            duration_seconds=self.report["duration_seconds"],
        )

    def _push_to_langfuse(self, trace: TraceWithDetails, score: ScoreSchema, metric: dict):
        """把一条评分写回 Langfuse.

        Args:
            trace: 被打分的那条 trace。
            score: 评分结果（分数 + 理由）。
            metric: 本次评测所用的指标定义。
        """
        self.langfuse.create_score(
            trace_id=trace.id,
            name=metric["name"],
            data_type="NUMERIC",
            value=score.score,
            comment=score.reasoning,
        )

    async def _run_metric_evaluation(self, metric: dict, input: str, output: str) -> ScoreSchema | None:
        """用单个指标评测一条 trace.

        Args:
            metric: 本次使用的指标定义。
            input: 待评的输入内容。
            output: 待评的输出内容。

        Returns:
            评分结果 ScoreSchema；评测未成功则返回 None。
        """
        metric_name = metric["name"]
        if not metric:
            logger.error("metric_not_found", metric_name=metric_name)
            return None
        system_metric_prompt = metric["prompt"]

        if not input or not output:
            logger.error(
                "metric_evaluation_failed_missing_io",
                metric_name=metric_name,
                has_input=bool(input),
                has_output=bool(output),
            )
            return None
        score = await self._call_openai(system_metric_prompt, input, output)
        if score:
            logger.info(
                "metric_evaluation_completed",
                metric_name=metric_name,
                score=score.score,
                reasoning=score.reasoning,
            )
        else:
            logger.error("metric_evaluation_failed", metric_name=metric_name)
        return score

    async def _call_openai(self, metric_system_prompt: str, input: str, output: str) -> ScoreSchema | None:
        """调用评分模型（OpenAI 兼容接口）给一条 trace 打分.

        Args:
            metric_system_prompt: 描述该指标口径的系统提示词。
            input: 格式化后的输入消息。
            output: 格式化后的输出消息。

        Returns:
            评分结果 ScoreSchema；接口调用失败则返回 None。
        """
        num_retries = 3
        for _ in range(num_retries):
            try:
                response = await self.client.beta.chat.completions.parse(
                    model=settings.EVALUATION_LLM,
                    messages=[
                        {"role": "system", "content": metric_system_prompt},
                        {"role": "user", "content": f"Input: {input}\nGeneration: {output}"},
                    ],
                    response_format=ScoreSchema,
                )
                return response.choices[0].message.parsed
            except Exception as e:
                SLEEP_TIME = 10
                logger.error(
                    "openai_evaluation_call_failed",
                    error=str(e),
                    sleep_seconds=SLEEP_TIME,
                )
                sleep(SLEEP_TIME)
                continue
        return None

    def __fetch_traces(self) -> list[TraceWithDetails]:
        """取最近 24 小时内还没有评分的 trace.

        Returns:
            尚未被打过分的 trace 列表。
        """
        last_24_hours = datetime.now() - timedelta(hours=24)
        logger.info("fetching_langfuse_traces", from_timestamp=str(last_24_hours))
        try:
            traces = self.langfuse.api.trace.list(
                from_timestamp=last_24_hours, order_by="timestamp.asc", limit=100
            ).data
            traces_without_scores = [trace for trace in traces if not trace.scores]
            return traces_without_scores
        except Exception as e:
            logger.error("langfuse_traces_fetch_failed", error=str(e))
            return []
