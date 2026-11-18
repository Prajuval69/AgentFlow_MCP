# Domain contract and workflow semantics

Implementation note: `schemas/plan.schema.json` is snapshot-tested and includes conditional per-action input schemas. `schemas/plan_example.json` is an executable current example. Compare inputs now use a nested typed `predicate`; evidence uses provenance objects and hashes. Golden fixtures explicitly include data, reviewer decisions and expected execution paths. Limits are 100 steps, 50 transitions on the longest path, predicate depth 10, 100KB request/plan, 16KB item fields and 4KB stub payload. Loops are rejected. Missing fields fail; numeric strings are safely coerced at evaluation; equality compares exact types and boolean predicates short-circuit. Lookup/write outputs merge into simulation state; custom summaries use `data.summary`. A handled failure path still ends with failed status, never fabricated success. Approvals are independent of input data and bound to the plan digest.

Plan includes id, title, intent, version, schema_version, steps, evidence, warnings, requires_manual_review, simulation_mode. Step fields: id, action_type from allowlist, inputs, next_on_success, next_on_failure, approval_required. Conditions expressed as typed predicates, never executable Python/JS strings. Supported operands: equals, greater_than, less_than, contains, and, or. Support numeric coercion safely and define missing field behavior.

Actions to seed: `manual_trigger`, `compare_number`, `manager_approval`, `send_notification`, `create_list_item`, `update_list_item`, `lookup_list_item`, `delay_simulated`, `terminate`, `log_event`.

Strong validation: valid DAG or explicitly bounded loops (prefer DAG), unique step IDs, no dangling references, all branches reachable, terminal path, size and depth limits, valid approved actions, well-typed action inputs, input/output contract for transitions, Pydantic strict mode and descriptive validation error codes.

Simulation: deterministic clock/time provider, captured execution trace per step, approval policy based on fixture decisions, zero external side effects, explicit `mode: simulated`. Approval cannot be silently auto-granted in authorization-critical flows.

Provide plan JSON Schema through Pydantic export and snapshot-test it. See schemas/plan_example.json as *illustrative* and refine as needed without breaking fixtures silently.
