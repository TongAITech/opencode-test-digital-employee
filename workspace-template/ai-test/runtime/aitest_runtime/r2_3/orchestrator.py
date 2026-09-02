"""R2.3 application orchestration over the existing R1.2 Work Graph."""

from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import CommandResult, RuntimeError as DurableRuntimeError
from aitest_runtime.durable_core import RuntimeService, canonical_sha256
from aitest_runtime.work_graph.contracts import EXTENSION_ID, PlanLifecycleState, WorkGraphState

from .contracts import (
    APPLIED,
    BLOCKED,
    DUPLICATE,
    GOAL_REVISION_REQUIRED,
    NO_CHANGE,
    REJECTED,
    STALE_CURSOR,
    PlanDecision,
    PlanResult,
    PlannerError,
    PlannerInput,
)
from .planner import derive_plan


CREATE_PLAN = "CREATE_PLAN"
RECORD_PLAN_REVISION = "RECORD_PLAN_REVISION"
ACTIVATE_PLAN_REVISION = "ACTIVATE_PLAN_REVISION"


def _command_id(planner_request_id: str, command_type: str) -> str:
    return f"r2.3:{planner_request_id}:{command_type}"


def _result(
    decision: PlanDecision,
    outcome: str,
    *,
    command_results: tuple[CommandResult, ...] = (),
    reason_code: str | None = None,
    reason: str | None = None,
    replayed: bool = False,
) -> PlanResult:
    return PlanResult(
        outcome=outcome,
        mission_id=decision.mission_id,
        active_goal_id=decision.active_goal_id,
        planner_request_id=decision.planner_request_id,
        request_digest=decision.request_digest,
        plan_id=decision.plan_id,
        revision_id=decision.revision_id,
        parent_revision_id=decision.parent_revision_id,
        content_hash=decision.content_hash,
        command_results=command_results,
        reason_code=reason_code or decision.reason_code,
        reason=reason or decision.reason,
        decision=decision,
        replayed=replayed,
    )


def _goal_scope_digest(definition: Mapping[str, Any]) -> str:
    value = definition.get("scope_digest")
    if isinstance(value, str) and value.strip():
        return value
    return canonical_sha256(definition.get("execution_scope", definition.get("scope", {})))


def _guard_goal(service: RuntimeService, item: PlannerInput) -> tuple[Any, WorkGraphState | None, PlanResult | None]:
    try:
        composed = service.get_composed_state(item.mission_id)
        mission = composed.core_state.mission
        if mission is None:
            raise DurableRuntimeError("MISSION_NOT_FOUND", f"Mission not found: {item.mission_id}")
        if mission.active_goal_id != item.active_goal_id:
            raise DurableRuntimeError("ACTIVE_GOAL_MISMATCH", "PlannerInput active_goal_id is not the durable active Goal")
        goal = composed.core_state.goal(item.active_goal_id)
        if goal is None:
            raise DurableRuntimeError("GOAL_NOT_FOUND", f"Goal not found: {item.active_goal_id}")
        if goal.status.value != "ACTIVE":
            raise DurableRuntimeError("GOAL_NOT_ACTIVE", "Planner requires an ACTIVE Goal")
        if goal.revision != item.goal_revision:
            decision = PlanDecision(
                GOAL_REVISION_REQUIRED,
                item.mission_id,
                item.active_goal_id,
                item.planner_request_id,
                item.request_digest,
                reason_code="GOAL_REVISION_REQUIRED",
                reason="durable Goal revision differs from PlannerInput",
                input=item,
            )
            return None, None, _result(decision, GOAL_REVISION_REQUIRED)
        actual_definition_digest = canonical_sha256(goal.definition)
        if actual_definition_digest != item.goal_definition_digest:
            decision = PlanDecision(
                GOAL_REVISION_REQUIRED,
                item.mission_id,
                item.active_goal_id,
                item.planner_request_id,
                item.request_digest,
                reason_code="GOAL_REVISION_REQUIRED",
                reason="durable Goal.definition differs from PlannerInput",
                input=item,
            )
            return None, None, _result(decision, GOAL_REVISION_REQUIRED)
        if _goal_scope_digest(goal.definition) != item.scope_digest:
            decision = PlanDecision(
                GOAL_REVISION_REQUIRED,
                item.mission_id,
                item.active_goal_id,
                item.planner_request_id,
                item.request_digest,
                reason_code="GOAL_REVISION_REQUIRED",
                reason="durable Goal scope differs from PlannerInput",
                input=item,
            )
            return None, None, _result(decision, GOAL_REVISION_REQUIRED)
        graph = composed.extension_state(EXTENSION_ID)
        if not isinstance(graph, WorkGraphState):
            raise DurableRuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Work Graph state")
        return goal, graph, None
    except DurableRuntimeError as exc:
        decision = PlanDecision(
            REJECTED,
            item.mission_id,
            item.active_goal_id,
            item.planner_request_id,
            item.request_digest,
            reason_code=exc.code,
            reason=exc.message,
            input=item,
        )
        return None, None, _result(decision, REJECTED)


