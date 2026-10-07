"""用 Windows 兼容的 asyncio 事件循环启动本地开发 API."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import uvicorn


def parse_args() -> argparse.Namespace:
    """解析本地服务的启动参数."""
    parser = argparse.ArgumentParser(description="Run the Fund Agent API locally")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--reload", action="store_true")
    return parser.parse_args()


def configure_event_loop() -> None:
    """Windows 上 psycopg 异步连接跑不了默认的 ProactorEventLoop，只能换成 selector 循环."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    """启动本地 Uvicorn 开发服务."""
    args = parse_args()
    os.environ.setdefault("APP_ENV", "development")
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    configure_event_loop()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop="asyncio",
    )


if __name__ == "__main__":
    main()
