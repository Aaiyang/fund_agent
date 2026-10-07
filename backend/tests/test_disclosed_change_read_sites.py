"""读侧口径：披露 0.00% 而净值步进对不上时，三个接口都不能显示成"没涨没跌"."""

from datetime import date, timedelta

from app.models.fund import Fund, FundNav
from app.models.portfolio import PortfolioPosition
from app.models.watchlist import Watchlist
from app.services.fund_service import fund_service
from app.services.portfolio_service import portfolio_service
from app.services.watchlist_service import watchlist_service

START = date(2026, 1, 5)
LIE_CODE = "539001"
FLAT_CODE = "001234"
WINDOW_CODE = "005678"
# 净值从 1.000 走到 1.014，日增长率却披露 0.00% —— 那天上游没有行情（境外休市），
# 说 0.00% 是假话。真实平盘的行净值不动，那个 0.00% 是事实，要留着。
MOVED_NAV = 1.014


def _row(code: str, offset: int, unit_nav: float, daily_return: float | None) -> FundNav:
    """生成一行净值，offset 越大越新，和仓储层的升序约定一致."""
    return FundNav(
        fund_code=code, nav_date=START + timedelta(days=offset), unit_nav=unit_nav, daily_return=daily_return
    )


def _series(code: str, last_nav: float) -> list[FundNav]:
    return [_row(code, 0, 1.0, 0.0), _row(code, 1, 1.0, 0.0), _row(code, 2, last_nav, 0.0)]


def _world() -> tuple[dict[str, Fund], dict[str, FundNav], dict[str, list[FundNav]]]:
    """三只基金：假平盘、真平盘、以及历史窗口取不到前一天净值的那一只."""
    codes = (LIE_CODE, FLAT_CODE, WINDOW_CODE)
    funds = {code: Fund(fund_code=code, fund_name=f"测试基金{code}", inception_date=START) for code in codes}
    history = {
        LIE_CODE: _series(LIE_CODE, MOVED_NAV),
        FLAT_CODE: _series(FLAT_CODE, 1.0),
        # 最新一行的日期比历史末尾还新：取不到前一天，就照披露说话，不猜。
        WINDOW_CODE: [_row(WINDOW_CODE, 0, 1.0, 0.0), _row(WINDOW_CODE, 1, MOVED_NAV, 1.4)],
    }
    latest = {code: rows[-1] for code, rows in history.items()}
    latest[WINDOW_CODE] = _row(WINDOW_CODE, 3, 1.02, 0.0)
    return funds, latest, history


class _FakeFundRepository:
    """只读替身：按代码给出主数据、最新行与历史序列，不碰数据库也不碰缓存."""

    def __init__(self, funds: dict[str, Fund], latest: dict[str, FundNav], history: dict[str, list[FundNav]]) -> None:
        self._funds = funds
        self._latest = latest
        self._history = history

    async def get_fund(self, fund_code: str) -> Fund | None:
        return self._funds.get(fund_code)

    async def get_funds(self, fund_codes: list[str]) -> dict[str, Fund]:
        return {code: self._funds[code] for code in fund_codes if code in self._funds}

    async def get_latest_nav(self, fund_code: str) -> FundNav | None:
        return self._latest.get(fund_code)

    async def get_latest_navs(self, fund_codes: list[str]) -> dict[str, FundNav]:
        return {code: self._latest[code] for code in fund_codes if code in self._latest}

    async def get_nav_history(self, fund_code: str, *dates: object) -> list[FundNav]:
        return self._history.get(fund_code, [])

    async def get_nav_history_map(self, fund_codes: list[str], *dates: object) -> dict[str, list[FundNav]]:
        return {code: self._history[code] for code in fund_codes if code in self._history}