def _command(
    item: PlannerInput,
    command_type: str,
    expected_seq: int,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "command_id": _command_id(item.planner_request_id, command_type),
        "type": command_type,
        "mission_id": item.mission_id,
        "expected_seq": expected_seq,
        "actor": dict(item.actor),
        "payload": dict(payload),
        "correlation_id": item.planner_request_id,
        "schema_version": 1,
    }


def _guard_payload(item: PlannerInput) -> dict[str, Any]:
    return {
        "planner_request_id": item.planner_request_id,
        "request_digest": item.request_digest,
        "active_goal_id": item.active_goal_id,
        "goal_revision": item.goal_revision,
        "goal_definition_digest": item.goal_definition_digest,
        "scope_digest": item.scope_digest,
        "planning_cursor": item.planning_cursor,
    }


def _command_error_result(
    decision: PlanDecision,
    command_results: list[CommandResult],
    result: CommandResult,
) -> PlanResult:
    error_code = result.error_code
    if error_code == "EXPECTED_SEQ_MISMATCH":
        return _result(
            decision,
            STALE_CURSOR,
            command_results=tuple(command_results),
            reason_code="STALE_CURSOR",
            reason="durable sequence advanced outside this planner continuation",
        )
    if error_code in {"COMMAND_ID_CONFLICT", "IDEMPOTENCY_CONFLICT"}:
        return _result(
            decision,
            REJECTED,
            command_results=tuple(command_results),
            reason_code="IDEMPOTENCY_CONFLICT",
            reason="planner_request_id is already bound to a different request digest",
        )
    return _result(
        decision,
        REJECTED,
        command_results=tuple(command_results),
        reason_code=error_code or "COMMAND_REJECTED",
        reason=(result.error.message if result.error else "durable Work Graph command was rejected"),
    )


def _persist_non_applied_marker(
    runtime_service: RuntimeService,
    item: PlannerInput,
    result: PlanResult,
) -> PlanResult:
    """Bind a non-APPLIED request identity using an R1.2 rejected command.

    The empty plan_id is rejected by the existing Work Graph handler before it
    can emit an Event. RuntimeService nevertheless records the rejected
    command in its existing command ledger, which lets a later different
    request_digest receive IDEMPOTENCY_CONFLICT without adding a private R2.3
    store or Event type.
    """
    marker = _command(
        item,
        CREATE_PLAN,
        item.planning_cursor,
        {
            "plan_id": "",
            "planner_request_id": item.planner_request_id,
            "request_digest": item.request_digest,
            "planning_cursor": item.planning_cursor,
        },
    )
    marker_result = runtime_service.execute(marker)
    if marker_result.error_code == "COMMAND_ID_CONFLICT":
        decision = result.decision
        if decision is None:
            return result
        return _result(
            decision,
            REJECTED,
            reason_code="IDEMPOTENCY_CONFLICT",
            reason="planner_request_id is already bound to a different request digest",
        )
    if marker_result.ok:
        decision = result.decision
        if decision is None:
            return result
        return _result(
            decision,
            REJECTED,
            reason_code="RUNTIME_INVARIANT_VIOLATION",
            reason="non-APPLIED marker unexpectedly mutated the Work Graph",
        )
    return result


