"""复用异步净值服务，输出紧凑对比证据，不向模型传输历史序列."""

import asyncio
import calendar
from bisect import bisect_right
from datetime import date

from app.analytics.fund_comparison import aligned_nav_metrics
from app.analytics.returns import NavPoint
from app.core.logging import logger
from app.repositories.fund_repository import fund_repository
from app.schemas.fund_analysis import FundChartReference
from app.schemas.fund_comparison import (
    FundComparisonData,
    FundComparisonPeriodReturns,
    FundComparisonPoint,
    FundComparisonRequest,
    FundComparisonSeriesFund,
    FundComparisonSeriesRequest,
    FundComparisonSeriesResponse,
)
from app.services.fund_analysis_service import normalize_points
from app.services.fund_service import fund_service
from app.utils.clock import business_today, range_start

_HISTORY_TIMEOUT = 7  # 最多三次读取仍低于研究子图单工具25秒期限。


def _months_before(day: date, months: int) -> date:
    """按自然月回退，短月夹到月末；只用于阶段收益的起算日."""
    month = day.month - months
    year = day.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def _period_return(common: list[date], values: dict[date, float], months: int) -> float | None:
    """用共同日期上不晚于目标日的最后一个点；窗口覆盖不足时返回 None."""
    if len(common) < 2:
        return None
    index = bisect_right(common, _months_before(common[-1], months)) - 1
    if index < 0 or index >= len(common) - 1:
        return None
    start = values[common[index]]
    end = values[common[-1]]
    return end / start - 1


