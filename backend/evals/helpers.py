"""评测流程用到的辅助函数：抽取输入输出、累计指标、生成报告."""

import json
import os
from datetime import datetime
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from langfuse.api.resources.commons.types.trace_with_details import TraceWithDetails

from app.core.logging import logger
from evals.schemas import ScoreSchema


def format_messages(messages: list[dict]) -> str:
    """把一组消息格式化成评测用的文本.

    Args:
        messages: 消息字典列表。

    Returns:
        格式化后的消息字符串。
    """
    formatted_messages = []
    for idx, message in enumerate(messages):
        if message["type"] == "tool":
            previous_message = messages[idx - 1]
            tool_call = previous_message.get("additional_kwargs", {}).get("tool_calls", [])
            if tool_call:
                args = tool_call[0].get("function", {}).get("arguments")
            else:
                prev_tool_calls = previous_message.get("tool_calls")
                args = prev_tool_calls[0].get("args") if prev_tool_calls else {}
            content = message.get("content") or ""
            formatted_messages.append(
                f"tool {message.get('name')} input: {args} {content[:100]}..."
                if len(content) > 100
                else f"tool {message.get('name')}: {content}"
            )
        elif message["content"]:
            formatted_messages.append(f"{message['type']}: {message['content']}")
    return "\n".join(formatted_messages)


def get_input_output(trace: TraceWithDetails) -> Tuple[Optional[str], Optional[str]]:
    """从 trace 中取出并格式化输入消息与最终输出.

    Args:
        trace: 要取消息的 trace。

    Returns:
        (格式化后的输入, 格式化后的输出)；trace 的 output 不是 dict 时返回 (None, None)。
    """
    if not isinstance(trace.output, dict):
        return None, None
    input_messages = trace.output.get("messages", [])[:-1]
    output_message = trace.output.get("messages", [])[-1]
    return format_messages(input_messages), format_messages([output_message])


def initialize_report(model_name: str) -> Dict[str, Any]:
    """初始化报告的数据结构.

    Args:
        model_name: 被评测的模型名。

    Returns:
        含各统计字段的初始报告 dict。
    """
    return {
        "timestamp": datetime.now().isoformat(),
        "model": model_name,
        "total_traces": 0,
        "successful_traces": 0,
        "failed_traces": 0,
        "duration_seconds": 0,
        "metrics_summary": {},
        "successful_traces_details": [],
        "failed_traces_details": [],
    }


def initialize_metrics_summary(report: Dict[str, Any], metrics: List[Dict[str, str]]) -> None:
    """在报告里为每个指标建好统计槽位.

    Args:
        report: 报告 dict。
        metrics: 指标定义列表。
    """
    for metric in metrics:
        report["metrics_summary"][metric["name"]] = {"success_count": 0, "failure_count": 0, "avg_score": 0.0}


def update_success_metrics(
    report: Dict[str, Any], trace_id: str, metric_name: str, score: ScoreSchema, trace_results: Dict[str, Any]
) -> None:
    """记录一次评测成功：累加成功次数并把分数计入均值.

    Args:
        report: 报告 dict。
        trace_id: 被评测的 trace ID。
        metric_name: 指标名。
        score: 评分对象。
        trace_results: 保存各 trace 结果的 dict。
    """
    trace_results[trace_id]["metrics_succeeded"] += 1
    trace_results[trace_id]["metrics_results"][metric_name] = {
        "success": True,
        "score": score.score,
        "reasoning": score.reasoning,
    }
    report["metrics_summary"][metric_name]["success_count"] += 1
    report["metrics_summary"][metric_name]["avg_score"] += score.score


def update_failure_metrics(
    report: Dict[str, Any], trace_id: str, metric_name: str, trace_results: Dict[str, Any]
) -> None:
    """记录一次评测失败：只累加失败次数，不计分.

    Args:
        report: 报告 dict。
        trace_id: 被评测的 trace ID。
        metric_name: 指标名。
        trace_results: 保存各 trace 结果的 dict。
    """
    trace_results[trace_id]["metrics_results"][metric_name] = {"success": False}
    report["metrics_summary"][metric_name]["failure_count"] += 1


def process_trace_results(
    report: Dict[str, Any], trace_id: str, trace_results: Dict[str, Any], metrics_count: int
) -> None:
    """结算单条 trace：全部指标都成功才算这条 trace 成功.

    Args:
        report: 报告 dict。
        trace_id: 被评测的 trace ID。
        trace_results: 保存各 trace 结果的 dict。
        metrics_count: 指标总数。
    """
    if trace_results[trace_id]["metrics_succeeded"] == metrics_count:
        trace_results[trace_id]["success"] = True
        report["successful_traces"] += 1
        report["successful_traces_details"].append(
            {"trace_id": trace_id, "metrics_results": trace_results[trace_id]["metrics_results"]}
        )
    else:
        report["failed_traces"] += 1
        report["failed_traces_details"].append(
            {
                "trace_id": trace_id,
                "metrics_evaluated": trace_results[trace_id]["metrics_evaluated"],
                "metrics_succeeded": trace_results[trace_id]["metrics_succeeded"],
                "metrics_results": trace_results[trace_id]["metrics_results"],
            }
        )


def calculate_avg_scores(report: Dict[str, Any]) -> None:
    """用成功评测的次数求出各指标的平均分.

    Args:
        report: 报告 dict。
    """
    for _, data in report["metrics_summary"].items():
        if data["success_count"] > 0:
            data["avg_score"] = round(data["avg_score"] / data["success_count"], 2)


def generate_report(report: Dict[str, Any]) -> str:
    """把评测结果写成 JSON 报告文件.

    Args:
        report: 报告 dict。

    Returns:
        str: 生成的报告文件路径。
    """
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(report_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"evaluation_report_{timestamp}.json")

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # 把报告文件路径也放回报告数据，方便调用方引用
    report["generate_report_path"] = report_path

    logger.info("evaluation_report_generated", report_path=report_path)
    return report_path
