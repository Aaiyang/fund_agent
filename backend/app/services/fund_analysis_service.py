"""公开近一年净值分析；不接收或缓存本人持仓/成本."""

from datetime import date

from app.analytics.fund_analysis import nav_metrics, weekly_chart_points
from app.analytics.returns import NavPoint
from app.schemas.fund import FundNavPoint
from app.schemas.fund_analysis import FundAnalysisData, FundAnalysisRequest, FundNavChart
from app.services.fund_service import fund_service
from app.utils.clock import business_today, range_start
from app.utils.market_quote_policy import finite_number


def normalize_points(rows: list[FundNavPoint], start: date, end: date) -> tuple[list[NavPoint], int, int, int]:
    """去掉无效/越界点，同日冲突整日排除，不能任意择一当事实."""
    values: dict[date, float] = {}
    conflicts: set[date] = set()
    invalid, duplicate = 0, 0
    for row in rows:
        nav = finite_number(row.unit_nav)
        if nav is None or nav <= 0 or not start <= row.nav_date <= end:
            invalid += 1
            continue
        if row.nav_date in conflicts:
            duplicate += 1
        elif row.nav_date not in values:
            values[row.nav_date] = nav
        elif values[row.nav_date] != nav:
            conflicts.add(row.nav_date)
            values.pop(row.nav_date)
        else:
            duplicate += 1
    return [NavPoint(day, values[day]) for day in sorted(values)], invalid, duplicate, len(conflicts)


class FundAnalysisService:
    """复用异步基金领域服务，财务计算与采样均在Python执行."""

    async def get_data(self, request: FundAnalysisRequest) -> FundAnalysisData:
        """返回指标及图表，明确短窗口/缺日/旧日/异常，不补造一年数据."""
        end = business_today()
        start = range_start("1y", end) or end
        history = await fund_service.get_nav_history(request.fund_code, start_date=start, end_date=end)
        if history.fund_code != request.fund_code:
            raise ValueError("history fund code mismatch")
        rows = history.points
        # 一年超过千点不应发生；有界处理，不让异常数据撑爆图表或上下文。
        capped = len(rows) > 1000
        considered = sorted(rows, key=lambda row: row.nav_date)[-1000:] if capped else rows
        points, invalid, duplicate, conflict = normalize_points(considered, start, end)
        source_truncated = history.has_more or capped
        covered = bool(points and (points[0].date - start).days <= 10)
        stale = bool(points and (end - points[-1].date).days > 7)
        max_gap = max(
            ((right.date - left.date).days for left, right in zip(points, points[1:], strict=False)), default=None
        )
        daily_quality = not (invalid or conflict or source_truncated) and (max_gap is None or max_gap <= 14)
        partial = not covered or not daily_quality or stale or len(points) < 2
        warnings = [
            "图与指标基于未复权单位净值，不等于含分红/费用的投资者总回报；分红可使净值下降。",
            "指标使用采样前可用日点；观察样本极值不保证完整历史极值。range_position_ratio是高低区间线性位置，不是估值分位。",
        ]
        if not covered:
            warnings.append("实际数据没有覆盖一年窗口起点，不能声称已取得完整一年走势；可能是新发基金或历史缺失。")
        if stale:
            warnings.append("最近净值距业务今天超过7个自然日，回答需标明实际日期，不能当作今日净值。")
        if invalid or conflict:
            warnings.append("无效/越界或同日冲突数据已排除，极值与变化仅为剩余样本。")
        if source_truncated:
            warnings.append("来源历史或处理条数被截断，不能称为完整区间。")
        if duplicate:
            warnings.append("相同日期重复记录已去重，未增加有效样本数。")
        if max_gap is not None and max_gap > 14:
            warnings.append("相邻净值间隔超过14个自然日，存在历史缺口，未推定缺口期间走势。")
        metrics = nav_metrics(points, daily_quality=daily_quality)
        if metrics.sharpe_ratio_rf0 is not None:
            warnings.append("夏普与索提诺按无风险利率 0 计算（字段名以 _rf0 标明），不是用真实无风险利率算出的。")
        if metrics.max_drawdown_peak_date is not None:
            warnings.append("回撤峰谷日期只描述观察样本内的这一段，不代表完整历史的最差区间。")
        if metrics.annualized_nav_volatility_ratio is None:
            warnings.append(
                "日点不足120或存在质量问题，未提供年化波动率、夏普、索提诺与下行波动；不以周采样计算年化风险。"
            )
        chart = None
        if len(points) >= 2:
            chart = FundNavChart(
                fund_code=request.fund_code,
                title=request.fund_code + " 近一年单位净值（实际可用区间）",
                requested_from=start,
                requested_to=end,
                observed_from=points[0].date,
                observed_to=points[-1].date,
                as_of=points[-1].date,
                points=weekly_chart_points(points),
                warnings=warnings,
            )
        else:
            warnings.append("有效净值不足两个日期，不能生成走势图。")
        return FundAnalysisData(
            fund_code=request.fund_code,
            requested_from=start,
            requested_to=end,
            observed_from=points[0].date if points else None,
            observed_to=points[-1].date if points else None,
            raw_count=len(rows),
            valid_daily_count=len(points),
            invalid_count=invalid,
            duplicate_count=duplicate,
            conflict_count=conflict,
            max_gap_days=max_gap,
            window_start_covered=covered,
            source_truncated=source_truncated,
            partial=partial,
            stale=stale,
            metrics=metrics,
            chart=chart,
            warnings=warnings,
        )


fund_analysis_service = FundAnalysisService()
