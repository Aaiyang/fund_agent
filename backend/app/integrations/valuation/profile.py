"""从基金档案页取「业绩比较基准」原文.

估值要读这句话才能知道跟哪条指数、股票部分占多少。`FundExternalProfile` 不带这个
字段（它当初作为展示文案被从 `fund` 表删掉），而估值是它唯一的消费者，所以在这里
直接读档案的 item/value 原始行，不往公共主数据模型上加一个只有本模块用的字段。

传输仍走 provider 的受保护通道：限流、并发信号量、重试、超时、线程池都在那里。
自己起一次 requests 等于绕开"这台机器上 AKShare 必须节流"这个既成事实。
"""

from typing import Any

from app.core.logging import logger
from app.integrations.fund_data.akshare_provider import akshare_fund_provider

_BENCHMARK_ITEM = "业绩比较基准"


def pick_benchmark(rows: list[dict[str, Any]]) -> str | None:
    """从档案的 item/value 行里挑出业绩比较基准."""
    for row in rows or []:
        if str(row.get("item") or "").strip() != _BENCHMARK_ITEM:
            continue
        text = str(row.get("value") or "").strip()
        return text or None
    return None


async def fetch_benchmark_text(fund_code: str) -> str | None:
    """取一只基金的基准原文；取不到返回 None，不抛错.

    档案接口对某些基金根本没有这一格（货基、部分老基金），那是"没有依据"而不是
    故障，不能让它把整批估值带崩。
    """
    try:
        rows = await akshare_fund_provider._call("fund_individual_basic_info_xq", symbol=fund_code)
    except Exception as e:
        logger.warning("fund_benchmark_fetch_failed", fund_code=fund_code, error=str(e))
        return None
    return pick_benchmark(rows)
