"""复用上市品种行情服务，给研究提供紧凑证据，不把K线序列交给模型."""

import asyncio
import re
from datetime import date

from app.analytics.drawdown import max_drawdown
from app.analytics.returns import NavPoint, window_return
from app.core.logging import logger
from app.integrations.fund_data.normalizer import market_kind
from app.schemas.research_card import StockChartReference, card_code_block
from app.schemas.market import SymbolQuoteResponse
from app.services.market_service import market_service
from app.utils.clock import utc_now
from app.utils.clock import business_now
from app.utils.market_quote_policy import finite_number, normalize_realtime_index


class StockResearchService:
    """公开股票研究；没有用户股票持仓账本，也不推断财报或即时消息."""

    async def collect(self, symbol: str) -> dict:
        """并发取快照、日K和公司简介；单源失败保持其他真实证据."""
        if not re.fullmatch(r"(?:sh|sz|bj)\d{6}|hk\d{5}|us[A-Z][A-Z.]{0,10}", symbol):
            raise ValueError("请提供带市场前缀的股票代码，例如sh600519、hk00700、usAAPL")
        if market_kind(symbol) != "stock":
            raise ValueError("该代码为指数，请使用行情工具")
        outcomes = await asyncio.gather(
            market_service.get_symbol_quote(symbol),
            market_service.get_symbol_history(symbol, "day", "1y"),
            market_service.get_symbol_company(symbol),
            return_exceptions=True,
        )
        warnings = [
            "公开报价可能延迟；报价时间未知或不是当日时，不能称为今日实时。",
            "价格指标由代码基于前复权日K计算，未计股息再投资；不是未来收益预测。",
            "未接入完整财报、股票公告、实时新闻或用户股票持仓账本。",
        ]
        data: dict = {"symbol": symbol, "fetched_at": utc_now().isoformat()}
        gaps: list[str] = []
        for name, outcome in zip(("quote", "history", "company"), outcomes, strict=True):
            if isinstance(outcome, BaseException):
                logger.warning(
                    "stock_research_source_failed", symbol=symbol, source=name, error_type=type(outcome).__name__
                )
                warnings.append(name + "查询失败，未据此推断不存在")
                gaps.append(name + "查询失败")
                continue
            if outcome is None:
                warnings.append(name + "暂无可用数据")
                gaps.append(name + "暂无可用数据")
                continue
            payload = outcome.model_dump(mode="json")
            if name != "history":
                if name == "company":
                    profile = payload.get("company")
                    if not isinstance(profile, dict):
                        warnings.append("公司概况未取得；不能据此分析完整财务状况")
                        gaps.append("公司概况未取得")
                        continue
                    payload = {
                        key: value[:1500] if isinstance(value, str) else value for key, value in profile.items()
                    }
                elif isinstance(outcome, SymbolQuoteResponse) and symbol.startswith(("sh", "sz", "bj")):
                    fresh = normalize_realtime_index(outcome, str(payload.get("name") or symbol), business_now())
                    if fresh is not None:
                        payload["stale"] = fresh.stale
                        payload["freshness"] = fresh.freshness
                data[name] = payload
                continue
            bars = payload.get("bars", [])
            points = [
                NavPoint(date.fromisoformat(row["trade_date"]), row["close"])
                for row in bars
                if finite_number(row["close"]) is not None and row["close"] > 0
            ]
            data["price_metrics"] = {
                "observed_from": points[0].date.isoformat() if points else None,
                "observed_to": points[-1].date.isoformat() if points else None,
                "point_count": len(points),
                "unit": "ratio",
                "observed_max_drawdown": max_drawdown(points),
                "returns": {
                    str(days) + "d": window_return(points, points[-1].date, days) for days in (30, 90, 180, 365)
                }
                if points
                else {},
            }
            if len(points) < 2:
                gaps.append("历史价格点不足，不能计算可靠的区间指标")
        if not data.get("quote") and data.get("price_metrics", {}).get("point_count", 0) < 2:
            return {"available": False, "symbol": symbol, "warnings": warnings}
        if symbol.startswith(("hk", "us")):
            warnings.append("海外市场报价时区与当日新鲜度未核验，不声称今日实时。")
        data.update(
            available=True,
            gaps=gaps,
            warnings=warnings,
            chart_code_block=card_code_block(StockChartReference(symbol=symbol)),
        )
        return data


stock_research_service = StockResearchService()
