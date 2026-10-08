"""Agent 图片导入适配：会话隔离、结构化复核及人工决策，模型没有应用持仓的入口."""

from fastapi import UploadFile

from app.repositories.import_repository import import_repository
from app.schemas.agent_import import HoldingImportReview
from app.schemas.holding_import import ImportDetail, ScreenshotImportAccepted
from app.services.holding_import_service import ImportStateError, holding_import_service
from app.utils.holding_review import holding_review_digest


class AgentHoldingImportService:
    """网页与移动端共用现有识别队列和持仓复核流程."""

    async def upload(
        self, user_id: int, session_id: str, account_id: int, files: list[UploadFile]
    ) -> ScreenshotImportAccepted:
        """只创建识别草稿，不写正式持仓；会话 ID 由认证依赖提供."""
        record = await holding_import_service.create_screenshot_import(
            user_id, account_id, files, chat_session_id=session_id
        )
        return ScreenshotImportAccepted(import_id=record.id, status="PARSING", image_count=record.image_count)

    async def detail(self, user_id: int, session_id: str, import_id: str) -> ImportDetail:
        """仅允许访问当前用户在当前会话上传的截图批次."""
        record = await import_repository.get_import(user_id, import_id)
        if record is None or record.chat_session_id != session_id or record.import_type != "SCREENSHOT":
            raise ImportStateError("import_not_found")
        detail = await holding_import_service.get_import_detail(user_id, import_id)
        if detail is None:
            raise ImportStateError("import_not_found")
        return detail

    async def review(self, user_id: int, session_id: str, import_id: str) -> HoldingImportReview:
        """使用真实草稿构造确认卡，绝不接受模型提交的持仓金额或基金代码."""
        detail = await self.detail(user_id, session_id, import_id)
        if detail.status != "REVIEW_REQUIRED":
            raise ImportStateError(f"import_not_reviewable_in_state_{detail.status}")
        return HoldingImportReview(
            import_id=detail.id,
            account_id=detail.account_id,
            image_count=detail.image_count,
            items=detail.items,
            review_digest=holding_review_digest(detail),
        )

    async def decide(
        self, user_id: int, session_id: str, import_id: str, *, decision: str, review_digest: str
    ) -> dict:
        """仅供已验证 LangGraph 中断的人工 HTTP 端点调用."""
        detail = await self.detail(user_id, session_id, import_id)
        if decision == "cancel":
            if detail.status != "CANCELLED":
                await holding_import_service.delete_import(user_id, import_id)
            return {"decision": "cancel", "import_id": import_id}
        if decision != "confirm":
            raise ImportStateError("invalid_import_decision")
        result = await holding_import_service.confirm_import(user_id, import_id, expected_review_digest=review_digest)
        return {"decision": "confirm", "import_id": import_id, **result}


agent_holding_import_service = AgentHoldingImportService()


def get_agent_holding_import_service() -> AgentHoldingImportService:
    """FastAPI 的服务依赖，客户端接入测试可独立替换它."""
    return agent_holding_import_service
