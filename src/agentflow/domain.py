"""Strict internal contracts; these are not Power Automate deployment schemas."""

import re
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
Role = Literal["viewer", "editor", "reviewer", "admin"]
ActionType = Literal[
    "manual_trigger",
    "compare_number",
    "manager_approval",
    "send_notification",
    "create_list_item",
    "update_list_item",
    "lookup_list_item",
    "delay_simulated",
    "terminate",
    "log_event",
    "custom_api",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_ids(cls, value, info):
        if info.field_name in {
            "id",
            "item_id",
            "step_id",
            "plan_id",
            "idempotency_key",
        } and isinstance(value, str):
            return value.strip()
        return value


class Predicate(StrictModel):
    operator: Literal["equals", "greater_than", "less_than", "contains", "and", "or"]
    field: Identifier | None = None
    value: JsonValue = None
    operands: list["Predicate"] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def shape(self) -> "Predicate":
        if self.operator in {"and", "or"}:
            if not 2 <= len(self.operands) <= 10 or self.field or self.value is not None:
                raise ValueError("Boolean predicates require 2–10 operands only.")
        elif self.field is None or self.operands:
            raise ValueError("Leaf predicates require a field and no operands.")
        elif self.operator in {"greater_than", "less_than"} and (
            type(self.value) not in {int, float} or abs(self.value) > 1e15
        ):
            raise ValueError("Numeric predicate requires a finite number within 1e15.")
        elif self.operator == "contains" and not isinstance(self.value, str):
            raise ValueError("Contains requires a string.")
        return self


class EmptyInputs(StrictModel):
    pass


class CompareInputs(StrictModel):
    predicate: Predicate


class ApprovalInputs(StrictModel):
    reviewer: Literal["demo-reviewer"] = "demo-reviewer"


class NotificationInputs(StrictModel):
    channel: Literal["mock_outbox"] = "mock_outbox"
    recipient: Annotated[str, Field(min_length=1, max_length=200)]
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class ListInputs(StrictModel):
    list_name: Literal["invoices"] = "invoices"
    item_id: Identifier
    fields: dict[str, JsonValue] = Field(default_factory=dict, max_length=20)

    @field_validator("fields")
    @classmethod
    def bounded_fields(cls, value):
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", k) for k in value):
            raise ValueError("Invalid field identifier.")
        if "id" in value:
            raise ValueError("Use item_id to identify the item.")
        return value


class LookupInputs(StrictModel):
    list_name: Literal["invoices"] = "invoices"
    item_id: Identifier


class DelayInputs(StrictModel):
    seconds: Annotated[int, Field(ge=0, le=31536000)]


class LogInputs(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class TerminateInputs(StrictModel):
    outcome: Annotated[str, Field(min_length=1, max_length=100)] = "completed_simulated"


class CustomInputs(StrictModel):
    endpoint: Literal["internal://invoice-summary"]
    payload: dict[str, JsonValue] = Field(default_factory=dict, max_length=20)


INPUT_MODELS = {
    "manual_trigger": EmptyInputs,
    "compare_number": CompareInputs,
    "manager_approval": ApprovalInputs,
    "send_notification": NotificationInputs,
    "create_list_item": ListInputs,
    "update_list_item": ListInputs,
    "lookup_list_item": LookupInputs,
    "delay_simulated": DelayInputs,
    "terminate": TerminateInputs,
    "log_event": LogInputs,
    "custom_api": CustomInputs,
}


class Step(StrictModel):
    id: Identifier
    action_type: ActionType
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    next_on_success: Identifier | None = None
    next_on_failure: Identifier | None = None
    approval_required: bool = False

    @model_validator(mode="after")
    def typed_inputs(self) -> "Step":
        # JSON validation also resolves recursive typed predicates without coercing strings.
        INPUT_MODELS[self.action_type].model_validate(self.inputs)
        return self


class Evidence(StrictModel):
    source_id: Identifier
    version: str
    title: str
    passage: str
    score: float
    content_sha256: str
    trusted_as_instructions: Literal[False] = False


class Plan(StrictModel):
    id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    intent: Annotated[str, Field(min_length=1, max_length=4000)]
    version: Annotated[int, Field(ge=1)] = 1
    schema_version: Literal["1.0"] = "1.0"
    steps: list[Step] = Field(max_length=100)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)
    warnings: list[str] = Field(default_factory=list)
    requires_manual_review: bool = False
    simulation_mode: Literal[True] = True
    provider: Literal["mock", "ollama"] = "mock"

    @classmethod
    def model_json_schema(cls, **kwargs) -> dict:
        schema = super().model_json_schema(**kwargs)
        constraints = []
        for action, model in INPUT_MODELS.items():
            inputs = model.model_json_schema()
            schema["$defs"].update(inputs.pop("$defs", {}))
            constraints.append(
                {
                    "if": {"properties": {"action_type": {"const": action}}},
                    "then": {"properties": {"inputs": inputs}},
                }
            )
        schema["$defs"]["Step"]["allOf"] = constraints
        return schema


class Issue(StrictModel):
    code: str
    message: str
    step_id: str | None = None


class Verdict(StrictModel):
    valid: bool
    requires_manual_review: bool
    issues: list[Issue]
    mode: Literal["simulated"] = "simulated"


class PlanRequest(StrictModel):
    prompt: Annotated[str, Field(min_length=1, max_length=4000)]

    @field_validator("prompt")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt cannot be blank.")
        return value.strip()


class SimulationRequest(StrictModel):
    data: dict[str, JsonValue] = Field(default_factory=dict, max_length=50)
    idempotency_key: Identifier | None = None


class ApprovalRequest(StrictModel):
    step_id: Identifier
    decision: Literal["approved", "rejected"]


class TraceStep(StrictModel):
    step_id: Identifier
    action_type: str
    status: Literal["succeeded", "false", "rejected", "blocked", "failed"]
    virtual_seconds: int
    details: dict[str, JsonValue] = Field(default_factory=dict)


class RunTrace(StrictModel):
    id: Identifier
    plan_id: Identifier
    status: Literal["completed", "blocked", "failed"]
    outcome: str
    persona: Role
    mode: Literal["simulated"] = "simulated"
    started_at: str
    steps: list[TraceStep]
    errors: list[Issue] = Field(default_factory=list)


class EventEnvelope(StrictModel):
    id: Identifier
    type: Literal["simulate_plan"]
    plan_id: Identifier
    data: dict[str, JsonValue] = Field(default_factory=dict, max_length=50)
    idempotency_key: Identifier


class Document(StrictModel):
    id: Identifier
    version: str
    title: str
    content: str


class CatalogAction(StrictModel):
    type: ActionType
    description: str
    requires_approval: bool
    side_effect: str
    input_schema: dict[str, JsonValue]


class Catalog(StrictModel):
    version: str
    mode: Literal["simulated"] = "simulated"
    actions: list[CatalogAction]


class Analysis(StrictModel):
    supported: bool
    reason: str
    evidence: list[Evidence]
    mode: Literal["simulated"] = "simulated"


class Health(StrictModel):
    status: Literal["ok", "degraded"]
    provider: Literal["mock", "ollama"]
    integrations: Literal["simulated"] = "simulated"
    identity: Literal["LOCAL_MOCK_PERSONAS_NOT_AUTHENTICATION"] = (
        "LOCAL_MOCK_PERSONAS_NOT_AUTHENTICATION"
    )
    notice: str = "SIMULATION — NOT CONNECTED TO MICROSOFT TENANT"
    webhook_enabled: bool
    provider_available: bool


class ApprovalRecord(StrictModel):
    plan_id: Identifier
    step_id: Identifier
    decision: Literal["approved", "rejected"]
    persona: Role
    plan_digest: str
    created_at: str


class AuditRecord(StrictModel):
    id: int
    kind: str
    created_at: str
    details: dict[str, JsonValue]


class EventRecord(StrictModel):
    id: Identifier
    status: Literal["pending", "processing", "retry", "completed", "dead_letter"]
    attempts: int
    next_attempt_at: float
    trace_id: str | None
    error: str | None


class EventReceipt(StrictModel):
    duplicate: bool
    event: EventRecord
    mode: Literal["simulated"] = "simulated"


class EvaluationReport(StrictModel):
    id: Identifier
    mode: Literal["simulated"] = "simulated"
    synthetic: Literal[True] = True
    provider: Literal["mock", "ollama"]
    model: str
    versions: dict[str, str]
    dataset: str
    metrics: dict[str, JsonValue]
    cases: list[dict[str, JsonValue]]
    failure_probes: list[dict[str, JsonValue]]
    limitations: list[str]


class Connection(StrictModel):
    id: Identifier
    provider: Literal["sharepoint", "m365", "azure", "internal"]
    mode: Literal["simulated"] = "simulated"
    status: Literal["SIMULATED_NOT_CONNECTED"] = "SIMULATED_NOT_CONNECTED"


class AgentFlowError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422, trace_id: str | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.trace_id = code, message, status, trace_id

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "trace_id": self.trace_id}


class ToolError(StrictModel):
    code: str
    message: str
    trace_id: str


T = TypeVar("T")


class ToolResponse(StrictModel, Generic[T]):
    ok: bool
    data: T | None = None
    error: ToolError | None = None
    mode: Literal["simulated"] = "simulated"
