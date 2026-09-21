"""Holdings import integrations: providers, extractors, vision adapters.

Import capability is decoupled from PortfolioService via the
HoldingImportProvider protocol (MVP spec 3.7). Providers convert different
inputs into a unified "pending draft"; only explicit user confirmation ever
writes to the authoritative portfolio_position table.
"""

from app.integrations.holdings.base import (
    HoldingImportDraft,
    HoldingImportPayload,
    HoldingImportProvider,
    RawExtractedPosition,
)
from app.integrations.holdings.manual_provider import ManualImportProvider
from app.integrations.holdings.screenshot_provider import ScreenshotImportProvider

__all__ = [
    "HoldingImportDraft",
    "HoldingImportPayload",
    "HoldingImportProvider",
    "ManualImportProvider",
    "RawExtractedPosition",
    "ScreenshotImportProvider",
]
