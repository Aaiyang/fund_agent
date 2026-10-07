"""应用限流配置.

本模块用 slowapi 配置限流，默认额度取自应用配置，
限流按客户端远端 IP 计数。

配置了 Valkey 时把它作为分布式存储后端，
这样多个应用实例之间限流额度才能正确共享。
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.cache import REDIS_AVAILABLE
from app.core.config import settings
from app.core.logging import logger

# 配了 Valkey 就拼出它的 storage URI。redis 是可选依赖（`cache` extra），
# 缺包时退回进程内存储，而不是让限流在 import 阶段抛 ConfigurationError。
_storage_uri = None
if settings.VALKEY_HOST and REDIS_AVAILABLE:
    _password_part = f":{settings.VALKEY_PASSWORD}@" if settings.VALKEY_PASSWORD else ""
    _storage_uri = f"redis://{_password_part}{settings.VALKEY_HOST}:{settings.VALKEY_PORT}/{settings.VALKEY_DB}"
    logger.info("rate_limiter_using_valkey", host=settings.VALKEY_HOST, port=settings.VALKEY_PORT)
elif settings.VALKEY_HOST:
    logger.warning(
        "rate_limiter_valkey_configured_but_redis_missing",
        hint="install with: uv add redis --optional cache",
    )

# 初始化限流器（没有 Valkey 就用进程内存储）
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=settings.RATE_LIMIT_DEFAULT,  # pyright: ignore[reportArgumentType]
    storage_uri=_storage_uri,
)
