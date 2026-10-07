"""基金数据源适配层包.

业务代码绝不能直接调用 AKShare/Choice/iFinD——所有取数都走 `FundDataProvider`
接口，这样替换生产数据源时不用动 service（MVP spec 5.3/5.5）.
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
