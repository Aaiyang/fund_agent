"""Measure scheduler overhead with a fixed-delay model substitute, without real LLM or fund calls.

Run from backend: python -m scripts.benchmark_multi_role --delay-ms 100 --runs 5
This is a controlled comparison of communication stages, not a real LLM latency benchmark.
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from app.agent.graph.multi_role_research import build_multi_role_subgraph
from app.schemas.multi_role_research import AgentAnalysis, EvidenceFinding, ResearchReview, TaskCoverage
from app.schemas.research import ResearchEvidence, ResearchGraphState, ResearchRequest, ResearchTask


async def measure(delay: float) -> dict:
    """Both schedulers use the same fixed call delay; evidence and final synthesis are excluded."""
    calls = 0

    async def model(prompt, data, schema, config) -> BaseModel:
        nonlocal calls
        calls += 1
        await asyncio.sleep(delay)
        if schema is ResearchReview:
            return ResearchReview()
        payload = json.loads(data)
        findings = []
        covered = []
        for task in payload["assignments"]:
            refs = [
                next(entry["evidence_id"] for entry in payload["evidence"] if entry["tool"] in group)
                for group in task["required_tool_groups"]
            ]
            refs = list(dict.fromkeys(refs or [payload["evidence"][0]["evidence_id"]]))
            covered.append(
                TaskCoverage(
                    task_id=task["task_id"],
                    status="completed",
                    finding_indices=[len(findings)],
                    evidence_ids=refs,
                    explanation="受控基准模拟覆盖",
                )
            )
            findings.append(
                EvidenceFinding(
                    claim="模拟发现，不用于投资分析",
                    kind="conditional",
                    evidence_ids=refs,
                    limitation="非真实基金证据",
                )
            )
        return AgentAnalysis(findings=findings, coverage=covered)

    async def fetch(*args) -> ResearchEvidence:
        raise AssertionError("clean review must not request supplements")

    task = ResearchTask(
        turn_id="benchmark",
        request=ResearchRequest(intent="fund_research", fund_queries=["000001"], strategy="multi_role"),
        instruction="受控基准",
    )
    state = ResearchGraphState(
        turn_id=task.turn_id,
        research_task=task,
        fund_codes=["000001"],
        evidence=[
            ResearchEvidence(tool=name, args={"fund_code": "000001"}, success=True, text="受控来源")
            for name in ("get_fund_snapshot", "get_fund_analysis_data", "get_fund_managers", "get_fund_holdings")
        ],
    )
    graph = build_multi_role_subgraph(model, lambda value: ([item.model_dump() for item in value.evidence], []), fetch)
    started = time.monotonic()
    result = await graph.ainvoke(state)
    optimized = time.monotonic() - started
    assert not result["gaps"]

    # Reference: two parallel analysts -> reviewer -> both analysts again, always.
    started = time.monotonic()
    await asyncio.gather(asyncio.sleep(delay), asyncio.sleep(delay))
    await asyncio.sleep(delay)
    await asyncio.gather(asyncio.sleep(delay), asyncio.sleep(delay))
    fixed_round = time.monotonic() - started
    return {
        "fixed_round_ms": round(fixed_round * 1000, 2),
        "optimized_ms": round(optimized * 1000, 2),
        "fixed_round_calls": 5,
        "optimized_calls": calls,
    }


async def benchmark(delay: float, runs: int, output: Path) -> None:
    """Warm the graph runtime, then save reproducible parameters and every measured sample."""
    await measure(delay)
    samples = [await measure(delay) for _ in range(runs)]
    report = {
        "scope": "mock communication stages; no evidence collection, final report or real provider",
        "delay_ms": delay * 1000,
        "runs": runs,
        "samples": samples,
        "median_fixed_round_ms": statistics.median(row["fixed_round_ms"] for row in samples),
        "median_optimized_ms": statistics.median(row["optimized_ms"] for row in samples),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table = Table(title="Controlled multi-role scheduler benchmark (mock model)")
    table.add_column("Scheduler")
    table.add_column("Calls", justify="right")
    table.add_column("Median ms", justify="right")
    table.add_row("Fixed two-round reference", "5", str(report["median_fixed_round_ms"]))
    table.add_row("Optimized graph", "3", str(report["median_optimized_ms"]))
    Console().print(table)
    Console().print("Saved:", str(output))


def main() -> None:
    """CLI entry point; clamp simulation cost and avoid real model calls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay-ms", type=float, default=100)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path(".runtime/multi-role-benchmark.json"))
    args = parser.parse_args()
    asyncio.run(benchmark(max(1, min(1000, args.delay_ms)) / 1000, max(1, min(20, args.runs)), args.output))


if __name__ == "__main__":
    main()
