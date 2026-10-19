"""单档与多角色的真实模型对照：只在显式确认时打真接口，不进 CI.

用法（后端已在跑，默认 127.0.0.1:8000）：
    cd backend && python -m scripts.compare_research_modes --fund-code 000001

两个档位用同一段用户文字、同一个新建会话，只换 ``research_strategy``。量的是客户端
真正看得见的东西：首字延迟、总耗时、正文结构、引用计数、进度帧与活动帧。测完把
``.runtime/research-mode-comparison.json`` 的结果贴进评测记录，不要凭正文观感下结论.
"""

import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

from app.services.database import database_service
from app.utils.auth import create_access_token

CITATION = re.compile(r"\[ev_[0-9a-f]{8,}\]")
AUDITED = re.compile(r"引用核对：(\d+) 处可核对、(\d+) 处")
SECTION = re.compile(r"^#{2,3} +\S", re.MULTILINE)
# 归属人抬头由代码给（completion[].heading），所以这里能直接数出"有几节真的署了名"。
OWNER_HEADING = re.compile(
    r"^### (?:业绩分析师|风险分析师|持仓与风格分析师|基金经理研究员|披露与来源质量审查员|组合配置顾问)｜", re.MULTILINE
)
INTERNAL_KEYS = re.compile(r"\b(?:performance|risk|holdings|manager|disclosure|portfolio|finding_index|task_id)\b")
MARKERS = {
    "范围核对": "**研究范围核对**",
    "来源核对": "**数据来源核对**",
    "综合结论": "综合结论与分歧",
    "分歧小节": "角色分歧与未解决项",
    "行动表": "行动建议与触发条件",
}


def parse_args() -> argparse.Namespace:
    """解析对照参数；真实调用必须显式确认，避免被误当成单测跑起来."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fund-code",
        dest="fund_codes",
        action="append",
        default=[],
        help="可重复；对比两只时传 --fund-code 000001 --fund-code 000002",
    )
    parser.add_argument("--query", default="请分析这只基金是否适合长期定投，并说明适用条件。")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--user-id", type=int, default=24, help="默认用测试账号，不要用真实用户")
    parser.add_argument("--strategies", nargs="+", default=["single", "multi_role"], choices=["single", "multi_role"])
    parser.add_argument("--timeout", type=float, default=420.0)
    parser.add_argument("--out", default=".runtime/research-mode-comparison.json")
    parser.add_argument("--yes-live", action="store_true", help="确认这次要打真模型与真数据源")
    return parser.parse_args()


async def mint_session(user_id: int) -> str:
    """建一条只为这次对照存在的会话，返回它的访问令牌."""
    session_id = str(uuid.uuid4())
    await database_service.create_session(session_id, user_id, name="research-mode-compare", username="tester")
    return create_access_token(session_id).access_token


def measure(text: str, frames: dict[str, int]) -> dict[str, Any]:
    """从正文和帧计数里提取可比较的结构指标."""
    audited = AUDITED.search(text)
    return {
        "chars": len(text),
        "sections": len(SECTION.findall(text)),
        "owner_sections": len(OWNER_HEADING.findall(text)),
        "internal_key_hits": len(INTERNAL_KEYS.findall(text)),
        "chart_blocks": text.count("```fund-chart"),
        "citations": len(CITATION.findall(text)),
        "audit_matched": int(audited.group(1)) if audited else None,
        "audit_unknown": int(audited.group(2)) if audited else None,
        "markers": {name: marker in text for name, marker in MARKERS.items()},
        **frames,
    }


async def run_once(client: httpx.AsyncClient, token: str, args: argparse.Namespace, strategy: str) -> dict[str, Any]:
    """跑一个档位，返回延迟与结构指标."""
    payload = {
        "messages": [{"role": "user", "content": args.query}],
        "research_fund_codes": list(args.fund_codes),
        "research_strategy": strategy,
    }
    started = time.perf_counter()
    first_content_at: float | None = None
    parts: list[str] = []
    frames = {"progress_frames": 0, "activity_frames": 0}
    async with client.stream(
        "POST", f"{args.base_url}/chatbot/chat/stream", json=payload, headers={"Authorization": f"Bearer {token}"}
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            frame = json.loads(line[6:])
            if frame.get("research_progress"):
                frames["progress_frames"] += 1
            elif frame.get("research_activity"):
                frames["activity_frames"] += 1
            content = frame.get("content") or ""
            if content:
                if first_content_at is None:
                    first_content_at = time.perf_counter()
                parts.append(content)
    text = "".join(parts)
    elapsed = time.perf_counter() - started
    metrics = {
        "strategy": strategy,
        "ttft_seconds": round((first_content_at or started) - started, 2),
        "total_seconds": round(elapsed, 2),
        **measure(text, frames),
    }
    return metrics, text


async def main() -> None:
    """两个档位各跑一次并打印对照表；结果落 .runtime/，便于跨轮比较."""
    args = parse_args()
    args.fund_codes = args.fund_codes or ["000001"]
    if not args.yes_live:
        raise SystemExit("真实对照会打真模型与真数据源，请加 --yes-live 明确确认。")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    token = await mint_session(args.user_id)
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(trust_env=False, timeout=args.timeout) as client:
        for strategy in args.strategies:
            console = Console()
            console.print(f"[cyan]running[/cyan] strategy={strategy} funds={','.join(args.fund_codes)}")
            metrics, text = await run_once(client, token, args, strategy)
            results.append(metrics)
            # 指标只能说明形状对不对；"像不像一个团队"要有人读一遍原文。
            Path(f"{args.out}.{strategy}.md").write_text(text, encoding="utf-8")

    table = Table(title="研究档位对照（真实模型，客户端可见口径）")
    for column in (
        "档位",
        "首字(s)",
        "总耗时(s)",
        "正文字符",
        "小节",
        "署名节",
        "漏键名",
        "图表块",
        "引用",
        "核对到/未知",
        "进度帧",
        "活动帧",
    ):
        table.add_column(column, justify="right")
    for item in results:
        table.add_row(
            item["strategy"],
            str(item["ttft_seconds"]),
            str(item["total_seconds"]),
            str(item["chars"]),
            str(item["sections"]),
            str(item["owner_sections"]),
            str(item["internal_key_hits"]),
            str(item["chart_blocks"]),
            str(item["citations"]),
            f"{item['audit_matched']}/{item['audit_unknown']}",
            str(item["progress_frames"]),
            str(item["activity_frames"]),
        )
    console = Console()
    console.print(table)
    for item in results:
        missing = [name for name, hit in item["markers"].items() if not hit]
        console.print(f"[yellow]{item['strategy']}[/yellow] 缺少小节：" + ("、".join(missing) if missing else "无"))

    payload = {"fund_codes": args.fund_codes, "query": args.query, "runs": results}
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    console.print(f"[green]saved[/green] {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
