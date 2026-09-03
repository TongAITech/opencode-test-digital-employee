"""EC2 read-only G5 product seam over existing durable runtime truth."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..durable_core import RuntimeError, RuntimeService, SessionStatus
from ..g2_1.router import SessionRouter
from .contracts import G5OperationResult, G5WorkerBinding


TRUTH_SOURCE = "R1_EVENT_STREAM"
DIRECTOR = "DIRECTOR"
DEFECT_HUNTER = "DEFECT_HUNTER"
DIAGNOSIS = "DIAGNOSIS"
DEFECT_HUNTER_AGENT = "aitest-diagnosis"

# These registries reserve the frozen product vocabulary. EC2 only opens status
# and work_context; every later-wave action remains recognized but fail-closed.
DIRECTOR_ACTIONS = frozenset(
    {
        "status",
        "intake_observations",
        "investigation_status",
        "open_investigation",
        "request_human_review",
        "canonical_defects",
    }
)
WORKER_ACTIONS = frozenset(
    {
        "status",
        "work_context",
        "record_anomaly",
        "create_candidate",
        "request_evidence_deepening",
        "record_evidence_assessment",
        "correlate_sources",
        "evaluate_reproducibility",
        "assess_false_positive",
        "assess_defect_truth",
        "record_rca",
        "record_checkpoint",
        "handoff_confirmed_defect",
    }
)


def _fail(code: str, message: str, **details: Any) -> None:
    raise RuntimeError(code, message, details)


def _payload_text(payload: Mapping[str, Any], name: str, code: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        _fail(code, f"{name} is required for a Mission-scoped G5 worker action", field=name)
    return value.strip()


@dataclass(frozen=True)
class _WorkerAdmission:
    binding: G5WorkerBinding
    route: Any
    current_attempt: Any
    current_session: Any
    durable_binding: Any
    head_seq: int


def _admit_g5_worker(
    runtime: RuntimeService,
    payload: Mapping[str, Any],
) -> _WorkerAdmission:
    mission_id = _payload_text(payload, "mission_id", "G5_ATTEMPT_TASK_MISMATCH")
    task_id = _payload_text(payload, "task_id", "G5_ROUTE_REQUIRED")
    attempt_id = _payload_text(payload, "attempt_id", "G5_ATTEMPT_NOT_FOUND")
    session_id = _payload_text(payload, "session_id", "G5_ATTEMPT_SESSION_MISMATCH")

    composed = runtime.replay_composed(mission_id)
    session_control = composed.extension_state("g2_1_session_control")
    route = session_control.route(task_id) if session_control is not None else None
    if route is None:
        _fail("G5_ROUTE_REQUIRED", "A persisted G2.1 route is required", task_id=task_id)
    if route.role != DEFECT_HUNTER or route.agent_name != DEFECT_HUNTER_AGENT:
        _fail(
            "G5_ROUTE_ROLE_MISMATCH",
            "G5 worker route must be the canonical DEFECT_HUNTER route",
            task_id=task_id,
            observed_role=route.role,
            observed_agent=route.agent_name,
        )

    execution = composed.extension_state("r1_3b_execution_resume")
    attempt = execution.attempt(attempt_id) if execution is not None else None
    if attempt is None:
        _fail("G5_ATTEMPT_NOT_FOUND", "Supplied execution Attempt does not exist", attempt_id=attempt_id)
    if attempt.mission_id != mission_id or attempt.task_id != task_id:
        _fail(
            "G5_ATTEMPT_TASK_MISMATCH",
            "Supplied execution Attempt does not belong to the Mission and Task",
            attempt_id=attempt_id,
            task_id=task_id,
        )
    latest = execution.latest_attempt(task_id)
    if latest is None or latest.attempt_id != attempt_id:
        _fail(
            "G5_ATTEMPT_NOT_CURRENT",
            "Supplied execution Attempt is not the current Task Attempt",
            attempt_id=attempt_id,
            current_attempt_id=latest.attempt_id if latest is not None else None,
        )
    if attempt.runtime_session_id != session_id:
        _fail(
            "G5_ATTEMPT_SESSION_MISMATCH",
            "Supplied Session does not match the current execution Attempt",
            attempt_id=attempt_id,
            session_id=session_id,
        )

    session = composed.core_state.session(session_id)
    if (
        session is None
        or session.mission_id != mission_id
        or session.status is not SessionStatus.OPEN
    ):
        _fail("G5_SESSION_NOT_OPEN", "Current G5 worker Session must exist and be OPEN", session_id=session_id)
    session_agent = session.attributes.get("opencode_agent")
    if session_agent is not None and session_agent != DEFECT_HUNTER_AGENT:
        _fail(
            "G5_LOGICAL_AGENT_BINDING_MISMATCH",
            "Current Session agent does not match the canonical Defect Hunter agent",
            session_id=session_id,
            observed_agent=session_agent,
        )

    root_attempt_id = attempt.root_attempt_id
    expected_logical_agent_id = SessionRouter.logical_agent_id(DEFECT_HUNTER_AGENT, task_id)
    orchestration = composed.extension_state("r2_5_session_orchestration")
    same_root = (
        [item for item in orchestration.bindings if item.root_attempt_id == root_attempt_id]
        if orchestration is not None
        else []
    )
    if not same_root:
        _fail(
            "G5_LOGICAL_AGENT_BINDING_MISSING",
            "Immutable-root R2.5 LogicalAgentBinding is required",
            root_attempt_id=root_attempt_id,
        )
    matching = [
        item
        for item in same_root
        if item.mission_id == mission_id
        and item.task_id == task_id
        and item.logical_agent_id == expected_logical_agent_id
    ]
    if len(matching) != 1:
        _fail(
            "G5_LOGICAL_AGENT_BINDING_MISMATCH",
            "R2.5 LogicalAgentBinding does not match Mission, Task, root, and logical agent",
            root_attempt_id=root_attempt_id,
            expected_logical_agent_id=expected_logical_agent_id,
        )
    durable_binding = matching[0]

    # The immutable R2.5 anchor may be a predecessor after rotation. Validate its
    # same-root lineage, but never require it to be the current/open Session.
    anchor_attempt = execution.attempt(durable_binding.attempt_id)
    anchor_session = composed.core_state.session(durable_binding.session_id)
    if (
        anchor_attempt is None
        or anchor_attempt.mission_id != mission_id
        or anchor_attempt.task_id != task_id
        or anchor_attempt.root_attempt_id != root_attempt_id
        or anchor_attempt.runtime_session_id != durable_binding.session_id
        or anchor_session is None
        or anchor_session.mission_id != mission_id
    ):
        _fail(
            "G5_LOGICAL_AGENT_BINDING_MISMATCH",
            "R2.5 binding anchor is outside the current execution lineage",
            binding_id=durable_binding.binding_id,
        )

    binding = G5WorkerBinding(
        mission_id=mission_id,
        task_id=task_id,
        current_attempt_id=attempt_id,
        root_attempt_id=root_attempt_id,
        current_session_id=session_id,
        logical_agent_id=expected_logical_agent_id,
        r2_5_binding_id=durable_binding.binding_id,
        r2_5_anchor_attempt_id=durable_binding.attempt_id,
        r2_5_anchor_session_id=durable_binding.session_id,
    )
    return _WorkerAdmission(
        binding=binding,
        route=route,
        current_attempt=attempt,
        current_session=session,
        durable_binding=durable_binding,
        head_seq=composed.core_state.seq,
    )


def require_g5_worker_binding(
    runtime: RuntimeService,
    payload: Mapping[str, Any],
) -> G5WorkerBinding:
    """Return a non-durable validated view of existing worker authority."""

    return _admit_g5_worker(runtime, payload).binding


class G5Service:
    """Read-only EC2 service; all EC3+ action vocabulary remains fail-closed."""

    def __init__(self, runtime: RuntimeService) -> None:
        self.runtime = runtime

    @staticmethod
    def normalize_role(role: str) -> str:
        normalized = str(role or "").strip().upper()
        if normalized == DIAGNOSIS:
            return DEFECT_HUNTER
        if normalized not in {DIRECTOR, DEFECT_HUNTER}:
            _fail("G5_ROLE_FORBIDDEN", "Role is not allowed at the G5 product seam", role=normalized)
        return normalized

    @staticmethod
    def _normalize_action(action: str) -> str:
        normalized = str(action or "").strip().lower()
        if not normalized:
            _fail("G5_ACTION_FORBIDDEN", "G5 action is required")
        return normalized

    @classmethod
    def preflight(cls, role: str, action: str) -> tuple[str, str]:
        """Validate the EC2 product vocabulary before runtime composition."""

        normalized_role = cls.normalize_role(role)
        normalized_action = cls._normalize_action(action)
        executable = (
            normalized_action == "status"
            or (normalized_role == DEFECT_HUNTER and normalized_action == "work_context")
        )
        if not executable:
            allowed_registry = DIRECTOR_ACTIONS if normalized_role == DIRECTOR else WORKER_ACTIONS
            _fail(
                "G5_ACTION_FORBIDDEN",
                "G5 action is not executable in EC2",
                role=normalized_role,
                action=normalized_action,
                recognized=normalized_action in allowed_registry,
            )
        return normalized_role, normalized_action

    def status(self, role: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        raw_mission_id = payload.get("mission_id")
        mission_id = raw_mission_id.strip() if isinstance(raw_mission_id, str) and raw_mission_id.strip() else None
        result = G5OperationResult(
            status="PASS",
            mission_id=mission_id,
            head_seq=self.runtime.get_head_seq(mission_id) if mission_id is not None else None,
            next_required_action="EC3_REMAINS_GOVERNANCE_HOLD",
        ).to_dict()
        return {
            **result,
            "conversation_is_not_truth": True,
            "role": role,
            "read_only": True,
        }

    def work_context(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        return {
            "status": "PASS",
            "truth_source": TRUTH_SOURCE,
            "conversation_is_not_truth": True,
            "read_only": True,
            "worker_binding": admission.binding.to_dict(),
            "head_seq": admission.head_seq,
            "route": admission.route.to_dict(),
            "current_attempt": admission.current_attempt.to_dict(),
            "current_session": admission.current_session.to_dict(),
            "r2_5_binding": admission.durable_binding.to_dict(),
        }

    def command(self, role: str, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized_role, normalized_action = self.preflight(role, action)

        if normalized_role == DIRECTOR and normalized_action == "status":
            return self.status(normalized_role, payload)
        if normalized_role == DEFECT_HUNTER and normalized_action == "status":
            # A payload carrying worker identity makes status Mission-scoped and
            # therefore subject to the same composite authority as work_context.
            if any(name in payload for name in ("mission_id", "task_id", "attempt_id", "session_id")):
                binding = require_g5_worker_binding(self.runtime, payload)
                return {**self.status(normalized_role, payload), "worker_binding": binding.to_dict()}
            return self.status(normalized_role, payload)
        if normalized_role == DEFECT_HUNTER and normalized_action == "work_context":
            return self.work_context(payload)

        _fail(
            "G5_ACTION_FORBIDDEN",
            "G5 action is not executable in EC2",
            role=normalized_role,
            action=normalized_action,
        )
