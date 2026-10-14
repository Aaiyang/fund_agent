"""密码不得出现在事件、上下文、异常文本或 broker 初始化日志中."""

from unittest.mock import Mock

from app.core import task_queue
from app.core.logging import redact_log_event


def test_redacts_nested_secrets_and_url_credentials():
    event = {
        "event": "redis://:fixture-password@cache:6379/0",  # pragma: allowlist secret
        "exception": "at redis://user:fixture-password@host/0",  # pragma: allowlist secret
        "nested": {"api_key": "fixture-key", "password": "fixture-password"},  # pragma: allowlist secret
    }
    redacted = redact_log_event(None, "info", event)
    assert "fixture-password" not in str(redacted) and "fixture-key" not in str(redacted)  # pragma: allowlist secret
    assert "cache:6379/0" in str(redacted)


def test_broker_initialization_logs_only_endpoint(monkeypatch):
    logger = Mock()
    constructor = Mock()
    monkeypatch.setattr(task_queue, "logger", logger)
    monkeypatch.setattr(task_queue, "ListQueueBroker", constructor)
    monkeypatch.setattr(
        task_queue.settings,
        "TASKIQ_REDIS_URL",
        "redis://user:fixture-password@cache:6379/0",  # pragma: allowlist secret
    )
    task_queue._create_broker()
    constructor.assert_called_once_with(url="redis://user:fixture-password@cache:6379/0")  # pragma: allowlist secret
    assert "fixture-password" not in str(logger.mock_calls)  # pragma: allowlist secret
