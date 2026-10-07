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
)

from app.api.v1.auth import AuthIdentity, get_current_identity
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.schemas.base import BaseResponse
from app.services.llm import llm_service, profile_store
from app.services.llm.registry import LLMRegistry

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


def _llm_profiles_response() -> LlmProfilesResponse:
    name, model, base_url, api_key = zip(
        LLMRegistry.get_all_names(),
        LLMRegistry.get_all_models(),
        [str(e["base_url"]) for e in LLMRegistry.LLMS],
        [str(e["api_key"]) for e in LLMRegistry.LLMS],
        strict=True,
    )
    profiles = [
        LlmProfileItem(name=name, model=model, base_url=base_url, key_hint=profile_store.key_hint(api_key))
        for name, model, base_url, api_key in zip(name, model, base_url, api_key, strict=True)
    ]
    return LlmProfilesResponse(active=llm_service.active_model_name(), profiles=profiles)


@router.get("/llm/profiles", response_model=LlmProfilesResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def list_llm_profiles(
    request: Request,
    identity: AuthIdentity = Depends(get_current_identity),
) -> LlmProfilesResponse:
    """列出已配置的 LLM 供应商档案以及当前生效的那个."""
    logger.info("llm_profiles_listed", user_id=identity.user_id, active=llm_service.active_model_name())
    return _llm_profiles_response()


@router.post("/llm/settings", response_model=LlmProfilesResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def update_llm_settings(
    request: Request,
    body: LlmSettingsUpdate,
    identity: AuthIdentity = Depends(get_current_identity),
) -> LlmProfilesResponse:
    """用设置页提交的列表整体替换供应商档案.

    写入服务端的档案文件并热重建注册表；只要原生效档案仍在新列表里就继续生效。
    已存在的档案若提交时留空 API Key，则沿用服务端已存的密钥。
    """
    if not body.profiles:
        raise HTTPException(status_code=400, detail="至少需要保留一个供应商档案")

    saved = profile_store.load_profiles()
    registry_keys = {str(e["name"]): str(e["api_key"]) for e in LLMRegistry.LLMS}
    merged: list[dict] = []
    seen: set[str] = set()
    for profile in body.profiles:
        item = {
            "name": profile.name.strip(),
            "model": profile.model.strip(),
            "base_url": profile.base_url.strip(),
            "api_key": profile.api_key.strip(),
        }
        item = dict(profile_store.keep_existing_key(item, saved, registry_keys))
        if not all(item.values()):
            missing = "API Key" if item["api_key"] == "" else "必填字段"
            raise HTTPException(
                status_code=400,
                detail=f"档案 '{item['name'] or '?'}' 缺少{missing}（新档案必须提供 API Key）",
            )
        if item["name"] in seen:
            raise HTTPException(status_code=400, detail=f"档案名称重复：{item['name']}")
        seen.add(item["name"])
        merged.append(item)

    active_name = llm_service.active_model_name()
    try:
        LLMRegistry.rebuild(merged)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    profile_store.save_profiles(merged)
    llm_service.refresh_profiles(active_name=active_name)

    logger.info(
        "llm_settings_updated",
        user_id=identity.user_id,
        count=len(merged),
        active=llm_service.active_model_name(),
    )
    return _llm_profiles_response()


@router.post("/llm/switch", response_model=LlmProfilesResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["agent"][0])
async def switch_llm_profile(
    request: Request,
    body: LlmSwitchRequest,
    identity: AuthIdentity = Depends(get_current_identity),
) -> LlmProfilesResponse:
    """运行时切换生效的 LLM 供应商档案（全局生效，无需重启）."""
    try:
        llm_service.activate_model(body.name)
        logger.info(
            "llm_profile_switched",
            user_id=identity.user_id,
            session_id=identity.session_id,
            active=body.name,
        )
        return _llm_profiles_response()
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
    base_url = body.base_url.strip().rstrip("/")
    if not base_url or not body.api_key.strip():
        raise HTTPException(status_code=400, detail="接口地址和 API Key 都必填")

    try:
        async with AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {body.api_key.strip()}"},
            )
            if response.status_code != 200:
                detail = f"厂家返回 {response.status_code}"
                payload = response.json()
                message = (payload.get("error") or {}).get("message") or payload.get("message")
                if message:
                    detail = f"{detail}：{message}"
                raise HTTPException(status_code=502, detail=detail)
            data = response.json().get("data", [])
            models = sorted(str(m["id"]) for m in data)
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
