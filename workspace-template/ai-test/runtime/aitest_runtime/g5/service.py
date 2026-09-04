"""EC2 read-only G5 product seam over existing durable runtime truth."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..durable_core import RuntimeError, RuntimeService, SessionStatus, canonical_sha256
from ..g2_1.router import SessionRouter
from ..g3.contracts import EXTENSION_ID as G3_EXTENSION_ID
from ..g4.contracts import EXTENSION_ID as G4_EXTENSION_ID
from ..r3_6.contracts import (
    EvidenceDeepeningReceipt,
    InvestigationWorkSetReceipt,
    InvestigationWorkSetRequest,
)
from ..r3_6.service import R36ApplicationService
from .admission import admit_g4_observation
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
EC3_WORKER_ACTIONS = frozenset(
    {
        "record_anomaly",
        "create_candidate",
        "request_evidence_deepening",
        "record_evidence_assessment",
        "correlate_sources",
        "evaluate_reproducibility",
        "assess_false_positive",
        "record_rca",
        "record_checkpoint",
    }
)
_ALTERNATIVE_CLASSIFICATIONS = frozenset(
    {
        "ENVIRONMENT_PROBLEM",
        "TEST_DATA_PROBLEM",
        "AUTOMATION_DEFECT",
        "CASE_SPEC_DEFECT",
        "KNOWLEDGE_FACT_ERROR",
        "UNKNOWN_INCONCLUSIVE",
    }
)
_SENSITIVE_KEYS = frozenset(
    {
        "raw",
        "raw_content",
        "raw_payload",
        "content",
        "body",
        "secret",
        "password",
        "passwd",
        "token",
        "cookie",
        "credential",
        "otp",
        "mfa",
        "authorization",
        "storage_state",
        "access_token",
        "refresh_token",
    }
)


def _fail(code: str, message: str, **details: Any) -> None:
    raise RuntimeError(code, message, details)


def _payload_text(payload: Mapping[str, Any], name: str, code: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        _fail(code, f"{name} is required for a Mission-scoped G5 worker action", field=name)
    return value.strip()


def _reject_sensitive(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS:
                _fail(
                    "G5_SENSITIVE_EVIDENCE_REJECTED",
                    "G5 accepts typed references and digests, not raw or secret payloads",
                    field=f"{path}.{key}",
                )
            _reject_sensitive(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_sensitive(child, f"{path}[{index}]")


def _entity_identity(entity: Any) -> tuple[str, str]:
    fields = getattr(entity, "__dataclass_fields__", {})
    identity = next((getattr(entity, name) for name in fields if name.endswith("_id")), None)
    digest = next((getattr(entity, name) for name in fields if name.endswith("_digest")), None)
    if not isinstance(identity, str) or not isinstance(digest, str):
        _fail("G5_EVIDENCE_REF_INVALID", "Frozen R3.6 result lacks exact entity identity/digest")
    return identity, digest


def _r36_result(runtime: RuntimeService, mission_id: str, action: str, result: Any) -> dict[str, Any]:
    if not result.ok or result.entity is None:
        _fail(
            "G5_EVIDENCE_REF_INVALID",
            "Frozen R3.6 rejected the G5 pre-confirmation operation",
            action=action,
            r3_6_error_code=result.error_code,
        )
    identity, digest = _entity_identity(result.entity)
    envelope = G5OperationResult(
        status="PASS",
        mission_id=mission_id,
        head_seq=runtime.get_head_seq(mission_id),
        canonical_refs=({"ref_id": identity, "digest": digest},),
    ).to_dict()
    return {**envelope, "operation": action, "entity": result.entity.to_dict()}


def _origin(admission: "_WorkerAdmission", *, source: str = "G5_PRECONFIRMATION_INVESTIGATION") -> dict[str, Any]:
    return {
        "mission_id": admission.binding.mission_id,
        "architecture_baseline_ref": "v7",
        "source": source,
        "task_id": admission.binding.task_id,
        "attempt_id": admission.binding.current_attempt_id,
        "session_id": admission.binding.current_session_id,
    }


def _candidate(runtime: RuntimeService, mission_id: str, candidate_id: str) -> Any:
    candidate = R36ApplicationService(runtime).state(mission_id).candidate(candidate_id)
    if candidate is None:
        _fail("G5_EVIDENCE_REF_INVALID", "DefectCandidate does not exist in the same Mission", candidate_id=candidate_id)
    return candidate


def _known_ref(runtime: RuntimeService, mission_id: str, value: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, str):
        ref_id = value.strip()
        supplied_digest = None
    elif isinstance(value, Mapping):
        ref_id = str(value.get("ref_id") or value.get("id") or "").strip()
        supplied_digest = value.get("digest")
    else:
        ref_id = ""
        supplied_digest = None
    if not ref_id:
        _fail("G5_EVIDENCE_REF_INVALID", "Existing evidence reference requires a stable identity")

    composed = runtime.replay_composed(mission_id)
    for extension_id in (G4_EXTENSION_ID, G3_EXTENSION_ID):
        state = composed.extension_state(extension_id)
        fact = state.by_id(ref_id) if state is not None and hasattr(state, "by_id") else None
        if fact is not None:
            if supplied_digest is not None and supplied_digest != fact.digest:
                _fail("G5_EVIDENCE_REF_INVALID", "Existing evidence digest does not match durable truth", ref_id=ref_id)
            return {"ref_id": ref_id, "digest": fact.digest, "fact_kind": fact.fact_kind}

    r36 = R36ApplicationService(runtime).state(mission_id)
    collections = (
        r36.anomalies,
        r36.candidates,
        r36.deepenings,
        r36.evidence_assessments,
        r36.correlations,
        r36.reproducibility_assessments,
        r36.false_positive_assessments,
        r36.defect_assessments,
        r36.rca_records,
        r36.checkpoints,
    )
    for collection in collections:
        for entity in collection:
            identity, digest = _entity_identity(entity)
            if identity == ref_id:
                if supplied_digest is not None and supplied_digest != digest:
                    _fail("G5_EVIDENCE_REF_INVALID", "R3.6 reference digest does not match durable truth", ref_id=ref_id)
                return {"ref_id": ref_id, "digest": digest, "entity_kind": type(entity).__name__}
    _fail("G5_EVIDENCE_REF_INVALID", "Reference is not existing same-Mission typed truth", ref_id=ref_id)


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
    """EC3 product service over exact G4 admission and frozen R3.6 truth."""

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
        """Validate the EC3 product vocabulary before runtime composition."""

        normalized_role = cls.normalize_role(role)
        normalized_action = cls._normalize_action(action)
        executable = (
            normalized_action == "status"
            or (
                normalized_role == DEFECT_HUNTER
                and (normalized_action == "work_context" or normalized_action in EC3_WORKER_ACTIONS)
            )
        )
        if not executable:
            allowed_registry = DIRECTOR_ACTIONS if normalized_role == DIRECTOR else WORKER_ACTIONS
            _fail(
                "G5_ACTION_FORBIDDEN",
                "G5 action is not executable in EC3",
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

    @staticmethod
    def _request(
        admission: _WorkerAdmission,
        action: str,
        entity_id: str,
        entity_key: str,
        entity: Mapping[str, Any],
        *,
        source: str = "G5_PRECONFIRMATION_INVESTIGATION",
    ) -> dict[str, Any]:
        return {
            "mission_id": admission.binding.mission_id,
            "session_id": admission.binding.current_session_id,
            "idempotency_key": f"g5:{action}:{entity_id}",
            "origin_lineage": _origin(admission, source=source),
            entity_key: dict(entity),
        }

    def record_anomaly(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        admitted = admit_g4_observation(
            self.runtime,
            mission_id=admission.binding.mission_id,
            observation_ref=payload.get("g4_observation_ref"),
        )
        lineage = admitted.admission
        anomaly_id = f"g5-anomaly-{str(lineage.observation_ref['digest'])[:24]}"
        upstream_refs = {
            "g4_observation": lineage.observation_ref,
            "g4_step_result": lineage.step_result_ref,
            "g3_case": lineage.case_ref,
            "g3_case_value": lineage.case_value_link_ref,
            "g4_execution_batch": lineage.execution_batch_ref,
            "r1_execution_attempt": lineage.execution_attempt_ref,
            "g4_step_cursor": lineage.step_cursor_ref,
        }
        source_refs = (
            lineage.quality_version_ref,
            *lineage.campaign_refs,
            *lineage.strategy_refs,
            lineage.source_identity_ref,
            lineage.execution_node_ref,
        )
        evidence_refs = (
            str(lineage.observation_ref["ref_id"]),
            str(lineage.step_result_ref["ref_id"]),
            *(str(item["ref_id"]) for item in lineage.evidence_refs),
        )
        origin = {
            **_origin(admission, source="G5_G4_ADMISSION"),
            "g4_observation_ref": lineage.observation_ref,
        }
        request = {
            "mission_id": admission.binding.mission_id,
            "session_id": admission.binding.current_session_id,
            "idempotency_key": f"g5:record_anomaly:{admitted.observation.fact_id}",
            "origin_lineage": origin,
            "anomaly": {
                "anomaly_id": anomaly_id,
                "scope": dict(lineage.scope),
                "trigger": lineage.oracle_result,
                "upstream_refs": {name: dict(value) for name, value in upstream_refs.items()},
                "source_refs": [dict(value) for value in source_refs],
                "evidence_refs": list(dict.fromkeys(evidence_refs)),
                "observed_digests": {
                    "observation": lineage.observation_ref["digest"],
                    "step_result": lineage.step_result_ref["digest"],
                    "expected": lineage.expected_ref["digest"],
                    "actual": [item["digest"] for item in lineage.actual_refs],
                    "evidence": [item["digest"] for item in lineage.evidence_refs],
                },
                "candidate_signal": f"GOVERNED_G4_{lineage.oracle_result}_OBSERVATION",
                "origin_lineage": origin,
            },
        }
        result = R36ApplicationService(self.runtime).record_test_anomaly(request)
        response = _r36_result(self.runtime, admission.binding.mission_id, "record_anomaly", result)
        return {**response, "g4_observation_admission": lineage.to_dict()}

    def create_candidate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        mission_id = admission.binding.mission_id
        candidate_id = _payload_text(payload, "candidate_id", "G5_EVIDENCE_REF_INVALID")
        anomaly_refs = payload.get("anomaly_refs")
        if not isinstance(anomaly_refs, (list, tuple)) or not anomaly_refs:
            _fail("G5_EVIDENCE_REF_INVALID", "create_candidate requires anomaly_refs")
        state = R36ApplicationService(self.runtime).state(mission_id)
        anomalies = []
        for anomaly_id in anomaly_refs:
            anomaly = state.anomaly(str(anomaly_id))
            if anomaly is None or anomaly.origin_lineage.get("source") != "G5_G4_ADMISSION":
                _fail("G5_EVIDENCE_REF_INVALID", "Candidate requires same-Mission G5-admitted anomalies")
            anomalies.append(anomaly)
        classification = str(payload.get("classification") or "").upper()
        if classification != "PRODUCT_DEFECT_CANDIDATE":
            _fail("G5_EVIDENCE_REF_INVALID", "EC3 candidate classification must be PRODUCT_DEFECT_CANDIDATE")
        alternatives = tuple(str(value).upper() for value in payload.get("alternative_classifications") or ())
        if not _ALTERNATIVE_CLASSIFICATIONS.issubset(alternatives):
            _fail("G5_EVIDENCE_REF_INVALID", "Candidate must preserve every frozen alternative classification")
        entity = {
            "candidate_id": candidate_id,
            "scope": dict(anomalies[0].scope),
            "anomaly_refs": [value.anomaly_id for value in anomalies],
            "classification": classification,
            "alternative_classifications": list(alternatives),
            "hypothesis": _payload_text(payload, "hypothesis", "G5_EVIDENCE_REF_INVALID"),
            "affected_scope": dict(payload.get("affected_scope") or anomalies[0].scope),
            "supporting_evidence_refs": list(
                payload.get("supporting_evidence_refs") or anomalies[0].evidence_refs
            ),
            "contradicting_evidence_refs": list(payload.get("contradicting_evidence_refs") or ()),
        }
        request = self._request(admission, "create_candidate", candidate_id, "candidate", entity)
        return _r36_result(
            self.runtime,
            mission_id,
            "create_candidate",
            R36ApplicationService(self.runtime).create_defect_candidate(request),
        )

    def request_evidence_deepening(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        mission_id = admission.binding.mission_id
        candidate_id = _payload_text(payload, "candidate_id", "G5_EVIDENCE_REF_INVALID")
        candidate = _candidate(self.runtime, mission_id, candidate_id)
        mode = str(payload.get("mode") or "").upper()
        if mode != "EXISTING_TYPED_REFS":
            _fail(
                "G5_ACTION_FORBIDDEN",
                "EC3 evidence deepening permits only EXISTING_TYPED_REFS",
                mode=mode,
            )
        evidence = payload.get("evidence_refs")
        if not isinstance(evidence, (list, tuple)) or not evidence:
            _fail("G5_EVIDENCE_REF_INVALID", "EXISTING_TYPED_REFS requires evidence_refs")
        selected = tuple(_known_ref(self.runtime, mission_id, value) for value in evidence)
        channels = tuple(str(value).strip().upper() for value in payload.get("requested_channels") or ())
        if not channels or any(not value for value in channels):
            _fail("G5_EVIDENCE_REF_INVALID", "Evidence deepening requires requested_channels")
        workset_id = str(payload.get("workset_id") or f"g5-workset-{canonical_sha256(selected)[:24]}")
        workset = InvestigationWorkSetRequest(
            workset_id=workset_id,
            candidate_id=candidate_id,
            scope=candidate.scope,
            channels=channels,
            relation_types=tuple(payload.get("relation_types") or ()),
            max_items=payload.get("max_items", 24),
            max_bytes=payload.get("max_bytes", 12288),
            max_hops=payload.get("max_hops", 2),
            cursor=payload.get("cursor"),
            session_ref=admission.binding.current_session_id,
            origin_lineage=_origin(admission),
        )
        result_digest = canonical_sha256([dict(value) for value in selected])
        receipt = InvestigationWorkSetReceipt(
            workset_id=workset_id,
            selected_items=selected,
            omitted_refs=(),
            truncation="NONE",
            source_statuses={channel: "COLLECTED" for channel in channels},
            next_cursor=payload.get("cursor") or selected[-1]["ref_id"],
            result_digest=result_digest,
        )
        deepening_id = str(payload.get("deepening_id") or f"g5-deepening-{result_digest[:24]}")
        deepening = EvidenceDeepeningReceipt(
            deepening_id=deepening_id,
            candidate_id=candidate_id,
            workset_request=workset,
            workset_receipt=receipt,
            channel_statuses={channel: "COLLECTED" for channel in channels},
            evidence_refs=tuple(value["ref_id"] for value in selected),
            origin_lineage=_origin(admission),
        )
        request = self._request(
            admission,
            "request_evidence_deepening",
            deepening_id,
            "deepening",
            deepening.to_dict(),
        )
        return _r36_result(
            self.runtime,
            mission_id,
            "request_evidence_deepening",
            R36ApplicationService(self.runtime).request_evidence_deepening(request),
        )

    def record_evidence_assessment(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        mission_id = admission.binding.mission_id
        candidate_id = _payload_text(payload, "candidate_id", "G5_EVIDENCE_REF_INVALID")
        _candidate(self.runtime, mission_id, candidate_id)
        evidence_refs = tuple(str(value) for value in payload.get("evidence_refs") or ())
        if not evidence_refs:
            _fail("G5_EVIDENCE_REF_INVALID", "EvidenceAssessment requires evidence_refs")
        state = R36ApplicationService(self.runtime).state(mission_id)
        admitted_refs = {
            ref
            for deepening in state.deepenings
            if deepening.candidate_id == candidate_id
            for ref in deepening.evidence_refs
        }
        if not set(evidence_refs).issubset(admitted_refs):
            _fail("G5_EVIDENCE_REF_INVALID", "EvidenceAssessment refs were not admitted by bounded deepening")
        assessment_id = _payload_text(payload, "assessment_id", "G5_EVIDENCE_REF_INVALID")
        entity = {
            "assessment_id": assessment_id,
            "candidate_id": candidate_id,
            "evidence_refs": list(evidence_refs),
            "evidence_role": payload.get("evidence_role"),
            "evidence_sufficiency": payload.get("evidence_sufficiency"),
            "relevance": payload.get("relevance"),
            "verification_method": payload.get("verification_method"),
            "freshness": payload.get("freshness"),
            "scope_match": payload.get("scope_match"),
            "conflict_refs": list(payload.get("conflict_refs") or ()),
            "evidence_class": payload.get("evidence_class"),
        }
        request = self._request(admission, "record_evidence_assessment", assessment_id, "evidence_assessment", entity)
        return _r36_result(
            self.runtime,
            mission_id,
            "record_evidence_assessment",
            R36ApplicationService(self.runtime).record_evidence_assessment(request),
        )

    def correlate_sources(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        mission_id = admission.binding.mission_id
        candidate_id = _payload_text(payload, "candidate_id", "G5_EVIDENCE_REF_INVALID")
        _candidate(self.runtime, mission_id, candidate_id)
        source_values = payload.get("source_refs")
        if not isinstance(source_values, (list, tuple)) or not source_values:
            _fail("G5_EVIDENCE_REF_INVALID", "Cross-source correlation requires exact source_refs")
        source_refs = tuple(_known_ref(self.runtime, mission_id, value) for value in source_values)
        correlation_id = _payload_text(payload, "correlation_id", "G5_EVIDENCE_REF_INVALID")
        entity = {
            "correlation_id": correlation_id,
            "candidate_id": candidate_id,
            "source_refs": [dict(value) for value in source_refs],
            "correlation_keys": dict(payload.get("correlation_keys") or {}),
            "method": payload.get("method"),
            "match_quality": payload.get("match_quality"),
            "confidence": payload.get("confidence"),
            "time_window": dict(payload.get("time_window") or {}),
            "conflict_refs": list(payload.get("conflict_refs") or ()),
        }
        request = self._request(admission, "correlate_sources", correlation_id, "correlation", entity)
        return _r36_result(
            self.runtime,
            mission_id,
            "correlate_sources",
            R36ApplicationService(self.runtime).record_cross_source_correlation(request),
        )

    def evaluate_reproducibility(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        mission_id = admission.binding.mission_id
        candidate_id = _payload_text(payload, "candidate_id", "G5_EVIDENCE_REF_INVALID")
        _candidate(self.runtime, mission_id, candidate_id)
        reproducibility_id = _payload_text(payload, "reproducibility_id", "G5_EVIDENCE_REF_INVALID")
        entity = {
            "reproducibility_id": reproducibility_id,
            "candidate_id": candidate_id,
            "status": payload.get("status"),
            "attempt_refs": list(payload.get("attempt_refs") or ()),
            "evidence_refs": list(payload.get("evidence_refs") or ()),
            "controlled_variables": dict(payload.get("controlled_variables") or {}),
            "signature": payload.get("signature"),
            "comparison": payload.get("comparison"),
            "blocking_basis": payload.get("blocking_basis"),
        }
        request = self._request(admission, "evaluate_reproducibility", reproducibility_id, "reproducibility", entity)
        return _r36_result(
            self.runtime,
            mission_id,
            "evaluate_reproducibility",
            R36ApplicationService(self.runtime).evaluate_reproducibility(request),
        )

    def assess_false_positive(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        mission_id = admission.binding.mission_id
        candidate_id = _payload_text(payload, "candidate_id", "G5_EVIDENCE_REF_INVALID")
        _candidate(self.runtime, mission_id, candidate_id)
        false_positive_id = _payload_text(payload, "false_positive_id", "G5_EVIDENCE_REF_INVALID")
        alternatives = tuple(str(value).upper() for value in payload.get("alternatives_considered") or ())
        if not _ALTERNATIVE_CLASSIFICATIONS.issubset(alternatives):
            _fail("G5_EVIDENCE_REF_INVALID", "False-positive assessment must consider all frozen alternatives")
        entity = {
            "false_positive_id": false_positive_id,
            "candidate_id": candidate_id,
            "status": payload.get("status"),
            "alternatives_considered": list(alternatives),
            "evidence_refs": list(payload.get("evidence_refs") or ()),
            "unresolved_refs": list(payload.get("unresolved_refs") or ()),
            "decision_basis": payload.get("decision_basis"),
        }
        request = self._request(admission, "assess_false_positive", false_positive_id, "false_positive", entity)
        return _r36_result(
            self.runtime,
            mission_id,
            "assess_false_positive",
            R36ApplicationService(self.runtime).assess_false_positive(request),
        )

    def record_rca(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        mission_id = admission.binding.mission_id
        candidate_id = _payload_text(payload, "candidate_id", "G5_EVIDENCE_REF_INVALID")
        _candidate(self.runtime, mission_id, candidate_id)
        rca_id = _payload_text(payload, "rca_id", "G5_EVIDENCE_REF_INVALID")
        entity = {
            "rca_id": rca_id,
            "candidate_id": candidate_id,
            "cause_class": payload.get("cause_class"),
            "status": payload.get("status"),
            "causal_chain_refs": list(payload.get("causal_chain_refs") or ()),
            "root_component": payload.get("root_component"),
            "contradiction_refs": list(payload.get("contradiction_refs") or ()),
            "decision_basis": payload.get("decision_basis"),
        }
        request = self._request(admission, "record_rca", rca_id, "rca", entity)
        return _r36_result(
            self.runtime,
            mission_id,
            "record_rca",
            R36ApplicationService(self.runtime).record_rca(request),
        )

    def record_checkpoint(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        admission = _admit_g5_worker(self.runtime, payload)
        mission_id = admission.binding.mission_id
        candidate_id = _payload_text(payload, "candidate_id", "G5_EVIDENCE_REF_INVALID")
        _candidate(self.runtime, mission_id, candidate_id)
        workset_digest = _payload_text(payload, "workset_digest", "G5_EVIDENCE_REF_INVALID")
        cursor = payload.get("cursor")
        omitted_refs = tuple(str(value) for value in payload.get("omitted_refs") or ())
        state = R36ApplicationService(self.runtime).state(mission_id)
        receipts = tuple(
            value.workset_receipt
            for value in state.deepenings
            if value.candidate_id == candidate_id
            and value.workset_receipt.receipt_digest == workset_digest
        )
        if (
            len(receipts) != 1
            or receipts[0].next_cursor != cursor
            or receipts[0].omitted_refs != omitted_refs
        ):
            _fail("G5_EVIDENCE_REF_INVALID", "Checkpoint must bind an exact bounded WorkSet receipt/digest/cursor")
        checkpoint_id = _payload_text(payload, "checkpoint_id", "G5_EVIDENCE_REF_INVALID")
        entity = {
            "checkpoint_id": checkpoint_id,
            "candidate_id": candidate_id,
            "cursor": cursor,
            "workset_digest": workset_digest,
            "session_ref": admission.binding.current_session_id,
            "omitted_refs": list(omitted_refs),
        }
        request = self._request(admission, "record_checkpoint", checkpoint_id, "checkpoint", entity)
        return _r36_result(
            self.runtime,
            mission_id,
            "record_checkpoint",
            R36ApplicationService(self.runtime).record_investigation_checkpoint(request),
        )

    def command(self, role: str, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        _reject_sensitive(payload)
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
        if normalized_role == DEFECT_HUNTER and normalized_action in EC3_WORKER_ACTIONS:
            handler = {
                "record_anomaly": self.record_anomaly,
                "create_candidate": self.create_candidate,
                "request_evidence_deepening": self.request_evidence_deepening,
                "record_evidence_assessment": self.record_evidence_assessment,
                "correlate_sources": self.correlate_sources,
                "evaluate_reproducibility": self.evaluate_reproducibility,
                "assess_false_positive": self.assess_false_positive,
                "record_rca": self.record_rca,
                "record_checkpoint": self.record_checkpoint,
            }[normalized_action]
            return handler(payload)

        _fail(
            "G5_ACTION_FORBIDDEN",
            "G5 action is not executable in EC3",
            role=normalized_role,
            action=normalized_action,
        )
