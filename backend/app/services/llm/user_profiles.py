"""个人模型配置服务：基础 GLM Flash 只读，用户档案存数据库."""

from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.core.config import settings
from app.repositories.user_llm_repository import user_llm_repository
from app.services.llm.credentials import decrypt_key, encrypt_key
from app.services.llm.profile_store import key_hint
from app.services.llm.registry import LLMRegistry

DEFAULT_PROFILE_NAME = "默认 GLM Flash"


class PersonalProfile(BaseModel):
    """个人供应商输入与请求内执行配置，不用于直接响应明文密钥."""

    name: str
    model: str
    base_url: str
    api_key: str = Field(default="", repr=False)


class PublicProfile(BaseModel):
    """供应商列表的安全展示信息."""

    name: str
    model: str
    base_url: str
    key_hint: str = ""
    read_only: bool = False


class UserProfiles(BaseModel):
    """用户可选择的基础档案、个人档案及当前选择."""

    active: str
    profiles: list[PublicProfile]


def basic_profile() -> PersonalProfile:
    """只使用配置中的 GLM Flash 基础模型，不暴露其他服务器档案."""
    candidate = next(
        (
            entry
            for entry in LLMRegistry.LLMS
            if entry["model"] == settings.BASIC_LLM_MODEL
            and str(entry["base_url"]).rstrip("/") == settings.BASIC_LLM_BASE_URL.rstrip("/")
        ),
        None,
    )
    return PersonalProfile(
        name=DEFAULT_PROFILE_NAME,
        model=settings.BASIC_LLM_MODEL,
        base_url=settings.BASIC_LLM_BASE_URL,
        api_key=settings.BASIC_LLM_API_KEY or (str(candidate["api_key"]) if candidate else ""),
    )


class UserProfileService:
    """所有读写只针对调用方用户，绝不重建全局 LLMRegistry."""

    async def _load(self, user_id: int) -> tuple[list[PersonalProfile], str]:
        row = await user_llm_repository.get(user_id)
        if row is None:
            return [], DEFAULT_PROFILE_NAME
        profiles = [
            PersonalProfile(
                name=entry["name"],
                model=entry["model"],
                base_url=entry["base_url"],
                api_key=decrypt_key(user_id, entry["encrypted_api_key"]),
            )
            for entry in row.profiles
        ]
        active = (
            row.active
            if row.active in {DEFAULT_PROFILE_NAME, *(profile.name for profile in profiles)}
            else DEFAULT_PROFILE_NAME
        )
        return profiles, active

    async def list_profiles(self, user_id: int) -> UserProfiles:
        """列出基础模型及本用户的个人模型，基础密钥不回传掩码."""
        profiles, active = await self._load(user_id)
        basic = basic_profile()
        return UserProfiles(
            active=active,
            profiles=[
                PublicProfile(name=basic.name, model=basic.model, base_url=basic.base_url, read_only=True),
                *(
                    PublicProfile(name=p.name, model=p.model, base_url=p.base_url, key_hint=key_hint(p.api_key))
                    for p in profiles
                ),
            ],
        )

    async def save_profiles(self, user_id: int, profiles: list[PersonalProfile]) -> UserProfiles:
        """整体替换本用户个人档案；可全部删除并回到基础模型."""
        saved, active = await self._load(user_id)
        saved_by_name = {profile.name: profile for profile in saved}
        encrypted = []
        names: set[str] = set()
        for profile in profiles:
            name, model, base_url = profile.name.strip(), profile.model.strip(), profile.base_url.strip().rstrip("/")
            if not name or not model or not base_url:
                raise ValueError("档案名称、模型和接口地址都是必填项")
            if name == DEFAULT_PROFILE_NAME:
                raise ValueError("基础 GLM Flash 档案不能修改，请创建个人档案")
            if name in names:
                raise ValueError(f"档案名称重复：{name}")
            url = urlparse(base_url)
            if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
                raise ValueError("接口地址必须是有效的 HTTP 或 HTTPS 地址")
            previous = saved_by_name.get(name)
            api_key = profile.api_key.strip()
            if not api_key:
                if previous is None:
                    raise ValueError(f"新档案 '{name}' 需要填写 API Key")
                if previous.base_url.rstrip("/") != base_url:
                    raise ValueError("接口地址已改变，请重新填写 API Key")
                api_key = previous.api_key
            names.add(name)
            encrypted.append(
                {
                    "name": name,
                    "model": model,
                    "base_url": base_url,
                    "encrypted_api_key": encrypt_key(user_id, api_key),
                }
            )
        if active not in names:
            active = DEFAULT_PROFILE_NAME
        await user_llm_repository.save(user_id, encrypted, active)
        return await self.list_profiles(user_id)

    async def switch_profile(self, user_id: int, name: str) -> UserProfiles:
        """只切换本用户的默认档案，不能通过名称选中其他用户的档案."""
        if not await user_llm_repository.set_active(user_id, name):
            raise ValueError("未找到当前用户的模型档案")
        return await self.list_profiles(user_id)

    async def execution_profiles(self, user_id: int) -> list[dict[str, str]]:
        """冻结本次请求的模型选择，仅在当前用户模型与基础模型间降级."""
        profiles, active = await self._load(user_id)
        basic = basic_profile()
        selected = next((profile for profile in profiles if profile.name == active), basic)
        usable = [selected]
        if selected.name != basic.name and basic.api_key:
            usable.append(basic)
        if not selected.api_key:
            raise RuntimeError("基础 GLM Flash 尚未配置 API Key，请配置基础模型或添加个人模型")
        return [profile.model_dump() for profile in usable]


user_profile_service = UserProfileService()
