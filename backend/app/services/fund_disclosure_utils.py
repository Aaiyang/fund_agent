"""基金披露服务的成功缓存及任职区间归并，不直接访问数据提供方."""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from app.core.cache import cache_service
from app.core.logging import logger
from app.schemas.fund_disclosure import FundManagerPeriod, FundManagerTenure
from app.utils.clock import utc_now

DisclosureT = TypeVar("DisclosureT", bound=BaseModel)


async def cached_disclosure(
    key: str,
    model: type[DisclosureT],
    fetch: Callable[[], Awaitable[DisclosureT]],
    *,
    ttl: int,
    refresh: bool,
    valid: Callable[[DisclosureT], bool],
) -> tuple[DisclosureT, datetime, bool]:
    """缓存故障不影响在线取数，业务异常、空缺或无效响应不会成为成功缓存."""
    if not refresh:
        try:
            raw = await cache_service.get(key)
            if raw:
                saved = json.loads(raw)
                stamp = datetime.fromisoformat(saved["fetched_at"])
                data = model.model_validate(saved["data"])
                age = (utc_now() - stamp).total_seconds() if stamp.tzinfo is None else -1
                if 0 <= age < ttl and valid(data):
                    return data, stamp, True
        except Exception:
            logger.exception("fund_disclosure_cache_read_failed")
    data = await fetch()
    stamp = utc_now()
    if valid(data):
        try:
            await cache_service.set(
                key,
                json.dumps(
                    {"data": data.model_dump(mode="json"), "fetched_at": stamp.isoformat()}, ensure_ascii=False
                ),
                ttl=ttl,
            )
        except Exception:
            logger.exception("fund_disclosure_cache_write_failed")
    return data, stamp, False


def merge_manager_tenures(periods: list[FundManagerPeriod]) -> list[FundManagerTenure]:
    """按经理ID归并相邻/重叠区间，保留离任再任和不同经理同名的区别."""
    grouped: dict[str, list[FundManagerTenure]] = {}
    for period in sorted(periods, key=lambda row: row.start_date):
        for manager in period.managers:
            key = manager.manager_id or manager.name
            rows = grouped.setdefault(key, [])
            previous = rows[-1] if rows else None
            if previous is not None and (
                previous.end_date is None or period.start_date.toordinal() <= previous.end_date.toordinal() + 1
            ):
                if previous.end_date is None or period.end_date is None:
                    previous.end_date = None
                else:
                    previous.end_date = max(previous.end_date, period.end_date)
                previous.is_current = previous.is_current or period.is_current
            else:
                rows.append(
                    FundManagerTenure(
                        manager=manager,
                        start_date=period.start_date,
                        end_date=period.end_date,
                        is_current=period.is_current,
                    )
                )
    return sorted(
        (row for rows in grouped.values() for row in rows),
        key=lambda row: (row.start_date, row.manager.name),
        reverse=True,
    )