class _FakeWatchlistRepository:
    """只读替身：把这几只基金都当成该用户的自选."""

    def __init__(self, codes: list[str]) -> None:
        self._codes = codes

    async def list_funds(self, user_id: int) -> list[Watchlist]:
        return [Watchlist(user_id=user_id, fund_code=code, sort_order=index) for index, code in enumerate(self._codes)]

    async def list_group_map(self, user_id: int) -> dict[str, list[tuple[int, str]]]:
        return {}

    async def list_held_fund_codes(self, user_id: int) -> set[str]:
        return set()


async def test_watchlist_reads_a_contradicted_zero_as_not_disclosed(monkeypatch) -> None:
    """自选列表：假平盘显示空，真平盘与取不到前一天的那一只照旧."""
    funds, latest, history = _world()
    monkeypatch.setattr("app.services.watchlist_service.fund_repository", _FakeFundRepository(funds, latest, history))
    monkeypatch.setattr(
        "app.services.watchlist_service.watchlist_repository",
        _FakeWatchlistRepository([LIE_CODE, FLAT_CODE, WINDOW_CODE]),
    )

    items = {item.fund_code: item for item in await watchlist_service.list_funds(user_id=24)}
    assert items[LIE_CODE].daily_return is None
    assert items[FLAT_CODE].daily_return == 0.0
    assert items[WINDOW_CODE].daily_return == 0.0


async def test_position_daily_return_and_profit_loss_stay_in_agreement(monkeypatch) -> None:
    """持仓列表：百分比判成没披露时，昨日收益不能还留着一笔钱."""
    funds, latest, history = _world()
    monkeypatch.setattr("app.services.portfolio_service.fund_repository", _FakeFundRepository(funds, latest, history))
    lying = PortfolioPosition(
        user_id=24,
        account_id=1,
        fund_code=LIE_CODE,
        shares=10_000.0,
        cost_amount=9_900.0,
        average_cost_nav=0.99,
        market_value=10_140.0,
        purchase_date=START,
    )

    lying_item = await portfolio_service._position_item(lying, 20_140.0, history[LIE_CODE], None)
    assert lying_item.daily_return is None
    assert lying_item.daily_profit_loss is None

    # 真平盘的那一只：披露 0.00% 就是 0.00%，钱也是 0。
    flat = lying.model_copy(update={"fund_code": FLAT_CODE, "market_value": 10_000.0})
    flat_item = await portfolio_service._position_item(flat, 20_140.0, history[FLAT_CODE], None)
    assert flat_item.daily_return == 0.0
    assert flat_item.daily_profit_loss == 0.0

    # 历史窗口取不到前一天时按披露说话，哪怕它和净值步进是矛盾的。
    moved = lying.model_copy(update={"fund_code": WINDOW_CODE})
    moved_item = await portfolio_service._position_item(moved, 20_140.0, history[WINDOW_CODE], None)
    assert moved_item.daily_return == 0.0
    assert moved_item.daily_profit_loss == 0.0


async def test_fund_detail_uses_the_same_call(monkeypatch) -> None:
    """基金详情：与两张列表同一个口径，不能这里空着那里显示 0.00%."""
    funds, latest, history = _world()
    monkeypatch.setattr("app.services.fund_service.fund_repository", _FakeFundRepository(funds, latest, history))

    async def _skip_sync(fund_code: str) -> None:
        return None

    async def _skip_cache(fund_code: str) -> FundNav | None:
        return latest.get(fund_code)

    async def _no_flags(fund_code: str, user_id: int) -> tuple[bool, bool]:
        return False, False

    monkeypatch.setattr(fund_service, "ensure_fund_data", _skip_sync)
    monkeypatch.setattr(fund_service, "_latest_nav_cached", _skip_cache)
    monkeypatch.setattr(fund_service, "_user_flags", _no_flags)

    detail = await fund_service.get_detail(LIE_CODE, user_id=24)
    assert detail is not None
    assert detail.daily_return is None

    flat_detail = await fund_service.get_detail(FLAT_CODE, user_id=24)
    assert flat_detail is not None
    assert flat_detail.daily_return == 0.0
