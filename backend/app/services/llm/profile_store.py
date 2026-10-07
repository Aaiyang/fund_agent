"""LLM 厂商 profile 的服务端持久化.

设置界面会把完整的 profile 列表写到这里；这个文件优先于
``FUND_LLM_PROFILES`` 环境变量，所以界面上的改动能挺过重启。API key 只留在
这个被 gitignore 的文件里——绝不会把完整内容返回给客户端。
"""

import json
import os
import tempfile
from typing import Any

from app.core.config import settings
from app.core.logging import logger

PROFILE_FIELDS = ("name", "model", "base_url", "api_key")


def _settings_path() -> str:
    return settings.LLM_PROFILES_FILE


def load_profiles() -> list[dict[str, Any]]:
    """从磁盘读取已存的 profiles；文件缺失或读坏时返回空列表."""
    path = _settings_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("llm_profiles_file_unreadable_ignoring", path=path, error=str(e))
        return []
    if not isinstance(data, list):
        logger.warning("llm_profiles_file_invalid_ignoring", path=path)
        return []
    return [p for p in data if isinstance(p, dict)]


def save_profiles(profiles: list[dict[str, Any]]) -> None:
    """原子落盘 profiles（写临时文件再整体替换）."""
    path = _settings_path()
    directory = os.path.dirname(path) or "."
    fd, temp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except OSError:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    logger.info("llm_profiles_saved", path=path, count=len(profiles))


def keep_existing_key(
    profile: dict[str, Any],
    saved: list[dict[str, Any]],
    fallback_keys: dict[str, str] | None = None,
) -> dict[str, Any]:
    """用同名 profile 把空的 ``api_key`` 补上.

    查找顺序：先查已落盘的 profile 文件，再看当前注册表——从环境变量来的
    profile，它的 key 客户端根本拿不到，不这么回退的话，第一次在设置界面保存
    就得让用户把 key 重新敲一遍。
    """
    if profile.get("api_key"):
        return profile
    previous = next((p for p in saved if p.get("name") == profile.get("name")), None)
    key = (previous or {}).get("api_key", "")
    if not key and fallback_keys:
        key = fallback_keys.get(str(profile.get("name")), "")
    return {**profile, "api_key": key}


def key_hint(api_key: str) -> str:
    """给界面用的打码预览——绝不返回完整 key."""
    return f"{api_key[:4]}****" if api_key else ""
