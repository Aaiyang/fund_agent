"""What a batched quote payload may be written, and what must be chased instead."""

from datetime import date

from app.integrations.fund_data.models import FundExternalNav
from app.models.fund import Fund
from app.services.fund_sync_service import plan_nav_writes

_DAY = date(2026, 9, 30)
_EARLIER = date(2026, 9, 29)


def _nav(code: str, when: date = _DAY, unit: float = 1.5) -> FundExternalNav:
    return FundExternalNav(fund_code=code, nav_date=when, unit_nav=unit, daily_return=0.28)


def _funds(*codes: str) -> dict[str, Fund]:
    return {code: Fund(fund_code=code, fund_name=f"基金{code}") for code in codes}


def test_rows_the_source_does_not_carry_are_reported_not_failed() -> None:
    """A fund missing from the batched table is a follow-up, not an error.

    Some funds are never listed in that table at all, so treating a miss as a
    failure would report "refresh failed" for a holding that simply needs the
    per-fund path.
    """
    writable, missing = plan_nav_writes(["005918", "270042"], [_nav("005918")], _funds("005918", "270042"))

    assert [nav.fund_code for nav in writable] == ["005918"]
    assert missing == ["270042"]


def test_a_code_without_a_master_row_is_chased_instead_of_written() -> None:
    """`fund_nav` has a foreign key onto `fund`, so one orphan fails the batch.

    The upsert is one statement over many rows: a code with no master row would
    abort it and cost every other fund its update. The per-fund sync creates the
    master row first, so the orphan goes to `missing`.
    """
    writable, missing = plan_nav_writes(["005918", "011452"], [_nav("005918"), _nav("011452")], _funds("005918"))

    assert [nav.fund_code for nav in writable] == ["005918"]
    assert missing == ["011452"]


def test_funds_the_caller_did_not_ask_for_are_ignored() -> None:
    """The source table covers every fund; only the requested set is written."""
    writable, missing = plan_nav_writes(["005918"], [_nav("005918"), _nav("002112")], _funds("005918", "002112"))

    assert [nav.fund_code for nav in writable] == ["005918"]
    assert missing == []


def test_an_empty_payload_reports_every_requested_code() -> None:
    """An outage-shaped payload must not read as a clean refresh."""
    writable, missing = plan_nav_writes(["005918", "011452"], [], _funds("005918", "011452"))

    assert writable == []
    assert missing == ["005918", "011452"]


def test_duplicate_rows_collapse_to_the_newest_date() -> None:
    """One row per fund is written, and it is the newest the source reported."""
    writable, _ = plan_nav_writes(
        ["005918"], [_nav("005918", _EARLIER, 1.4), _nav("005918", _DAY, 1.5)], _funds("005918")
    )

    assert [(nav.nav_date, nav.unit_nav) for nav in writable] == [(_DAY, 1.5)]
