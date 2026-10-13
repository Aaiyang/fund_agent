"""超限截图不能整份进内存.

上传端点只需会话令牌，而单文件字节数若只在读完后判定，一个认证用户就能用
5×大文件把进程 OOM 打死——崩溃正好落在工具轮上还会连带损坏会话检查点。
"""

import pytest

from app.core.config import settings
from app.services.holding_import_service import UploadValidationError, holding_import_service

MAX_BYTES = settings.HOLDING_IMPORT_MAX_IMAGE_MB * 1024 * 1024


class _FakeUpload:
    def __init__(self, size: int | None, payload: bytes = b"") -> None:
        self.size = size
        self.payload = payload
        self.read_amounts: list[int] = []

    async def read(self, amount: int = -1) -> bytes:
        self.read_amounts.append(amount)
        return self.payload


async def test_declared_size_is_rejected_before_any_read() -> None:
    upload = _FakeUpload(size=MAX_BYTES + 1)
    with pytest.raises(UploadValidationError, match="exceeds"):
        await holding_import_service._save_images("imp-1", [upload])
    assert upload.read_amounts == []


async def test_undeclared_size_is_read_with_a_bound() -> None:
    upload = _FakeUpload(size=None, payload=b"not-an-image")
    # 内容校验在后面才做，这里只确认读取本身有上限
    with pytest.raises(UploadValidationError, match="not_valid"):
        await holding_import_service._save_images("imp-2", [upload])
    assert upload.read_amounts == [MAX_BYTES + 1]
