"""估值输入数据的读写：业绩比较基准原文."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from app.core.database import get_async_session
from app.core.logging import logger
from app.models.valuation import FundBenchmark
from app.utils.clock import utc_now

# 与 `FundBenchmark.text` 的列宽一致。超出去**不截断**：截掉的是最后一段的权重，
# 而解析器读到半句话会算出一个偏小的基准权重，错得很安静。
_MAX_TEXT_LENGTH = 400


class ValuationRepository:
    """估值模块自己的数据访问."""

    async def get_benchmarks(self, fund_codes: list[str]) -> dict[str, str]:
        """一次取回多只基金的基准原文；没存过的代码不在结果里."""
        if not fund_codes:
            return {}
        async with get_async_session() as session:
            rows = (
                (await session.execute(select(FundBenchmark).where(col(FundBenchmark.fund_code).in_(fund_codes))))
                .scalars()
                .all()
            )
            return {row.fund_code: row.text for row in rows}

    async def save_benchmark(self, fund_code: str, text: str) -> bool:
        """写入或刷新一只基金的基准原文.

        Returns:
            是否真的存下了。超长时不存（返回 False），让上层退到"没有基准"这条
            路上，而不是存进一句读不懂的话。
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        if len(cleaned) > _MAX_TEXT_LENGTH:
            logger.warning("fund_benchmark_too_long", fund_code=fund_code, length=len(cleaned))
            return False

        now = utc_now()
        values = {
            "fund_code": fund_code,
            "text": cleaned,
            "source": "akshare",
            "fetched_at": now,
        }
        async with get_async_session() as session:
            statement = pg_insert(FundBenchmark).values(created_at=now, **values)
            statement = statement.on_conflict_do_update(
                index_elements=[FundBenchmark.fund_code],
                # created_at 不在 set_ 里：它记的是这行第一次出现的时间。
                set_={key: value for key, value in values.items() if key != "fund_code"},
            )
            await session.execute(statement)
        logger.debug("fund_benchmark_saved", fund_code=fund_code, length=len(cleaned))
        return True


valuation_repository = ValuationRepository()
