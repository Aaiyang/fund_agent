"""估值编排：定口径、取数、算数，并把"为什么没给"一起带回去.

分工与本模块不做的事：

- `integrations/valuation/*` 只取外部事实（基准原文、指数与个股行情、披露持仓）；
- `analytics/valuation.py` 只做纯算术与口径判定；
- 本模块只做编排、并发与缓存，不做任何算术，也不把"估不出来"当错误抛出。

估值是派生指标，按项目口径**不落库**：每次请求现算。唯一存下来的是它的输入
（业绩比较基准原文），那是外部事实而不是我们算出来的数。
"""

import asyncio
import re
from collections.abc import Mapping, Sequence
from datetime import date

from app.analytics.valuation import HoldingWeight, benchmark_change, choose_method, penetration_change
from app.core.logging import logger
from app.integrations.valuation.benchmark import BenchmarkPlan, parse_benchmark
from app.integrations.valuation.profile import fetch_benchmark_text
from app.models.fund import Fund
from app.repositories.fund_repository import fund_repository
from app.repositories.valuation_repository import valuation_repository
from app.schemas.fund import FundHoldingsResponse
from app.schemas.market import IndexQuoteItem
from app.schemas.valuation import FundEstimateItem, ValuationEstimatesResponse
from app.services.fund_service import fund_service
from app.services.market_service import market_service
from app.utils.clock import utc_now

# 上游调用都带节流，但一次请求里也别把并发打满。
_FETCH_CONCURRENCY = 5

# 名称里出现这些词基本就是境外口径的基金。单看名称不可靠（会漏），所以它只是
# `_is_offshore_calendar` 三条证据之一。
_OFFSHORE_NAME_TOKENS = (
    "QDII",
    "纳指",
    "纳斯达克",
    "标普",
    "道琼斯",
    "恒生",
    "日经",
    "东证",
    "中概",
    "亚太",
    "全球",
    "美国",
    "德国",
    "法国",
    "英国",
)


def _is_offshore_calendar(fund: Fund | None, plan: BenchmarkPlan) -> bool:
    """判断这只基金的净值是不是跟着境外收盘出的——是的话就不给盘中估值.

    三条证据取并集，因为任何一条单独都不可靠：`fund_type` 最准但库里多数行是 NULL
    （539001 建信纳斯达克100(QDII)A人民币 就没有类型）；名称关键词覆盖率高但会漏；
    基准里权重最大的那条指数在境外，是三者里最稳的信号。

    反过来，"基准里出现了恒生"不能作为否决理由：A 股主动基金常配 10%~20% 的港股
    基准，它们的主口径仍在 A 股，穿透照样能估。
    """
    if plan.dominant_offshore:
        return True
    if fund is None:
        return False
    if str(fund.fund_type or "").upper().startswith("QDII"):
        return True
    name = str(fund.fund_name or "").upper()
    return any(token.upper() in name for token in _OFFSHORE_NAME_TOKENS)


def _benchmark_ready(plan: BenchmarkPlan, quotes: Mapping[str, IndexQuoteItem]) -> bool:
    """基准的每一条指数都能取到价，才认为基准法可用.

    缺一块就不是那条基准了：按剩下的几段加权会系统性偏掉，所以这里要求全齐，
    而不是把缺的那段当 0。
    """
    if not plan.parseable or not plan.parts:
        return False
    return all(part.index_name in quotes and quotes[part.index_name].change_pct is not None for part in plan.parts)


_QUOTE_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _latest_quote_date(quote_times: Sequence[str]) -> date | None:
    """从持仓行情快照时间里取最晚的一个日期.

    上游这个字段格式因市场而异（A 股是 "2026-09-30 15:00:00"，港股与美股各有写法），
    所以只认第一个能看出来的年月日；一个都认不出就返回 None，不拿"今天"顶替——
    节假日里"今天"恰恰是错的答案。
    """
    days: list[date] = []
    for text in quote_times:
        match = _QUOTE_DATE.search(text)
        if match is None:
            continue
        try:
            days.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    return max(days, default=None)


