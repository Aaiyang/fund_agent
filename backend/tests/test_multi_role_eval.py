"""离线多角色 fixture 回归门：固定证据、固定输出，不联网、不调用模型."""

import json

from evals.multi_role_eval import _FIXTURES, evaluate


async def test_every_fixture_meets_its_expected_metrics() -> None:
    report = await evaluate()
    cases = json.loads(_FIXTURES.read_text(encoding="utf-8"))
    assert report["case_count"] == len(cases) >= 10
    results = {item["id"]: item for item in report["results"]}
    assert len(results) == len(cases)
    for case in cases:
        result = results[case["id"]]
        expected = case["expected"]
        for role, status in expected.get("coverage", {}).items():
            assert result["coverage"][role] == status, (case["id"], role, result["coverage"])
        assert result["revision_roles"] == expected.get("revision_roles", []), case["id"]
        assert result["unknown_citations"] == expected.get("unknown_citations", 0), case["id"]
        assert result["challenge_count"] == expected.get("challenge_count", 0), case["id"]
        assert result["duplicate_claims"] >= expected.get("min_duplicate_claims", 0), case["id"]
        assert result["findings"] > 0


async def test_eval_aggregate_stays_bounded_and_offline() -> None:
    report = await evaluate()
    summary = report["summary"]
    assert summary["unknown_citation_rate"] <= 0.05
    assert summary["mean_calls"] <= 8
    assert summary["max_wall_ms"] < 5000
