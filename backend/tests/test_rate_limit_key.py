"""限流计数主键：代理之后的真实客户端.

X-Forwarded-For 由客户端可控，只有直连来源确实是已登记代理时才能采信，
否则全站会共用代理地址的那一份额度。
"""

from starlette.requests import Request

from app.core import limiter as limiter_module


def _request(peer: str | None, forwarded: str | None = None) -> Request:
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    scope = {"type": "http", "headers": headers, "client": (peer, 54321) if peer else None}
    return Request(scope)


def test_untrusted_peer_never_selects_forwarded_header(monkeypatch) -> None:
    monkeypatch.setattr(limiter_module, "_TRUSTED_PROXIES", set())
    assert limiter_module.rate_limit_key(_request("203.0.113.9", "198.51.100.1")) == "203.0.113.9"


def test_trusted_proxy_selects_leftmost_forwarded_entry(monkeypatch) -> None:
    monkeypatch.setattr(limiter_module, "_TRUSTED_PROXIES", {"10.0.0.1"})
    assert limiter_module.rate_limit_key(_request("10.0.0.1", "198.51.100.7, 10.0.0.1")) == "198.51.100.7"


def test_missing_or_empty_forwarded_header_falls_back_to_peer(monkeypatch) -> None:
    monkeypatch.setattr(limiter_module, "_TRUSTED_PROXIES", {"10.0.0.1"})
    assert limiter_module.rate_limit_key(_request("10.0.0.1")) == "10.0.0.1"
    assert limiter_module.rate_limit_key(_request("10.0.0.1", "   ")) == "10.0.0.1"


def test_request_without_client_information_is_labelled(monkeypatch) -> None:
    monkeypatch.setattr(limiter_module, "_TRUSTED_PROXIES", {"10.0.0.1"})
    assert limiter_module.rate_limit_key(_request(None)) == "unknown"