class FundComparisonService:
    """读取最多三只基金；个别故障仍返回各对象的可用范围和明确缺口."""

    async def _load_series(
        self, fund_codes: list[str], start: date, end: date
    ) -> tuple[dict[str, list[NavPoint]], dict[str, bool], dict[str, list[str]]]:
        """串行读取每只基金的净值并保留质量标记；失败基金不拖垮其余对象."""
        series: dict[str, list[NavPoint]] = {}
        quality: dict[str, bool] = {}
        per_fund_gaps: dict[str, list[str]] = {}
        # 串行仓储调用避免继承事务作用域时并发共用AsyncSession。
        # 外层研究子图仍可并发获取概况、经理及披露持仓。
        for code in fund_codes:
            series[code], quality[code], per_fund_gaps[code] = [], False, []
            try:
                async with asyncio.timeout(_HISTORY_TIMEOUT):
                    history = await fund_service.get_nav_history(code, start_date=start, end_date=end)
                if history.fund_code != code:
                    raise ValueError("history fund code mismatch")
                capped = len(history.points) > 1000
                considered = sorted(history.points, key=lambda row: row.nav_date)[-1000:]
                points, invalid, duplicate, conflict = normalize_points(considered, start, end)
                series[code] = points
                quality[code] = not (invalid or conflict or capped or history.has_more)
                if invalid or conflict:
                    per_fund_gaps[code].append("无效或同日冲突净值已排除")
                if capped or history.has_more:
                    per_fund_gaps[code].append("净值来源或处理条数被截断")
                if not points:
                    per_fund_gaps[code].append("没有有效净值")
                elif (points[0].date - start).days > 10:
                    per_fund_gaps[code].append("未覆盖近一年请求起点，只能比较实际共同窗口")
                if duplicate:
                    logger.info("fund_comparison_duplicate_dates_removed", fund_code=code, count=duplicate)
            except Exception:
                logger.exception("fund_comparison_history_failed", fund_code=code)
                per_fund_gaps[code].append("净值历史读取失败，未进行完整对象量化比较")
        return series, quality, per_fund_gaps

    async def get_data(self, request: FundComparisonRequest) -> FundComparisonData:
        """以同一业务日期读取净值，失败仍保留对象与不可比较状态."""
        end = business_today()
        start = range_start("1y", end) or end
        series, quality, per_fund_gaps = await self._load_series(request.fund_codes, start, end)

        common, calculated = aligned_nav_metrics(series, quality)
        rows = []
        gaps = []
        if len(common) < 2:
            gaps.append("全部对比对象没有至少两个共同有效净值日期，无法统一窗口量化比较")
        common_stale = len(common) >= 2 and (end - common[-1]).days > 7
        if common_stale:
            gaps.append("共同比较窗口截止日期距业务今天超过7个自然日")
        for code in request.fund_codes:
            points = series[code]
            row = calculated[code]
            row.valid_daily_count = len(points)
            row.observed_from = points[0].date if points else None
            row.observed_to = points[-1].date if points else None
            row.stale = bool(points and (end - points[-1].date).days > 7)
            row.gaps = [*per_fund_gaps[code], *row.gaps]
            if row.stale:
                row.gaps.append("最新净值距业务今天超过7个自然日")
            if len(points) >= 2:
                reference = FundChartReference(fund_code=code)
                row.chart_code_block = "```fund-chart\n" + reference.model_dump_json() + "\n```"
            gaps.extend(code + ":" + gap for gap in row.gaps)
            rows.append(row)
        logger.info("fund_comparison_completed", fund_count=len(rows), common_count=len(common), gap_count=len(gaps))
        return FundComparisonData(
            status="unavailable" if len(common) < 2 else "partial" if gaps else "completed",
            requested_from=start,
            requested_to=end,
            common_from=common[0] if len(common) >= 2 else None,
            common_to=common[-1] if len(common) >= 2 else None,
            common_count=len(common),
            stale=common_stale or any(row.stale for row in rows),
            rows=rows,
            gaps=gaps,
            warnings=[
                "所有变化与风险基于未复权单位净值，不是含分红和费用的总回报；不可据此判断A/C费用优劣。",
                "共同窗口只对齐日期，不证明类型、币种、交易日历或投资目标可比，不提供综合排名和预测。",
                "观察回撤仅描述实际日点；回撤峰谷日期同样只描述这段共同窗口。单基金图表卡片独立查询各基金；"
                "同期收益对比图由客户端按本次共同窗口重取对齐序列，不是各基金各自区间的拼接。",
                "夏普与索提诺按无风险利率 0 计算（字段名以 _rf0 标明），不是用真实无风险利率算出的。",
            ],
        )

    async def get_series(self, request: FundComparisonSeriesRequest) -> FundComparisonSeriesResponse:
        """只在报告已经确定的共同窗口内重取对齐序列，不重新选窗口."""
        start, end = request.from_date, request.to_date
        series, quality, per_fund_gaps = await self._load_series(request.fund_codes, start, end)
        common, _ = aligned_nav_metrics(series, quality)
        names = await fund_repository.get_funds(request.fund_codes)
        funds: list[FundComparisonSeriesFund] = []
        gaps: list[str] = []
        if len(common) < 2:
            gaps.append("固定共同窗口内没有至少两个共同有效净值日期，无法绘制对比曲线")
        for code in request.fund_codes:
            points = series[code]
            values = {point.date: point.nav for point in points}
            changes = []
            if len(common) >= 2:
                base = values[common[0]]
                changes = [FundComparisonPoint(nav_date=day, change_ratio=values[day] / base - 1) for day in common]
            fund_gaps = list(per_fund_gaps[code])
            if not points:
                fund_gaps.append("没有有效净值")
            gaps.extend(code + ":" + gap for gap in fund_gaps)
            fund = names.get(code)
            funds.append(
                FundComparisonSeriesFund(
                    fund_code=code,
                    fund_name=fund.fund_name if fund is not None else None,
                    points=changes,
                    period_returns=FundComparisonPeriodReturns(
                        return_1m=_period_return(common, values, 1),
                        return_3m=_period_return(common, values, 3),
                        return_6m=_period_return(common, values, 6),
                        return_1y=_period_return(common, values, 12),
                    ),
                )
            )
        logger.info(
            "fund_comparison_series_built",
            fund_count=len(funds),
            common_count=len(common),
            gap_count=len(gaps),
        )
        return FundComparisonSeriesResponse(
            common_from=common[0] if len(common) >= 2 else None,
            common_to=common[-1] if len(common) >= 2 else None,
            aligned_count=len(common),
            funds=funds,
            gaps=gaps,
            warnings=[
                "曲线按报告的共同窗口重取，以该窗口首个共同净值为 0% 定基；未复权单位净值，不是含分红和费用的总回报。",
                "共同窗口只对齐日期，不证明基金类型、币种或投资目标可比。",
            ],
        )


fund_comparison_service = FundComparisonService()
