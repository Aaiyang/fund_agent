"""Agent API（MVP spec 第 4 章）.

Phase 1 保持 LangGraph 基础设施（graph、checkpointer、LLM service、工具
注册、Langfuse）就绪，但 Agent 对话端点仍为占位。LLM 供应商档案的
查看/保存/切换/探测已在此先行开放（设置页用）。未来的工具只能经由
领域服务取业务数据——不允许直连数据库（spec 4.4）。
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from fastapi.responses import JSONResponse
from httpx import (
    AsyncClient,
    HTTPError as HttpxError,
    Response,
)

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.schemas.base import BaseResponse
from app.services.llm.user_profiles import PersonalProfile, UserProfiles, user_profile_service
from app.utils.provider_url import validate_provider_base_url

router = APIRouter()


class AgentChatRequest(BaseResponse):
    """POST /agent/chat 的请求体（预留）."""

    message: str
    fund_code: str | None = None


class LlmProfileItem(BaseResponse):
    """一个可切换的供应商档案；API Key 只做掩码，绝不回传明文."""

    name: str
    model: str
    base_url: str
    key_hint: str = ""
    read_only: bool = False


class LlmProfilesResponse(BaseResponse):
    """GET /agent/llm/profiles 响应——档案列表加上当前生效的那一个."""

    active: str
    profiles: list[LlmProfileItem]


class LlmProfileUpdate(BaseResponse):
    """保存设置时提交的单个档案。api_key 留空表示沿用已存的 Key."""

    name: str
    model: str
    base_url: str
    api_key: str = ""


class LlmSettingsUpdate(BaseResponse):
    """POST /agent/llm/settings 请求——整份替换现有档案列表."""

    profiles: list[LlmProfileUpdate]


class LlmSwitchRequest(BaseResponse):
    """POST /agent/llm/switch 请求体."""

    name: str


class LlmModelsRequest(BaseResponse):
    """POST /agent/llm/models 请求——探测某厂家的模型列表."""

    base_url: str
    api_key: str


class LlmModelsResponse(BaseResponse):
    """POST /agent/llm/models 响应——该 Key 实际可用的模型 id."""

    models: list[str]


def _llm_profiles_response(data: UserProfiles) -> LlmProfilesResponse:
    return LlmProfilesResponse(
        active=data.active, profiles=[LlmProfileItem(**profile.model_dump()) for profile in data.profiles]
    )


def _safe_json_object(response: Response) -> dict:
    """非 JSON、非对象的响应体一律当空对象，不让解析异常变成 500."""
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _vendor_error_message(payload: dict) -> str | None:
    """只取厂家错误里可安全展示的一句话，其余响应体不回传给客户端."""
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    message = payload.get("message")
    return message if isinstance(message, str) else None


@router.get("/llm/profiles", response_model=LlmProfilesResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def list_llm_profiles(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> LlmProfilesResponse:
    """列出已配置的 LLM 供应商档案以及当前生效的那个."""
    data = await user_profile_service.list_profiles(identity.user_id)
    logger.info("llm_profiles_listed", user_id=identity.user_id, active=data.active)
    return _llm_profiles_response(data)


@router.post("/llm/settings", response_model=LlmProfilesResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def update_llm_settings(
    request: Request,
    body: LlmSettingsUpdate,
    identity: AuthIdentity = Depends(get_current_identity),
) -> LlmProfilesResponse:
    """只替换当前用户的个人档案；空列表表示仅使用基础模型."""
    try:
        data = await user_profile_service.save_profiles(
            identity.user_id,
            [
                PersonalProfile(name=p.name, model=p.model, base_url=p.base_url, api_key=p.api_key)
                for p in body.profiles
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("llm_settings_updated", user_id=identity.user_id, count=len(body.profiles), active=data.active)
    return _llm_profiles_response(data)


@router.post("/llm/switch", response_model=LlmProfilesResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def switch_llm_profile(
    request: Request,
    body: LlmSwitchRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> LlmProfilesResponse:
    """切换当前用户的模型选择，不影响其他用户及已开始的请求."""
    try:
        data = await user_profile_service.switch_profile(identity.user_id, body.name)
        logger.info(
            "llm_profile_switched",
            user_id=identity.user_id,
            session_id=identity.session_id,
            active=body.name,
        )
        return _llm_profiles_response(data)
    except ValueError as e:
        logger.warning("llm_profile_switch_rejected", user_id=identity.user_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/llm/models", response_model=LlmModelsResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def list_vendor_models(
    request: Request,
    body: LlmModelsRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> LlmModelsResponse:
    """查询某厂家 OpenAI 兼容的 ``/models`` 接口.

    让设置页直接列出这把 Key 真正可用的模型，而不是写死一份猜测。
    """
    if not body.base_url.strip() or not body.api_key.strip():
        raise HTTPException(status_code=400, detail="接口地址和 API Key 都必填")
    # 这是服务端替用户发起的请求，先把可达范围框住，否则它就是访问内网的跳板。
    try:
        base_url = validate_provider_base_url(
            body.base_url, allow_private_network=settings.LLM_PROVIDER_ALLOW_PRIVATE_NETWORK
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        async with AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {body.api_key.strip()}"},
            )
            payload = _safe_json_object(response)
            if response.status_code != 200:
                detail = f"厂家返回 {response.status_code}"
                message = _vendor_error_message(payload)
                if message:
                    detail = f"{detail}：{message}"
                raise HTTPException(status_code=502, detail=detail)
            data = payload.get("data", [])
            models = sorted(str(item["id"]) for item in data if isinstance(item, dict) and "id" in item)
            return LlmModelsResponse(models=models)
    except HttpxError as e:
        logger.warning("llm_vendor_models_unreachable", error=str(e))
        raise HTTPException(status_code=502, detail=f"无法连接厂家接口：{e}") from e
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=502, detail=f"厂家返回的模型列表无法解析：{e}") from e


@router.post("/chat")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def agent_chat(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> JSONResponse:
    """预留的 agent 端点——Phase 7 之前一律返回 501（spec 4.2）."""
    logger.info(
        "agent_chat_placeholder_called",
        session_id=identity.session_id,
        user_id=identity.user_id,
    )
    return JSONResponse(
        status_code=501,
        content={
            "detail": "agent_not_implemented",
            "message": "Agent 能力将在后续阶段开放（Phase 7）",
        },
    )
