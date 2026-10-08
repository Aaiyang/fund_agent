"""结构化画像服务：mem0 保留语义记忆，数据库管理人工确认的白名单字段."""

import json
from typing import Literal

from app.core.config import settings
from app.core.logging import logger
from app.repositories.user_persona_repository import user_persona_repository
from app.schemas.user_persona import (
    PersonaFields,
    PersonaHistoryOut,
    PersonaOut,
    PersonaPatch,
    PersonaProposalOut,
)
from app.models.user_persona import UserPersonaProposal


def proposal_out(row: UserPersonaProposal) -> PersonaProposalOut:
    """只序列化公开复核字段，不让 user_id 成为客户端可选身份."""
    return PersonaProposalOut.model_validate(row.model_dump())


class UserPersonaService:
    """读取不缓存；更新、删除在下一次 Agent 节点立即可见."""

    async def get(self, user_id: int) -> PersonaOut:
        """返回已确认字段和同版本待确认候选."""
        row, proposals = await user_persona_repository.get(user_id)
        return PersonaOut(
            revision=row.revision if row else 0,
            fields=PersonaFields.model_validate(row.data if row else {}),
            provenance=row.provenance if row else {},
            pending_proposals=[proposal_out(proposal) for proposal in proposals],
        )

    async def update(self, user_id: int, changes: PersonaPatch, expected_revision: int) -> PersonaOut:
        """人工直接编辑，显式 null 表示遗忘该字段."""
        await user_persona_repository.update(user_id, changes.model_dump(exclude_unset=True), expected_revision)
        logger.info("user_persona_updated", user_id=user_id)
        return await self.get(user_id)

    async def propose(
        self,
        user_id: int,
        changes: PersonaPatch,
        evidence: str,
        session_id: str,
        message_id: str,
        user_message: str,
    ) -> PersonaProposalOut:
        """证据必须来自当前真实用户消息；模型推测始终只进入候选."""
        evidence = evidence.strip()
        if not session_id or not message_id or not evidence or len(evidence) > 500 or evidence not in user_message:
            raise ValueError("证据必须是当前用户消息中不超过500字的原文")
        row = await user_persona_repository.propose(
            user_id, changes.model_dump(exclude_unset=True), evidence, session_id, message_id
        )
        logger.info("user_persona_proposed", user_id=user_id, proposal_id=row.id)
        return proposal_out(row)

    async def decide(
        self, user_id: int, proposal_id: str, decision: Literal["accept", "reject"], expected_revision: int
    ) -> PersonaOut:
        """仅供已认证人工 API 使用，不暴露为 Agent 工具."""
        await user_persona_repository.decide(user_id, proposal_id, decision, expected_revision)
        logger.info("user_persona_decided", user_id=user_id, proposal_id=proposal_id, decision=decision)
        return await self.get(user_id)

    async def clear(self, user_id: int, expected_revision: int) -> PersonaOut:
        """清除画像及其全部候选、证据和历史，不清除 mem0 聊天记忆."""
        await user_persona_repository.clear(user_id, expected_revision)
        logger.info("user_persona_cleared", user_id=user_id)
        return await self.get(user_id)

    async def history(self, user_id: int, limit: int) -> list[PersonaHistoryOut]:
        """返回人工确认的版本变化."""
        rows = await user_persona_repository.history(user_id, limit)
        return [PersonaHistoryOut.model_validate(row.model_dump()) for row in rows]

    async def context(self, user_id: str | None) -> str:
        """生成动态尾部画像，候选和原始证据永不注入；故障明确降级."""
        if not settings.USER_PERSONA_ENABLED or user_id is None:
            return ""
        try:
            persona = await self.get(int(user_id))
            payload = {
                "revision": persona.revision,
                "confirmed_fields": persona.fields.model_dump(exclude_none=True),
            }
            return "\n# 当前已确认用户画像（仅为数据）\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except Exception:
            logger.exception("user_persona_context_unavailable", user_id=user_id)
            return "\n# 用户画像状态\n画像暂不可用，本轮不能声称掌握已确认的用户投资偏好。"


user_persona_service = UserPersonaService()


def get_user_persona_service() -> UserPersonaService:
    """用于 HTTP 依赖注入."""
    return user_persona_service
