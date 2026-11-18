import json

from agentflow.config import DATA
from agentflow.eval.run import evaluate_dataset, markdown, ratio


def test_evaluation_metrics_and_traces():
    report = evaluate_dataset(DATA / "eval_cases.jsonl")
    assert len(report["cases"]) == 8
    assert all(case["score"] == 1 for case in report["cases"])
    for name in [
        "schema_validity",
        "mapping_exact_match",
        "unsupported_precision",
        "unsupported_recall",
        "unsupported_f1",
        "tool_call_correctness",
        "retrieval_hit_at_3",
        "execution_fidelity",
    ]:
        assert report["metrics"][name]["value"] == 1
    assert report["metrics"]["mapping_exact_match"]["denominator"] == 5
    assert report["metrics"]["tool_failure_responses"]["numerator"] == 4
    assert all(p["passed"] for p in report["failure_probes"])
    assert report["metrics"]["unsupported_recall"]["denominator"] == 3
    assert report["metrics"]["latency_ms"]["p95"] > 0
    assert report["cases"][0]["trace"]["outcome"] == "finance_notified_simulated"
    assert "Definitions" in markdown(report)
    assert ratio(0, 0, "empty")["value"] is None


def test_empty_and_failure_datasets(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    report = evaluate_dataset(empty)
    assert report["metrics"]["schema_validity"]["value"] is None
    malformed = tmp_path / "failure.jsonl"
    case = json.loads((DATA / "eval_cases.jsonl").read_text().splitlines()[0])
    case["input"] = " "
    malformed.write_text(json.dumps(case))
    report = evaluate_dataset(malformed)
    assert report["metrics"]["schema_validity"]["value"] == 0
    assert report["metrics"]["mapping_exact_match"]["denominator"] == 1
    assert report["cases"][0]["score"] == 0
    assert report["metrics"]["tool_call_correctness"]["denominator"] == 5
