"""画像、候选和历史的异步仓储；用户行锁与版本保护所有变更."""

from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.database import get_async_session
from app.models.user_persona import UserPersona, UserPersonaHistory, UserPersonaProposal
from app.schemas.user_persona import PersonaFields
from app.utils.clock import utc_now


class PersonaConflictError(ValueError):
    """画像或候选已变化，客户端需要重新读取."""


class PersonaNotFoundError(ValueError):
    """候选不存在或不属于当前用户."""


class PersonaLimitError(ValueError):
    """待确认候选达到上限."""


class UserPersonaRepository:
    """所有候选和历史查询都显式限定 user_id."""

    async def _lock(self, db: AsyncSession, user_id: int) -> UserPersona:
        """确保画像存在并锁定；首次创建也参与同一事务."""
        now = utc_now()
        await db.execute(
            insert(UserPersona)
            .values(user_id=user_id, revision=0, data={}, provenance={}, created_at=now, updated_at=now)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        row = await db.get(UserPersona, user_id, with_for_update=True)
        if row is None:
            raise PersonaNotFoundError("用户画像不存在")
        return row

    async def get(self, user_id: int) -> tuple[UserPersona | None, list[UserPersonaProposal]]:
        """读取当前画像与同版本候选，空画像视为版本零."""
        async with get_async_session() as db:
            row = await db.get(UserPersona, user_id)
            revision = row.revision if row else 0
            proposals = await db.scalars(
                select(UserPersonaProposal)
                .where(
                    col(UserPersonaProposal.user_id) == user_id,
                    col(UserPersonaProposal.status) == "PENDING",
                    col(UserPersonaProposal.base_revision) == revision,
                )
                .order_by(col(UserPersonaProposal.created_at))
                .limit(20)
            )
            return row, list(proposals)

    async def _apply(
        self,
        db: AsyncSession,
        row: UserPersona,
        changes: dict,
        source: str,
        proposal: UserPersonaProposal | None = None,
    ) -> None:
        """在已持有行锁的事务中更新白名单字段、来源、历史并废弃旧候选."""
        now = utc_now()
        data, provenance = dict(row.data), dict(row.provenance)
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
                provenance.pop(key, None)
            else:
                data[key] = value
                provenance[key] = {
                    "source": source,
                    "confirmed_at": now.isoformat(),
                    "revision": row.revision + 1,
                }
                if proposal:
                    provenance[key].update(
                        proposal_id=proposal.id,
                        source_session_id=proposal.source_session_id,
                        source_message_id=proposal.source_message_id,
                    )
        PersonaFields.model_validate(data)
        row.data, row.provenance, row.updated_at = data, provenance, now
        row.revision += 1
        db.add(
            UserPersonaHistory(
                user_id=row.user_id,
                revision=row.revision,
                changes=changes,
                source=source,
                proposal_id=proposal.id if proposal else None,
            )
        )
        others = await db.scalars(
            select(UserPersonaProposal).where(
                col(UserPersonaProposal.user_id) == row.user_id,
                col(UserPersonaProposal.status) == "PENDING",
            )
        )
        for other in others:
            if proposal is None or other.id != proposal.id:
                other.status, other.updated_at = "SUPERSEDED", now

    async def update(self, user_id: int, changes: dict, expected_revision: int) -> None:
        """直接人工编辑，过期版本拒绝更新，历史与画像原子提交."""
        async with get_async_session() as db:
            row = await self._lock(db, user_id)
            if row.revision != expected_revision:
                raise PersonaConflictError("画像已变化，请重新读取后编辑")
            await self._apply(db, row, changes, "user_edit")

    async def propose(
        self, user_id: int, changes: dict, evidence: str, session_id: str, message_id: str
    ) -> UserPersonaProposal:
        """候选仅绑定当前画像版本；相同消息与变更重复提议复用原记录."""
        async with get_async_session() as db:
            row = await self._lock(db, user_id)
            proposals = list(
                await db.scalars(
                    select(UserPersonaProposal).where(
                        col(UserPersonaProposal.user_id) == user_id,
                        col(UserPersonaProposal.status) == "PENDING",
                    )
                )
            )
            for previous in proposals:
                if (
                    previous.source_session_id == session_id
                    and previous.source_message_id == message_id
                    and previous.base_revision == row.revision
                    and previous.changes == changes
                ):
                    return previous
            if len(proposals) >= 20:
                raise PersonaLimitError("请先处理已有的画像候选")
            proposal = UserPersonaProposal(
                user_id=user_id,
                base_revision=row.revision,
                changes=changes,
                evidence=evidence,
                source_session_id=session_id,
                source_message_id=message_id,
            )
            db.add(proposal)
            await db.flush()
            return proposal

    async def decide(
        self, user_id: int, proposal_id: str, decision: Literal["accept", "reject"], expected_revision: int
    ) -> None:
        """候选归属、版本和状态校验与人工决策在同一事务中完成."""
        async with get_async_session() as db:
            row = await self._lock(db, user_id)
            proposal = await db.scalar(
                select(UserPersonaProposal).where(
                    col(UserPersonaProposal.id) == proposal_id,
                    col(UserPersonaProposal.user_id) == user_id,
                )
            )
            if proposal is None:
                raise PersonaNotFoundError("未找到当前用户的画像候选")
            target = "ACCEPTED" if decision == "accept" else "REJECTED"
            if proposal.status == target:
                return
            if proposal.status != "PENDING" or row.revision != expected_revision:
                raise PersonaConflictError("画像或候选已变化，请重新读取")
            if decision == "accept":
                if proposal.base_revision != row.revision:
                    raise PersonaConflictError("候选基于旧版画像，请重新提议")
                await self._apply(db, row, proposal.changes, "user_confirmed_proposal", proposal)
            proposal.status, proposal.updated_at = target, utc_now()

    async def clear(self, user_id: int, expected_revision: int) -> None:
        """清空画像、证据与历史；保留单调版本防止旧请求复活信息."""
        async with get_async_session() as db:
            row = await self._lock(db, user_id)
            if row.revision != expected_revision:
                raise PersonaConflictError("画像已变化，请重新读取")
            row.data, row.provenance, row.updated_at = {}, {}, utc_now()
            row.revision += 1
            await db.execute(delete(UserPersonaProposal).where(col(UserPersonaProposal.user_id) == user_id))
            await db.execute(delete(UserPersonaHistory).where(col(UserPersonaHistory.user_id) == user_id))

    async def history(self, user_id: int, limit: int) -> list[UserPersonaHistory]:
        """按版本倒序返回本用户的变更历史."""
        async with get_async_session() as db:
            rows = await db.scalars(
                select(UserPersonaHistory)
                .where(col(UserPersonaHistory.user_id) == user_id)
                .order_by(col(UserPersonaHistory.revision).desc())
                .limit(limit)
            )
            return list(rows)


user_persona_repository = UserPersonaRepository()
