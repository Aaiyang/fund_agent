"""Agent 图片导入适配：会话隔离、结构化复核及人工决策，模型没有应用持仓的入口."""

import re

from fastapi import UploadFile

from app.core.database import transaction_scope

from app.repositories.import_repository import import_repository
from app.schemas.agent_import import HoldingAccountOption, HoldingImportReview
from app.schemas.holding_import import ImportDetail, ScreenshotImportAccepted
from app.services.holding_import_service import ImportStateError, holding_import_service
from app.services.portfolio_service import portfolio_service
from app.utils.holding_review import holding_review_digest
from app.utils.screenshot_errors import screenshot_failure_message


class AgentHoldingImportService:
    """网页与移动端共用现有识别队列和持仓复核流程."""

    async def upload(
        self, user_id: int, session_id: str, account_id: int | None, files: list[UploadFile]
    ) -> ScreenshotImportAccepted:
        """只创建识别草稿，不写正式持仓；会话 ID 由认证依赖提供."""
        record = await holding_import_service.create_screenshot_import(
            user_id, account_id, files, chat_session_id=session_id, defer_processing=True
        )
        return ScreenshotImportAccepted(import_id=record.id, status="UPLOADED", image_count=record.image_count)

    async def accounts(self, user_id: int) -> list[HoldingAccountOption]:
        """目标列表只来自当前认证用户，空列表要求用户先创建账户."""
        return [
            HoldingAccountOption(id=account.id, name=account.name)
            for account in await portfolio_service.list_accounts(user_id)
        ]

    async def resolve_account(self, user_id: int, instruction: str, account_id: int | None = None) -> int | None:
        """接收显式 ID 或本轮指令中的明确账户名，不用历史、图片文字或第一个账户兜底."""
        if account_id is not None:
            await portfolio_service.ensure_account(user_id, account_id)
            return account_id
        matches = []
        destinations = []
        clauses = re.split(r"[，,。；;\n]", instruction)
        for account in await self.accounts(user_id):
            if not account.name or account.name not in instruction:
                continue
            relevant = [clause.strip() for clause in clauses if account.name in clause]
            if any(re.search(r"不要|别|不能|不是|除外|排除|不导入|不同步|不需要|无需", clause) for clause in relevant):
                continue
            if any(
                re.search(r"导入|同步|更新|覆盖|添加|放到|存入", clause)
                or clause in {account.name, f"{account.name}账户", f"{account.name}持仓"}
                for clause in relevant
            ):
                matches.append(account.id)
                if any(
                    re.search(r"(?:到|至|进|入)\s*(?:我的)?\s*" + re.escape(account.name), clause)
                    for clause in relevant
                ):
                    destinations.append(account.id)
        if len(matches) > 1 and re.search(r"或|还是|和|、", instruction):
            return None
        if destinations:
            return destinations[0] if len(destinations) == 1 else None
        return matches[0] if len(matches) == 1 else None

    async def start(self, user_id: int, session_id: str, import_id: str) -> None:
        """子图启动识别前验证会话归属，不接受模型提供的本地路径."""
        await self.detail(user_id, session_id, import_id)
        await holding_import_service.start_screenshot_import(user_id, import_id)

    async def select_account(self, user_id: int, session_id: str, import_id: str, account_id: int) -> None:
        """只绑定目标草稿；正式持仓仍必须经过后续人工复核."""
        await portfolio_service.ensure_account(user_id, account_id)
        async with transaction_scope():
            record = await import_repository.get_import(user_id, import_id, for_update=True)
            if record is None or record.chat_session_id != session_id or record.import_type != "SCREENSHOT":
                raise ImportStateError("import_not_found")
            if record.status in {"APPLIED", "CANCELLED", "PARSE_FAILED"}:
                raise ImportStateError("import_account_not_editable")
            record.account_id = account_id

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
        if detail.account_id is None:
            raise ImportStateError("import_account_required")
        account = await portfolio_service.ensure_account(user_id, detail.account_id)
        review = HoldingImportReview(
            import_id=detail.id,
            account_id=detail.account_id,
            account_name=account.name,
            image_count=detail.image_count,
            items=detail.items,
            review_digest=holding_review_digest(detail),
        )
        if detail.error_message:
            _, notice = screenshot_failure_message(detail.error_message)
            review.notice += " 部分图片未识别出持仓，请核对本次草稿是否完整。" + notice.replace("持仓未更新。", "")
        return review

    async def decide(
        self, user_id: int, session_id: str, import_id: str, *, decision: str, review_digest: str | None
    ) -> dict:
        """仅供已验证 LangGraph 中断的人工 HTTP 端点调用."""
        detail = await self.detail(user_id, session_id, import_id)
        if decision == "cancel":
            if detail.status != "CANCELLED":
                await holding_import_service.delete_import(user_id, import_id)
            return {"decision": "cancel", "import_id": import_id}
        if decision != "confirm":
            raise ImportStateError("invalid_import_decision")
        if review_digest is None or detail.account_id is None:
            raise ImportStateError("import_confirmation_requires_review")
        result = await holding_import_service.confirm_import(user_id, import_id, expected_review_digest=review_digest)
        return {"decision": "confirm", "import_id": import_id, **result}


agent_holding_import_service = AgentHoldingImportService()


def get_agent_holding_import_service() -> AgentHoldingImportService:
    """FastAPI 的服务依赖，客户端接入测试可独立替换它."""
    return agent_holding_import_service
