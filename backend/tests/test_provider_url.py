"""厂商接口地址的可达范围校验.

服务端会替用户向这些地址发请求，所以除了格式，还要按部署策略挡住内网目标。
"""

import pytest

from app.utils.provider_url import validate_provider_base_url

PUBLIC_URLS = ["https://api.deepseek.com/v1", "https://open.bigmodel.cn/api/paas/v4/", "http://11.22.33.44:8000/v1"]
PRIVATE_URLS = [
    "http://127.0.0.1:11434/v1",
    "http://localhost:11434/v1",
    "http://10.0.0.7:8000/v1",
    "http://192.168.1.5/v1",
    "http://169.254.169.254/latest/meta-data",  # 云元数据
    "http://[::1]:8000/v1",
]


@pytest.mark.parametrize("url", PUBLIC_URLS)
def test_public_urls_pass_regardless_of_policy(url: str) -> None:
    assert validate_provider_base_url(url, allow_private_network=False).rstrip("/") == url.rstrip("/")


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_private_targets_follow_the_deployment_policy(url: str) -> None:
    # 自带 Ollama/vLLM 的开发环境按字面允许；生产必须拒绝。
    assert validate_provider_base_url(url, allow_private_network=True)
    with pytest.raises(ValueError, match="内网"):
        validate_provider_base_url(url, allow_private_network=False)


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/model", "garbage", "https://", "https://user:pass@example.com/v1"],  # pragma: allowlist secret
)
def test_malformed_targets_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="HTTP|认证"):
        validate_provider_base_url(url, allow_private_network=True)


def test_trailing_slash_is_normalised() -> None:
    assert validate_provider_base_url("https://x.test/v1/", allow_private_network=True) == "https://x.test/v1"
