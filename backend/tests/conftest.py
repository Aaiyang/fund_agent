"""测试配置：在导入任何 app 模块之前把环境变量默认值设好，并集中放置共享 fixture."""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-0123456789abcdef-0123456789ab")
os.environ.setdefault("VALKEY_HOST", "")
os.environ.setdefault("TASKIQ_REDIS_URL", "")
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
os.environ.setdefault("LONG_TERM_MEMORY_ENABLED", "false")
os.environ.setdefault("SESSION_NAMING_ENABLED", "false")
