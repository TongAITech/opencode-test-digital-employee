from __future__ import annotations

from dataclasses import fields, replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent

from .contracts import *
from .errors import *
from .reducer import R45State


_GENERATED = {"created_seq", "created_at", "record_digest", "eligibility_digest"}


def _state(composed: ComposedRuntimeState) -> R45State:
    if not isinstance(composed, ComposedRuntimeState):
        raise R45Error(R45_COMMAND_INVALID, "R4.5 commands require a composed RuntimeService")
    if composed.core_state.mission is None:
        raise R45Error(R45_SCOPE_MISMATCH, "R4.5 commands require an existing Mission")
    value = composed.extension_state(EXTENSION_ID)
    if not isinstance(value, R45State):
        raise R45Error(R45_COMMAND_INVALID, "R4.5 extension state is not registered")
    return value


def _payload(command: Any, record_type: type[Any]) -> dict[str, Any]:
    if command.session_id is not None:
        raise R45Error(R45_COMMAND_INVALID, "R4.5 commands are session-independent")
    if not isinstance(command.idempotency_key, str) or not command.idempotency_key.strip():
        raise R45Error(R45_COMMAND_INVALID, "R4.5 command idempotency_key is required")
    raw = dict(command.payload)
    allowed = {item.name for item in fields(record_type)} - _GENERATED
    if set(raw) != allowed:
        raise R45Error(
            R45_COMMAND_INVALID,
            f"{command.type} payload contains unknown or missing fields",
            {"missing": sorted(allowed - set(raw)), "unknown": sorted(set(raw) - allowed)},
        )
    owner = raw.get("stream_owner_mission_id")
    if owner != command.mission_id:
        raise R45Error(R45_SCOPE_MISMATCH, "stream_owner_mission_id must equal the command Mission")
    return raw


def _next_record(record_type: type[Any], raw: Mapping[str, Any], composed: ComposedRuntimeState, command: Any) -> Any:
    payload = dict(raw)
    payload["created_seq"] = composed.seq + 1
    payload["created_at"] = f"seq:{composed.seq + 1}"
    payload["correlation_id"] = command.correlation_id
    payload["causation_id"] = command.command_id
    if record_type is ResumeEligibilityAssessment:
        payload["eligibility_digest"] = None
    return record_type.from_dict({**payload, "record_digest": None})


def _require_scope(record: Any, state: R45State) -> None:
    if record.release_scope.stream_owner_mission_id != state.mission_id:
        raise R45Error(R45_SCOPE_MISMATCH, "release scope is owned by another Mission")
    if record.stream_owner_mission_id != state.mission_id:
        raise R45Error(R45_SCOPE_MISMATCH, "record is owned by another Mission")


def _validate_ref(reference: ScopedReference, mission_id: str, cursor: int, name: str, *, current: bool = False) -> None:
    if reference.stream_owner_mission_id != mission_id and reference.access_mode is not ScopedReferenceAccessMode.READ_ONLY_CROSS_MISSION:
        raise R45Error(R45_SCOPE_MISMATCH, f"{name} is cross-Mission without READ_ONLY_CROSS_MISSION")
    if reference.stream_owner_mission_id == mission_id and reference.access_mode is not ScopedReferenceAccessMode.LOCAL:
        raise R45Error(R45_SCOPE_MISMATCH, f"{name} must use LOCAL access for its owning Mission")
    if reference.source_cursor is None:
        if current:
            raise R45Error(R45_REFERENCE_INVALID, f"{name} is not source-backed")
        return
    if reference.source_cursor != reference.source_seq:
        raise R45Error(R45_SEQUENCE_MISMATCH, f"{name} source cursor and source sequence differ")
    if reference.source_cursor > cursor:
        raise R45Error(R45_SEQUENCE_MISMATCH, f"{name} is ahead of the as-of cursor")


