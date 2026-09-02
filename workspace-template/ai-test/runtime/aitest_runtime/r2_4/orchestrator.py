"""R2.4 bounded, serial loop orchestration over existing R1.2 truth."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from aitest_runtime.durable_core import CommandResult
from aitest_runtime.work_graph import EXTENSION_ID, TaskLifecycleState, WorkGraphState

from .contracts import (
    ACCEPTED,
    BLOCKED,
    DISPATCH,
    EVALUATE,
    OBSERVE,
    PLAN_COMPLETE,
    REJECTED,
    REPLAN_REQUEST,
    SCHEDULE,
    UNKNOWN,
    WAIT,
    BlockReason,
    DispatchRequest,
    DispatchResult,
    LoopDecision,
    LoopRequest,
    LoopAccounting,
    LoopBudget,
    LoopProgress,
    LOOP_BUDGET_LIMIT_EXHAUSTED,
    LOOP_DEADLINE_EXCEEDED,
    LOOP_MAX_CYCLES_EXHAUSTED,
    LOOP_MAX_DISPATCHES_EXHAUSTED,
    LOOP_PROGRESS_REQUIRED,
    NextProgressCandidate,
    ReplanRequest,
    R2_4Error,
    SchedulingPolicy,
    TaskReadiness,
    WaitCondition,
)
from .dispatcher import TaskDispatcher, activation_command, make_dispatch_request
from .readiness import ReadinessReport, evaluate_readiness, select_ready_tasks


TRANSITION_TASK = "TRANSITION_TASK"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R2_4Error("R2_4_INPUT_INVALID", f"{name} must be a non-empty string")
    return value.strip()


_MISSING = object()


def _parse_timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be an ISO-8601 timestamp")
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be an ISO-8601 timestamp") from exc


def _timestamp_at_or_after(left: Any, right: Any, *, left_name: str, right_name: str) -> bool:
    left_value = _parse_timestamp(left, left_name)
    right_value = _parse_timestamp(right, right_name)
    try:
        return left_value >= right_value
    except TypeError as exc:
        raise R2_4Error("R2_4_SCHEMA_INVALID", "timestamps must use comparable timezone forms") from exc


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _progress_required_decision(value: Any, reason: str) -> LoopDecision:
    raw = _raw(value)
    mission_id = raw.get("mission_id")
    if not _valid_text(mission_id):
        raise R2_4Error("R2_4_SCHEMA_INVALID", "mission_id must be a non-empty string")
    loop_budget = LoopBudget.from_mapping(raw.get("loop_budget", raw.get("budget")))
    plan_id = raw.get("plan_id")
    plan_revision_id = raw.get("plan_revision_id", raw.get("plan_revision"))
    loop_id = raw.get("loop_id")
    observed_seq = raw.get("observed_seq", raw.get("as_of_seq"))
    progress = raw.get("loop_progress", raw.get("progress"))
    if not _valid_text(loop_id) and isinstance(progress, Mapping) and _valid_text(progress.get("loop_id")):
        loop_id = progress.get("loop_id")
    if not isinstance(observed_seq, int) or isinstance(observed_seq, bool) or observed_seq < 0:
        observed_seq = None
    return LoopDecision(
        state=OBSERVE,
        next_state=BLOCKED,
        mission_id=mission_id,
        plan_id=plan_id if _valid_text(plan_id) else None,
        plan_revision_id=plan_revision_id if _valid_text(plan_revision_id) else None,
        loop_id=loop_id if _valid_text(loop_id) else None,
        budget_id=loop_budget.budget_id,
        observed_seq=observed_seq,
        reason_code=LOOP_PROGRESS_REQUIRED,
        reason=reason,
        block_reason=BlockReason(LOOP_PROGRESS_REQUIRED, reason),
        dispatch_attempt_count=0,
    )


def _progress_trust_reason(value: Any) -> str | None:
    """Return a progress-boundary reason without swallowing unrelated schema errors."""
    raw = _raw(value)
    if not isinstance(raw, Mapping):
        return None

    # Only enter this narrow gate when the non-progress request envelope is
    # structurally usable. Other malformed request fields must retain their
    # ordinary R2.4 schema error behavior.
    required_texts = ("mission_id", "plan_id", "plan_revision_id", "observed_at")
    if any(not _valid_text(raw.get(name)) for name in required_texts):
        return None
    observed_seq = raw.get("observed_seq", raw.get("as_of_seq"))
    if not isinstance(observed_seq, int) or isinstance(observed_seq, bool) or observed_seq < 0:
        return None
    try:
        policy = raw.get("scheduling_policy", raw.get("policy"))
        budget = LoopBudget.from_mapping(raw.get("loop_budget", raw.get("budget")))
        # Validate only the surrounding envelope needed to issue a deterministic
        # blocked decision; do not catch arbitrary request schema failures.
        SchedulingPolicy.from_mapping(policy)
        _parse_timestamp(raw.get("observed_at"), "observed_at")
        _parse_timestamp(budget.deadline, "loop_budget.deadline")
        if not isinstance(raw.get("resolution"), Mapping):
            return None
        bindings = raw.get("dispatch_bindings", raw.get("bindings", ()))
        if not isinstance(bindings, (list, tuple)):
            return None
        actor = raw.get("actor", {"type": "SYSTEM", "id": "r2.4-orchestrator"})
        if not isinstance(actor, Mapping) or not _valid_text(actor.get("type")) or not _valid_text(actor.get("id")):
            return None
    except R2_4Error:
        return None

    progress_raw = raw.get("loop_progress", raw.get("progress", _MISSING))
    if progress_raw is _MISSING or progress_raw is None:
        return "authoritative LoopProgress is required"
    try:
        progress = LoopProgress.from_mapping(progress_raw)
    except R2_4Error:
        return "authoritative LoopProgress is invalid or untrusted"

    accounting_raw = raw.get("loop_accounting", raw.get("accounting", _MISSING))
    if accounting_raw is _MISSING or accounting_raw is None:
        return "authoritative LoopAccounting is required"
    try:
        accounting = LoopAccounting.from_mapping(accounting_raw)
    except R2_4Error:
        return "authoritative LoopAccounting is invalid or untrusted"

    loop_id = raw.get("loop_id")
    if not _valid_text(loop_id) or progress.loop_id != loop_id.strip():
        return "LoopProgress does not match the active loop_id"
    if progress.budget_id != budget.budget_id or accounting.budget_id != budget.budget_id:
        return "LoopProgress/LoopAccounting do not match the active budget_id"
    try:
        if not _timestamp_at_or_after(
            raw.get("observed_at"),
            progress.observed_at,
            left_name="observed_at",
            right_name="loop_progress.observed_at",
        ):
            return "observed_at cannot precede LoopProgress.observed_at"
    except R2_4Error:
        return "LoopProgress.observed_at is invalid or untrusted"
    return None


def _raw(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raw = getattr(value, "__dict__", None)
    if isinstance(raw, Mapping):
        return raw
    return {}


def _command_ok(result: Any) -> bool:
    return isinstance(result, CommandResult) and result.ok or bool(getattr(result, "ok", False))


def _command_error_code(result: Any) -> str | None:
    return getattr(result, "error_code", None)


def _command_last_seq(result: Any) -> int | None:
    value = getattr(result, "last_seq", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _get_work_graph(runtime_service: Any, request: LoopRequest, supplied: Any = None) -> tuple[WorkGraphState, int]:
    if isinstance(supplied, WorkGraphState):
        return supplied, request.observed_seq
    if runtime_service is None:
        raise R2_4Error("R2_4_INPUT_INVALID", "R2.4 requires an R1.2 WorkGraphState or RuntimeService")
    if hasattr(runtime_service, "get_head_seq"):
        head = runtime_service.get_head_seq(request.mission_id)
        if head != request.observed_seq:
            raise R2_4Error("STALE_CURSOR", "durable sequence differs from observed_seq")
    if hasattr(runtime_service, "replay_composed"):
        composed = runtime_service.replay_composed(request.mission_id, through_seq=request.observed_seq)
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, WorkGraphState):
            raise R2_4Error("EXTENSION_SCHEMA_MISMATCH", "invalid R1.2 Work Graph state")
        return state, composed.seq
    if hasattr(runtime_service, "get_work_graph_state"):
        state = runtime_service.get_work_graph_state(request.mission_id)
        if isinstance(state, WorkGraphState):
            return state, request.observed_seq
    raise R2_4Error("R2_4_INPUT_INVALID", "runtime service does not expose the R1.2 Work Graph")


def _transition(
    runtime_service: Any,
    port: Any,
    command: Mapping[str, Any],
) -> Any:
    if runtime_service is not None and hasattr(runtime_service, "execute"):
        return runtime_service.execute(command)
    if port is None:
        raise R2_4Error("R2_4_DISPATCH_INVALID", "no R1.2 transition port was supplied")
    target = port if callable(port) else getattr(port, "execute", None)
    if not callable(target):
        raise R2_4Error("R2_4_DISPATCH_INVALID", "transition port must be callable or expose execute")
    return target(command)


def _dispatcher_result(dispatcher: Any, request: DispatchRequest) -> DispatchResult:
    if isinstance(dispatcher, TaskDispatcher):
        return dispatcher.dispatch(request)
    target = dispatcher if callable(dispatcher) else getattr(dispatcher, "dispatch", None)
    if not callable(target):
        raise R2_4Error("DISPATCH_PORT_INVALID", "TaskDispatcher must be callable or expose dispatch")
    raw = target(request)
    if isinstance(raw, DispatchResult):
        result = raw
    elif raw is True:
        result = DispatchResult(request.dispatch_id, ACCEPTED, receipt={"dispatch_id": request.dispatch_id})
    elif raw is False:
        result = DispatchResult(request.dispatch_id, REJECTED, reason_code="DISPATCH_REJECTED")
    elif raw is None:
        result = DispatchResult(request.dispatch_id, UNKNOWN, reason_code="DISPATCH_STATUS_UNKNOWN")
    elif isinstance(raw, Mapping):
        status = str(raw.get("status", raw.get("outcome", UNKNOWN))).upper()
        receipt = raw.get("receipt", raw.get("dispatch_receipt"))
        result = DispatchResult(
            str(raw.get("dispatch_id", request.dispatch_id)),
            status,
            receipt=receipt if isinstance(receipt, Mapping) else None,
            reason_code=raw.get("reason_code", raw.get("error_code")),
            reason=raw.get("reason"),
            attempt_count=raw.get("attempt_count", 1),
        )
    else:
        raise R2_4Error("DISPATCH_RESPONSE_INVALID", "dispatcher returned an unsupported result")
    if result.dispatch_id != request.dispatch_id:
        raise R2_4Error("DISPATCH_ID_MISMATCH", "dispatcher receipt identity differs from dispatch_id")
    return result


def _reconcile(dispatcher: Any, request: DispatchRequest, supplied: Any = None) -> str:
    if supplied is not None:
        if isinstance(supplied, Mapping):
            status = str(supplied.get("status", supplied.get("outcome", ""))).upper()
            if status in {ACCEPTED, REJECTED, UNKNOWN, "ABSENT", "NONE", "NOT_FOUND", "NOT_ATTEMPTED", "NO_EXECUTION"}:
                return "ABSENT" if status in {"NONE", "NOT_FOUND", "NOT_ATTEMPTED", "NO_EXECUTION"} else status
            if any(supplied.get(key) not in (None, "", {}, []) for key in ("receipt", "dispatch_receipt", "attempt_id", "execution_reference", "tool_execution_id")):
                return ACCEPTED
        elif isinstance(supplied, str):
            status = supplied.upper()
            if status in {ACCEPTED, REJECTED, UNKNOWN, "ABSENT"}:
                return status
        return UNKNOWN
    target = getattr(dispatcher, "reconcile", None)
    if not callable(target):
        return UNKNOWN
    raw = target(request)
    if isinstance(raw, DispatchResult):
        return raw.status
    if isinstance(raw, str):
        normalized = raw.upper()
        if normalized in {ACCEPTED, REJECTED, UNKNOWN, "ABSENT"}:
            return normalized
    if isinstance(raw, Mapping):
        status = str(raw.get("status", raw.get("outcome", ""))).upper()
        if status in {ACCEPTED, REJECTED, UNKNOWN, "ABSENT"}:
            return status
        if any(raw.get(key) not in (None, "", {}, []) for key in ("receipt", "dispatch_receipt", "attempt_id", "execution_reference", "tool_execution_id")):
            return ACCEPTED
        if status in {"NONE", "ABSENT", "NOT_FOUND", "NOT_ATTEMPTED", "NO_EXECUTION"}:
            return "ABSENT"
    return UNKNOWN


def _decision(
    request: LoopRequest,
    report: ReadinessReport,
    *,
    state: str,
    next_state: str,
    reason_code: str | None = None,
    reason: str | None = None,
    selected: tuple[TaskReadiness, ...] = (),
    command_results: tuple[Any, ...] = (),
    dispatch_results: tuple[DispatchResult, ...] = (),
    candidate: NextProgressCandidate | None = None,
    wait_condition: WaitCondition | None = None,
    block_reason: BlockReason | None = None,
    replan_request: ReplanRequest | None = None,
    attempts: int = 0,
) -> LoopDecision:
    return LoopDecision(
        state=state,
        next_state=next_state,
        mission_id=request.mission_id,
        plan_id=request.plan_id,
        plan_revision_id=request.plan_revision_id,
        loop_id=request.loop_id,
        budget_id=request.loop_budget.budget_id,
        observed_seq=request.observed_seq,
        selected_task_ids=tuple(item.task_id for item in selected),
        readiness=report.tasks,
        dispatch_results=dispatch_results,
        command_results=command_results,
        reason_code=reason_code,
        reason=reason,
        wait_condition=wait_condition,
        block_reason=block_reason,
        replan_request=replan_request,
        next_progress_candidate=candidate,
        dispatch_attempt_count=attempts,
    )


def _candidate(request: LoopRequest, attempts: int) -> NextProgressCandidate:
    if not _timestamp_at_or_after(
        request.observed_at,
        request.loop_progress.observed_at,
        left_name="observed_at",
        right_name="loop_progress.observed_at",
    ):
        raise R2_4Error(LOOP_PROGRESS_REQUIRED, "observed_at cannot precede LoopProgress.observed_at")
    return NextProgressCandidate.build(
        loop_id=request.loop_id,
        budget_id=request.loop_budget.budget_id,
        cycle=request.loop_progress.cycle + 1,
        dispatches_used=request.loop_progress.dispatches_used + attempts,
        budget_used=request.loop_progress.budget_used + request.loop_accounting.observed_budget_delta,
        observed_at=request.observed_at,
    )


def _validate_budget(request: LoopRequest) -> tuple[str | None, str | None]:
    if request.loop_budget.budget_id != request.loop_progress.budget_id:
        return "LOOP_BUDGET_MISMATCH", "LoopBudget and LoopProgress budget_id differ"
    if request.loop_progress.loop_id != request.loop_id:
        return "LOOP_PROGRESS_MISMATCH", "LoopProgress loop_id differs from the active loop"
    if request.loop_budget.budget_id != request.loop_accounting.budget_id:
        return "LOOP_ACCOUNTING_MISMATCH", "LoopAccounting and LoopBudget budget_id differ"
    try:
        if _timestamp_at_or_after(
            request.observed_at,
            request.loop_budget.deadline,
            left_name="observed_at",
            right_name="loop_budget.deadline",
        ):
            return LOOP_DEADLINE_EXCEEDED, "loop deadline has elapsed"
    except R2_4Error as exc:
        return exc.code, exc.message
    if request.loop_progress.cycle >= request.loop_budget.max_cycles:
        return LOOP_MAX_CYCLES_EXHAUSTED, "maximum loop cycles reached"
    if request.loop_progress.dispatches_used >= request.loop_budget.max_dispatches:
        return LOOP_MAX_DISPATCHES_EXHAUSTED, "maximum dispatches reached"
    if request.loop_progress.budget_used + request.loop_accounting.observed_budget_delta >= request.loop_budget.budget_limit:
        return LOOP_BUDGET_LIMIT_EXHAUSTED, "budget limit has been reached"
    return None, None


def _request_from(value: Any) -> LoopRequest:
    return LoopRequest.from_mapping(value)


def orchestrate_loop(
    runtime_service: Any,
    value: LoopRequest | Mapping[str, Any],
    dispatcher: Any,
    *,
    transition_port: Any = None,
    work_graph: WorkGraphState | None = None,
) -> LoopDecision:
    """Run exactly one bounded, serial R2.4 cycle."""
    progress_reason = _progress_trust_reason(value)
    if progress_reason is not None:
        return _progress_required_decision(value, progress_reason)
    request = _request_from(value)
    raw = _raw(value)
    supplied_graph = work_graph or raw.get("work_graph") or raw.get("state")
    try:
        graph, _ = _get_work_graph(runtime_service, request, supplied_graph)
    except R2_4Error as exc:
        report = ReadinessReport(request.mission_id, request.plan_id, request.plan_revision_id, request.observed_seq, (), (), BLOCKED, exc.code, exc.message)
        if exc.code == "STALE_CURSOR":
            return _decision(request, report, state=OBSERVE, next_state=OBSERVE, reason_code="STALE_CURSOR", reason=exc.message)
        return _decision(request, report, state=OBSERVE, next_state=BLOCKED, reason_code=exc.code, reason=exc.message, block_reason=BlockReason(exc.code, exc.message))

    report = evaluate_readiness(
        graph,
        mission_id=request.mission_id,
        plan_id=request.plan_id,
        plan_revision_id=request.plan_revision_id,
        observed_seq=request.observed_seq,
        resolution=request.resolution,
        dispatch_bindings=request.dispatch_bindings,
        observed_at=request.observed_at,
    )
    if raw.get("request_replan") or raw.get("replan_request"):
        replan = raw.get("replan_request")
        if isinstance(replan, Mapping):
            replan_request = ReplanRequest(
                mission_id=request.mission_id,
                plan_id=replan.get("plan_id", request.plan_id),
                plan_revision_id=replan.get("plan_revision_id", request.plan_revision_id),
                reason_code=replan.get("reason_code", "REPLAN_REQUESTED"),
                reason=replan.get("reason"),
            )
        else:
            replan_request = ReplanRequest(request.mission_id, request.plan_id, request.plan_revision_id, "REPLAN_REQUESTED", "Caller requested a replan")
        return _decision(request, report, state=EVALUATE, next_state=REPLAN_REQUEST, reason_code=replan_request.reason_code, reason=replan_request.reason, replan_request=replan_request)
    budget_code, budget_reason = _validate_budget(request)
    if budget_code:
        return _decision(request, report, state=OBSERVE, next_state=BLOCKED, reason_code=budget_code, reason=budget_reason, block_reason=BlockReason(budget_code, budget_reason))
    if report.plan_complete:
        return _decision(request, report, state=EVALUATE, next_state=PLAN_COMPLETE)
    if report.next_state == BLOCKED:
        return _decision(
            request,
            report,
            state=EVALUATE,
            next_state=BLOCKED,
            reason_code=report.reason_code,
            reason=report.reason,
            block_reason=BlockReason(report.reason_code or "READINESS_BLOCKED", report.reason),
        )
    if report.active_tasks:
        active = report.active_tasks[0]
        assert active.binding is not None
        active_request = make_dispatch_request(
            mission_id=request.mission_id,
            plan_id=request.plan_id,
            plan_revision_id=request.plan_revision_id,
            task_id=active.task_id,
            binding=active.binding,
        )
        supplied_execution = raw.get("execution_state", raw.get("execution_observation", raw.get("execution_observations")))
        if isinstance(supplied_execution, Mapping):
            supplied_execution = supplied_execution.get(active.task_id, supplied_execution.get(active_request.dispatch_id, supplied_execution))
        reconciled = _reconcile(dispatcher, active_request, supplied_execution)
        selected_active = (active,)
        if reconciled == ACCEPTED:
            result = DispatchResult(active_request.dispatch_id, ACCEPTED, receipt={"reconciled": True}, attempt_count=0)
            return _decision(request, report, state=OBSERVE, next_state=DISPATCH, selected=selected_active, dispatch_results=(result,), candidate=_candidate(request, 0), attempts=0)
        if reconciled != "ABSENT":
            code, reason = "DISPATCH_STATUS_UNKNOWN", "authoritative execution state is not reconciled"
            return _decision(request, report, state=OBSERVE, next_state=WAIT, selected=selected_active, reason_code=code, reason=reason, dispatch_results=(), candidate=_candidate(request, 0), wait_condition=WaitCondition(code, ("R1.3", "R1.4"), reason), attempts=0)
        attempts = 1
        dispatch_result = _dispatcher_result(dispatcher, active_request)
        if dispatch_result.status == ACCEPTED and dispatch_result.receipt is None:
            code, reason = "DISPATCH_STATUS_UNKNOWN", "TaskDispatcher did not return an authoritative ACCEPTED receipt"
            return _decision(request, report, state=DISPATCH, next_state=WAIT, selected=selected_active, reason_code=code, reason=reason, dispatch_results=(dispatch_result,), candidate=_candidate(request, attempts), wait_condition=WaitCondition(code, ("R1.3", "R1.4"), reason), attempts=attempts)
        if dispatch_result.status == REJECTED:
            code = dispatch_result.reason_code or "DISPATCH_REJECTED"
            reason = dispatch_result.reason or "TaskDispatcher rejected the retry"
            return _decision(request, report, state=DISPATCH, next_state=BLOCKED, selected=selected_active, reason_code=code, reason=reason, dispatch_results=(dispatch_result,), candidate=_candidate(request, attempts), block_reason=BlockReason(code, reason), attempts=attempts)
        if dispatch_result.status == UNKNOWN:
            code = dispatch_result.reason_code or "DISPATCH_STATUS_UNKNOWN"
            reason = dispatch_result.reason or "TaskDispatcher could not establish a receipt"
            return _decision(request, report, state=DISPATCH, next_state=WAIT, selected=selected_active, reason_code=code, reason=reason, dispatch_results=(dispatch_result,), candidate=_candidate(request, attempts), wait_condition=WaitCondition(code, ("R1.3", "R1.4"), reason), attempts=attempts)
        return _decision(request, report, state=DISPATCH, next_state=DISPATCH, selected=selected_active, dispatch_results=(dispatch_result,), candidate=_candidate(request, attempts), attempts=attempts)
    if report.next_state == WAIT:
        return _decision(
            request,
            report,
            state=EVALUATE,
            next_state=WAIT,
            reason_code=report.reason_code,
            reason=report.reason,
            wait_condition=WaitCondition(report.reason_code or "WAITING_FOR_OBSERVATION", ("R1.3", "R1.4", "R2.1"), report.reason),
            candidate=_candidate(request, 0),
        )

    selected = select_ready_tasks(report, request.scheduling_policy, request.loop_budget, request.loop_progress)
    if not selected:
        code, reason = LOOP_MAX_DISPATCHES_EXHAUSTED, "no dispatch budget remains"
        return _decision(request, report, state=SCHEDULE, next_state=BLOCKED, reason_code=code, reason=reason, block_reason=BlockReason(code, reason))

    current_seq = request.observed_seq
    command_results: list[Any] = []
    dispatch_results: list[DispatchResult] = []
    attempts = 0
    for item in selected:
        assert item.binding is not None
        dispatch_request = make_dispatch_request(
            mission_id=request.mission_id,
            plan_id=request.plan_id,
            plan_revision_id=request.plan_revision_id,
            task_id=item.task_id,
            binding=item.binding,
        )

        task = graph.task(item.task_id)
        if task is None:
            code, reason = "TASK_NOT_FOUND", "Task disappeared from the observed R1.2 graph"
            return _decision(request, report, state=OBSERVE, next_state=OBSERVE, reason_code=code, reason=reason, selected=selected, command_results=tuple(command_results), dispatch_results=tuple(dispatch_results), candidate=_candidate(request, attempts), attempts=attempts)

        if task.lifecycle_state == TaskLifecycleState.ACTIVE:
            supplied_execution = raw.get("execution_state", raw.get("execution_observation", raw.get("execution_observations")))
            if isinstance(supplied_execution, Mapping):
                supplied_execution = supplied_execution.get(item.task_id, supplied_execution.get(dispatch_request.dispatch_id, supplied_execution))
            reconciled = _reconcile(dispatcher, dispatch_request, supplied_execution)
            if reconciled == ACCEPTED:
                dispatch_results.append(DispatchResult(dispatch_request.dispatch_id, ACCEPTED, receipt={"reconciled": True}, attempt_count=0))
                continue
            if reconciled != "ABSENT":
                code, reason = "DISPATCH_STATUS_UNKNOWN", "authoritative execution state is not reconciled"
                return _decision(request, report, state=OBSERVE, next_state=WAIT, reason_code=code, reason=reason, selected=selected, command_results=tuple(command_results), dispatch_results=tuple(dispatch_results), candidate=_candidate(request, attempts), wait_condition=WaitCondition(code, ("R1.3", "R1.4"), reason), attempts=attempts)
        else:
            command = activation_command(dispatch_request, expected_seq=current_seq, actor=request.actor)
            result = _transition(runtime_service, transition_port, command)
            command_results.append(result)
            error_code = _command_error_code(result)
            if not _command_ok(result):
                if error_code == "EXPECTED_SEQ_MISMATCH":
                    return _decision(request, report, state=OBSERVE, next_state=OBSERVE, reason_code="STALE_CURSOR", reason="R1.2 sequence advanced during serial activation", selected=selected, command_results=tuple(command_results), dispatch_results=tuple(dispatch_results), candidate=_candidate(request, attempts), attempts=attempts)
                code, reason = error_code or "TASK_ACTIVATION_REJECTED", "R1.2 rejected the PENDING to ACTIVE transition"
                return _decision(request, report, state=OBSERVE, next_state=BLOCKED, reason_code=code, reason=reason, selected=selected, command_results=tuple(command_results), dispatch_results=tuple(dispatch_results), candidate=_candidate(request, attempts), block_reason=BlockReason(code, reason), attempts=attempts)
            next_seq = _command_last_seq(result)
            if next_seq is None:
                code, reason = "R1_2_CURSOR_MISSING", "successful R1.2 activation did not return last_seq"
                return _decision(request, report, state=OBSERVE, next_state=OBSERVE, reason_code=code, reason=reason, selected=selected, command_results=tuple(command_results), dispatch_results=tuple(dispatch_results), candidate=_candidate(request, attempts), attempts=attempts)
            current_seq = next_seq

        attempts += 1
        dispatch_result = _dispatcher_result(dispatcher, dispatch_request)
        dispatch_results.append(dispatch_result)
        if dispatch_result.status == ACCEPTED and dispatch_result.receipt is None:
            code, reason = "DISPATCH_STATUS_UNKNOWN", "TaskDispatcher did not return an authoritative ACCEPTED receipt"
            return _decision(request, report, state=DISPATCH, next_state=WAIT, reason_code=code, reason=reason, selected=selected, command_results=tuple(command_results), dispatch_results=tuple(dispatch_results), candidate=_candidate(request, attempts), wait_condition=WaitCondition(code, ("R1.3", "R1.4"), reason), attempts=attempts)
        if dispatch_result.status == REJECTED:
            code = dispatch_result.reason_code or "DISPATCH_REJECTED"
            reason = dispatch_result.reason or "TaskDispatcher rejected the dispatch"
            return _decision(request, report, state=DISPATCH, next_state=BLOCKED, reason_code=code, reason=reason, selected=selected, command_results=tuple(command_results), dispatch_results=tuple(dispatch_results), candidate=_candidate(request, attempts), block_reason=BlockReason(code, reason), attempts=attempts)
        if dispatch_result.status == UNKNOWN:
            code = dispatch_result.reason_code or "DISPATCH_STATUS_UNKNOWN"
            reason = dispatch_result.reason or "TaskDispatcher could not establish a receipt"
            return _decision(request, report, state=DISPATCH, next_state=WAIT, reason_code=code, reason=reason, selected=selected, command_results=tuple(command_results), dispatch_results=tuple(dispatch_results), candidate=_candidate(request, attempts), wait_condition=WaitCondition(code, ("R1.3", "R1.4"), reason), attempts=attempts)

    return _decision(
        request,
        report,
        state=SCHEDULE,
        next_state=DISPATCH,
        selected=selected,
        command_results=tuple(command_results),
        dispatch_results=tuple(dispatch_results),
        candidate=_candidate(request, attempts),
        attempts=attempts,
    )


def run_loop_cycle(runtime_service: Any, value: LoopRequest | Mapping[str, Any], dispatcher: Any, **kwargs: Any) -> LoopDecision:
    return orchestrate_loop(runtime_service, value, dispatcher, **kwargs)


def advance_loop(runtime_service: Any, value: LoopRequest | Mapping[str, Any], dispatcher: Any, **kwargs: Any) -> LoopDecision:
    return orchestrate_loop(runtime_service, value, dispatcher, **kwargs)


def schedule_and_dispatch(runtime_service: Any, value: LoopRequest | Mapping[str, Any], dispatcher: Any, **kwargs: Any) -> LoopDecision:
    return orchestrate_loop(runtime_service, value, dispatcher, **kwargs)


class LoopOrchestrator:
    def __init__(self, runtime_service: Any, dispatcher: Any, *, transition_port: Any = None) -> None:
        self.runtime_service = runtime_service
        self.dispatcher = dispatcher
        self.transition_port = transition_port

    def run_cycle(self, value: LoopRequest | Mapping[str, Any], **kwargs: Any) -> LoopDecision:
        return orchestrate_loop(self.runtime_service, value, self.dispatcher, transition_port=self.transition_port, **kwargs)

    def execute(self, value: LoopRequest | Mapping[str, Any], **kwargs: Any) -> LoopDecision:
        return self.run_cycle(value, **kwargs)


Orchestrator = LoopOrchestrator


__all__ = [
    "LoopOrchestrator",
    "Orchestrator",
    "TRANSITION_TASK",
    "advance_loop",
    "orchestrate_loop",
    "run_loop_cycle",
    "schedule_and_dispatch",
]
