"""净值分页保留最新的那一段，同时告知是否还有更早的行."""

from datetime import date, timedelta

from app.models.fund import FundNav
from app.services.fund_service import _newest_page

START = date(2026, 1, 1)


def _series(count: int) -> list[FundNav]:
    """按净值日期升序生成行，最新一条在末尾，和仓储层返回的顺序一致."""
    return [
        FundNav(fund_code="011452", nav_date=START + timedelta(days=index), unit_nav=1.0) for index in range(count)
    ]


class TestNewestPage:
    def test_no_limit_returns_everything(self) -> None:
        history = _series(50)
        page, has_more = _newest_page(history, None)
        assert page == history
        assert has_more is False

    def test_limit_keeps_the_newest_tail(self) -> None:
        history = _series(50)
        page, has_more = _newest_page(history, 30)
        assert [row.nav_date for row in page] == [row.nav_date for row in history[-30:]]
        assert has_more is True

    def test_exact_fit_has_no_older_pages(self) -> None:
        page, has_more = _newest_page(_series(30), 30)
        assert len(page) == 30
        assert has_more is False
