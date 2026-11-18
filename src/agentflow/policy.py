"""Catalog grounding, DAG validation and non-executable predicates."""

import hashlib
import json
import math
from typing import Any

from pydantic import ValidationError

from agentflow.domain import Catalog, Document, Issue, Plan, Predicate, Verdict

PROTECTED = {"manager_approval", "create_list_item", "update_list_item"}
WRITES = {"send_notification", "create_list_item", "update_list_item", "log_event"}


def evaluate(predicate: Predicate, data: dict[str, Any], depth: int = 0) -> bool:
    if depth > 10:
        raise ValueError("Predicate nesting exceeds 10")
    if predicate.operator == "and":
        return all(evaluate(p, data, depth + 1) for p in predicate.operands)
    if predicate.operator == "or":
        return any(evaluate(p, data, depth + 1) for p in predicate.operands)
    if predicate.field not in data:
        raise ValueError(f"Missing condition field: {predicate.field}")
    actual = data[predicate.field]
    if predicate.operator == "equals":
        return type(actual) is type(predicate.value) and actual == predicate.value
    if predicate.operator == "contains":
        if not isinstance(actual, str):
            raise ValueError("Contains requires string data")
        return predicate.value in actual
    if isinstance(actual, bool) or not isinstance(actual, (int, float, str)):
        raise ValueError("Expected bounded numeric data")
    try:
        number = float(actual)
    except (ValueError, OverflowError):
        raise ValueError("Invalid numeric data") from None
    if not math.isfinite(number) or abs(number) > 1e15:
        raise ValueError("Nonfinite or unbounded numeric data")
    return (
        number > predicate.value
        if predicate.operator == "greater_than"
        else number < predicate.value
    )


def validate(raw: dict | Plan, catalog: Catalog, documents: list[Document]) -> Verdict:
    issues: list[Issue] = []
    try:
        if len(json.dumps(raw.model_dump() if isinstance(raw, Plan) else raw).encode()) > 100_000:
            return Verdict(
                valid=False,
                requires_manual_review=True,
                issues=[Issue(code="PLAN_SIZE", message="Plan exceeds 100KB.")],
            )
        plan = Plan.model_validate(raw.model_dump() if isinstance(raw, Plan) else raw)
    except (ValidationError, ValueError, TypeError, RecursionError):
        return Verdict(
            valid=False,
            requires_manual_review=True,
            issues=[
                Issue(
                    code="SCHEMA_INVALID",
                    message="Plan schema rejected; check typed action inputs and required fields.",
                )
            ],
        )

    def add(code: str, message: str, step_id: str | None = None) -> None:
        issues.append(Issue(code=code, message=message, step_id=step_id))

    if plan.requires_manual_review:
        add("MANUAL_REVIEW", "Plan requires human review and cannot execute.")
    if not plan.steps:
        add("EMPTY_PLAN", "Executable plans require at least one step.")
    ids = [step.id for step in plan.steps]
    if len(set(ids)) != len(ids):
        add("DUPLICATE_STEP", "Step IDs must be unique.")
    by_id = {step.id: step for step in plan.steps}
    allowed = {a.type: a for a in catalog.actions}
    doc_map = {doc.id: doc for doc in documents}
    if plan.steps and not plan.evidence:
        add("UNGROUNDED", "Executable plans require local document evidence.")
    for evidence in plan.evidence:
        doc = doc_map.get(evidence.source_id)
        if (
            not doc
            or not evidence.passage
            or evidence.version != doc.version
            or evidence.title != doc.title
            or evidence.passage not in doc.content
            or evidence.content_sha256 != hashlib.sha256(doc.content.encode()).hexdigest()
        ):
            add("INVALID_EVIDENCE", "Evidence must match a seeded document and version.")
    for step in plan.steps:
        if step.action_type not in allowed:
            add("UNSUPPORTED_ACTION", "Action is absent from the local catalog.", step.id)
        if (
            step.action_type in PROTECTED
            or (step.action_type in allowed and allowed[step.action_type].requires_approval)
        ) and not step.approval_required:
            add("APPROVAL_REQUIRED", "Protected action must declare approval_required.", step.id)
        for target in (step.next_on_success, step.next_on_failure):
            if target and target not in by_id:
                add("DANGLING_EDGE", "Transition references a missing step.", step.id)
        if step.action_type == "terminate" and (step.next_on_success or step.next_on_failure):
            add("TERMINAL_EDGE", "Terminate must have no transitions.", step.id)
        if step.action_type != "terminate" and not step.next_on_success:
            add("MISSING_SUCCESS", "Nonterminal steps require a success transition.", step.id)
        if step.action_type in {"compare_number", "manager_approval"} and not step.next_on_failure:
            add("MISSING_BRANCH", "Condition/approval requires both outcomes.", step.id)
        if step.action_type == "compare_number":
            predicate = Predicate.model_validate(step.inputs["predicate"])

            def check_depth(p: Predicate, depth: int = 0, step_id: str = step.id):
                if depth > 10:
                    add("PREDICATE_DEPTH", "Predicate depth exceeds 10.", step_id)
                else:
                    for operand in p.operands:
                        check_depth(operand, depth + 1, step_id)

            check_depth(predicate)
    if plan.steps and plan.steps[0].action_type != "manual_trigger":
        add("ENTRYPOINT", "First step must be a manual trigger.")
    if sum(s.action_type == "manual_trigger" for s in plan.steps) != 1:
        add("ENTRYPOINT_COUNT", "Executable plans require exactly one manual trigger.")
    visited, active = set(), set()

    def walk(key: str, depth: int) -> None:
        if key in active:
            add("CYCLE", "Loops are not supported.", key)
            return
        if depth > 50:
            add("DEPTH_LIMIT", "Plan depth exceeds 50.", key)
            return
        if key in visited or key not in by_id:
            return
        active.add(key)
        step = by_id[key]
        for target in (step.next_on_success, step.next_on_failure):
            if target:
                walk(target, depth + 1)
        active.remove(key)
        visited.add(key)

    if plan.steps:
        walk(plan.steps[0].id, 0)
        if not any(issue.code in {"CYCLE", "DANGLING_EDGE"} for issue in issues):
            longest_paths: dict[str, int] = {}

            def longest(key: str) -> int:
                if key not in longest_paths:
                    step = by_id[key]
                    targets = [t for t in (step.next_on_success, step.next_on_failure) if t]
                    longest_paths[key] = 1 + max((longest(t) for t in targets), default=0)
                return longest_paths[key]

            if longest(plan.steps[0].id) > 51:
                add("DEPTH_LIMIT", "Longest plan path exceeds 50 transitions.")
        if visited != set(by_id):
            add("UNREACHABLE", "All declared steps must be reachable from entry.")
        if not any(step.action_type == "terminate" for step in plan.steps):
            add("NO_TERMINAL", "Plan must include a terminal path.")
    return Verdict(valid=not issues, requires_manual_review=bool(issues), issues=issues)
