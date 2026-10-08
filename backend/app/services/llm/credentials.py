"""个人模型密钥的加密存储，密文按用户绑定."""

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _cipher(user_id: int) -> Fernet:
    """从服务器主密钥派生独立的用户密钥."""
    master = settings.LLM_PROFILE_ENCRYPTION_KEY or settings.JWT_SECRET_KEY
    if not master:
        raise RuntimeError("未配置模型档案加密密钥")
    derived = hmac.new(master.encode(), f"fund-agent:llm-profile:v1:{user_id}".encode(), hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_key(user_id: int, api_key: str) -> str:
    """加密用户刚提交的密钥，仅将密文持久化."""
    return _cipher(user_id).encrypt(api_key.encode()).decode()


def decrypt_key(user_id: int, encrypted_key: str) -> str:
    """按当前用户解密；损坏或属于其他用户的密文不能使用."""
    try:
        return _cipher(user_id).decrypt(encrypted_key.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("模型密钥无法解密，请检查服务端加密密钥配置") from exc
