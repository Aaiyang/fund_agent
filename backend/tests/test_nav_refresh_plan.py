"""批量行情里拿到的净值，哪些可以直接落库，哪些必须回头走单基金补拉."""

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
    """批量表里查不到的基金是要跟进补拉，不是出错.

    有些基金根本不会出现在那张表里，把「没查到」当成失败，就会让一个其实只需要
    走单基金路径的持仓被报成刷新失败。
    """
    writable, missing = plan_nav_writes(["005918", "270042"], [_nav("005918")], _funds("005918", "270042"))

    assert [nav.fund_code for nav in writable] == ["005918"]
    assert missing == ["270042"]


def test_a_code_without_a_master_row_is_chased_instead_of_written() -> None:
    """`fund_nav` 对 `fund` 有外键，一条孤儿代码就会让整批写入失败.

    upsert 是把很多行合成一条语句执行的：某个代码没有对应的主档行会中断整条语句，
    其他基金这次更新也就全丢了。单基金同步会先把主档行建出来，所以孤儿代码进 `missing`。
    """
    writable, missing = plan_nav_writes(["005918", "011452"], [_nav("005918"), _nav("011452")], _funds("005918"))

    assert [nav.fund_code for nav in writable] == ["005918"]
    assert missing == ["011452"]


def test_funds_the_caller_did_not_ask_for_are_ignored() -> None:
    """来源表本身覆盖全部基金，落库时只写调用方请求的那一组."""
    writable, missing = plan_nav_writes(["005918"], [_nav("005918"), _nav("002112")], _funds("005918", "002112"))

    assert [nav.fund_code for nav in writable] == ["005918"]
    assert missing == []


def test_an_empty_payload_reports_every_requested_code() -> None:
    """上游不可用导致的空结果，不能被当成一次干净的刷新."""
    writable, missing = plan_nav_writes(["005918", "011452"], [], _funds("005918", "011452"))

    assert writable == []
    assert missing == ["005918", "011452"]


def test_duplicate_rows_collapse_to_the_newest_date() -> None:
    """每只基金只写一行，写的是来源报上来的最新日期."""
    writable, _ = plan_nav_writes(
        ["005918"], [_nav("005918", _EARLIER, 1.4), _nav("005918", _DAY, 1.5)], _funds("005918")
    )

    assert [(nav.nav_date, nav.unit_nav) for nav in writable] == [(_DAY, 1.5)]