def _validate_refs(values: Any, mission_id: str, cursor: int, name: str, *, current: bool = False) -> None:
    for index, reference in enumerate(values):
        _validate_ref(reference, mission_id, cursor, f"{name}[{index}]", current=current)


def _same_reference(left: ScopedReference, right: ScopedReference) -> bool:
    return left.to_dict() == right.to_dict()


def _record_reference(kind: str, record: Any) -> ScopedReference:
    identity = next(
        getattr(record, name)
        for name in (
            "risk_assessment_id", "readiness_assessment_id", "wait_id", "wake_linkage_id",
            "eligibility_id", "resume_intent_id", "resume_receipt_id", "disposition_id",
        )
        if hasattr(record, name)
    )
    return ScopedReference(
        ref_kind=kind,
        stream_owner_mission_id=record.stream_owner_mission_id,
        object_id=identity,
        object_revision=getattr(record, "revision", 1),
        object_digest=record.record_digest,
        source_seq=record.created_seq,
        source_cursor=record.created_seq,
        access_mode=ScopedReferenceAccessMode.LOCAL,
        source_stream_key=f"r4.5:{kind}",
    )


def _risk_outcome(snapshot: InputSnapshot) -> ReleaseRiskOutcome:
    if snapshot.conflict_refs:
        return ReleaseRiskOutcome.CONFLICT
    if snapshot.freshness != "CURRENT":
        return ReleaseRiskOutcome.STALE
    if snapshot.availability != "AVAILABLE" or snapshot.blocked_refs:
        return ReleaseRiskOutcome.BLOCKED
    if snapshot.field_validation_state in {
        R45FieldValidationState.PENDING,
        R45FieldValidationState.UNKNOWN,
        R45FieldValidationState.UNAVAILABLE,
    } or snapshot.unknown_refs:
        return ReleaseRiskOutcome.INCOMPLETE
    if snapshot.remaining_risk_refs:
        return ReleaseRiskOutcome.RISK_PRESENT
    return ReleaseRiskOutcome.WITHIN_POLICY


def _readiness_verdict(candidate: ReleaseReadinessAssessment, risk: ReleaseRiskAssessment | None) -> tuple[ReadinessVerdict, ReadinessLifecycleState]:
    lifecycle = ReadinessLifecycleState.CURRENT
    reasons: list[str] = []
    current_refs = (
        candidate.current_r3_7_decision_ref, candidate.current_r4_4_closure_ref,
        candidate.current_quality_version_ref, candidate.current_campaign_ref,
        candidate.current_selection_revision_ref, candidate.deployment_ref, candidate.environment_ref,
    )
    if candidate.source_freshness != "CURRENT":
        lifecycle = ReadinessLifecycleState.STALE
        reasons.append("source_stale")
    if candidate.source_availability != "AVAILABLE":
        reasons.append("source_unavailable")
    if candidate.field_validation_state is not R45FieldValidationState.PASSED:
        reasons.append("field_validation_not_passed")
    if candidate.unresolved_conflict_refs:
        reasons.append("unresolved_conflict")
    if candidate.unresolved_blocker_refs:
        reasons.append("unresolved_blocker")
    if risk is None:
        reasons.append("risk_assessment_missing")
    elif risk.outcome is not ReleaseRiskOutcome.WITHIN_POLICY:
        reasons.append(f"risk_{risk.outcome.value.lower()}")
    if any(reference.source_cursor is None for reference in current_refs):
        reasons.append("current_source_missing")
    gate = candidate.human_gate_linkage
    if gate.decision_outcome != "ALLOW":
        reasons.append("human_gate_not_allow")
    if gate.continuation_state in {"PENDING", "CONTINUATION_PENDING", "ROUTE_REVISION", "BLOCKED"}:
        reasons.append("continuation_not_ready")
    if gate.continuation_reference is None:
        reasons.append("continuation_missing")
    if reasons:
        if any(item in reasons for item in {"unresolved_conflict"}):
            return ReadinessVerdict.BLOCKED, lifecycle
        if any(item in reasons for item in {"source_unavailable", "human_gate_not_allow", "continuation_not_ready", "continuation_missing"}):
            return ReadinessVerdict.WAITING, lifecycle
        if any(item in reasons for item in {"unresolved_blocker", "risk_blocked"}):
            return ReadinessVerdict.BLOCKED, lifecycle
        return ReadinessVerdict.NOT_READY, lifecycle
    return ReadinessVerdict.READY, lifecycle


