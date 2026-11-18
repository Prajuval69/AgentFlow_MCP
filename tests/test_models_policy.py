import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from agentflow.domain import Plan, PlanRequest, Predicate, Step
from agentflow.policy import evaluate


@pytest.mark.parametrize("prompt", ["", " ", "a" * 4001])
def test_invalid_prompts(prompt):
    with pytest.raises(ValidationError):
        PlanRequest(prompt=prompt)


def test_strict_fields_and_identifier():
    with pytest.raises(ValidationError):
        PlanRequest(prompt="hello", unexpected="secret")
    assert Step(id=" start ", action_type="manual_trigger").id == "start"
    for step_id in ["../evil", "a b", "$(shell)", "x" * 81]:
        with pytest.raises(ValidationError):
            Step(id=step_id, action_type="manual_trigger")


@pytest.mark.parametrize(
    "action,inputs",
    [
        (
            "compare_number",
            {"predicate": {"operator": "greater_than", "field": "total_amount", "value": "5"}},
        ),
        ("send_notification", {"recipient": "x", "text": "test", "url": "http://evil"}),
        ("custom_api", {"endpoint": "http://169.254.169.254/metadata", "payload": {}}),
        ("create_list_item", {"item_id": "ok", "fields": {"id": "replace"}}),
        ("delay_simulated", {"seconds": "123"}),
        ("delay_simulated", {"seconds": -1}),
        ("execute_shell", {"command": "whoami"}),
        ("manual_trigger", {"approval": True}),
    ],
)
def test_typed_action_inputs(action, inputs):
    with pytest.raises(ValidationError):
        Step(id="x", action_type=action, inputs=inputs)


@pytest.mark.parametrize(
    "operator,value,data,expected",
    [
        ("greater_than", 50, 51, True),
        ("greater_than", 50, "50", False),
        ("less_than", 50, "49", True),
        ("equals", "x", "x", True),
        ("equals", 1, True, False),
        ("contains", "ab", "abc", True),
    ],
)
def test_conditions(operator, value, data, expected):
    assert evaluate(Predicate(operator=operator, field="x", value=value), {"x": data}) is expected


@pytest.mark.parametrize(
    "data", [{}, {"x": "nan"}, {"x": "inf"}, {"x": True}, {"x": []}, {"x": "no"}, {"x": "1e20"}]
)
def test_condition_bad_data(data):
    with pytest.raises(ValueError):
        evaluate(Predicate(operator="greater_than", field="x", value=5), data)


def test_boolean_conditions():
    p = Predicate(
        operator="and",
        operands=[
            Predicate(operator="equals", field="x", value="ok"),
            Predicate(operator="greater_than", field="y", value=10),
        ],
    )
    assert evaluate(p, {"x": "ok", "y": 11})
    assert not evaluate(p, {"x": "no", "y": 11})
    with pytest.raises(ValidationError):
        Predicate(operator="or", operands=[])


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda p: p["steps"].append(p["steps"][0].copy()), "DUPLICATE_STEP"),
        (lambda p: p["steps"][0].update(next_on_success="missing"), "DANGLING_EDGE"),
        (lambda p: p["steps"][1].update(next_on_success="start"), "CYCLE"),
        (lambda p: p["steps"][2].update(approval_required=False), "APPROVAL_REQUIRED"),
        (lambda p: p["steps"][1].update(next_on_failure=None), "MISSING_BRANCH"),
        (lambda p: p["steps"][0].update(next_on_success=None), "MISSING_SUCCESS"),
        (lambda p: p["steps"][-1].update(next_on_success="start"), "TERMINAL_EDGE"),
        (lambda p: p.update(evidence=[]), "UNGROUNDED"),
        (lambda p: p["evidence"][0].update(version="forged"), "INVALID_EVIDENCE"),
        (
            lambda p: p["steps"].append(
                {"id": "unreachable", "action_type": "terminate", "inputs": {}}
            ),
            "UNREACHABLE",
        ),
        (lambda p: p.update(requires_manual_review=True), "MANUAL_REVIEW"),
        (lambda p: p["steps"][0].update(action_type="download_tool"), "SCHEMA_INVALID"),
    ],
)
def test_graph_and_security_validation(service, invoice, mutate, code):
    raw = invoice.model_dump()
    mutate(raw)
    result = service.validate(raw)
    assert not result.valid
    assert result.requires_manual_review
    assert code in [issue.code for issue in result.issues]


def test_schema_snapshot_and_conditional_inputs(invoice):
    snapshot = json.loads(Path("schemas/plan.schema.json").read_text())
    assert snapshot == Plan.model_json_schema()
    jsonschema.Draft202012Validator.check_schema(snapshot)
    jsonschema.validate(invoice.model_dump(), snapshot)
    example = json.loads(Path("schemas/plan_example.json").read_text())
    jsonschema.validate(example, snapshot)
    assert Plan.model_validate(example).simulation_mode
    bad = invoice.model_dump()
    bad["steps"][0]["inputs"] = {"arbitrary": "value"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, snapshot)
