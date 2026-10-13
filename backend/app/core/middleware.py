"""自定义中间件：采集指标等横切关注点."""

import json
import time
import tracemalloc
from typing import (
    TYPE_CHECKING,
    Callable,
    override,
)

from asgi_correlation_id import correlation_id
from fastapi import Request
from jose import (
    JWTError,
    jwt,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import (
    bind_context,
    clear_context,
    logger,
)
from app.core.metrics import (
    http_request_duration_seconds,
    http_requests_total,
)

if TYPE_CHECKING:
    from pyinstrument import Profiler  # pyright: ignore[reportMissingImports]
    from pyinstrument.renderers import JSONRenderer  # pyright: ignore[reportMissingImports]

    PYINSTRUMENT_AVAILABLE = True
else:
    try:
        from pyinstrument import Profiler
        from pyinstrument.renderers import JSONRenderer

        PYINSTRUMENT_AVAILABLE = True
    except ImportError:
        Profiler = None
        JSONRenderer = None
        PYINSTRUMENT_AVAILABLE = False


class MetricsMiddleware(BaseHTTPMiddleware):
    """采集 HTTP 请求指标的中间件."""

    @staticmethod
    def _endpoint_label(request: Request) -> str:
        """用路由模板当标签，而不是实际路径.

        实际路径里有 import_id(uuid)、session_id、基金代码，直接当 Prometheus
        标签会让时间序列随流量无界增长，抓取端与本进程内存一起被打爆。
        ``scope["route"]`` 由 FastAPI 在路由命中后写入，所以只能在请求处理
        结束后（finally 里）读取。
        """
        route = request.scope.get("route")
        path = getattr(route, "path", None)
        return str(path) if path else "unmatched"

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """为每个请求记录指标.

        Args:
            request: 进来的请求
            call_next: 下一个中间件或路由处理函数

        Returns:
            Response: 应用返回的响应
        """
        start_time = time.time()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            raise
        finally:
            duration = time.time() - start_time

            # 记录指标
            endpoint = self._endpoint_label(request)
            http_requests_total.labels(method=request.method, endpoint=endpoint, status=status_code).inc()

            http_request_duration_seconds.labels(method=request.method, endpoint=endpoint).observe(duration)

        return response


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """把 user_id 与 session_id 注入日志上下文的中间件."""

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """从带凭证的请求里取出 user_id 和 session_id，写入日志上下文.

        Args:
            request: 进来的请求
            call_next: 下一个中间件或路由处理函数

        Returns:
            Response: 应用返回的响应
        """
        try:
            # 先清掉上一个请求可能残留的上下文
            clear_context()

            # 从 Authorization 头里取 token
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]

                try:
                    # 解出 token 里的 session_id（存放在 "sub" 声明中）
                    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
                    session_id = payload.get("sub")

                    if session_id:
                        # 把 session_id 绑进日志上下文
                        bind_context(session_id=session_id)

                        # user_id 要等鉴权之后才能拿到，来自 request state
                        # 只要该接口用了认证，依赖注入就会把它设置好
                        # 这里等请求处理完再检查

                except JWTError:
                    # token 无效，但不在此处判失败 —— 交给鉴权依赖去处理
                    pass

            # 处理请求
            response = await call_next(request)

            # 请求处理完后，检查鉴权依赖有没有把用户信息写进 request state
            if hasattr(request.state, "user_id"):
                bind_context(user_id=request.state.user_id)

            return response

        finally:
            # 请求结束后必须清空上下文，否则会串到其他请求的日志里
            clear_context()


class ProfilingMiddleware(BaseHTTPMiddleware):
    """用 pyinstrument 自动逐请求剖析的中间件.

    只在 DEBUG=true 时生效。它对每个请求做剖析，请求耗时超过
    PROFILING_THRESHOLD_SECONDS 时把 HTML 火焰图存进 PROFILING_DIR。文件名取
    {request_id}.html，方便和日志对上。/tmp 由操作系统自动清理。
    """

    @override
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """剖析每个请求；耗时超过阈值就存一份带附加信息的 JSON."""
        if not PYINSTRUMENT_AVAILABLE:
            return await call_next(request)

        # 三个剖析手段一起启动
        tracemalloc.start()
        cpu_start = time.process_time()

        profiler = Profiler(async_mode="enabled")
        with profiler:
            response = await call_next(request)

        # 请求一结束就取走各项指标
        cpu_ms = round((time.process_time() - cpu_start) * 1000, 2)
        mem_current_kb, mem_peak_kb = (v // 1024 for v in tracemalloc.get_traced_memory())
        snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()

        wall_ms = round((profiler.last_session.duration if profiler.last_session else 0.0) * 1000, 2)

        if wall_ms / 1000 >= settings.PROFILING_THRESHOLD_SECONDS:
            raw_id = correlation_id.get() or "unknown"
            if len(raw_id) == 32 and "-" not in raw_id:
                raw_id = f"{raw_id[:8]}-{raw_id[8:12]}-{raw_id[12:16]}-{raw_id[16:20]}-{raw_id[20:]}"

            settings.PROFILING_DIR.mkdir(parents=True, exist_ok=True)
            filepath = settings.PROFILING_DIR / f"{raw_id}.json"

            # 占用最高的 20 个内存分配点 —— 剔除剖析器和标准库带来的噪声
            _excluded = ("tracemalloc", "pyinstrument", "<frozen", "logging/__init__")
            top_allocs = [
                {
                    "file": str(stat.traceback[0].filename).replace(str(__file__).rsplit("/", 3)[0] + "/", ""),
                    "line": stat.traceback[0].lineno,
                    "size_kb": round(stat.size / 1024, 2),
                    "count": stat.count,
                }
                for stat in snapshot.statistics("lineno")
                if not any(ex in str(stat.traceback[0].filename) for ex in _excluded)
            ]

            call_tree = json.loads(profiler.output(renderer=JSONRenderer()))
            report = {
                "request_id": raw_id,
                "endpoint": f"{request.method} {request.url.path}",
                "wall_time_ms": wall_ms,
                "cpu_time_ms": cpu_ms,
                "io_wait_ms": round(wall_ms - cpu_ms, 2),
                "memory_peak_kb": mem_peak_kb,
                "memory_allocated_kb": mem_current_kb,
                "top_memory_allocators": top_allocs,
                "call_tree": call_tree,
            }
            filepath.write_text(json.dumps(report, indent=2))
            logger.debug(
                "slow_request_profile_saved",
                path=request.url.path,
                method=request.method,
                wall_time_ms=wall_ms,
                cpu_time_ms=cpu_ms,
                memory_peak_kb=mem_peak_kb,
                io_wait_ms=round(wall_ms - cpu_ms, 2),
                profile_file=str(filepath),
            )

        return response
