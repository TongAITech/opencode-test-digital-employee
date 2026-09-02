from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState, canonical_sha256

from .contracts import *
from .errors import *


def _append(values: tuple[Any, ...], value: Any, identity: str, name: str) -> tuple[Any, ...]:
    if any(getattr(item, identity) == getattr(value, identity) for item in values):
        raise R45Error(R45_IDENTITY_CONFLICT, f"{name} identity is already durable")
    return values + (value,)


def _record_ref(kind: str, record: Any) -> ScopedReference:
    identity = next(
        getattr(record, name)
        for name in (
            "risk_assessment_id", "readiness_assessment_id", "wait_id", "wake_linkage_id",
            "eligibility_id", "resume_intent_id", "resume_receipt_id", "disposition_id",
        )
        if hasattr(record, name)
    )
    revision = getattr(record, "revision", 1)
    return ScopedReference(
        ref_kind=kind,
        stream_owner_mission_id=record.stream_owner_mission_id,
        object_id=identity,
        object_revision=revision,
        object_digest=record.record_digest,
        source_seq=record.created_seq,
        source_cursor=record.created_seq,
        access_mode=ScopedReferenceAccessMode.LOCAL,
        source_stream_key=f"r4.5:{kind}",
    )


@dataclass(frozen=True)
class R45State:
    mission_id: str
    release_risk_assessments: tuple[ReleaseRiskAssessment, ...] = ()
    release_readiness_assessments: tuple[ReleaseReadinessAssessment, ...] = ()
    release_wait_states: tuple[ReleaseWaitState, ...] = ()
    wake_linkages: tuple[WakeLinkage, ...] = ()
    resume_eligibility_assessments: tuple[ResumeEligibilityAssessment, ...] = ()
    resume_intents: tuple[R2ResumeIntent, ...] = ()
    resume_receipts: tuple[R2ResumeReceipt, ...] = ()
    readiness_dispositions: tuple[ReadinessDispositionLinkage, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, str) or not self.mission_id.strip():
            raise R45Error(R45_SCHEMA_INVALID, "mission_id is required")
        for name in (
            "release_risk_assessments", "release_readiness_assessments", "release_wait_states", "wake_linkages",
            "resume_eligibility_assessments", "resume_intents", "resume_receipts", "readiness_dispositions",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise R45Error(R45_SCHEMA_INVALID, f"{name} must be immutable")
            for item in values:
                if getattr(item, "stream_owner_mission_id", self.mission_id) != self.mission_id:
                    raise R45Error(R45_SCOPE_MISMATCH, f"{name} contains a cross-Mission canonical record")

    def risk(self, identity: str) -> ReleaseRiskAssessment | None:
        return next((item for item in self.release_risk_assessments if item.risk_assessment_id == identity), None)

    def readiness(self, identity: str) -> ReleaseReadinessAssessment | None:
        return next((item for item in self.release_readiness_assessments if item.readiness_assessment_id == identity), None)

    def wait(self, identity: str) -> ReleaseWaitState | None:
        return next((item for item in self.release_wait_states if item.wait_id == identity), None)

    def wake(self, identity: str) -> WakeLinkage | None:
        return next((item for item in self.wake_linkages if item.wake_linkage_id == identity), None)

    def eligibility(self, identity: str) -> ResumeEligibilityAssessment | None:
        return next((item for item in self.resume_eligibility_assessments if item.eligibility_id == identity), None)

    def intent(self, identity: str) -> R2ResumeIntent | None:
        return next((item for item in self.resume_intents if item.resume_intent_id == identity), None)

    def receipt(self, identity: str) -> R2ResumeReceipt | None:
        return next((item for item in self.resume_receipts if item.resume_receipt_id == identity), None)

    def disposition(self, identity: str) -> ReadinessDispositionLinkage | None:
        return next((item for item in self.readiness_dispositions if item.disposition_id == identity), None)

    def receipt_for_intent(self, identity: str) -> R2ResumeReceipt | None:
        values = tuple(item for item in self.resume_receipts if item.resume_intent_ref.object_id == identity)
        if len(values) > 1:
            digests = {item.r2_result_digest for item in values}
            if len(digests) > 1:
                raise R45Error(R45_RECONCILIATION_REQUIRED, "one resume intent has incomparable R2 result digests")
        return values[0] if values else None

    def wake_for_coalescing_key(self, key: str) -> tuple[WakeLinkage, ...]:
        return tuple(item for item in self.wake_linkages if item.coalescing_key == key)

    def current_resolution(self, release_scope: ReleaseScope | Mapping[str, Any]) -> CurrentReadinessResolution:
        scope = release_scope if isinstance(release_scope, ReleaseScope) else ReleaseScope.from_dict(release_scope)
        readiness_values = tuple(item for item in self.release_readiness_assessments if item.release_scope.to_dict() == scope.to_dict())
        revoked_ids = {
            item.readiness_ref.object_id
            for item in self.readiness_dispositions
            if item.release_scope.to_dict() == scope.to_dict()
            and item.disposition in {ReadinessDisposition.REVOKE, ReadinessDisposition.STALE}
        }
        superseded_ids = {
            item.readiness_ref.object_id
            for item in self.readiness_dispositions
            if item.release_scope.to_dict() == scope.to_dict()
            and isinstance(item.reason, Mapping)
            and item.reason.get("supersedes_ref")
        }
        active = tuple(
            item for item in readiness_values
            if item.lifecycle_state is ReadinessLifecycleState.CURRENT
            and item.readiness_assessment_id not in revoked_ids
            and item.readiness_assessment_id not in superseded_ids
        )
        state = "UNKNOWN"
        current_readiness: ReleaseReadinessAssessment | None = None
        if len(active) == 1:
            current_readiness = active[0]
            state = "CURRENT"
        elif len(active) > 1:
            state = "CONFLICT"
        elif readiness_values:
            state = "REVOKED" if revoked_ids else "SUPERSEDED" if superseded_ids else "STALE"

        current_wait: ReleaseWaitState | None = None
        current_eligibility: ResumeEligibilityAssessment | None = None
        current_disposition: ReadinessDispositionLinkage | None = None
        if current_readiness is not None:
            waits = tuple(
                item for item in self.release_wait_states
                if item.release_scope.to_dict() == scope.to_dict()
                and item.readiness_revision_ref.object_id == current_readiness.readiness_assessment_id
                and item.lifecycle_state is WaitLifecycleState.CURRENT
            )
            if len(waits) == 1:
                current_wait = waits[0]
            elif len(waits) > 1:
                state = "CONFLICT"
            if current_wait is not None:
                eligibilities = tuple(
                    item for item in self.resume_eligibility_assessments
                    if item.release_scope.to_dict() == scope.to_dict()
                    and item.readiness_revision_ref.object_id == current_readiness.readiness_assessment_id
                    and item.wait_ref.object_id == current_wait.wait_id
                )
                if len(eligibilities) == 1:
                    current_eligibility = eligibilities[0]
                elif len(eligibilities) > 1:
                    state = "CONFLICT"
            dispositions = tuple(
                item for item in self.readiness_dispositions
                if item.release_scope.to_dict() == scope.to_dict()
                and item.readiness_ref.object_id == current_readiness.readiness_assessment_id
            )
            if len(dispositions) == 1:
                current_disposition = dispositions[0]
            elif len(dispositions) > 1:
                state = "CONFLICT"

        def reference(kind: str, value: Any) -> ScopedReference | None:
            return _record_ref(kind, value) if value is not None else None

        values = {
            "stream_owner_mission_id": self.mission_id,
            "release_scope": scope,
            "current_risk_ref": reference("RELEASE_RISK_ASSESSMENT", current_readiness and self.risk(current_readiness.risk_assessment_ref.object_id)),
            "current_readiness_ref": reference("RELEASE_READINESS_ASSESSMENT", current_readiness),
            "current_wait_ref": reference("RELEASE_WAIT_STATE", current_wait),
            "current_eligibility_ref": reference("RESUME_ELIGIBILITY_ASSESSMENT", current_eligibility),
            "current_disposition_ref": reference("READINESS_DISPOSITION", current_disposition),
            "resolution_state": state,
            "resolution_digest": None,
            "resolution_revision": canonical_sha256({
                "risk": current_readiness.risk_assessment_ref.to_dict() if current_readiness else None,
                "readiness": _record_ref("RELEASE_READINESS_ASSESSMENT", current_readiness).to_dict() if current_readiness else None,
                "wait": _record_ref("RELEASE_WAIT_STATE", current_wait).to_dict() if current_wait else None,
                "eligibility": _record_ref("RESUME_ELIGIBILITY_ASSESSMENT", current_eligibility).to_dict() if current_eligibility else None,
                "disposition": _record_ref("READINESS_DISPOSITION", current_disposition).to_dict() if current_disposition else None,
                "state": state,
            }),
            "as_of_seq": max((item.created_seq for item in readiness_values), default=0),
            "source_cursor": max((item.source_cursor for item in readiness_values), default=0),
            "superseded_refs": tuple(_record_ref("RELEASE_READINESS_ASSESSMENT", item) for item in readiness_values if item.readiness_assessment_id in superseded_ids),
            "revoked_refs": tuple(_record_ref("RELEASE_READINESS_ASSESSMENT", item) for item in readiness_values if item.readiness_assessment_id in revoked_ids),
        }
        return CurrentReadinessResolution(**values)

    resolve_current = current_resolution

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "release_risk_assessments": [item.to_dict() for item in self.release_risk_assessments],
            "release_readiness_assessments": [item.to_dict() for item in self.release_readiness_assessments],
            "release_wait_states": [item.to_dict() for item in self.release_wait_states],
            "wake_linkages": [item.to_dict() for item in self.wake_linkages],
            "resume_eligibility_assessments": [item.to_dict() for item in self.resume_eligibility_assessments],
            "resume_intents": [item.to_dict() for item in self.resume_intents],
            "resume_receipts": [item.to_dict() for item in self.resume_receipts],
            "readiness_dispositions": [item.to_dict() for item in self.readiness_dispositions],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "R45State":
        return cls(
            mission_id=str(value["mission_id"]),
            release_risk_assessments=tuple(ReleaseRiskAssessment.from_dict(item) for item in value.get("release_risk_assessments") or ()),
            release_readiness_assessments=tuple(ReleaseReadinessAssessment.from_dict(item) for item in value.get("release_readiness_assessments") or ()),
            release_wait_states=tuple(ReleaseWaitState.from_dict(item) for item in value.get("release_wait_states") or ()),
            wake_linkages=tuple(WakeLinkage.from_dict(item) for item in value.get("wake_linkages") or ()),
            resume_eligibility_assessments=tuple(ResumeEligibilityAssessment.from_dict(item) for item in value.get("resume_eligibility_assessments") or ()),
            resume_intents=tuple(R2ResumeIntent.from_dict(item) for item in value.get("resume_intents") or ()),
            resume_receipts=tuple(R2ResumeReceipt.from_dict(item) for item in value.get("resume_receipts") or ()),
            readiness_dispositions=tuple(ReadinessDispositionLinkage.from_dict(item) for item in value.get("readiness_dispositions") or ()),
        )


def initial_state(mission_id: str) -> R45State:
    return R45State(mission_id)


def _context(state: R45State, event: EventEnvelope, core_state: RuntimeState) -> None:
    if event.schema_version != 1:
        raise R45Error(R45_UNKNOWN_EVENT, f"unsupported R4.5 event schema: {event.schema_version}")
    if event.event_type not in EVENT_TYPES:
        raise R45Error(R45_UNKNOWN_EVENT, f"unsupported R4.5 event: {event.event_type}")
    if event.mission_id != state.mission_id or event.mission_id != core_state.mission_id:
        raise R45Error(R45_SCOPE_MISMATCH, "R4.5 event Mission differs from state")
    if event.seq != core_state.seq:
        raise R45Error(R45_SEQUENCE_MISMATCH, "R4.5 event must share the Core sequence")
    if event.session_id is not None:
        raise R45Error(R45_SCHEMA_INVALID, "R4.5 events are session-independent")
    if not event.entity_id or not event.command_id or not event.correlation_id:
        raise R45Error(R45_SCHEMA_INVALID, "R4.5 event causation and identity are required")


class R45ReducerContribution:
    def reduce(self, state: R45State, event: EventEnvelope, core_state: RuntimeState) -> R45State:
        if not isinstance(state, R45State):
            raise R45Error(R45_SCHEMA_INVALID, "invalid R4.5 state")
        _context(state, event, core_state)
        if event.event_type == R45_RELEASE_RISK_ASSESSED:
            value = ReleaseRiskAssessment.from_dict(event.payload)
            if event.entity_id != value.risk_assessment_id:
                raise R45Error(R45_SCHEMA_INVALID, "risk event identity mismatch")
            return R45State(state.mission_id, _append(state.release_risk_assessments, value, "risk_assessment_id", "risk"), state.release_readiness_assessments, state.release_wait_states, state.wake_linkages, state.resume_eligibility_assessments, state.resume_intents, state.resume_receipts, state.readiness_dispositions)
        if event.event_type == R45_RELEASE_READINESS_ASSESSED:
            value = ReleaseReadinessAssessment.from_dict(event.payload)
            risk = state.risk(value.risk_assessment_ref.object_id)
            if event.entity_id != value.readiness_assessment_id or risk is None or risk.record_digest != value.risk_assessment_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "readiness event has an invalid risk lineage")
            return R45State(state.mission_id, state.release_risk_assessments, _append(state.release_readiness_assessments, value, "readiness_assessment_id", "readiness"), state.release_wait_states, state.wake_linkages, state.resume_eligibility_assessments, state.resume_intents, state.resume_receipts, state.readiness_dispositions)
        if event.event_type == R45_RELEASE_WAIT_OPENED:
            value = ReleaseWaitState.from_dict(event.payload)
            readiness = state.readiness(value.readiness_revision_ref.object_id)
            risk = state.risk(value.risk_assessment_ref.object_id)
            if event.entity_id != value.wait_id or readiness is None or risk is None:
                raise R45Error(R45_REFERENCE_INVALID, "wait event has missing readiness or risk lineage")
            if readiness.record_digest != value.readiness_revision_ref.object_digest or risk.record_digest != value.risk_assessment_ref.object_digest:
                raise R45Error(R45_DIGEST_CONFLICT, "wait event lineage digest mismatch")
            return R45State(state.mission_id, state.release_risk_assessments, state.release_readiness_assessments, _append(state.release_wait_states, value, "wait_id", "wait"), state.wake_linkages, state.resume_eligibility_assessments, state.resume_intents, state.resume_receipts, state.readiness_dispositions)
        if event.event_type == R45_WAKE_LINKAGE_RECORDED:
            value = WakeLinkage.from_dict(event.payload)
            wait = state.wait(value.wait_ref.object_id)
            if event.entity_id != value.wake_linkage_id or wait is None or wait.record_digest != value.wait_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "wake event has missing or stale wait lineage")
            return R45State(state.mission_id, state.release_risk_assessments, state.release_readiness_assessments, state.release_wait_states, _append(state.wake_linkages, value, "wake_linkage_id", "wake"), state.resume_eligibility_assessments, state.resume_intents, state.resume_receipts, state.readiness_dispositions)
        if event.event_type == R45_RESUME_ELIGIBILITY_ASSESSED:
            value = ResumeEligibilityAssessment.from_dict(event.payload)
            readiness = state.readiness(value.readiness_revision_ref.object_id)
            wait = state.wait(value.wait_ref.object_id)
            if event.entity_id != value.eligibility_id or readiness is None or wait is None:
                raise R45Error(R45_REFERENCE_INVALID, "eligibility event has missing readiness or wait lineage")
            if readiness.record_digest != value.readiness_revision_ref.object_digest or wait.record_digest != value.wait_ref.object_digest:
                raise R45Error(R45_DIGEST_CONFLICT, "eligibility event lineage digest mismatch")
            for wake_ref in value.wake_refs:
                wake = state.wake(wake_ref.object_id)
                if wake is None or wake.record_digest != wake_ref.object_digest:
                    raise R45Error(R45_REFERENCE_INVALID, "eligibility event has missing wake lineage")
            return R45State(state.mission_id, state.release_risk_assessments, state.release_readiness_assessments, state.release_wait_states, state.wake_linkages, _append(state.resume_eligibility_assessments, value, "eligibility_id", "eligibility"), state.resume_intents, state.resume_receipts, state.readiness_dispositions)
        if event.event_type == R45_RESUME_INTENT_RECORDED:
            value = R2ResumeIntent.from_dict(event.payload)
            eligibility = state.eligibility(value.eligibility_ref.object_id)
            readiness = state.readiness(value.readiness_ref.object_id)
            wait = state.wait(value.wait_ref.object_id)
            if event.entity_id != value.resume_intent_id or eligibility is None or readiness is None or wait is None:
                raise R45Error(R45_REFERENCE_INVALID, "intent event has missing upstream lineage")
            if eligibility.record_digest != value.eligibility_ref.object_digest or readiness.record_digest != value.readiness_ref.object_digest or wait.record_digest != value.wait_ref.object_digest:
                raise R45Error(R45_DIGEST_CONFLICT, "intent event lineage digest mismatch")
            if eligibility.outcome is not ResumeEligibilityOutcome.ELIGIBLE:
                raise R45Error(R45_NOT_ELIGIBLE, "intent event requires an eligible assessment")
            return R45State(state.mission_id, state.release_risk_assessments, state.release_readiness_assessments, state.release_wait_states, state.wake_linkages, state.resume_eligibility_assessments, _append(state.resume_intents, value, "resume_intent_id", "intent"), state.resume_receipts, state.readiness_dispositions)
        if event.event_type == R45_R2_RESUME_RECEIPT_RECONCILED:
            value = R2ResumeReceipt.from_dict(event.payload)
            intent = state.intent(value.resume_intent_ref.object_id)
            if event.entity_id != value.resume_receipt_id or intent is None:
                raise R45Error(R45_REFERENCE_INVALID, "receipt event has missing intent lineage")
            if intent.record_digest != value.resume_intent_ref.object_digest:
                raise R45Error(R45_DIGEST_CONFLICT, "receipt event intent digest mismatch")
            if not any(item.r2_result_digest == value.r2_result_digest for item in state.resume_receipts if item.resume_intent_ref.object_id == intent.resume_intent_id) and value.receipt_status is R2ResumeReceiptStatus.RECONCILIATION_REQUIRED:
                raise R45Error(R45_RECONCILIATION_REQUIRED, "reconciliation receipt lacks an existing result")
            return R45State(state.mission_id, state.release_risk_assessments, state.release_readiness_assessments, state.release_wait_states, state.wake_linkages, state.resume_eligibility_assessments, state.resume_intents, _append(state.resume_receipts, value, "resume_receipt_id", "receipt"), state.readiness_dispositions)
        if event.event_type == R45_READINESS_DISPOSITION_RECORDED:
            value = ReadinessDispositionLinkage.from_dict(event.payload)
            readiness = state.readiness(value.readiness_ref.object_id)
            if event.entity_id != value.disposition_id or readiness is None or readiness.record_digest != value.readiness_ref.object_digest:
                raise R45Error(R45_REFERENCE_INVALID, "disposition event has missing or stale readiness lineage")
            return R45State(state.mission_id, state.release_risk_assessments, state.release_readiness_assessments, state.release_wait_states, state.wake_linkages, state.resume_eligibility_assessments, state.resume_intents, state.resume_receipts, _append(state.readiness_dispositions, value, "disposition_id", "disposition"))
        raise R45Error(R45_UNKNOWN_EVENT, f"unsupported R4.5 event: {event.event_type}")


SUPPORTED_EVENTS = EVENT_TYPES


__all__ = ["R45State", "R45ReducerContribution", "SUPPORTED_EVENTS", "initial_state"]
