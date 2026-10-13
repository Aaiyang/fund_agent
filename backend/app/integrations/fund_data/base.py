"""`FundDataProvider` 协议：所有基金事实唯一的取数入口."""

from datetime import date
from typing import Protocol, runtime_checkable

from app.integrations.fund_data.models import (
    FundExternalHolding,
    FundExternalIndustry,
    FundExternalManager,
    FundExternalNav,
    FundExternalProfile,
    FundExternalRecord,
    StockExternalQuote,
)
from app.schemas.fund_disclosure import FundAnnouncementPage, FundManagerHistoryData


@runtime_checkable
class FundDataProvider(Protocol):
    """每个基金数据源都必须实现的异步接口.

    实现要把阻塞式 SDK 调用（例如 AKShare 的同步 HTTP）隔离在有界并发、超时与
    重试之后，绝不阻塞 FastAPI 事件循环（MVP spec 7.6）.
    """

    async def search_funds(self, keyword: str) -> list[FundExternalRecord]:
        """按代码、全称、简称或模糊名称搜索基金."""
        ...

    async def get_fund_profile(self, fund_code: str) -> FundExternalProfile | None:
        """取基金主数据（名称、类型、管理公司、基金经理、成立日期）."""
        ...

    async def get_latest_nav(self, fund_code: str) -> FundExternalNav | None:
        """取某只基金最近一天的净值."""
        ...

    async def get_latest_navs(self, fund_codes: list[str], force: bool = False) -> list[FundExternalNav]:
        """一次取多只基金的最新净值，供列表页使用.

        `force` 会跳过已缓存的源表并重新拉取，按需刷新报价正需要这样；默认读取
        走缓存，因为这张表是对全市场基金的一次大请求.
        """
        ...

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundExternalNav]:
        """取可选日期区间内的历史净值行."""
        ...

    async def get_fund_manager(self, fund_code: str) -> FundExternalManager | None:
        """取现任基金经理."""
        ...

    async def get_manager_history(self, fund_code: str) -> FundManagerHistoryData:
        """取历任经理团队区间，不将现任姓名假装成完整历史."""
        ...

    async def get_announcements(
        self, fund_code: str, category: int, page: int, page_size: int
    ) -> FundAnnouncementPage:
        """取公开公告的一页索引，保留上游总量及真实来源链接."""
        ...

    async def get_holdings(self, fund_code: str) -> list[FundExternalHolding]:
        """取基金披露的股票持仓，最近两个季度."""
        ...

    async def get_stock_quotes(self, stock_codes: list[str]) -> list[StockExternalQuote]:
        """给持仓股票跨 A股 / 港股 / 美股取行情."""
        ...

    async def get_industry_allocation(self, fund_code: str) -> list[FundExternalIndustry]:
        """取最新一次披露的行业权重."""
        ...
