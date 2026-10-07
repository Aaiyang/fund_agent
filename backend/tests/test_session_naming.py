"""会话自动命名的回归测试.

生成标题的那次 LLM 调用不能点名要某个模型：注册表里只有配置的那个默认模型，
而 ``reasoning`` 这类额外的 ChatOpenAI kwarg 在构造阶段就会被拒。
这两点以前都会让每一次 `_persist_session_name` 在发出任何 HTTP 请求之前就失败。
"""

from app.schemas.chat import SessionTitle
from app.services import session_naming as sn


class FakeLLMService:
    def __init__(self):
        self.captured_kwargs: dict = {}

    async def call(self, messages, **kwargs):
        self.captured_kwargs = kwargs
        return SessionTitle(title="Fund research")


class FakeDatabaseService:
    def __init__(self):
        self.updated: tuple | None = None

    async def update_session_name(self, session_id, name):
        self.updated = (session_id, name)


async def test_persist_session_name_uses_registered_model(monkeypatch):
    fake_llm = FakeLLMService()
    fake_db = FakeDatabaseService()
    monkeypatch.setattr(sn, "llm_service", fake_llm)
    monkeypatch.setattr(sn, "database_service", fake_db)

    await sn._persist_session_name("session-1", "help me pick a fund")

    assert fake_db.updated == ("session-1", "Fund research")
    assert fake_llm.captured_kwargs["response_format"] is SessionTitle
    # 不显式传 model_name：任何没注册过的名字都会在 LLMRegistry.get 里抛 ValueError，
    # 标题就永远写不进库。
    assert "model_name" not in fake_llm.captured_kwargs
    # 也不传 `reasoning` kwarg：ChatOpenAI 不接受构造器里的未知字段。
    assert "reasoning" not in fake_llm.captured_kwargs
