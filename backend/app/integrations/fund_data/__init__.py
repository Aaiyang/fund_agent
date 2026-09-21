"""Fund data provider package.

Business code must never call AKShare/Choice/iFinD directly — everything goes
through the FundDataProvider interface so the production data source can be
swapped without touching services (MVP spec 5.3/5.5).
"""

from app.integrations.fund_data.akshare_provider import AKShareFundProvider
from app.integrations.fund_data.base import FundDataProvider
from app.integrations.fund_data.models import (
    FundExternalHolding,
    FundExternalManager,
    FundExternalNav,
    FundExternalProfile,
    FundExternalRecord,
)

__all__ = [
    "AKShareFundProvider",
    "FundDataProvider",
    "FundExternalHolding",
    "FundExternalManager",
    "FundExternalNav",
    "FundExternalProfile",
    "FundExternalRecord",
]
