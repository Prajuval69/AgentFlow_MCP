"""Run labeled fixtures, keeping actual per-case evidence, traces and denominators."""

import argparse
import asyncio
import json
import math
import time
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from agentflow.config import DATA, Settings
from agentflow.domain import (
    INPUT_MODELS,
    ActionType,
    ApprovalRequest,
    EvaluationReport,
    Identifier,
    Plan,
    PlanRequest,
    SimulationRequest,
    StrictModel,
)
from agentflow.service import Service


class EvalCase(StrictModel):
    id: Identifier
    input: str
    supported: bool
    expected_actions: list[ActionType]
    required_doc_ids: list[Identifier]
    expected_outcome: str
    data: dict = Field(default_factory=dict)
    approvals: dict[str, str] = Field(default_factory=dict)
    expected_path: list[ActionType] = Field(default_factory=list)


def ratio(numerator: int, denominator: int, definition: str) -> dict:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "definition": definition,
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


async def failure_probes() -> list[dict]:
    from mcp.types import CallToolResult

    from agentflow.mcp_server import create_server

    service = Service(Settings(db_path=":memory:"))
    server = create_server(service)
    probes = [
        ("get_run_trace", {"run_id": "missing"}, "NOT_FOUND"),
        ("generate_workflow_plan", {"prompt": " "}, "SCHEMA_INVALID"),
        ("execute_shell", {"command": "blocked"}, "UNKNOWN_TOOL"),
        ("simulate_workflow", {"plan_id": "missing", "persona": "admin"}, "SCHEMA_INVALID"),
    ]
    results = []
    try:
        for tool, inputs, expected in probes:
            response = await server.call_tool(tool, inputs)
            body = (
                response.structuredContent if isinstance(response, CallToolResult) else response[1]
            )
            results.append(
                {
                    "tool": tool,
                    "input": inputs,
                    "expected_code": expected,
                    "response": body,
                    "passed": body["ok"] is False
                    and body["error"]["code"] == expected
                    and bool(body["error"]["trace_id"]),
                }
            )
    finally:
        service.store.close()
    return results


