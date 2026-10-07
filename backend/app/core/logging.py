"""应用的日志配置与初始化.

本模块基于 structlog 提供结构化日志配置，按环境选择不同渲染器与 handler：
既支持开发环境适合控制台阅读的输出，也支持
生产环境的 JSON 格式日志。
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    override,
)

import structlog
from asgi_correlation_id import correlation_id

from app.core.config import (
    Environment,
    settings,
)

# 确保日志目录存在
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

# 存放单次请求专有数据的上下文变量
_request_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("request_context", default=None)


def bind_context(**kwargs: Any) -> None:
    """把上下文变量绑定到当前请求.

    Args:
        **kwargs: 要绑定进日志上下文的键值对
    """
    current = _request_context.get() or {}
    _request_context.set({**current, **kwargs})


def clear_context() -> None:
    """清空当前请求的所有上下文变量."""
    _request_context.set(None)


def get_context() -> Dict[str, Any]:
    """取当前日志上下文.

    Returns:
        Dict[str, Any]: 当前上下文字典
    """
    return _request_context.get() or {}


def add_context_to_event_dict(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """把上下文变量并入事件字典.

    这个处理器会把已绑定的上下文变量追加到每条日志事件里。

    Args:
        logger: logger 实例
        method_name: 日志方法名
        event_dict: 待修改的事件字典
    """
    context = get_context()
    if context:
        event_dict.update(context)
    return event_dict


def add_request_id_to_event_dict(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """把当前 request_id（来自 asgi-correlation-id）追加到每条日志事件.

    Args:
        logger: logger 实例
        method_name: 日志方法名
        event_dict: 待修改的事件字典
    """
    request_id = correlation_id.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def get_log_file_path() -> Path:
    """按日期和环境算出当前该写的日志文件路径.

    Returns:
        Path: 日志文件路径
    """
    env_prefix = settings.ENVIRONMENT.value
    return settings.LOG_DIR / f"{env_prefix}-{datetime.now().strftime('%Y-%m-%d')}.jsonl"


class JsonlFileHandler(logging.Handler):
    """自定义 handler：把 JSONL 日志按天写进文件."""

    def __init__(self, file_path: Path):
        """初始化 JSONL 文件 handler.

        Args:
            file_path: 日志条目要写入的文件路径。
        """
        super().__init__()
        self.file_path = file_path

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """把一条日志记录写进 JSONL 文件."""
        try:
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
                "filename": record.pathname,
                "line": record.lineno,
                "environment": settings.ENVIRONMENT.value,
            }
            extra = getattr(record, "extra", None)
            if isinstance(extra, dict):
                log_entry.update(extra)

            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            self.handleError(record)

    @override
    def close(self) -> None:
        """关闭 handler."""
        super().close()


def get_structlog_processors(include_file_info: bool = True) -> List[Any]:
    """按配置组装 structlog 处理器链.

    Args:
        include_file_info: 日志里是否带上调用处的文件信息

    Returns:
        List[Any]: structlog 处理器列表
    """
    # 控制台输出与文件输出都要用的处理器
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        # 把上下文变量（user_id、session_id 等）并入每条日志事件
        add_context_to_event_dict,
        # 把 asgi-correlation-id 的 request_id 并入每条日志事件
        add_request_id_to_event_dict,
    ]

    # 需要文件信息时才追加调用点参数
    if include_file_info:
        processors.append(
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.PATHNAME,
                }
            )
        )

    # 追加环境信息
    processors.append(lambda _, __, event_dict: {**event_dict, "environment": settings.ENVIRONMENT.value})

    return processors


def setup_logging() -> None:
    """按环境给 structlog 配置不同的渲染器.

    开发环境：易读的控制台输出
    staging/生产环境：结构化 JSON 日志
    """
    # 由 DEBUG 开关决定日志级别
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    # 为 JSON 日志建文件 handler
    file_handler = JsonlFileHandler(get_log_file_path())
    file_handler.setLevel(log_level)

    # 建控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # 取共用的处理器链
    shared_processors = get_structlog_processors(
        # 只在 development 和 test 下带上详细的文件信息
        include_file_info=settings.ENVIRONMENT in [Environment.DEVELOPMENT, Environment.TEST]
    )

    # 配置标准库 logging
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=[file_handler, console_handler],
    )

    # 第三方库的 DEBUG 噪音统一压到 WARNING：HTTP 追踪（httpx/httpcore/
    # hpack/urllib3/openai 客户端）、搜索库的 Cookie 引擎（primp/cookie_store）、
    # Langfuse 回调——单日可刷出数万行，把业务日志淹没。
    for noisy_logger in (
        "langfuse",
        "httpx",
        "httpcore",
        "openai",
        "hpack",
        "urllib3",
        "primp",
        "cookie_store",
        "ddgs",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # 按环境配置 structlog
    if settings.LOG_FORMAT == "console":
        # 开发环境：控制台友好输出
        structlog.configure(
            processors=[
                *shared_processors,
                # 用 ConsoleRenderer 给控制台输出易读的排版
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # 生产环境：JSON 日志
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )


# 初始化日志
setup_logging()

# 创建 logger 实例
logger = structlog.get_logger()
log_level_name = "DEBUG" if settings.DEBUG else "INFO"
logger.info(
    "logging_initialized",
    environment=settings.ENVIRONMENT.value,
    log_level=log_level_name,
    log_format=settings.LOG_FORMAT,
    debug=settings.DEBUG,
)