def estimate_one(
    fund_code: str,
    *,
    fund: Fund | None,
    plan: BenchmarkPlan,
    quotes: Mapping[str, IndexQuoteItem],
    holdings: FundHoldingsResponse | None,
) -> FundEstimateItem:
    """给一只基金定口径并算出估值.

    没有依据时返回 `available=False` 并带上原因码，而不是 0.0 或异常：界面对
    None 显示 `--`，而 0.0 会被读成"今天没涨没跌"这个事实。
    """
    if fund is None:
        return FundEstimateItem(fund_code=fund_code, reason="fund_not_found")

    usable: list[tuple[str, float, float]] = []
    quote_times: list[str] = []
    for item in holdings.items if holdings else []:
        symbol = item.symbol or item.stock_code
        if item.weight is None or item.change_pct is None or not symbol:
            continue
        usable.append((symbol, item.weight, item.change_pct))
        if item.quote_time:
            quote_times.append(item.quote_time)
    coverage = sum(weight for _, weight, _ in usable)
    ready = _benchmark_ready(plan, quotes)
    offshore = _is_offshore_calendar(fund, plan)
    method = choose_method(
        offshore_calendar=offshore,
        benchmark_ready=ready,
        disclosed_coverage_pp=coverage,
    )

    if method == "index":
        parts = [(part.index_name, part.weight) for part in plan.parts]
        # `_benchmark_ready` 已经保证每条指数都取到了价，这里只是把值从 Optional 里
        # 取出来，不额外放宽条件。
        changes: dict[str, float] = {}
        dates: list[date] = []
        for name, _weight in parts:
            quote = quotes.get(name)
            if quote is None or quote.change_pct is None:
                continue
            changes[name] = quote.change_pct
            if quote.trade_date is not None:
                dates.append(quote.trade_date)
        change = benchmark_change(parts, changes)
        return FundEstimateItem(
            fund_code=fund_code,
            available=change is not None,
            method="index",
            change_pct=change,
            basis="＋".join(f"{name}×{weight:g}%" for name, weight in parts),
            quote_date=min(dates, default=None),
            reason=None if change is not None else "no_quotable_basis",
        )

    if method == "penetration":
        change = penetration_change(
            [HoldingWeight(symbol=symbol, weight_pp=weight) for symbol, weight, _ in usable],
            {symbol: value for symbol, _, value in usable},
        )
        quarter = f"（{holdings.quarter}）" if holdings and holdings.quarter else ""
        return FundEstimateItem(
            fund_code=fund_code,
            available=change is not None,
            method="penetration",
            change_pct=change,
            # 说的是"已取到行情的披露持仓占净值多少"，不是披露权重本身：两者在
            # 有股票取不到价时（港股、美股）会差一截，写成后者会让人以为覆盖率虚高。
            basis=f"已取到行情的持仓 {coverage:.1f}%{quarter}",
            quote_date=_latest_quote_date(quote_times),
            reason=None if change is not None else "thin_disclosure",
        )

    return FundEstimateItem(
        fund_code=fund_code,
        method="unavailable",
        reason="offshore_calendar" if offshore else "no_quotable_basis",
    )


class ValuationService:
    """把上面三块拼起来：先便宜地定口径，缺输入才去取."""

    async def estimates(self, codes: Sequence[str]) -> ValuationEstimatesResponse:
        """按代码批量算盘中估值.

        取披露持仓是这批里最贵的动作（每只 2~4 次上游调用），所以只对**用不上基准法
        且不是境外口径**的基金去做：指数型基金有基准就够了。
        """
        ordered = list(dict.fromkeys(codes))
        funds = await fund_repository.get_funds(ordered)
        quotes = {quote.name: quote for quote in await market_service.get_quotes()}
        benchmarks = await self._benchmarks(ordered, funds)
        plans = {code: parse_benchmark(benchmarks.get(code)) for code in ordered}

        needs_holdings = [
            code
            for code in ordered
            if not _is_offshore_calendar(funds.get(code), plans[code]) and not _benchmark_ready(plans[code], quotes)
        ]
        holdings = await self._holdings(needs_holdings)

        items = [
            estimate_one(
                code,
                fund=funds.get(code),
                plan=plans[code],
                quotes=quotes,
                holdings=holdings.get(code),
            )
            for code in ordered
        ]
        logger.info(
            "valuation_estimates_computed",
            requested=len(ordered),
            available=sum(1 for item in items if item.available),
            penetration=len(needs_holdings),
        )
        return ValuationEstimatesResponse(items=items, total=len(items), generated_at=utc_now())

    async def _benchmarks(self, codes: Sequence[str], funds: Mapping[str, Fund]) -> dict[str, str]:
        """基准原文优先读库；没读过的一起并发补一次档案，读到的存下来.

        基准几乎不变，所以这是"第一次遇到这只基金才付的成本"。取不到的基金不会
        被反复重试：没有这一格就是没有，走穿透那条路。
        """
        stored = await valuation_repository.get_benchmarks(list(codes))
        missing = [code for code in codes if code not in stored]
        if not missing:
            return stored

        semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def fetch(code: str) -> str | None:
            async with semaphore:
                try:
                    text = await fetch_benchmark_text(code)
                except Exception as e:
                    logger.warning("fund_benchmark_fetch_failed", fund_code=code, error=str(e))
                    return None
            if text:
                await valuation_repository.save_benchmark(code, text)
            return text

        fetched = await asyncio.gather(*(fetch(code) for code in missing))
        result = dict(stored)
        result.update({code: text for code, text in zip(missing, fetched, strict=True) if text})
        logger.info("fund_benchmarks_fetched", requested=len(missing), resolved=len(result) - len(stored))
        return result

    async def _holdings(self, codes: Sequence[str]) -> dict[str, FundHoldingsResponse | None]:
        """并发取披露持仓；单只失败只让那一只降级，不牵连同批其他基金."""
        if not codes:
            return {}
        semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def fetch(code: str) -> FundHoldingsResponse | None:
            async with semaphore:
                try:
                    return await fund_service.get_holdings(code)
                except Exception as e:
                    logger.warning("valuation_holdings_unavailable", fund_code=code, error=str(e))
                    return None

        values = await asyncio.gather(*(fetch(code) for code in codes))
        return dict(zip(codes, values, strict=True))


valuation_service = ValuationService()
