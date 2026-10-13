"""应用限流配置.

本模块用 slowapi 配置限流，默认额度取自应用配置，
限流按客户端远端 IP 计数。

配置了 Valkey 时把它作为分布式存储后端，
这样多个应用实例之间限流额度才能正确共享。
"""

from slowapi import Limiter
from starlette.requests import Request

from app.core.cache import REDIS_AVAILABLE
from app.core.config import Environment, settings
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

# 直连来源在这些地址里时，才采信它写来的 X-Forwarded-For。
_TRUSTED_PROXIES = set(settings.RATE_LIMIT_TRUSTED_PROXIES)
if not _TRUSTED_PROXIES and settings.ENVIRONMENT in (Environment.PRODUCTION, Environment.STAGING):
    logger.warning(
        "rate_limit_trusted_proxies_missing",
        hint="反向代理部署需设置 RATE_LIMIT_TRUSTED_PROXIES，否则全站共用代理 IP 的额度",
    )


def rate_limit_key(request: Request) -> str:
    """返回限流计数用的客户端标识.

    挂在 nginx/SLB 后面时 ``request.client.host`` 是代理地址，全站会共用同一份
    额度（生产默认 50/hour 会立刻把正常用户挡在门外）。这里只在直连来源确实是
    已登记代理时才取 XFF 最左段——该头由客户端可控，不能无条件相信。
    """
    peer = request.client.host if request.client else "unknown"
    if _TRUSTED_PROXIES and peer in _TRUSTED_PROXIES:
        forwarded = request.headers.get("x-forwarded-for", "")
        client = forwarded.split(",")[0].strip()
        if client:
            return client
    return peer


# 初始化限流器（没有 Valkey 就用进程内存储）
limiter = Limiter(
    key_func=rate_limit_key,
    default_limits=settings.RATE_LIMIT_DEFAULT,  # pyright: ignore[reportArgumentType]
    storage_uri=_storage_uri,
)
