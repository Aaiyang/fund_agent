"""Holding import contracts: payload, draft, provider protocol."""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ManualPositionInput(BaseModel):
    """One manually entered holding row."""

    fund_code: str | None = Field(default=None, max_length=12)
    fund_name: str | None = Field(default=None, max_length=200)
    market_value: float | None = Field(default=None, ge=0)
    shares: float | None = Field(default=None, ge=0)
    cost_amount: float | None = Field(default=None, ge=0)
    average_cost_nav: float | None = Field(default=None, ge=0)
    profit_loss: float | None = None
    profit_loss_rate: float | None = None


class HoldingImportPayload(BaseModel):
    """Provider input: manual rows and/or screenshot image paths."""

    account_id: int
    source_app: str | None = None
    manual_positions: list[ManualPositionInput] = Field(default_factory=list)
    image_paths: list[str] = Field(default_factory=list)


class RawExtractedPosition(BaseModel):
    """One position extracted from a screenshot, pre-resolution.

    Every field is optional — screenshots vary wildly in what they show
    (MVP spec 3.7.2). Confidence is per-item (0.0–1.0).
    """

    fund_name: str | None = None
    fund_code: str | None = None
    market_value: float | None = None
    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None
    daily_profit_loss: float | None = None
    # The app clipped the name with an ellipsis: it will not match a fund
    # exactly, and the review page should show candidates rather than one guess.
    truncated: bool = False
    # One of the row's columns stopped short — the screenshot ended mid-row, so
    # some figure was never on the screen to be read.
    partial: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class DraftPositionItem(BaseModel):
    """One normalized draft row awaiting user confirmation."""

    raw_fund_name: str | None = None
    matched_fund_code: str | None = None
    matched_fund_name: str | None = None
    market_value: float | None = None
    shares: float | None = None
    cost_amount: float | None = None
    average_cost_nav: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None
    # Carried from the screenshot: the app clipped this name with an ellipsis,
    # so the row is only trustworthy once he has picked the fund himself.
    truncated: bool = False
    partial: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    validation_status: str = "valid"
    validation_issues: list[str] = Field(default_factory=list)


class HoldingImportDraft(BaseModel):
    """Unified parse result from any provider: rows + stats + error."""

    items: list[DraftPositionItem] = Field(default_factory=list)
    image_count: int = 0
    image_hashes: list[str] = Field(default_factory=list)
    error_message: str | None = None


@runtime_checkable
class HoldingImportProvider(Protocol):
    """Convert a raw payload into a pending draft — never writes holdings."""

    async def parse(self, payload: HoldingImportPayload) -> HoldingImportDraft:
        """Parse the payload into a draft for review."""
        ...
