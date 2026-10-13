"""厂商接口地址校验.

服务端会替用户向这些地址发请求（建连推理、探测模型列表），所以地址的可达范围
必须说清楚：格式合法只是底线，是否允许指向内网由部署策略决定。
"""

import ipaddress
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = frozenset({"localhost"})


def validate_provider_base_url(base_url: str, *, allow_private_network: bool) -> str:
    """返回去掉尾部斜杠的接口地址；不合法时抛 ValueError，消息可直接回给客户端.

    Args:
        base_url: 用户提交的 OpenAI 兼容接口地址。
        allow_private_network: 是否允许指向回环、私网与链路本地地址。自带
            Ollama/vLLM 的开发环境需要 True；生产应为 False，否则认证用户可以
            把服务端当成访问云元数据与内网管理口的跳板。

    Raises:
        ValueError: 协议、主机名或可达范围不符合当前部署策略。
    """
    normalized = base_url.strip().rstrip("/")
    url = urlparse(normalized)
    if url.scheme not in {"http", "https"} or not url.hostname:
        raise ValueError("接口地址必须是有效的 HTTP 或 HTTPS 地址")
    if url.username or url.password:
        raise ValueError("接口地址必须是有效的 HTTP 或 HTTPS 地址，且不能携带认证信息；密钥请只填在 API Key 字段")

    if not allow_private_network:
        host = url.hostname
        if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
            raise ValueError("当前部署不允许模型接口指向内网地址")
        try:
            address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = ipaddress.ip_address(host)
        except ValueError:
            # 字面量之外的主机名不做解析校验：解析结果可被重绑定，
            # 这道边界最终由网络出口策略（egress 防火墙/安全组）兜住。
            address = None
        if address is not None and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
        ):
            raise ValueError("当前部署不允许模型接口指向内网地址")

    return normalized
