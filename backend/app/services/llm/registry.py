"""LLM 模型注册表，实例在启动时就全部预建好.

支持多套可随时切换的厂商 profile：``FUND_LLM_PROFILES``（JSON 数组）里
每个条目是一个 OpenAI 兼容数据源；没有配置时退回扁平的 FUND_LLM_* 变量。
设置页保存后会调用 :meth:`LLMRegistry.rebuild` 原地替换全部条目。
"""

import hashlib
import json
from collections import OrderedDict
from typing import (
    Any,
    Dict,
    List,
    cast,
)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import settings
from app.core.logging import logger
from app.services.llm import profile_store
from app.services.llm.chat_model import ProgressChatOpenAI

# 一个 profile 必须带齐这四个字段才算可用
_PROFILE_FIELDS = ("name", "model", "base_url", "api_key")


def _new_chat_model(model: str, api_key: str, base_url: str, *, report_mode: bool = False, **kwargs) -> ChatOpenAI:
    """用应用级的公共默认参数构造一个 ChatOpenAI.

    调用方显式传入的 kwargs 优先于默认值；``max_tokens`` 一律放进
    ``extra_body`` 传输，因为这里配的厂商都只认这一个入口。
    """
    params: dict[str, Any] = {
        "temperature": settings.DEFAULT_LLM_TEMPERATURE,
        "timeout": settings.LLM_REQUEST_TIMEOUT,
        # 选择/继续接口用 graph.ainvoke，不能依赖 messages 流的隐式回调。
        # ainvoke 仍汇总返回完整结果，底层流式让首段/无进展超时观察到真实进度。
        "streaming": True,
        # 重试由 service.py 的 tenacity 统一管理，避免 SDK 隐式重试叠加。
        "max_retries": 0,
    }
    kwargs = dict(kwargs)
    max_tokens = kwargs.pop("max_tokens", None)
    extra_body = dict(kwargs.pop("extra_body", None) or {})
    extra_body["max_tokens"] = max_tokens or settings.MAX_TOKENS
    if report_mode and model.lower().startswith("glm-5.3"):
        # GLM-5.3 强制推理，默认 max 易耗尽报告正文额度；取证/角色研究保持原配置。
        # https://docs.z.ai/guides/capabilities/thinking
        extra_body.setdefault("reasoning_effort", "low")
    params.update(kwargs)
    return ProgressChatOpenAI(
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
        extra_body=extra_body,
        **params,
    )


# ChatOpenAI 首次调用会懒建一个 AsyncOpenAI + httpx 连接池，而且没有任何关闭入口。
# 逐请求新建就等于每轮对话重付一次 TCP/TLS 握手，并留下一批只能等 GC 回收的空闲
# 套接字。这里按 (模型, 接口, 密钥, 参数) 复用，容量有界，淘汰的实例交给 GC。
_MODEL_CACHE_MAX = 32
_MODEL_CACHE: OrderedDict[tuple, ChatOpenAI] = OrderedDict()


def _build_chat_model(model: str, api_key: str, base_url: str, **kwargs) -> ChatOpenAI:
    """返回可复用的 ChatOpenAI 实例；参数不同的调用不会共享同一个连接池."""
    cache_key = (
        model,
        base_url,
        hashlib.sha256(api_key.encode()).hexdigest(),
        json.dumps(kwargs, sort_keys=True, default=str),
    )
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        _MODEL_CACHE.move_to_end(cache_key)
        return cached
    built = _new_chat_model(model, api_key, base_url, **kwargs)
    _MODEL_CACHE[cache_key] = built
    while len(_MODEL_CACHE) > _MODEL_CACHE_MAX:
        _MODEL_CACHE.popitem(last=False)
    return built


def _parse_profiles() -> list[dict]:
    """给出校验过的厂商 profiles：设置文件 → 环境变量 → 扁平配置.

    设置界面会把结果写进文件，用户在文件里表达的意愿高于环境变量。
    """
    raw = settings.LLM_PROFILES_JSON
    profiles: list[dict] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list) or not parsed:
                raise ValueError("FUND_LLM_PROFILES must be a non-empty JSON array")
            for item in parsed:
                if not isinstance(item, dict):
                    raise ValueError("every profile must be a JSON object")
                missing = [field for field in _PROFILE_FIELDS if not item.get(field)]
                if missing:
                    raise ValueError(f"profile is missing fields: {missing}")
                profiles.append(item)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("llm_profiles_env_invalid", error=str(e))
    if not profiles:
        # 环境变量缺省/非法时，退回扁平配置合成一个档位
        profiles = [
            {
                "name": settings.DEFAULT_LLM_MODEL,
                "model": settings.DEFAULT_LLM_MODEL,
                "base_url": settings.OPENAI_BASE_URL,
                "api_key": settings.OPENAI_API_KEY,
            }
        ]
    saved = profile_store.load_profiles()
    if saved:
        profiles = saved
    return profiles