def _eligibility_outcome(candidate: ResumeEligibilityAssessment, state: R45State) -> tuple[ResumeEligibilityOutcome, dict[str, Any]]:
    source = dict(candidate.source_state)
    reasons: list[str] = []
    explicit = str(source.get("outcome", source.get("status", ""))).upper()
    if explicit in {"CONFLICT", "AUTHORIZATION_CONFLICT"} or source.get("digest_compatible") is False:
        return ResumeEligibilityOutcome.CONFLICT, {"outcome": "CONFLICT", "reasons": ["authorization_conflict"]}
    if explicit in {"STALE", "ROUTE_REVISION"} or source.get("cursor_compatible") is False:
        return ResumeEligibilityOutcome.STALE, {"outcome": "STALE", "reasons": ["stale_or_cursor_mismatch"]}
    if explicit == "BLOCKED" or source.get("blocked") is True:
        return ResumeEligibilityOutcome.BLOCKED, {"outcome": "BLOCKED", "reasons": ["blocked_source"]}
    if explicit in {"PENDING", "CONTINUATION_PENDING", "NOT_ELIGIBLE"}:
        reasons.append(explicit.lower())
    if not candidate.human_gate_refs:
        reasons.append("missing_human_gate")
    if not candidate.upstream_current_refs:
        reasons.append("missing_upstream_current_refs")
    gate_state = str(source.get("human_gate_state", source.get("decision_outcome", "ALLOW"))).upper()
    continuation_state = str(source.get("continuation_state", "READY")).upper()
    if gate_state in {"PENDING", "BLOCKED", "DENY", "REJECTED"}:
        reasons.append(gate_state.lower())
    if continuation_state in {"PENDING", "CONTINUATION_PENDING", "ROUTE_REVISION", "BLOCKED"}:
        reasons.append(continuation_state.lower())
    if source.get("missing_continuation") is True:
        reasons.append("missing_continuation")
    if source.get("expected_seq_match") is False:
        reasons.append("expected_seq_mismatch")
    if source.get("mission_match") is False:
        reasons.append("wrong_mission")
    if reasons:
        if any(item in reasons for item in {"blocked", "missing_human_gate", "wrong_mission"}):
            return ResumeEligibilityOutcome.BLOCKED, {"outcome": "BLOCKED", "reasons": reasons}
        return ResumeEligibilityOutcome.NOT_ELIGIBLE, {"outcome": "NOT_ELIGIBLE", "reasons": reasons}
    return ResumeEligibilityOutcome.ELIGIBLE, {"outcome": "ELIGIBLE", "reasons": []}


def _ensure_quota_fact(wait: ReleaseWaitState) -> None:
    if wait.wait_reason is not WaitReason.QUOTA_UNAVAILABLE:
        return
    facts = tuple(
        item for item in wait.blocking_refs
        if "QUOTA" in item.ref_kind.upper() or "QUOTA" in (item.relation_kind or "").upper()
    )
    if not facts:
        facts = tuple(
            item for item in wait.source_refs
            if "QUOTA" in item.ref_kind.upper() or "QUOTA" in (item.relation_kind or "").upper()
        )
    if not facts:
        raise R45Error(R45_REFERENCE_INVALID, "QUOTA_UNAVAILABLE requires a source-backed quota fact")
    _validate_refs(facts, wait.stream_owner_mission_id, wait.as_of_seq, "quota_fact", current=True)


