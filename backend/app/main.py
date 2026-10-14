"""本文件是应用的主入口."""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    Request,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from asgi_correlation_id import CorrelationIdMiddleware

from app.api.v1.api import api_router
from app.api.v1.chatbot import agent
from app.core.cache import cache_service
from app.core.config import settings
from app.core.database import async_engine
from app.core.limiter import limiter
from app.core.logging import logger
from app.core.metrics import setup_metrics
from app.core.middleware import (
    LoggingContextMiddleware,
    MetricsMiddleware,
    ProfilingMiddleware,
)
from app.core.observability import langfuse_init
from app.core.task_queue import shutdown_broker, startup_broker
from app.services.database import database_service
from app.services.memory import memory_service
from app.workers import fund_sync, memory_write, screenshot_import  # noqa: F401  register broker tasks
from app.workers.scheduler import start_periodic_jobs, stop_periodic_jobs

# 加载环境变量
load_dotenv()
langfuse_init()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """处理应用的启动与关停事件."""
    logger.info(
        "application_startup",
        project_name=settings.PROJECT_NAME,
        version=settings.VERSION,
        api_prefix=settings.API_V1_STR,
    )

    # 初始化缓存服务（配了 Valkey 才会去建连接）
    try:
        await cache_service.initialize()
    except Exception as e:
        logger.exception("cache_initialization_failed", error=str(e))

    # 预热 LangGraph agent：启动时就建好图和连接池，
    # 否则第一个请求要承担冷启动延迟
    try:
        await agent.create_graph()
        logger.info("graph_pre_warmed")
    except Exception as e:
        logger.exception("graph_pre_warm_failed", error=str(e))

    # 预热 mem0 AsyncMemory：初始化 pgvector 连接并检查 schema，
    # 免得第一次 search() 缓存未命中或 add() 时付那 ~130ms 的冷启动开销
    try:
        await memory_service.initialize()
    except Exception as e:
        logger.exception("memory_service_pre_warm_failed", error=str(e))

    # Taskiq broker（Redis）；没配 Redis 时后台任务走进程内兜底
    try:
        await startup_broker()
    except Exception as e:
        logger.exception("task_broker_startup_failed", error=str(e))

    # 周期性入队热门基金同步（spec 7.13）
    try:
        start_periodic_jobs()
    except Exception as e:
        logger.exception("periodic_jobs_startup_failed", error=str(e))

    # 保证持仓导入的临时图片目录存在
    try:
        Path(settings.HOLDING_IMPORT_TEMP_DIR).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.exception("import_temp_dir_creation_failed", error=str(e))

    yield

    # 关停时做清理
    await stop_periodic_jobs()
    await shutdown_broker()
    await memory_service.close()
    await cache_service.close()
    if agent._connection_pool:
        await agent._connection_pool.close()
        logger.info("connection_pool_closed")
    await async_engine.dispose()
    logger.info("application_shutdown")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# 配置 Prometheus 指标
setup_metrics(app)

# 添加日志上下文中间件（必须在其他中间件之前加，才能拿到上下文）
app.add_middleware(LoggingContextMiddleware)

# 添加自定义指标中间件
app.add_middleware(MetricsMiddleware)

# 添加剖析中间件（仅 DEBUG 生效 —— 慢请求会把剖析结果存到 /tmp）
if settings.DEBUG:
    app.add_middleware(ProfilingMiddleware)

# 添加 correlation ID 中间件 —— 必须处于最外层，这样 request_id 先于其他所有中间件写好
app.add_middleware(CorrelationIdMiddleware)

# 配置限流异常处理器
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]


# 配置校验异常处理器
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求数据校验失败.

    Args:
        request: 触发校验错误的那个请求
        exc: 校验错误本身

    Returns:
        JSONResponse: 格式化后的错误响应
    """
    # 记录这条校验错误
    logger.error(
        "validation_error",
        client_host=request.client.host if request.client else "unknown",
        path=request.url.path,
        errors=str(exc.errors()),
    )

    # 把错误整理成对用户更友好的形式
    formatted_errors = []
    for error in exc.errors():
        loc = " -> ".join([str(loc_part) for loc_part in error["loc"] if loc_part != "body"])
        formatted_errors.append({"field": loc, "message": error["msg"]})

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Validation error", "errors": formatted_errors},
    )


# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 API 路由
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["root"][0])
async def root(request: Request):
    """根端点，返回 API 的基本信息."""
    logger.info("root_endpoint_called")
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "healthy",
        "environment": settings.ENVIRONMENT.value,
        "swagger_url": "/docs",
        "redoc_url": "/redoc",
    }


@app.get("/health")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["health"][0])
async def health_check(request: Request) -> JSONResponse:
    """健康检查端点，返回随环境而不同的信息.

    Returns:
        JSONResponse: 健康状态负载；数据库连不上时返回 HTTP 503，
        好让负载均衡把这台实例摘掉。
    """
    logger.info("health_check_called")

    # 检查数据库连通性
    db_healthy = await database_service.health_check()
    # 缓存是可降级的：Valkey 连不上只会拖慢读取，不会丢数据，
    # 所以它只把整体状态标成 degraded，不单独让探针失败。
    cache_healthy = await cache_service.is_healthy()

    response = {
        "status": "healthy" if db_healthy and cache_healthy else "degraded",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT.value,
        "components": {
            "api": "healthy",
            "database": "healthy" if db_healthy else "unhealthy",
            "cache": "healthy" if cache_healthy else "unhealthy",
        },
        "timestamp": datetime.now().isoformat(),
    }

    # 数据库不健康时，返回对应的状态码
    status_code = status.HTTP_200_OK if db_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(content=response, status_code=status_code)
