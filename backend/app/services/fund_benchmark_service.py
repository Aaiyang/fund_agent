"""业绩比较基准：原文与构成始终给，相对指标只在成分指数全部可查时给."""

from app.analytics.returns import NavPoint
from app.analytics.risk_metrics import (
    AlignedSeries,
    align_series,
    alpha,
    annual_returns,
    beta,
    excess_return,
    tracking_error,
    weighted_benchmark_series,
)
from app.core.logging import logger
from app.integrations.valuation.benchmark import BenchmarkPlan, parse_benchmark
from app.schemas.fund import NavRange
from app.schemas.fund_benchmark import BenchmarkAnnualRow, BenchmarkPartItem, FundBenchmarkData
from app.services.fund_analysis_service import normalize_points
from app.services.fund_service import fund_service
from app.services.market_service import BENCHMARK_INDEXES, market_service
from app.services.valuation_service import valuation_service
from app.utils.clock import business_today, range_start
from app.utils.market_quote_policy import finite_number

# 名称到代码只在这份硬编码目录里查：调用方可控的字符串永远不会传进第三方客户端。
_INDEX_CODES = {name: code for code, name in BENCHMARK_INDEXES.items()}
_DEFAULT_RANGE: NavRange = "3y"
_STALE_DAYS = 7
_MIN_ALIGNED_DAYS = 120