def evaluate_dataset(
    dataset: Path,
    provider: str = "mock",
    settings: Settings | None = None,
    async_runner: Callable = asyncio.run,
) -> dict:
    cases = [
        EvalCase.model_validate_json(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("Evaluation case IDs must be unique")
    results, durations = [], []
    schema_valid = matches = tp = fp = fn = retrieval_hits = execution_matches = 0
    correct_calls = call_denominator = 0
    supported_count = sum(case.supported for case in cases)
    retrieval_count = sum(bool(case.required_doc_ids) for case in cases)
    config = (settings or Settings()).model_copy(
        update={"db_path": ":memory:", "provider": provider}
    )
    for case in cases:
        started = time.perf_counter()
        expected_path = case.expected_path or case.expected_actions
        if case.supported:
            call_denominator += len(expected_path)
        service = Service(config)
        try:
            plan = service.generate(PlanRequest(prompt=case.input))
            Plan.model_validate_json(plan.model_dump_json())
            schema_valid += 1
            verdict = service.validate(plan)
            predicted_unsupported = plan.requires_manual_review
            tp += int(predicted_unsupported and not case.supported)
            fp += int(predicted_unsupported and case.supported)
            fn += int(not predicted_unsupported and not case.supported)
            # Mapping is ordered unique action types; branch terminal duplication is structural.
            actions = list(dict.fromkeys(s.action_type for s in plan.steps))
            mapping_match = actions == case.expected_actions
            if case.supported:
                matches += int(mapping_match)
            retrieved = [e.source_id for e in plan.evidence[:3]]
            hit = all(doc in retrieved for doc in case.required_doc_ids)
            retrieval_hits += int(bool(case.required_doc_ids) and hit)
            run = None
            if case.supported:
                for step_id, decision in case.approvals.items():
                    service.approve(
                        plan.id, ApprovalRequest(step_id=step_id, decision=decision), "reviewer"
                    )
                run = service.simulate(plan.id, SimulationRequest(data=case.data))
                execution_matches += int(
                    run.status == "completed" and run.outcome == case.expected_outcome
                )
                expected_path = case.expected_path or case.expected_actions
                actual_path = [step.action_type for step in run.steps]
                call_denominator += max(0, len(actual_path) - len(expected_path))
                by_id = {step.id: step for step in plan.steps}
                for index, step in enumerate(run.steps):
                    typed_valid = False
                    try:
                        INPUT_MODELS[step.action_type].model_validate(by_id[step.step_id].inputs)
                        typed_valid = step.status in {"succeeded", "false", "rejected"}
                    except (ValueError, KeyError):
                        typed_valid = False
                    correct_calls += int(
                        typed_valid
                        and index < len(expected_path)
                        and step.action_type == expected_path[index]
                    )
            duration = (time.perf_counter() - started) * 1000
            results.append(
                {
                    "id": case.id,
                    "input": case.input,
                    "supported": case.supported,
                    "expected_actions": case.expected_actions,
                    "predicted_actions": actions,
                    "mapping_match": mapping_match,
                    "expected_outcome": case.expected_outcome,
                    "predicted_outcome": run.outcome if run else "manual_review",
                    "unsupported_detected": predicted_unsupported,
                    "retrieval_hit_at_3": hit,
                    "citations": [e.model_dump() for e in plan.evidence],
                    "predicted_plan": plan.model_dump(),
                    "validation": verdict.model_dump(),
                    "trace_id": run.id if run else None,
                    "trace": run.model_dump() if run else None,
                    "duration_ms": duration,
                    "score": int(
                        mapping_match
                        and hit
                        and (not case.supported or (run and run.outcome == case.expected_outcome))
                    ),
                }
            )
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000
            if not case.supported:
                fn += 1
            results.append(
                {
                    "id": case.id,
                    "input": case.input,
                    "error": type(exc).__name__,
                    "score": 0,
                    "duration_ms": duration,
                }
            )
        finally:
            service.store.close()
        durations.append(duration)
    precision = ratio(tp, tp + fp, "Correct unsupported predictions / all unsupported predictions")
    recall = ratio(tp, tp + fn, "Detected unsupported cases / all labeled unsupported cases")
    p, r = precision["value"], recall["value"]
    probes = async_runner(failure_probes())
    metrics = {
        "schema_validity": ratio(
            schema_valid,
            len(cases),
            "Strict schema-valid generated plans / all attempted generations, including review plans",
        ),
        "mapping_exact_match": ratio(
            matches,
            supported_count,
            "Ordered unique action types equal labels / all supported labeled cases",
        ),
        "unsupported_precision": precision,
        "unsupported_recall": recall,
        "unsupported_f1": {
            "value": None if p is None or r is None else (2 * p * r / (p + r) if p + r else 0),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        },
        "tool_call_correctness": ratio(
            correct_calls,
            call_denominator,
            "Schema-valid successful/false/rejected executed step at expected path position / sum(max(expected path length, actual path length)); missing and unexpected calls penalized",
        ),
        "retrieval_hit_at_3": ratio(
            retrieval_hits,
            retrieval_count,
            "Cases with ALL required source IDs in top 3 / cases with source labels",
        ),
        "execution_fidelity": ratio(
            execution_matches,
            supported_count,
            "Completed simulations matching expected terminal outcome / supported labeled cases",
        ),
        "tool_failure_responses": ratio(
            sum(p["passed"] for p in probes),
            len(probes),
            "Negative tool probes returning expected structured error code and durable audit trace ID / executed negative SDK handler probes; real transport is tested by pytest",
        ),
        "latency_ms": {
            "p50": percentile(durations, 0.5),
            "p95": percentile(durations, 0.95),
            "samples": len(durations),
            "definition": "Observed service initialization + retrieval + planning + reviewer fixture decisions + simulation; nearest-rank percentiles",
        },
    }
    return EvaluationReport.model_validate(
        {
            "id": "eval-" + uuid4().hex,
            "mode": "simulated",
            "synthetic": True,
            "provider": provider,
            "model": "deterministic-grammar-v1" if provider == "mock" else config.ollama_model,
            "versions": {name: version(name) for name in ("agentflow-mcp", "mcp", "pydantic")},
            "dataset": str(dataset),
            "metrics": metrics,
            "cases": results,
            "failure_probes": probes,
            "limitations": [
                "Synthetic fixtures measure this grammar, not general LLM accuracy.",
                "Each case has an isolated SQLite store. Complete traces are embedded in this report.",
                "Unsafe external-endpoint label 'rejected' is implemented as non-executable manual review.",
                "Tool call correctness measures action dispatch; negative responses use official SDK handlers; real stdio protocol is tested separately.",
            ],
        }
    ).model_dump()


def markdown(report: dict) -> str:
    lines = [
        "# AgentFlow evaluation",
        "",
        "SIMULATION — synthetic data; no Microsoft tenant.",
        "",
        f"Provider: {report['provider']}; model: {report['model']}",
        "",
        "| Metric | Observed value | Numerator / denominator |",
        "|---|---:|---:|",
    ]
    for name, metric in report["metrics"].items():
        lines.append(
            f"| {name} | {metric.get('value', metric)} | {metric.get('numerator', '—')} / {metric.get('denominator', '—')} |"
        )
    lines.extend(["", "| Case | Score | Duration (ms) |", "|---|---:|---:|"])
    lines.extend(
        f"| {case['id']} | {case['score']} | {case['duration_ms']:.3f} |"
        for case in report["cases"]
    )
    lines.extend(["", "## Definitions", ""])
    lines.extend(
        f"- {name}: {metric['definition']}"
        for name, metric in report["metrics"].items()
        if "definition" in metric
    )
    lines.extend(["", "## Limitations", ""])
    lines.extend("- " + limit for limit in report["limitations"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATA / "eval_cases.jsonl")
    parser.add_argument("--output", type=Path, default=Path("reports/eval.json"))
    parser.add_argument("--provider", choices=["mock", "ollama"], default="mock")
    args = parser.parse_args()
    report = evaluate_dataset(args.dataset, args.provider, Settings.from_env())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    if any("error" in case for case in report["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
