"""本文件存放应用的输入净化工具."""

import html
import re
from typing import (
    Any,
    Dict,
    List,
)


def sanitize_string(value: str) -> str:
    """净化字符串，防 XSS 与其他注入攻击.

    Args:
        value: 待净化的字符串

    Returns:
        str: 净化后的字符串
    """
    # 不是字符串就先转成字符串
    if not isinstance(value, str):
        value = str(value)

    # HTML 转义，堵住 XSS
    value = html.escape(value)

    # 清掉转义之后仍残留的 script 标签
    value = re.sub(r"&lt;script.*?&gt;.*?&lt;/script&gt;", "", value, flags=re.DOTALL)

    # 去掉空字节
    value = value.replace("\0", "")

    return value


def sanitize_email(email: str) -> str:
    """净化邮箱地址.

    Args:
        email: 待净化的邮箱地址

    Returns:
        str: 净化后的邮箱地址
    """
    # 先按通用规则净化
    email = sanitize_string(email)

    # 校验邮箱格式（只做简单检查）
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        raise ValueError("Invalid email format")

    return email.lower()


def sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """递归净化字典里所有字符串值.

    Args:
        data: 待净化的字典

    Returns:
        Dict[str, Any]: 净化后的字典
    """
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            sanitized[key] = sanitize_string(value)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_dict(value)
        elif isinstance(value, list):
            sanitized[key] = sanitize_list(value)
        else:
            sanitized[key] = value
    return sanitized


def sanitize_list(data: List[Any]) -> List[Any]:
    """递归净化列表里所有字符串值.

    Args:
        data: 待净化的列表

    Returns:
        List[Any]: 净化后的列表
    """
    sanitized = []
    for item in data:
        if isinstance(item, str):
            sanitized.append(sanitize_string(item))
        elif isinstance(item, dict):
            sanitized.append(sanitize_dict(item))
        elif isinstance(item, list):
            sanitized.append(sanitize_list(item))
        else:
            sanitized.append(item)
    return sanitized


def validate_password_strength(password: str) -> bool:
    """校验密码强度.

    Args:
        password: 待校验的密码

    Returns:
        bool: 密码是否足够强

    Raises:
        ValueError: 密码强度不够时抛出，消息里带上原因
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")

    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")

    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")

    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one number")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValueError("Password must contain at least one special character")

    return True