def _commands_for(decision: PlanDecision, item: PlannerInput, initial: bool) -> list[tuple[str, dict[str, Any]]]:
    assert decision.plan_id is not None
    assert decision.revision_id is not None
    guards = _guard_payload(item)
    revision_payload = {
        **guards,
        "plan_id": decision.plan_id,
        "revision_id": decision.revision_id,
        "parent_revision_id": decision.parent_revision_id,
        "objective": decision.objective or "",
        "constraints": [dict(value) for value in decision.constraints],
        "task_definitions": [dict(value) for value in decision.task_definitions],
        "dependencies": [dict(value) for value in decision.dependencies],
    }
    commands: list[tuple[str, dict[str, Any]]] = []
    if initial:
        commands.append((CREATE_PLAN, {**guards, "plan_id": decision.plan_id}))
    commands.append((RECORD_PLAN_REVISION, revision_payload))
    commands.append(
        (
            ACTIVATE_PLAN_REVISION,
            {
                **guards,
                "plan_id": decision.plan_id,
                "revision_id": decision.revision_id,
            },
        )
    )
    return commands


def _plan_or_revise(runtime_service: RuntimeService, value: Mapping[str, Any] | PlannerInput) -> PlanResult:
    try:
        item = PlannerInput.from_mapping(value)
    except PlannerError as exc:
        decision = derive_plan(value)
        return _result(decision, REJECTED, reason_code=exc.code, reason=exc.message)

    decision = derive_plan(item)
    if decision.outcome != APPLIED:
        return _persist_non_applied_marker(runtime_service, item, _result(decision, decision.outcome))

    _, graph, guard_failure = _guard_goal(runtime_service, item)
    if guard_failure is not None:
        return _persist_non_applied_marker(runtime_service, item, guard_failure)
    assert graph is not None
    assert decision.plan_id is not None
    assert decision.revision_id is not None

    plan = graph.plan(decision.plan_id)
    if item.existing_plan_id is not None and item.existing_plan_id != decision.plan_id:
        return _result(decision, REJECTED, reason_code="PLAN_ID_MISMATCH", reason="PlannerInput plan identity is not canonical")
    if plan is not None and plan.lifecycle_state != PlanLifecycleState.OPEN:
        return _result(decision, REJECTED, reason_code="PLAN_NOT_OPEN", reason="only an OPEN Plan can be revised")
    if plan is not None and plan.current_revision_id is not None:
        if decision.parent_revision_id != plan.current_revision_id and decision.revision_id != plan.current_revision_id:
            return _result(
                decision,
                REJECTED,
                reason_code="PLAN_REVISION_PARENT_MISMATCH",
                reason="replan must parent the durable current Revision",
            )

    # A new request whose candidate is already the durable current content is
    # a no-op.  A retry of the same request keeps the deterministic Revision id
    # and must replay its commands instead.
    if (
        plan is not None
        and plan.current_revision_id is not None
        and plan.current_revision_id != decision.revision_id
    ):
        current_revision = graph.revision(plan.current_revision_id)
        if current_revision is not None and current_revision.content_hash == decision.content_hash:
            return _result(
                decision,
                NO_CHANGE,
                reason_code="PLAN_UNCHANGED",
                reason="candidate content matches the durable current Revision",
            )

    initial = plan is None or plan.current_revision_id is None or (
        decision.parent_revision_id is None and plan.current_revision_id == decision.revision_id
    )
    commands = _commands_for(decision, item, initial)
    expected_seq = item.planning_cursor
    command_results: list[CommandResult] = []
    any_applied = False

    for index, (command_type, payload) in enumerate(commands):
        # A completed command is replayed even when the durable head has
        # advanced; RuntimeService will return its stored result by command
        # identity. For a genuinely unfinished command, check the head
        # before submitting it so an external advancement becomes
        # STALE_CURSOR without adding a rejected command or any Work Graph
        # fact.
        unfinished = (
            (command_type == RECORD_PLAN_REVISION and graph.revision(decision.revision_id) is None)
            or (
                command_type == ACTIVATE_PLAN_REVISION
                and (
                    graph.plan(decision.plan_id) is None
                    or graph.plan(decision.plan_id).current_revision_id != decision.revision_id
                )
            )
        )
        if index > 0 and unfinished:
            head = runtime_service.get_head_seq(item.mission_id)
            if head != expected_seq:
                return _result(
                    decision,
                    STALE_CURSOR,
                    command_results=tuple(command_results),
                    reason_code="STALE_CURSOR",
                    reason=f"expected continuation cursor {expected_seq}, durable head is {head}",
                )
        head_before = runtime_service.get_head_seq(item.mission_id)
        command_result = runtime_service.execute(_command(item, command_type, expected_seq, payload))
        command_results.append(command_result)
        head_after = runtime_service.get_head_seq(item.mission_id)
        if command_result.outcome == "APPLIED" and head_after > head_before:
            any_applied = True
        if not command_result.ok:
            return _command_error_result(decision, command_results, command_result)
        if command_result.last_seq is None:
            return _result(
                decision,
                REJECTED,
                command_results=tuple(command_results),
                reason_code="RUNTIME_INVARIANT_VIOLATION",
                reason="successful Work Graph command did not return last_seq",
            )
        expected_seq = command_result.last_seq

    replayed = bool(command_results) and not any_applied
    return _result(
        decision,
        DUPLICATE if replayed else APPLIED,
        command_results=tuple(command_results),
        replayed=replayed,
    )


