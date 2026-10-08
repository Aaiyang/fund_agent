"""Application configuration management.

This module handles environment-specific configuration loading, parsing, and management
for the application. It includes environment detection, .env file loading, and
configuration value parsing.
"""

import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv


WEAK_JWT_SECRET_KEYS = {
    "",
    "changeme",
    "change_me",
    "change_me_to_a_random_32_plus_char_string",
    "supersecretkeythatshouldbechangedforproduction",
    "your-jwt-secret-key",
}


# Define environment types
class Environment(str, Enum):
    """Application environment types.

    Defines the possible environments the application can run in:
    development, staging, production, and test.
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


# Determine environment
def get_environment() -> Environment:
    """Get the current environment.

    Returns:
        Environment: The current environment (development, staging, production, or test)
    """
    match os.getenv("APP_ENV", "development").lower():
        case "production" | "prod":
            return Environment.PRODUCTION
        case "staging" | "stage":
            return Environment.STAGING
        case "test":
            return Environment.TEST
        case _:
            return Environment.DEVELOPMENT


# Load appropriate .env file based on environment
def load_env_file():
    """Load environment-specific .env file."""
    env = get_environment()
    print(f"Loading environment: {env}")
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    # Define env files in priority order
    env_files = [
        os.path.join(base_dir, f".env.{env.value}.local"),
        os.path.join(base_dir, f".env.{env.value}"),
        os.path.join(base_dir, ".env.local"),
        os.path.join(base_dir, ".env"),
    ]

    # Load the first env file that exists
    for env_file in env_files:
        if os.path.isfile(env_file):
            load_dotenv(dotenv_path=env_file)
            print(f"Loaded environment from {env_file}")
            return env_file

    # Fall back to default if no env file found
    return None


ENV_FILE = load_env_file()


# Parse list values from environment variables
def parse_list_from_env(env_key, default=None):
    """Parse a comma-separated list from an environment variable."""
    value = os.getenv(env_key)
    if not value:
        return default or []

    # Remove quotes if they exist
    value = value.strip("\"'")
    # Handle single value case
    if "," not in value:
        return [value]
    # Split comma-separated values
    return [item.strip() for item in value.split(",") if item.strip()]


# Parse dict of lists from environment variables with prefix
def parse_dict_of_lists_from_env(prefix, default_dict=None):
    """Parse dictionary of lists from environment variables with a common prefix."""
    result = default_dict or {}

    # Look for all env vars with the given prefix
    for key, value in os.environ.items():
        if key.startswith(prefix):
            endpoint = key[len(prefix) :].lower()  # Extract endpoint name
            # Parse the values for this endpoint
            if value:
                value = value.strip("\"'")
                if "," in value:
                    result[endpoint] = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    result[endpoint] = [value]

    return result


class Settings:
    """Application settings without using pydantic."""

    def __init__(self):
        """Initialize application settings from environment variables.

        Loads and sets all configuration values from environment variables,
        with appropriate defaults for each setting. Also applies
        environment-specific overrides based on the current environment.
        """
        # Set the environment
        self.ENVIRONMENT = get_environment()

        # Application Settings
        self.PROJECT_NAME = os.getenv("PROJECT_NAME", "Fund Agent")
        self.VERSION = os.getenv("VERSION", "1.0.0")
        self.DESCRIPTION = os.getenv(
            "DESCRIPTION", "A production-ready FastAPI template with LangGraph and Langfuse integration"
        )
        self.API_V1_STR = os.getenv("API_V1_STR", "/api/v1")
        self.DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "t", "yes")

        # CORS Settings
        self.ALLOWED_ORIGINS = parse_list_from_env("ALLOWED_ORIGINS", ["*"])

        # Langfuse Configuration
        self.LANGFUSE_TRACING_ENABLED = os.getenv("LANGFUSE_TRACING_ENABLED", "true").lower() in (
            "true",
            "1",
            "t",
            "yes",
        )
        self.LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        self.LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
        self.LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        # LangGraph Configuration
        self.LLM_PROVIDER = os.getenv("FUND_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "openai"))
        self.OPENAI_BASE_URL = os.getenv(
            "FUND_LLM_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        )
        self.OPENAI_API_KEY = os.getenv("FUND_LLM_API_KEY", os.getenv("OPENAI_API_KEY", ""))
        self.DEFAULT_LLM_MODEL = os.getenv("FUND_LLM_MODEL", os.getenv("DEFAULT_LLM_MODEL", "gpt-5.6-luna"))
        # 可选的可切换模型档位 JSON 数组，例如
        # FUND_LLM_PROFILES='[{"name":"智谱","model":"glm-5.3-flash","base_url":"...","api_key":"..."}]'。
        # 未设置时，registry 直接用上面那组扁平的 FUND_LLM_* 变量合成一个档位。
        self.LLM_PROFILES_JSON = os.getenv("FUND_LLM_PROFILES", "")
        # 设置页编辑后的档位落盘到这个文件；它优先于 FUND_LLM_PROFILES，
        # 因此改动能在重启后保留。该文件已被 gitignore。
        _backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.LLM_PROFILES_FILE = os.getenv(
            "FUND_LLM_PROFILES_FILE", os.path.join(_backend_root, ".llm_profiles.local.json")
        )
        self.LLM_PROFILE_ENCRYPTION_KEY = os.getenv("FUND_LLM_PROFILE_ENCRYPTION_KEY", "")
        self.BASIC_LLM_MODEL = os.getenv("FUND_BASIC_LLM_MODEL", "glm-5.3-flash")
        self.BASIC_LLM_BASE_URL = os.getenv("FUND_BASIC_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
        self.BASIC_LLM_API_KEY = os.getenv("FUND_BASIC_LLM_API_KEY", "")
        self.SESSION_NAMING_ENABLED = os.getenv("SESSION_NAMING_ENABLED", "true").lower() == "true"
        self.DEFAULT_LLM_TEMPERATURE = float(
            os.getenv("FUND_LLM_TEMPERATURE", os.getenv("DEFAULT_LLM_TEMPERATURE", "0.2"))
        )
        self.MAX_TOKENS = int(os.getenv("FUND_LLM_MAX_TOKENS", os.getenv("MAX_TOKENS", "2000")))
        # 上下文组装（历史 + 工具结果）的修剪预算，独立于回复输出上限：
        # 调大窗口不会同时放大回复长度。
        self.CONTEXT_TOKEN_BUDGET = int(
            os.getenv("FUND_CONTEXT_TOKEN_BUDGET", os.getenv("CONTEXT_TOKEN_BUDGET", "16384"))
        )
        # 上下文组装策略：legacy（trim_messages 旧路径）/ structured（ContextManager v1）
        self.CONTEXT_STRATEGY = os.getenv("CONTEXT_STRATEGY", "structured")

        # ---- ContextManager Phase 2 开关（独立控制，按上线顺序逐个打开）----
        def _flag(name: str, default: str) -> bool:
            return os.getenv(name, default).lower() == "true"

        # AgentStatus Dynamic Tail（每轮统计工具调用，附在上下文最末）
        self.AGENT_STATUS_ENABLED = _flag("AGENT_STATUS_ENABLED", "true")
        # Duplicate Tool Guard（同工具同参数重复调用拦截）
        self.DUPLICATE_TOOL_GUARD_ENABLED = _flag("DUPLICATE_TOOL_GUARD_ENABLED", "true")
        # Conversation Summary（已完成旧 Turn 的批量压缩）
        self.CONVERSATION_SUMMARY_ENABLED = _flag("CONVERSATION_SUMMARY_ENABLED", "false")
        # Batch Compaction（达到水位阈值时整批压缩旧 Turn）
        self.BATCH_COMPACTION_ENABLED = _flag("BATCH_COMPACTION_ENABLED", "false")
        # Guard：同一工具同参数的前 N 次执行放行，之后拦截
        self.DUPLICATE_TOOL_MAX_SAME_CALLS = int(os.getenv("DUPLICATE_TOOL_MAX_SAME_CALLS", "2"))
        # Batch Compaction：至少积攒多少个已完成旧 Turn 才触发压缩
        self.CONTEXT_COMPACTION_MIN_TURNS = int(os.getenv("CONTEXT_COMPACTION_MIN_TURNS", "4"))
        # 单条 ToolMessage 的硬上限（token），超长工具结果在组装时被截断
        self.TOOL_MESSAGE_HARD_LIMIT_TOKENS = int(os.getenv("TOOL_MESSAGE_HARD_LIMIT_TOKENS", "4000"))
        # 摘要区总 token 占预算的比例上限，超过则对最旧的段做两两合并
        self.SUMMARY_REGION_MAX_RATIO = float(os.getenv("SUMMARY_REGION_MAX_RATIO", "0.30"))
        # 摘要段数硬上限，超过同样触发合并
        self.SUMMARY_SEGMENT_MERGE_COUNT = int(os.getenv("SUMMARY_SEGMENT_MERGE_COUNT", "8"))
        # 每轮合并取最旧的多少比例（size-tiered：约一半，段数对数增长）
        self.SUMMARY_MERGE_FRACTION = float(os.getenv("SUMMARY_MERGE_FRACTION", "0.5"))
        self.MAX_LLM_CALL_RETRIES = int(os.getenv("MAX_LLM_CALL_RETRIES", "3"))
        self.LLM_TOTAL_TIMEOUT = int(os.getenv("FUND_LLM_TIMEOUT_SECONDS", os.getenv("LLM_TOTAL_TIMEOUT", "60")))
        self.LLM_REQUEST_TIMEOUT = float(
            os.getenv("FUND_LLM_TIMEOUT_SECONDS", os.getenv("LLM_REQUEST_TIMEOUT", str(self.LLM_TOTAL_TIMEOUT)))
        )

        # Long term memory Configuration
        self.LONG_TERM_MEMORY_ENABLED = os.getenv("LONG_TERM_MEMORY_ENABLED", "true").lower() in (
            "true",
            "1",
            "t",
            "yes",
        )
        self.LONG_TERM_MEMORY_MODEL = os.getenv("LONG_TERM_MEMORY_MODEL", "gpt-5-nano")
        self.EMBEDDING_PROVIDER = os.getenv("FUND_EMBEDDING_PROVIDER", "openai")
        self.EMBEDDING_BASE_URL = os.getenv(
            "FUND_EMBEDDING_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        )
        self.EMBEDDING_API_KEY = os.getenv(
            "SILICONFLOW_API_KEY", os.getenv("FUND_EMBEDDING_API_KEY", self.OPENAI_API_KEY)
        )
        self.LONG_TERM_MEMORY_EMBEDDER_MODEL = os.getenv(
            "FUND_EMBEDDING_MODEL", os.getenv("LONG_TERM_MEMORY_EMBEDDER_MODEL", "text-embedding-3-small")
        )
        self.EMBEDDING_DIM = int(os.getenv("FUND_EMBEDDING_DIM", "1536"))
        self.EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("FUND_EMBEDDING_TIMEOUT_SECONDS", "60"))
        self.LONG_TERM_MEMORY_COLLECTION_NAME = os.getenv("LONG_TERM_MEMORY_COLLECTION_NAME", "longterm_memory")
        # JWT Configuration
        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
        self.JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
        self.JWT_ACCESS_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_DAYS", "1"))
        self.JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "90"))
        self.validate_jwt_secret_key()

        # Logging Configuration
        self.LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # "json" or "console"

        # Profiling Configuration (DEBUG only)
        self.PROFILING_DIR = Path(os.getenv("PROFILING_DIR", "/tmp/fastapi_profiles"))
        self.PROFILING_THRESHOLD_SECONDS = float(os.getenv("PROFILING_THRESHOLD_SECONDS", "2.0"))

        # Postgres Configuration
        self.POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
        self.POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
        self.POSTGRES_DB = os.getenv("POSTGRES_DB", "food_order_db")
        self.POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
        self.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
        self.POSTGRES_POOL_SIZE = int(os.getenv("POSTGRES_POOL_SIZE", "20"))
        self.POSTGRES_MAX_OVERFLOW = int(os.getenv("POSTGRES_MAX_OVERFLOW", "10"))
        self.CHECKPOINT_TABLES = ["checkpoint_blobs", "checkpoint_writes", "checkpoints"]

        # Valkey/Redis Cache Configuration (optional — if host is set, caching is enabled)
        self.VALKEY_HOST = os.getenv("VALKEY_HOST", "")
        self.VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
        self.VALKEY_DB = int(os.getenv("VALKEY_DB", "0"))
        self.VALKEY_PASSWORD = os.getenv("VALKEY_PASSWORD", "")
        self.VALKEY_MAX_CONNECTIONS = int(os.getenv("VALKEY_MAX_CONNECTIONS", "20"))
        self.CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))

        # Fund data provider (AKShare) Configuration
        self.AKSHARE_MAX_CONCURRENCY = int(os.getenv("AKSHARE_MAX_CONCURRENCY", "5"))
        self.AKSHARE_TIMEOUT_SECONDS = float(os.getenv("AKSHARE_TIMEOUT_SECONDS", "20"))
        self.AKSHARE_MAX_RETRIES = int(os.getenv("AKSHARE_MAX_RETRIES", "2"))
        self.AKSHARE_MIN_INTERVAL_SECONDS = float(os.getenv("AKSHARE_MIN_INTERVAL_SECONDS", "0.2"))
        self.FUND_NAV_STALE_HOURS = int(os.getenv("FUND_NAV_STALE_HOURS", "24"))
        # On-demand quote refresh (opening 持仓): the source table is published once a
        # day, so a shorter gap only buys duplicate upstream work.
        self.FUND_NAV_REFRESH_COOLDOWN_SECONDS = int(os.getenv("FUND_NAV_REFRESH_COOLDOWN_SECONDS", "120"))
        # The batched quote table is one request over every fund; measured at ~5 s, so
        # this is headroom, not a promise to keep the request open that long.
        self.FUND_NAV_REFRESH_TIMEOUT_SECONDS = float(os.getenv("FUND_NAV_REFRESH_TIMEOUT_SECONDS", "15"))
        # Hot Fund sweep (spec 7.13): the API only enqueues; a worker executes
        self.FUND_HOT_SYNC_ENABLED = os.getenv("FUND_HOT_SYNC_ENABLED", "false").lower() in ("true", "1", "t", "yes")
        self.FUND_HOT_SYNC_INTERVAL_MINUTES = int(os.getenv("FUND_HOT_SYNC_INTERVAL_MINUTES", "360"))
        # Calendar dates (trade_date, nav freshness) follow the fund market, not the host tz
        self.FUND_BUSINESS_TZ = os.getenv("FUND_BUSINESS_TZ", "Asia/Shanghai")

        # Holding import Configuration
        self.HOLDING_IMPORT_MAX_IMAGES = int(os.getenv("HOLDING_IMPORT_MAX_IMAGES", "5"))
        self.HOLDING_IMPORT_MAX_IMAGE_MB = int(os.getenv("HOLDING_IMPORT_MAX_IMAGE_MB", "8"))
        self.HOLDING_IMPORT_TEMP_DIR = Path(os.getenv("HOLDING_IMPORT_TEMP_DIR", ".runtime/holding_imports"))
        self.HOLDING_IMPORT_STALE_MINUTES = int(os.getenv("HOLDING_IMPORT_STALE_MINUTES", "30"))

        # Task queue Configuration (empty → derived from VALKEY_*; no Redis → in-process fallback)
        self.TASKIQ_REDIS_URL = os.getenv("TASKIQ_REDIS_URL", "")
        # Total attempts for a durable background task (first try + retries)
        self.BACKGROUND_TASK_MAX_ATTEMPTS = int(os.getenv("BACKGROUND_TASK_MAX_ATTEMPTS", "3"))

        # Rate Limiting Configuration
        self.RATE_LIMIT_DEFAULT = parse_list_from_env("RATE_LIMIT_DEFAULT", ["200 per day", "50 per hour"])

        # Rate limit endpoints defaults
        default_endpoints = {
            "chat": ["30 per minute"],
            "chat_stream": ["20 per minute"],
            "messages": ["50 per minute"],
            "register": ["10 per hour"],
            "login": ["20 per minute"],
            "auth": ["60 per minute"],
            "root": ["10 per minute"],
            "health": ["20 per minute"],
            "funds": ["120 per minute"],
            "funds_search": ["60 per minute"],
            "funds_refresh": ["30 per minute"],
            "indexes": ["120 per minute"],
            "markets": ["120 per minute"],
            "watchlist": ["60 per minute"],
            "watchlist_groups": ["60 per minute"],
            "portfolio": ["120 per minute"],
            "accounts": ["60 per minute"],
            "transactions": ["60 per minute"],
            "auto_invest": ["60 per minute"],
            "holding_imports": ["30 per minute"],
            "agent": ["10 per minute"],
        }

        # Update rate limit endpoints from environment variables
        self.RATE_LIMIT_ENDPOINTS = default_endpoints.copy()
        for endpoint in default_endpoints:
            env_key = f"RATE_LIMIT_{endpoint.upper()}"
            value = parse_list_from_env(env_key)
            if value:
                self.RATE_LIMIT_ENDPOINTS[endpoint] = value

        # Evaluation Configuration
        self.EVALUATION_LLM = os.getenv("EVALUATION_LLM", "gpt-5")
        self.EVALUATION_BASE_URL = os.getenv("EVALUATION_BASE_URL", "https://api.openai.com/v1")
        self.EVALUATION_API_KEY = os.getenv("EVALUATION_API_KEY", self.OPENAI_API_KEY)
        self.EVALUATION_SLEEP_TIME = int(os.getenv("EVALUATION_SLEEP_TIME", "10"))

        # Apply environment-specific settings
        self.apply_environment_settings()

    def apply_environment_settings(self):
        """Apply environment-specific settings based on the current environment."""
        env_settings = {
            Environment.DEVELOPMENT: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "console",
                "RATE_LIMIT_DEFAULT": ["1000 per day", "200 per hour"],
            },
            Environment.STAGING: {
                "DEBUG": False,
                "LOG_LEVEL": "INFO",
                "RATE_LIMIT_DEFAULT": ["500 per day", "100 per hour"],
            },
            Environment.PRODUCTION: {
                "DEBUG": False,
                "LOG_LEVEL": "WARNING",
                "RATE_LIMIT_DEFAULT": ["200 per day", "50 per hour"],
            },
            Environment.TEST: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "console",
                "RATE_LIMIT_DEFAULT": ["1000 per day", "1000 per hour"],  # Relaxed for testing
            },
        }

        # Get settings for current environment
        current_env_settings = env_settings.get(self.ENVIRONMENT, {})

        # Apply settings if not explicitly set in environment variables
        for key, value in current_env_settings.items():
            env_var_name = key.upper()
            # Only override if environment variable wasn't explicitly set
            if env_var_name not in os.environ:
                setattr(self, key, value)

    def validate_jwt_secret_key(self):
        """Reject empty, short, or placeholder JWT secrets outside test runs."""
        if self.ENVIRONMENT == Environment.TEST:
            return

        secret = self.JWT_SECRET_KEY.strip()
        if len(secret) < 32:
            raise RuntimeError("JWT_SECRET_KEY must be at least 32 characters long")

        if secret.lower() in WEAK_JWT_SECRET_KEYS:
            raise RuntimeError("JWT_SECRET_KEY must be a strong random value, not a placeholder or default")


# Create settings instance
settings = Settings()
