"""FundDataProvider protocol — the only data-source seam for fund facts."""

from datetime import date
from typing import Protocol, runtime_checkable

from app.integrations.fund_data.models import (
    FundExternalHolding,
    FundExternalManager,
    FundExternalNav,
    FundExternalProfile,
    FundExternalRecord,
)


@runtime_checkable
class FundDataProvider(Protocol):
    """Async interface every fund data source must implement.

    Implementations isolate blocking SDK calls (e.g. AKShare's synchronous
    HTTP) behind bounded concurrency, timeouts and retries so the FastAPI
    event loop is never blocked (MVP spec 7.6).
    """

    async def search_funds(self, keyword: str) -> list[FundExternalRecord]:
        """Search funds by code, full name, abbreviation or fuzzy name."""
        ...

    async def get_fund_profile(self, fund_code: str) -> FundExternalProfile | None:
        """Fetch fund master data (name, type, company, manager, inception)."""
        ...

    async def get_latest_nav(self, fund_code: str) -> FundExternalNav | None:
        """Fetch the most recent NAV for a fund."""
        ...

    async def get_latest_navs(self, fund_codes: list[str]) -> list[FundExternalNav]:
        """Fetch the latest NAV for many funds at once, for list views."""
        ...

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundExternalNav]:
        """Fetch historical NAV rows between optional dates."""
        ...

    async def get_fund_manager(self, fund_code: str) -> FundExternalManager | None:
        """Fetch the current fund manager."""
        ...

    async def get_holdings(self, fund_code: str) -> list[FundExternalHolding]:
        """Fetch the fund's stock holdings (empty when unsupported)."""
        ...
