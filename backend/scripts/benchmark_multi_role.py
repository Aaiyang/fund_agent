"""Measure scheduler overhead with a fixed-delay model substitute, without real LLM or fund calls.

Run from backend: python -m scripts.benchmark_multi_role --delay-ms 100 --runs 5
This is a controlled comparison of the communication stages only. It proves the graph
fans the dimensions out in parallel and skips unneeded revision rounds; it says nothing
about report quality or real provider latency. Use ``scripts.compare_research_modes``
for that.
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from app.agent.graph.multi_role_research import build_multi_role_subgraph
from app.agent.graph.research_contract import build_assignments
from app.schemas.multi_role_research import AgentAnalysis, EvidenceFinding, ResearchReview
from app.schemas.research import ResearchEvidence, ResearchGraphState, ResearchRequest, ResearchTask

# 五个维度各自要求的来源；补齐这几项，受控基准才会走满今天真实的扇出。
_SOURCES = (
    "get_fund_snapshot",
    "get_fund_benchmark",
    "get_fund_analysis_data",
    "get_fund_holdings",
    "get_fund_managers",
    "get_fund_announcements",
)


async def measure(delay: float) -> dict:
    """Both schedulers use the same fixed call delay; evidence and final synthesis are excluded."""
    calls = 0

    async def model(prompt: str, data: str, schema: type[BaseModel], config: Any, **_: Any) -> BaseModel:
        nonlocal calls
        calls += 1
        await asyncio.sleep(delay)
        if schema is ResearchReview:
            return ResearchReview()
        payload = json.loads(data)
        findings = []
        for requirement in payload["assignments"][0]["required_evidence"]:
            refs = [item["evidence_id"] for item in payload["evidence"] if item["tool"] in requirement["tools"]]
            if refs:
                findings.append(
                    EvidenceFinding(
                        claim="模拟发现，不用于投资分析",
                        kind="conditional",
                        evidence_ids=[refs[0]],
                        limitation="非真实基金证据",
                    )
                )
        return AgentAnalysis(findings=findings)

    async def fetch(*args: Any) -> ResearchEvidence:
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
            for name in _SOURCES
        ],
    )
    dimensions = len(build_assignments(state))
    graph = build_multi_role_subgraph(model, lambda value: ([item.model_dump() for item in value.evidence], []), fetch)
    started = time.monotonic()
    result = await graph.ainvoke(state)
    optimized = time.monotonic() - started
    assert not result["gaps"], result["gaps"]

    # Reference: every dimension always runs two rounds, whatever the reviewer says.
    started = time.monotonic()
    await asyncio.gather(*(asyncio.sleep(delay) for _ in range(dimensions)))
    await asyncio.sleep(delay)
    await asyncio.gather(*(asyncio.sleep(delay) for _ in range(dimensions)))
    fixed_round = time.monotonic() - started
    return {
        "dimensions": dimensions,
        "fixed_round_ms": round(fixed_round * 1000, 2),
        "optimized_ms": round(optimized * 1000, 2),
        "fixed_round_calls": 2 * dimensions + 1,
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
    dimensions = samples[0]["dimensions"]
    table = Table(title="Controlled multi-role scheduler benchmark (mock model)")
    table.add_column("Scheduler")
    table.add_column("Structured calls", justify="right")
    table.add_column("Median ms", justify="right")
    table.add_row(
        f"Fixed two-round reference ({dimensions} dimensions)",
        str(samples[0]["fixed_round_calls"]),
        str(report["median_fixed_round_ms"]),
    )
    table.add_row(
        "Optimized graph (revision only when asked)",
        str(statistics.median(row["optimized_calls"] for row in samples)),
        str(report["median_optimized_ms"]),
    )
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