class FundBenchmarkService:
    """只读公开基准原文与指数收盘；不接收也不缓存任何本人持仓."""

    async def get_data(self, fund_code: str, range_key: NavRange = _DEFAULT_RANGE) -> FundBenchmarkData:
        """基准读不懂或成分指数不在目录内时，只给原文与构成，不编造相对指标."""
        text = await valuation_service.benchmark_text(fund_code)
        plan = parse_benchmark(text)
        data = FundBenchmarkData(
            fund_code=fund_code,
            range_key=range_key,
            benchmark_text=text,
            parseable=plan.parseable,
            parts=[
                BenchmarkPartItem(
                    index_name=part.index_name,
                    weight_pp=part.weight,
                    index_code=_INDEX_CODES.get(part.index_name),
                )
                for part in plan.parts
            ],
            cash_weight_pp=plan.cash_weight,
            has_offshore_index=plan.has_offshore_index,
            fx_adjusted=plan.fx_adjusted,
            warnings=[
                "基准原文是基金公司自己的表述，权重单位为百分点；比值 0.1 表示 10%。",
                "基准里含境外指数时，其净值口径与 A 股交易日不同，跨市场比较要说明这一点。",
            ],
        )
        if not text:
            return self._stop(data, "档案页没有取到业绩比较基准原文，无法判断跟踪对象。")
        if not plan.parseable or not plan.parts:
            return self._stop(data, "业绩比较基准原文读不懂或缺少指数段，只给原文与构成，不给相对指标。")
        missing = sorted({item.index_name for item in data.parts if item.index_code is None})
        if missing:
            return self._stop(
                data,
                "基准成分指数不在可查目录内：" + "、".join(missing) + "；缺一段就不再是那条基准，不给相对指标。",
            )
        return await self._relative_metrics(data, plan, fund_code, range_key)

    async def _relative_metrics(
        self, data: FundBenchmarkData, plan: BenchmarkPlan, fund_code: str, range_key: NavRange
    ) -> FundBenchmarkData:
        """对齐基金净值与合成基准，算超额、beta、alpha、跟踪误差与分年度对照."""
        end = business_today()
        start = range_start(range_key, end) or end
        history = await fund_service.get_nav_history(fund_code, start_date=start, end_date=end)
        if history.fund_code != fund_code:
            raise ValueError("benchmark history fund code mismatch")
        fund_points, invalid, _duplicate, conflict = normalize_points(history.points, start, end)
        if invalid or conflict:
            data.warnings.append("无效或同日冲突的净值已排除，相对指标只基于剩余样本。")

        series: dict[str, list[NavPoint]] = {}
        for part in plan.parts:
            code = _INDEX_CODES.get(part.index_name)
            response = await market_service.get_history(code, range_key) if code else None
            if response is None:
                return self._stop(data, "指数收盘序列不可用：" + part.index_name + "，不给相对指标。")
            series[part.index_name] = [
                NavPoint(point.trade_date, point.close) for point in response.points if point.close and point.close > 0
            ]
            if not series[part.index_name]:
                return self._stop(data, "指数收盘序列为空：" + part.index_name + "，不给相对指标。")

        benchmark_points = weighted_benchmark_series(
            [(part.index_name, part.weight) for part in plan.parts], series, plan.cash_weight
        )
        aligned = align_series(fund_points, benchmark_points)
        if len(aligned.fund) < 2:
            return self._stop(data, "基金净值与基准指数的共同交易日不足两天，不给相对指标。")

        data.observed_from = aligned.fund[0].date
        data.observed_to = aligned.fund[-1].date
        data.aligned_days = len(aligned.fund)
        data.fund_return_ratio = finite_number(aligned.fund[-1].nav / aligned.fund[0].nav - 1)
        data.benchmark_return_ratio = finite_number(aligned.benchmark[-1].nav / aligned.benchmark[0].nav - 1)
        data.excess_return_ratio = excess_return(aligned)
        data.beta = beta(aligned)
        data.alpha_ratio = alpha(aligned)
        data.tracking_error_ratio = tracking_error(aligned)
        data.annual = _annual_rows(aligned)
        data.stale = (end - aligned.fund[-1].date).days > _STALE_DAYS
        data.warnings.extend(
            [
                "基准是按权重合成的指数净值（现金段按 0 收益），不是基金公司公布的基准净值序列。",
                "相对指标基于未复权单位净值与指数收盘价，不含分红与费用，不是投资者总回报。",
                "alpha 按无风险利率 0 计算；系统里没有可信的无风险利率来源。",
            ]
        )
        if data.aligned_days < _MIN_ALIGNED_DAYS:
            data.warnings.append(
                f"共同交易日不足 {_MIN_ALIGNED_DAYS} 天，beta/alpha/跟踪误差为空，只给区间收益与收益差。"
            )
        if data.stale:
            data.warnings.append(f"最近净值距业务今天超过 {_STALE_DAYS} 个自然日，不能当作今日表现。")
        logger.info(
            "fund_benchmark_metrics_ready",
            fund_code=fund_code,
            range_key=range_key,
            aligned_days=data.aligned_days,
            has_beta=data.beta is not None,
        )
        return data

    @staticmethod
    def _stop(data: FundBenchmarkData, reason: str) -> FundBenchmarkData:
        """记录为什么没有相对指标；原文与构成仍然可用，不让缺口看起来像 0."""
        data.unavailable_reason = reason
        data.warnings.append(reason)
        logger.info("fund_benchmark_metrics_unavailable", fund_code=data.fund_code, reason=reason)
        return data


def _annual_rows(series: AlignedSeries) -> list[BenchmarkAnnualRow]:
    """基金与基准的分年度收益对照；某一年只有一侧有数据就不给收益差."""
    fund = {row.year: row for row in annual_returns(series.fund)}
    benchmark = {row.year: row for row in annual_returns(series.benchmark)}
    return [
        BenchmarkAnnualRow(
            year=year,
            fund_ratio=fund[year].ratio if year in fund else None,
            benchmark_ratio=benchmark[year].ratio if year in benchmark else None,
            excess_ratio=finite_number(fund[year].ratio - benchmark[year].ratio)
            if year in fund and year in benchmark
            else None,
            full_year=year in fund and year in benchmark and fund[year].full_year and benchmark[year].full_year,
        )
        for year in sorted(set(fund) | set(benchmark))
    ]


fund_benchmark_service = FundBenchmarkService()
