from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService
from aitest_runtime.durable_core.contracts import RuntimeError as DurableRuntimeError

from .contracts import *
from .errors import *
from .extension import r4_7_extension


def _raw(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    raise R47Error(R47_COMMAND_INVALID, "R4.7 value must be a record or mapping")


def _common_defaults(raw: dict[str, Any], *, mission_id: str | None = None, actor: ActorRef | None = None) -> dict[str, Any]:
    selected = str(raw.get("owner_mission_id") or raw.get("mission_id") or mission_id or "")
    if selected:
        raw["owner_mission_id"] = selected
    raw.setdefault("owner_stream_key", f"r4.7:{selected}")
    raw.setdefault("revision", 1)
    raw.setdefault("record_digest", None)
    raw.setdefault("as_of_seq", 0)
    raw.setdefault("correlation_id", "r4.7")
    raw.setdefault("causation_id", "r4.7")
    raw.setdefault("created_by", (actor or ActorRef("SYSTEM", "r4.7")).to_dict())
    raw.setdefault("created_seq", 1)
    raw.setdefault("created_at", "seq:1")
    return raw


def _provisional(cls: type[Any], value: Any, *, mission_id: str | None = None, actor: ActorRef | None = None) -> Any:
    return cls.from_dict(_common_defaults(_raw(value), mission_id=mission_id, actor=actor))


def _record_cls(value: Any) -> type[Any]:
    if isinstance(value, LegacySourceObservationInput):
        return LegacySourceObservation
    if isinstance(value, LegacySourceObservation):
        return LegacySourceObservation
    if isinstance(value, Mapping):
        if "observation_id" in value or "owner_mission_id" in value:
            return LegacySourceObservation
    return LegacySourceObservation


def _identity(record: Any) -> str:
    for name in ("observation_id", "assessment_id", "mapping_id", "decision_id", "handoff_id", "receipt_id"):
        if hasattr(record, name):
            return str(getattr(record, name))
    raise R47Error(R47_COMMAND_INVALID, "record has no R4.7 identity")


class R47ApplicationService:
    """Caller-owned R4.7 service; all durability goes through the existing RuntimeService."""

    def __init__(self, runtime_service: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if not isinstance(runtime_service, RuntimeService):
            raise TypeError("runtime_service must be the existing RuntimeService")
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        self._runtime = runtime_service
        self.runtime_service = runtime_service
        self.runtime = runtime_service
        self.actor = actor or ActorRef("SYSTEM", "r4.7")

    def state(self, mission_id: str) -> R47State:
        value = self._runtime.get_composed_state(mission_id).extension_state(EXTENSION_ID)
        if not isinstance(value, R47State):
            raise R47Error(R47_COMMAND_INVALID, "R4.7 extension state is invalid")
        return value

    get_state = state

    def observation(self, mission_id: str, observation_id: str) -> LegacySourceObservation | None:
        return self.state(mission_id).observation(observation_id)

    def assessment(self, mission_id: str, assessment_id: str) -> ReconciliationAssessment | None:
        return self.state(mission_id).assessment(assessment_id)

    def mapping(self, mission_id: str, mapping_id: str) -> LegacyCanonicalMapping | None:
        return self.state(mission_id).mapping(mapping_id)

    def decision(self, mission_id: str, decision_id: str) -> ReconciliationDecision | None:
        return self.state(mission_id).decision(decision_id)

    def handoff(self, mission_id: str, handoff_id: str) -> CanonicalHandoffLinkage | None:
        return self.state(mission_id).handoff(handoff_id)

    def receipt(self, mission_id: str, receipt_id: str) -> ReconciliationReceipt | None:
        return self.state(mission_id).receipt(receipt_id)

    def current_resolution(self, mission_id: str, case_id: str) -> CurrentReconciliationResolution:
        case = self.state(mission_id).case(case_id)
        if case is None or case.resolution is None:
            return CurrentReconciliationResolution(mission_id, case_id, status=ResolutionStatus.UNKNOWN)
        return case.resolution

    def reconciliation_case(self, mission_id: str, case_id: str) -> ReconciliationCase | None:
        return self.state(mission_id).case(case_id)

    def _error(self, command_id: str, mission_id: str, exc: Exception) -> R47OperationResult:
        error = exc if isinstance(exc, (R47Error, DurableRuntimeError)) else R47Error(R47_COMMAND_INVALID, str(exc))
        return R47OperationResult(CommandResult("REJECTED", command_id, mission_id, error=error))

    @staticmethod
    def _same_record(left: Any, right: Any) -> bool:
        return left.to_dict() == right.to_dict() or left.record_digest == right.record_digest

    def _execute(self, *, record: Any, command_type: str, key: str, payload_key: str, current: Any | None = None, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        mission_id = record.owner_mission_id
        command_identifier = command_id or f"r4.7:{key}"
        try:
            if current is not None:
                if not self._same_record(record, current):
                    return self._error(command_identifier, mission_id, R47Error(R47_IDENTITY_CONFLICT, "immutable identity already owns a different digest"))
                return R47OperationResult(CommandResult("DUPLICATE", command_identifier, mission_id, duplicate_of=command_identifier, first_seq=current.created_seq, last_seq=current.created_seq), current)
            result = self._runtime.execute(
                {
                    "command_id": command_identifier,
                    "type": command_type,
                    "mission_id": mission_id,
                    "session_id": None,
                    "expected_seq": self._runtime.get_head_seq(mission_id) if expected_seq is None else expected_seq,
                    "actor": (actor or self.actor).to_dict(),
                    "payload": {payload_key: record.to_dict()},
                    "idempotency_key": f"r4.7:{key}",
                    "correlation_id": correlation_id or record.correlation_id,
                    "schema_version": SCHEMA_VERSION,
                }
            )
            entity = None
            if result.ok:
                state = self.state(mission_id)
                entity = {
                    "observation": state.observation(record.observation_id) if hasattr(record, "observation_id") else None,
                    "assessment": state.assessment(record.assessment_id) if hasattr(record, "assessment_id") else None,
                    "mapping": state.mapping(record.mapping_id) if hasattr(record, "mapping_id") else None,
                    "decision": state.decision(record.decision_id) if hasattr(record, "decision_id") else None,
                    "handoff": state.handoff(record.handoff_id) if hasattr(record, "handoff_id") else None,
                    "receipt": state.receipt(record.receipt_id) if hasattr(record, "receipt_id") else None,
                }.get(payload_key)
            return R47OperationResult(result, entity)
        except Exception as exc:
            return self._error(command_identifier, mission_id, exc)

    def _observation(self, value: LegacySourceObservationInput | LegacySourceObservation | Mapping[str, Any], *, mission_id: str | None = None, actor: ActorRef | None = None) -> LegacySourceObservation:
        if isinstance(value, LegacySourceObservationInput):
            raw = value.to_dict()
            raw.update(_common_defaults({}, mission_id=mission_id, actor=actor))
            raw["owner_mission_id"] = mission_id or raw.get("owner_mission_id", "")
            raw["owner_stream_key"] = f"r4.7:{raw['owner_mission_id']}"
            return LegacySourceObservation.from_dict(raw)
        if isinstance(value, LegacySourceObservation):
            return value
        return _provisional(LegacySourceObservation, value, mission_id=mission_id, actor=actor)

    def record_legacy_source_observation(self, value: LegacySourceObservationInput | LegacySourceObservation | Mapping[str, Any], *, mission_id: str | None = None, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        try:
            record = self._observation(value, mission_id=mission_id, actor=actor)
            current = self.state(record.owner_mission_id).observation(record.observation_id)
            return self._execute(record=record, command_type=R4_7_RECORD_LEGACY_SOURCE_OBSERVATION, key=f"observation:{record.observation_id}", payload_key="observation", current=current, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("observation_id") or ""), str(raw.get("owner_mission_id") or mission_id or ""), exc)

    record_observation = record_legacy_source_observation

    def _assessment(self, value: ReconciliationAssessment | Mapping[str, Any], mission_id: str | None = None, actor: ActorRef | None = None) -> ReconciliationAssessment:
        return value if isinstance(value, ReconciliationAssessment) else _provisional(ReconciliationAssessment, value, mission_id=mission_id, actor=actor)

    def record_reconciliation_assessment(self, value: ReconciliationAssessment | Mapping[str, Any], *, mission_id: str | None = None, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        try:
            record = self._assessment(value, mission_id, actor)
            current = self.state(record.owner_mission_id).assessment(record.assessment_id)
            return self._execute(record=record, command_type=R4_7_RECORD_RECONCILIATION_ASSESSMENT, key=f"assessment:{record.assessment_id}", payload_key="assessment", current=current, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("assessment_id") or ""), str(raw.get("owner_mission_id") or mission_id or ""), exc)

    record_assessment = record_reconciliation_assessment

    def evaluate_reconciliation(self, observation: LegacySourceObservation | Mapping[str, Any], *, canonical_target: Mapping[str, Any] | None = None, policy_snapshot_ref: Any = None, mission_id: str | None = None, actor: ActorRef | None = None) -> ReconciliationAssessment:
        value = observation if isinstance(observation, LegacySourceObservation) else _provisional(LegacySourceObservation, observation, mission_id=mission_id, actor=actor)
        target = dict(canonical_target or {})
        gate_outcome = str(target.get("human_gate_decision", target.get("human_gate_outcome", "ALLOW"))).upper()
        field_validation = str(target.get("field_validation_state", "NOT_APPLICABLE")).upper()
        if target.get("conflict"):
            outcome = AssessmentOutcome.CONFLICT
        elif value.availability is SourceAvailability.UNAVAILABLE or gate_outcome not in {"ALLOW", "NOT_REQUIRED", "NOT_APPLICABLE"}:
            outcome = AssessmentOutcome.BLOCKED
        elif value.active_writer_state is ActiveWriterState.ACTIVE or target.get("source_content_changed"):
            outcome = AssessmentOutcome.STALE if value.native_source_digest else AssessmentOutcome.REVALIDATION_REQUIRED
        elif field_validation in {"PENDING", "UNKNOWN", "UNAVAILABLE"}:
            outcome = AssessmentOutcome.REVALIDATION_REQUIRED
        elif target.get("out_of_scope"):
            outcome = AssessmentOutcome.OUT_OF_SCOPE
        elif value.source_family is SourceFamily.UNKNOWN or (not value.source_object_identity and not value.native_id):
            outcome = AssessmentOutcome.UNKNOWN
        elif target.get("target_object_ref") and target.get("write_required"):
            outcome = AssessmentOutcome.HANDOFF_REQUIRED
        elif target.get("target_object_ref"):
            outcome = AssessmentOutcome.MAPPABLE
        else:
            outcome = AssessmentOutcome.REFERENCE_ONLY if target.get("reference_only") else AssessmentOutcome.NO_CANONICAL_TARGET
        return ReconciliationAssessment(
            owner_mission_id=value.owner_mission_id,
            owner_stream_key=value.owner_stream_key,
            assessment_id="pending",
            observation_ref={"object_id": value.observation_id, "source_digest": value.record_digest},
            observation_digest=value.record_digest or "0" * 64,
            outcome=outcome,
            source_identity_completeness="COMPLETE" if value.source_object_identity or value.native_id else "INCOMPLETE",
            provenance_completeness="COMPLETE" if value.adapter_id else "INCOMPLETE",
            scope_completeness="COMPLETE" if value.source_scope else "UNKNOWN",
            source_availability=value.availability,
            source_freshness=value.freshness,
            active_writer_risk=value.active_writer_state.value,
            canonical_target_discoverability="FOUND" if target else "NOT_FOUND",
            canonical_target_exactness="EXACT" if target.get("target_object_ref") else "UNKNOWN",
            legacy_canonical_conflict="CONFLICT" if target.get("conflict") else "NONE",
            field_validation_relevance="PENDING" if value.source_family is SourceFamily.LEGACY_KNOWLEDGE else "NOT_APPLICABLE",
            human_approval_requirement="REQUIRED" if outcome is AssessmentOutcome.HANDOFF_REQUIRED else "NOT_REQUIRED",
            migration_eligibility="ELIGIBLE" if outcome in {AssessmentOutcome.MAPPABLE, AssessmentOutcome.HANDOFF_REQUIRED} else "NOT_ELIGIBLE",
            shadow_truth_risk=ShadowTruthStatus.IDENTIFIED,
            out_of_scope_status="IN_SCOPE",
            policy_snapshot_ref=policy_snapshot_ref,
        )

    def record_legacy_canonical_mapping(self, value: LegacyCanonicalMapping | Mapping[str, Any], *, mission_id: str | None = None, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        try:
            record = value if isinstance(value, LegacyCanonicalMapping) else _provisional(LegacyCanonicalMapping, value, mission_id=mission_id, actor=actor)
            current = self.state(record.owner_mission_id).mapping(record.mapping_id)
            return self._execute(record=record, command_type=R4_7_RECORD_LEGACY_CANONICAL_MAPPING, key=f"mapping:{record.mapping_id}", payload_key="mapping", current=current, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("mapping_id") or ""), str(raw.get("owner_mission_id") or mission_id or ""), exc)

    record_mapping = record_legacy_canonical_mapping

    def record_reconciliation_decision(self, value: ReconciliationDecision | Mapping[str, Any], *, mission_id: str | None = None, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        try:
            record = value if isinstance(value, ReconciliationDecision) else _provisional(ReconciliationDecision, value, mission_id=mission_id, actor=actor)
            current = self.state(record.owner_mission_id).decision(record.decision_id)
            return self._execute(record=record, command_type=R4_7_RECORD_RECONCILIATION_DECISION, key=f"decision:{record.decision_id}", payload_key="decision", current=current, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("decision_id") or ""), str(raw.get("owner_mission_id") or mission_id or ""), exc)

    record_decision = record_reconciliation_decision

    def create_canonical_handoff(self, value: CanonicalHandoffLinkage | Mapping[str, Any], *, mission_id: str | None = None, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        try:
            record = value if isinstance(value, CanonicalHandoffLinkage) else _provisional(CanonicalHandoffLinkage, value, mission_id=mission_id, actor=actor)
            current = self.state(record.owner_mission_id).handoff(record.handoff_id)
            if current is not None:
                # Handoff identity is stable across state revisions; creation only duplicates READY.
                return self._execute(record=record, command_type=R4_7_CREATE_CANONICAL_HANDOFF, key=f"handoff:{record.handoff_id}", payload_key="handoff", current=current, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)
            return self._execute(record=record, command_type=R4_7_CREATE_CANONICAL_HANDOFF, key=f"handoff:{record.handoff_id}", payload_key="handoff", expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("handoff_id") or ""), str(raw.get("owner_mission_id") or mission_id or ""), exc)

    create_handoff = create_canonical_handoff

    def submit_canonical_handoff(self, handoff_id: str, handoff_digest: str, *, mission_id: str, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        command_identifier = command_id or f"r4.7:submit-handoff:{handoff_id}"
        try:
            current = self.state(mission_id).handoff(handoff_id)
            if current is None:
                raise R47Error(R47_REFERENCE_INVALID, "handoff does not exist")
            result = self._runtime.execute({"command_id": command_identifier, "type": R4_7_SUBMIT_CANONICAL_HANDOFF, "mission_id": mission_id, "session_id": None, "expected_seq": self._runtime.get_head_seq(mission_id) if expected_seq is None else expected_seq, "actor": (actor or self.actor).to_dict(), "payload": {"handoff": {"handoff_id": handoff_id, "handoff_digest": handoff_digest}}, "idempotency_key": f"r4.7:submit:{handoff_id}:{handoff_digest}", "correlation_id": correlation_id or current.correlation_id, "schema_version": SCHEMA_VERSION})
            entity = self.state(mission_id).handoff(handoff_id) if result.ok else None
            return R47OperationResult(result, entity)
        except Exception as exc:
            return self._error(command_identifier, mission_id, exc)

    submit_handoff = submit_canonical_handoff

    def record_handoff(self, value: CanonicalHandoffLinkage | Mapping[str, Any], *, mission_id: str | None = None, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        """Append the independent terminal handoff revision before its receipt."""
        try:
            record = value if isinstance(value, CanonicalHandoffLinkage) else _provisional(CanonicalHandoffLinkage, value, mission_id=mission_id, actor=actor)
            current = self.state(record.owner_mission_id).handoff(record.handoff_id)
            if current is None:
                raise R47Error(R47_REFERENCE_INVALID, "handoff does not exist")
            command_identifier = command_id or f"r4.7:complete-handoff:{record.handoff_id}:{current.record_digest}"
            if current.state is HandoffState.COMPLETED:
                if self._same_record(record, current):
                    return R47OperationResult(CommandResult("DUPLICATE", command_identifier, record.owner_mission_id, duplicate_of=command_identifier, first_seq=current.created_seq, last_seq=current.created_seq), current)
                raise R47Error(R47_IDENTITY_CONFLICT, "completed handoff owns a different terminal digest")
            if current.state is not HandoffState.SUBMITTED:
                raise R47Error(R47_COMMAND_INVALID, "only SUBMITTED handoffs may be completed")
            if record.state is not HandoffState.COMPLETED or record.handoff_id != current.handoff_id:
                raise R47Error(R47_COMMAND_INVALID, "record_handoff requires a COMPLETED revision for the current handoff")
            result = self._runtime.execute(
                {
                    "command_id": command_identifier,
                    "type": R4_7_SUBMIT_CANONICAL_HANDOFF,
                    "mission_id": record.owner_mission_id,
                    "session_id": None,
                    "expected_seq": self._runtime.get_head_seq(record.owner_mission_id) if expected_seq is None else expected_seq,
                    "actor": (actor or self.actor).to_dict(),
                    "payload": {"handoff": {"handoff_id": record.handoff_id, "handoff_digest": current.record_digest, "handoff": record.to_dict()}},
                    "idempotency_key": f"r4.7:complete:{record.handoff_id}:{current.record_digest}",
                    "correlation_id": correlation_id or current.correlation_id,
                    "schema_version": SCHEMA_VERSION,
                }
            )
            entity = self.state(record.owner_mission_id).handoff(record.handoff_id) if result.ok else None
            return R47OperationResult(result, entity)
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("handoff_id") or ""), str(raw.get("owner_mission_id") or mission_id or ""), exc)

    complete_handoff = record_handoff

    def record_reconciliation_receipt(self, value: ReconciliationReceipt | Mapping[str, Any], *, mission_id: str | None = None, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        try:
            record = value if isinstance(value, ReconciliationReceipt) else _provisional(ReconciliationReceipt, value, mission_id=mission_id, actor=actor)
            state = self.state(record.owner_mission_id)
            existing = state.receipt(record.receipt_id)
            if existing is not None:
                return self._execute(record=record, command_type=R4_7_RECORD_RECONCILIATION_RECEIPT, key=f"receipt:{record.receipt_id}", payload_key="receipt", current=existing, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)
            handoff_id = str((record.handoff_ref or {}).get("object_id", "")) if isinstance(record.handoff_ref, Mapping) else ""
            same_handoff = [item for item in state.receipts if isinstance(item.handoff_ref, Mapping) and item.handoff_ref.get("object_id") == handoff_id]
            for prior in same_handoff:
                same_result = (prior.authority_operation_id, prior.canonical_result_ref, prior.canonical_result_digest) == (record.authority_operation_id, record.canonical_result_ref, record.canonical_result_digest)
                if same_result:
                    return R47OperationResult(CommandResult("DUPLICATE", command_id or record.receipt_id, record.owner_mission_id, duplicate_of=prior.receipt_id, first_seq=prior.created_seq, last_seq=prior.created_seq), prior)
                return self._error(command_id or record.receipt_id, record.owner_mission_id, R47Error(R47_CONFLICT, "same handoff has a different authority result"))
            return self._execute(record=record, command_type=R4_7_RECORD_RECONCILIATION_RECEIPT, key=f"receipt:{record.receipt_id}", payload_key="receipt", expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("receipt_id") or ""), str(raw.get("owner_mission_id") or mission_id or ""), exc)

    def record_receipt(self, value: ReconciliationReceipt | Mapping[str, Any], *, mission_id: str | None = None, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R47OperationResult:
        """Compatibility alias; canonical callers use record_reconciliation_receipt.

        Older direct callers supplied a receipt against the SUBMITTED revision.
        Preserve that call shape by first recording the explicit terminal revision,
        then rebuilding the receipt against its digest before entering the strict
        receipt command path.
        """
        try:
            record = value if isinstance(value, ReconciliationReceipt) else _provisional(ReconciliationReceipt, value, mission_id=mission_id, actor=actor)
            handoff_id = str((record.handoff_ref or {}).get("object_id", "")) if isinstance(record.handoff_ref, Mapping) else ""
            current = self.state(record.owner_mission_id).handoff(handoff_id)
            if current is not None and current.state is HandoffState.SUBMITTED and record.handoff_digest == current.record_digest:
                terminal_raw = current.to_dict()
                terminal_raw.update(
                    {
                        "state": HandoffState.COMPLETED.value,
                        "authority_result_ref": record.canonical_result_ref,
                        "authority_result_digest": record.canonical_result_digest,
                        "record_digest": None,
                    }
                )
                terminal_result = self.record_handoff(
                    CanonicalHandoffLinkage.from_dict(terminal_raw),
                    expected_seq=expected_seq,
                    actor=actor,
                )
                if not terminal_result.ok or terminal_result.entity is None:
                    return terminal_result
                terminal = terminal_result.entity
                migrated = replace(
                    record,
                    receipt_id=receipt_id_for(
                        terminal.handoff_id,
                        terminal.record_digest,
                        record.authority_operation_id,
                        record.canonical_result_ref,
                        record.canonical_result_digest,
                    ),
                    handoff_ref={"object_id": terminal.handoff_id, "source_digest": terminal.record_digest},
                    handoff_digest=terminal.record_digest,
                    record_digest=None,
                )
                return self.record_reconciliation_receipt(migrated, expected_seq=None, command_id=command_id, correlation_id=correlation_id, actor=actor)
        except Exception as exc:
            raw = _raw(value)
            return self._error(str(raw.get("receipt_id") or ""), str(raw.get("owner_mission_id") or mission_id or ""), exc)
        return self.record_reconciliation_receipt(value, mission_id=mission_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)

    def rebuild_projections(self, mission_id: str | None = None) -> dict[str, Any]:
        # Delegates to RuntimeService's existing EventStore/rebuild path; legacy source is never scanned.
        return self._runtime.rebuild_projections(mission_id)


def compose_r4_7_runtime(db_path: str | Path, base_extensions: Iterable[Any] = (), *, clock: Any = None, failure_injector: Any = None) -> RuntimeService:
    extensions = tuple(base_extensions)
    if any(getattr(item, "extension_id", None) == EXTENSION_ID for item in extensions):
        raise R47Error(R47_COMMAND_INVALID, "R4.7 extension is already present in explicit composition")
    return RuntimeService(db_path, clock=clock, failure_injector=failure_injector, extensions=extensions + (r4_7_extension(),))


__all__ = ["R47ApplicationService", "compose_r4_7_runtime"]
