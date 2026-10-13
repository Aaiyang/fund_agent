"""HTTP 指标标签用路由模板，不用实际路径.

路径里带 import_id(uuid)、session_id、基金代码，直接当标签会让时间序列随流量
无界增长。
"""

from types import SimpleNamespace

from starlette.requests import Request

from app.core.middleware import MetricsMiddleware


def _request(path: str, route_path: str | None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [],
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
    }
    if route_path is not None:
        scope["route"] = SimpleNamespace(path=route_path)
    return Request(scope)


def test_label_uses_the_route_template() -> None:
    path = "/api/v1/chatbot/holding-imports/0f0f0f0f/decision"
    template = "/api/v1/chatbot/holding-imports/{import_id}/decision"
    assert MetricsMiddleware._endpoint_label(_request(path, template)) == template


def test_unmatched_paths_share_one_label() -> None:
    # 404 没有命中路由，也不能把探测到的任意路径变成新时间序列。
    assert MetricsMiddleware._endpoint_label(_request("/api/v1/probe/../../etc", None)) == "unmatched"