def _build_registry() -> list[dict]:
    """按校验过的 profiles 预建全部 ChatOpenAI 实例，重名 profile 跳过."""
    entries: list[dict] = []
    seen: set[str] = set()
    for profile in _parse_profiles():
        if profile["name"] in seen:
            logger.warning("llm_profile_duplicate_name_skipped", name=profile["name"])
            continue
        seen.add(profile["name"])
        entries.append(
            {
                "name": profile["name"],
                "model": profile["model"],
                "base_url": profile["base_url"],
                "api_key": profile["api_key"],
                "llm": _build_chat_model(
                    model=profile["model"],
                    api_key=profile["api_key"],
                    base_url=profile["base_url"],
                ),
            }
        )
    return entries


class LLMRegistry:
    """可用 LLM 模型的注册表，实例都已预先建好.

    维护一份 LLM 配置列表，按 profile 名称取用，取的时候可以带上参数覆盖。
    """

    LLMS: List[Dict[str, Any]] = _build_registry()

    @classmethod
    def rebuild(cls, profiles: List[Dict[str, Any]]) -> List[str]:
        """运行时替换全部注册表条目（设置界面保存走的正是这条路）.

        逐个 profile 校验并新建 ChatOpenAI 实例；共享列表是原地改的，
        所以外部已持有的 ``LLMS`` 引用不会失效。

        Returns:
            新注册表里的全部 profile 名称。

        Raises:
            ValueError: 某个 profile 缺字段、重名，或一个都没有。
        """
        entries: list[dict] = []
        seen: set[str] = set()
        for profile in profiles:
            missing = [field for field in _PROFILE_FIELDS if not profile.get(field)]
            if missing:
                raise ValueError(f"profile '{profile.get('name', '?')}' is missing fields: {missing}")
            if profile["name"] in seen:
                raise ValueError(f"duplicate profile name: {profile['name']}")
            seen.add(profile["name"])
            entries.append(
                {
                    "name": profile["name"],
                    "model": profile["model"],
                    "base_url": profile["base_url"],
                    "api_key": profile["api_key"],
                    "llm": _build_chat_model(
                        model=profile["model"],
                        api_key=profile["api_key"],
                        base_url=profile["base_url"],
                    ),
                }
            )
        if not entries:
            raise ValueError("at least one profile is required")
        cls.LLMS[:] = entries
        logger.info("llm_registry_rebuilt", profiles=[entry["name"] for entry in entries])
        return cls.get_all_names()

    @classmethod
    def get(cls, model_name: str, **kwargs) -> BaseChatModel:
        """按 profile 名称取一个 LLM，可选地覆盖部分参数.

        只要传了 kwargs，就新建一个应用了这些覆盖的 ChatOpenAI 返回，
        注册表里共享的那条记录不受影响。显式传入的 kwargs 覆盖默认值。

        Args:
            model_name: profile 名称（找不到时兜底按模型 id 匹配一次）。
            **kwargs: 要覆盖的模型参数。

        Returns:
            BaseChatModel 实例。

        Raises:
            ValueError: 该名称没有注册。
        """
        model_entry = next((e for e in cls.LLMS if e["name"] == model_name), None)

        if not model_entry:
            available = ", ".join(e["name"] for e in cls.LLMS)
            raise ValueError(f"model '{model_name}' not found in registry. available models: {available}")

        if kwargs:
            # 用条目里的模型 id / 密钥重建，注册表共享的那条不受影响
            logger.debug(
                "creating_llm_with_custom_args",
                model_name=model_name,
                model=model_entry["model"],
                custom_args=list(kwargs.keys()),
            )
            return cast(
                BaseChatModel,
                _build_chat_model(
                    model=cast(str, model_entry["model"]),
                    api_key=cast(str, model_entry["api_key"]),
                    base_url=cast(str, model_entry["base_url"]),
                    **kwargs,
                ),
            )

        logger.debug("using_default_llm_instance", model_name=model_name)
        return model_entry["llm"]

    @classmethod
    def get_all_names(cls) -> List[str]:
        """按顺序返回全部已注册的 profile 名称.

        Returns:
            模型名称字符串列表。
        """
        return [e["name"] for e in cls.LLMS]

    @classmethod
    def get_all_models(cls) -> List[str]:
        """按顺序返回全部已注册 profile 的模型 id."""
        return [e["model"] for e in cls.LLMS]

    @classmethod
    def get_model_at_index(cls, index: int) -> Dict[str, Any]:
        """返回指定位置的模型条目，越界时绕回第 0 个.

        Args:
            index: 在注册表中的下标。

        Returns:
            注册表条目字典。
        """
        if 0 <= index < len(cls.LLMS):
            return cls.LLMS[index]
        return cls.LLMS[0]

    @classmethod
    def default_index(cls) -> int:
        """配置里指定的默认模型所在的下标.

        先比对 profile 名称，再比对模型 id，因此名字是展示名、模型却是
        ``FUND_LLM_MODEL`` 的那个 profile 依然能被选为启动默认。
        """
        for index, entry in enumerate(cls.LLMS):
            if entry["name"] == settings.DEFAULT_LLM_MODEL:
                return index
        for index, entry in enumerate(cls.LLMS):
            if entry["model"] == settings.DEFAULT_LLM_MODEL:
                return index
        return 0