class R45CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        state = _state(composed)

        if command.type == R4_5_EVALUATE_RELEASE_RISK:
            raw = _payload(command, ReleaseRiskAssessment)
            candidate = _next_record(ReleaseRiskAssessment, raw, composed, command)
            _require_scope(candidate, state)
            if candidate.input_snapshot.stream_owner_mission_id != state.mission_id:
                raise R45Error(R45_SCOPE_MISMATCH, "input snapshot is owned by another Mission")
            if candidate.input_snapshot.release_scope.to_dict() != candidate.release_scope.to_dict():
                raise R45Error(R45_SCOPE_MISMATCH, "risk input snapshot scope differs from the assessment scope")
            if candidate.policy_snapshot.scope.to_dict() != candidate.release_scope.to_dict():
                raise R45Error(R45_SCOPE_MISMATCH, "risk policy scope differs from the assessment scope")
            _validate_refs(candidate.input_snapshot.source_refs, state.mission_id, candidate.as_of_seq, "input_snapshot.source_refs")
            _validate_refs(candidate.input_snapshot.blocked_refs + candidate.input_snapshot.unknown_refs + candidate.input_snapshot.conflict_refs, state.mission_id, candidate.as_of_seq, "input_snapshot.source_refs")
            computed = _risk_outcome(candidate.input_snapshot)
            candidate = replace(candidate, outcome=computed, record_digest=None)
            if state.risk(candidate.risk_assessment_id) is not None:
                raise R45Error(R45_IDENTITY_CONFLICT, "risk assessment identity already exists")
            return [PendingEvent(R45_RELEASE_RISK_ASSESSED, "R4_5_RELEASE_RISK_ASSESSMENT", candidate.risk_assessment_id, candidate.to_dict())]

        if command.type == R4_5_EVALUATE_RELEASE_READINESS:
            raw = _payload(command, ReleaseReadinessAssessment)
            candidate = _next_record(ReleaseReadinessAssessment, raw, composed, command)
            _require_scope(candidate, state)
            risk = state.risk(candidate.risk_assessment_ref.object_id)
            if risk is None or risk.record_digest != candidate.risk_assessment_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "readiness risk reference is missing, stale, or digest-incompatible")
            _validate_ref(candidate.risk_assessment_ref, state.mission_id, candidate.as_of_seq, "risk_assessment_ref", current=True)
            current_refs = (
                candidate.current_r3_7_decision_ref, candidate.current_r4_4_closure_ref,
                candidate.current_quality_version_ref, candidate.current_campaign_ref,
                candidate.current_selection_revision_ref, candidate.deployment_ref, candidate.environment_ref,
            )
            _validate_refs(current_refs, state.mission_id, candidate.as_of_seq, "readiness.current_refs", current=True)
            _validate_ref(candidate.human_gate_linkage.gate_ref, state.mission_id, candidate.as_of_seq, "human_gate.gate_ref", current=True)
            _validate_ref(candidate.human_gate_linkage.actor_ref, state.mission_id, candidate.as_of_seq, "human_gate.actor_ref", current=True)
            _validate_ref(candidate.human_gate_linkage.policy_ref, state.mission_id, candidate.as_of_seq, "human_gate.policy_ref", current=True)
            if candidate.human_gate_linkage.continuation_reference is not None:
                _validate_ref(candidate.human_gate_linkage.continuation_reference, state.mission_id, candidate.as_of_seq, "human_gate.continuation_reference", current=True)
            if candidate.human_gate_linkage.decision_digest != candidate.human_gate_linkage.gate_ref.object_digest and candidate.human_gate_linkage.decision_outcome == "ALLOW":
                raise R45Error(R45_DIGEST_CONFLICT, "ALLOW HumanGate decision is not digest-compatible with its gate reference")
            _validate_refs(candidate.unresolved_conflict_refs + candidate.unresolved_blocker_refs, state.mission_id, candidate.as_of_seq, "readiness.unresolved_refs")
            verdict, lifecycle = _readiness_verdict(candidate, risk)
            candidate = replace(candidate, verdict=verdict, lifecycle_state=lifecycle, record_digest=None)
            if state.readiness(candidate.readiness_assessment_id) is not None:
                raise R45Error(R45_IDENTITY_CONFLICT, "readiness assessment identity already exists")
            return [PendingEvent(R45_RELEASE_READINESS_ASSESSED, "R4_5_RELEASE_READINESS_ASSESSMENT", candidate.readiness_assessment_id, candidate.to_dict())]

        if command.type == R4_5_OPEN_RELEASE_WAIT:
            raw = _payload(command, ReleaseWaitState)
            candidate = _next_record(ReleaseWaitState, raw, composed, command)
            _require_scope(candidate, state)
            readiness = state.readiness(candidate.readiness_revision_ref.object_id)
            risk = state.risk(candidate.risk_assessment_ref.object_id)
            if readiness is None or readiness.record_digest != candidate.readiness_revision_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "wait readiness reference is missing or stale")
            if risk is None or risk.record_digest != candidate.risk_assessment_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "wait risk reference is missing or stale")
            _validate_refs((candidate.readiness_revision_ref, candidate.risk_assessment_ref), state.mission_id, candidate.as_of_seq, "wait.references", current=True)
            _validate_refs(candidate.blocking_refs + candidate.source_refs, state.mission_id, candidate.as_of_seq, "wait.source_refs")
            if candidate.lifecycle_state is not WaitLifecycleState.CURRENT:
                raise R45Error(R45_COMMAND_INVALID, "opening a release wait requires lifecycle_state=CURRENT")
            if "TIMER_ELAPSED" in str(candidate.wake_criteria).upper():
                raise R45Error(R45_COMMAND_INVALID, "TIMER_ELAPSED is forbidden")
            _ensure_quota_fact(candidate)
            if state.wait(candidate.wait_id) is not None:
                raise R45Error(R45_IDENTITY_CONFLICT, "wait identity already exists")
            return [PendingEvent(R45_RELEASE_WAIT_OPENED, "R4_5_RELEASE_WAIT_STATE", candidate.wait_id, candidate.to_dict())]

        if command.type == R4_5_RECORD_WAKE_LINKAGE:
            raw = _payload(command, WakeLinkage)
            candidate = _next_record(WakeLinkage, raw, composed, command)
            _require_scope(candidate, state)
            wait = state.wait(candidate.wait_ref.object_id)
            if wait is None or wait.record_digest != candidate.wait_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "wake wait reference is missing or stale")
            _validate_ref(candidate.wait_ref, state.mission_id, candidate.as_of_seq, "wake.wait_ref", current=True)
            _validate_ref(candidate.source_ref, state.mission_id, candidate.as_of_seq, "wake.source_ref", current=True)
            if candidate.source_digest != candidate.source_ref.object_digest:
                raise R45Error(R45_DIGEST_CONFLICT, "wake source digest does not match source reference")
            if candidate.source_ref.source_cursor != candidate.source_cursor:
                raise R45Error(R45_SEQUENCE_MISMATCH, "wake source cursor differs from source reference cursor")
            if candidate.source_cursor < wait.created_cursor:
                raise R45Error(R45_SEQUENCE_MISMATCH, "wake source is older than the durable wait checkpoint")
            if candidate.wake_kind.value == "TIMER_ELAPSED":
                raise R45Error(R45_COMMAND_INVALID, "TIMER_ELAPSED is forbidden")
            if state.wake(candidate.wake_linkage_id) is not None:
                raise R45Error(R45_IDENTITY_CONFLICT, "wake linkage identity already exists")
            return [PendingEvent(R45_WAKE_LINKAGE_RECORDED, "R4_5_WAKE_LINKAGE", candidate.wake_linkage_id, candidate.to_dict())]

        if command.type == R4_5_EVALUATE_RESUME_ELIGIBILITY:
            raw = _payload(command, ResumeEligibilityAssessment)
            candidate = _next_record(ResumeEligibilityAssessment, raw, composed, command)
            _require_scope(candidate, state)
            readiness = state.readiness(candidate.readiness_revision_ref.object_id)
            wait = state.wait(candidate.wait_ref.object_id)
            if readiness is None or readiness.record_digest != candidate.readiness_revision_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "eligibility readiness reference is missing or stale")
            if wait is None or wait.record_digest != candidate.wait_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "eligibility wait reference is missing or stale")
            _validate_refs((candidate.readiness_revision_ref, candidate.wait_ref), state.mission_id, candidate.as_of_seq, "eligibility.references", current=True)
            for wake_ref in candidate.wake_refs:
                wake = state.wake(wake_ref.object_id)
                if wake is None or wake.record_digest != wake_ref.object_digest:
                    raise R45Error(R45_REFERENCE_INVALID, "eligibility wake reference is missing or stale")
            _validate_refs(candidate.human_gate_refs + candidate.upstream_current_refs, state.mission_id, candidate.as_of_seq, "eligibility.source_refs", current=True)
            if candidate.r2_target.stream_owner_mission_id != state.mission_id:
                raise R45Error(R45_SCOPE_MISMATCH, "R2 resume target belongs to another Mission")
            computed, reasons = _eligibility_outcome(candidate, state)
            candidate = replace(candidate, outcome=computed, blocking_reason_evaluation=reasons, eligibility_digest=None, record_digest=None)
            if state.eligibility(candidate.eligibility_id) is not None:
                raise R45Error(R45_IDENTITY_CONFLICT, "eligibility identity already exists")
            return [PendingEvent(R45_RESUME_ELIGIBILITY_ASSESSED, "R4_5_RESUME_ELIGIBILITY", candidate.eligibility_id, candidate.to_dict())]

        if command.type == R4_5_RECORD_RESUME_INTENT:
            raw = _payload(command, R2ResumeIntent)
            candidate = _next_record(R2ResumeIntent, raw, composed, command)
            _require_scope(candidate, state)
            eligibility = state.eligibility(candidate.eligibility_ref.object_id)
            readiness = state.readiness(candidate.readiness_ref.object_id)
            wait = state.wait(candidate.wait_ref.object_id)
            if eligibility is None or eligibility.record_digest != candidate.eligibility_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "resume intent eligibility reference is missing or stale")
            if readiness is None or readiness.record_digest != candidate.readiness_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "resume intent readiness reference is missing or stale")
            if wait is None or wait.record_digest != candidate.wait_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "resume intent wait reference is missing or stale")
            if eligibility.outcome is not ResumeEligibilityOutcome.ELIGIBLE:
                raise R45Error(R45_NOT_ELIGIBLE, "resume intent requires ELIGIBLE assessment")
            _validate_refs((candidate.eligibility_ref, candidate.readiness_ref, candidate.wait_ref, candidate.r2_authorization_ref), state.mission_id, candidate.as_of_seq, "resume_intent.references", current=True)
            if not any(_same_reference(candidate.r2_authorization_ref, value) for value in eligibility.human_gate_refs):
                raise R45Error(R45_AUTHORITY_MISSING, "resume intent authorization is not an exact HumanGate lineage reference")
            if dict(eligibility.source_state).get("continuation_state", "READY").upper() in {"CONTINUATION_PENDING", "PENDING", "ROUTE_REVISION"}:
                raise R45Error(R45_NOT_ELIGIBLE, "continuation is pending or revised")
            if candidate.continuation_ref is not None:
                _validate_ref(candidate.continuation_ref, state.mission_id, candidate.as_of_seq, "resume_intent.continuation_ref", current=True)
            if candidate.supersedes_ref is not None:
                prior = state.intent(candidate.supersedes_ref.object_id)
                if prior is None or prior.record_digest != candidate.supersedes_ref.object_digest:
                    raise R45Error(R45_REFERENCE_INVALID, "supersedes_ref does not reference an exact existing intent")
            if state.intent(candidate.resume_intent_id) is not None:
                raise R45Error(R45_IDENTITY_CONFLICT, "resume intent identity already exists")
            return [PendingEvent(R45_RESUME_INTENT_RECORDED, "R4_5_R2_RESUME_INTENT", candidate.resume_intent_id, candidate.to_dict())]

        if command.type == R4_5_RECONCILE_R2_RESUME_RECEIPT:
            raw = _payload(command, R2ResumeReceipt)
            candidate = _next_record(R2ResumeReceipt, raw, composed, command)
            _require_scope(candidate, state)
            intent = state.intent(candidate.resume_intent_ref.object_id)
            if intent is None or intent.record_digest != candidate.resume_intent_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "receipt intent reference is missing or stale")
            if not _same_reference(candidate.r2_authorization_ref, intent.r2_authorization_ref):
                raise R45Error(R45_AUTHORITY_MISSING, "receipt authorization is not the exact intent authorization")
            if (candidate.continuation_ref is None) != (intent.continuation_ref is None) or candidate.continuation_ref is not None and not _same_reference(candidate.continuation_ref, intent.continuation_ref):
                raise R45Error(R45_REFERENCE_INVALID, "receipt continuation is not the exact intent continuation")
            _validate_refs((candidate.resume_intent_ref, candidate.r2_authorization_ref, candidate.r2_result_ref), state.mission_id, candidate.as_of_seq, "receipt.references", current=True)
            if candidate.r2_result_digest != candidate.r2_result_ref.object_digest:
                raise R45Error(R45_DIGEST_CONFLICT, "R2 result digest does not match exact result reference")
            existing = state.receipt_for_intent(intent.resume_intent_id)
            if existing is not None and existing.r2_result_digest != candidate.r2_result_digest:
                candidate = replace(candidate, receipt_status=R2ResumeReceiptStatus.RECONCILIATION_REQUIRED, reconciled_from_existing_result=True, record_digest=None)
            if state.receipt(candidate.resume_receipt_id) is not None:
                raise R45Error(R45_IDENTITY_CONFLICT, "receipt identity already exists")
            return [PendingEvent(R45_R2_RESUME_RECEIPT_RECONCILED, "R4_5_R2_RESUME_RECEIPT", candidate.resume_receipt_id, candidate.to_dict())]

        if command.type == R4_5_RECORD_READINESS_DISPOSITION:
            raw = _payload(command, ReadinessDispositionLinkage)
            candidate = _next_record(ReadinessDispositionLinkage, raw, composed, command)
            _require_scope(candidate, state)
            readiness = state.readiness(candidate.readiness_ref.object_id)
            if readiness is None or readiness.record_digest != candidate.readiness_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "disposition readiness reference is missing or stale")
            _validate_ref(candidate.readiness_ref, state.mission_id, candidate.as_of_seq, "disposition.readiness_ref", current=True)
            _validate_refs(candidate.source_refs, state.mission_id, candidate.as_of_seq, "disposition.source_refs", current=True)
            if candidate.disposition in {ReadinessDisposition.REVOKE, ReadinessDisposition.STALE} and not candidate.reason:
                raise R45Error(R45_COMMAND_INVALID, "revocation and staleness require a source-backed reason")
            if state.disposition(candidate.disposition_id) is not None:
                raise R45Error(R45_IDENTITY_CONFLICT, "disposition identity already exists")
            return [PendingEvent(R45_READINESS_DISPOSITION_RECORDED, "R4_5_READINESS_DISPOSITION", candidate.disposition_id, candidate.to_dict())]

        raise R45Error(R45_COMMAND_INVALID, f"unsupported R4.5 command: {command.type}")


__all__ = ["R45CommandContribution"]
