"""运行离线多角色 fixture 评测并写出 JSON 报告.

用法：python -m scripts.eval_multi_role --output .runtime/multi-role-eval.json
"""

import argparse
import asyncio
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from evals.multi_role_eval import evaluate


async def run(output: Path) -> dict:
    """执行 fixture 评测、写 JSON 报告并打印汇总."""
    report = await evaluate()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table = Table(title="Offline multi-role fixture evaluation")
    table.add_column("Case")
    table.add_column("Coverage")
    table.add_column("Revisions")
    table.add_column("Unknown", justify="right")
    table.add_column("Duplicate", justify="right")
    table.add_column("Calls", justify="right")
    for item in report["results"]:
        table.add_row(
            item["id"],
            ",".join(f"{role}:{status}" for role, status in item["coverage"].items()),
            ",".join(item["revision_roles"]) or "-",
            str(item["unknown_citations"]),
            str(item["duplicate_claims"]),
            str(item["calls"]),
        )
    Console().print(table)
    Console().print("Summary:", json.dumps(report["summary"], ensure_ascii=False))
    Console().print("Saved:", str(output))
    return report


def main() -> None:
    """CLI entry point; no network or model call is made."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".runtime/multi-role-eval.json"))
    args = parser.parse_args()
    asyncio.run(run(args.output))


if __name__ == "__main__":
    main()