def plan_or_revise(
    runtime_service_or_input: RuntimeService | Mapping[str, Any] | PlannerInput,
    planner_input_or_service: Mapping[str, Any] | PlannerInput | RuntimeService | None = None,
    *,
    runtime_service: RuntimeService | None = None,
    planner_input: Mapping[str, Any] | PlannerInput | None = None,
) -> PlanResult:
    """Apply a derived candidate through only the injected RuntimeService.

    Both ``plan_or_revise(service, input)`` and
    ``plan_or_revise(input, service)`` are accepted at this boundary.
    """
    service = runtime_service
    value: Mapping[str, Any] | PlannerInput | None = planner_input
    if service is None and isinstance(runtime_service_or_input, RuntimeService):
        service = runtime_service_or_input
        value = planner_input_or_service if value is None else value
    elif service is None and isinstance(planner_input_or_service, RuntimeService):
        service = planner_input_or_service
        value = runtime_service_or_input if value is None else value
    elif service is None and hasattr(runtime_service_or_input, "execute") and hasattr(runtime_service_or_input, "get_head_seq"):
        service = runtime_service_or_input  # type: ignore[assignment]
        value = planner_input_or_service if value is None else value
    if service is None or value is None:
        raise ValueError("plan_or_revise requires an injected RuntimeService and PlannerInput")
    return _plan_or_revise(service, value)


class PlannerOrchestrator:
    """Small application object exposing the frozen R2.3 operation."""

    def __init__(self, runtime_service: RuntimeService) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        self._runtime_service = runtime_service

    @property
    def runtime_service(self) -> RuntimeService:
        return self._runtime_service

    def plan_or_revise(self, value: Mapping[str, Any] | PlannerInput) -> PlanResult:
        return _plan_or_revise(self._runtime_service, value)

    plan = plan_or_revise
    execute = plan_or_revise
    submit = plan_or_revise


def orchestrate_plan(
    runtime_service: RuntimeService,
    value: Mapping[str, Any] | PlannerInput,
) -> PlanResult:
    return _plan_or_revise(runtime_service, value)


__all__ = [
    "ACTIVATE_PLAN_REVISION",
    "CREATE_PLAN",
    "PlannerOrchestrator",
    "RECORD_PLAN_REVISION",
    "orchestrate_plan",
    "plan_or_revise",
]
