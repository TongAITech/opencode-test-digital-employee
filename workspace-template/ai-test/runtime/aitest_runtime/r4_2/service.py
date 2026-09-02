from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService, RuntimeError as DurableRuntimeError, canonical_sha256
from aitest_runtime.r4_1 import R41ApplicationService
from aitest_runtime.r4_1.contracts import TypedReference, selection_revision_digest

from .contracts import (
    ASSESSMENT_POLICY_VERSION,
    BridgeStatus,
    ContinuousTestTrigger,
    ImpactAssessment,
    ImpactDecision,
    PlanRevisionBridgeReceipt,
    PlanRevisionIntent,
    R42State,
    R4_2_LINK_SELECTION_REVISION,
    R4_2_RECORD_IMPACT_ASSESSMENT,
    R4_2_RECORD_R2_BRIDGE_RESULT,
    R4_2_RECORD_TRIGGER_RECEIPT,
    R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE,
    SelectionRevisionLink,
    SourceEligibility,
    TriggerKind,
    build_impact_assessment,
    bridge_receipt_id_for,
    command_id_for,
    plan_revision_intent_digest,
    ref_for,
    selection_link_digest,
)
from .errors import (
    ARCHITECTURE_BOUNDARY_VIOLATION,
    IMPACT_INPUT_INVALID,
    INVALID_TRIGGER,
    R2_BRIDGE_REJECTED,
    R2_BRIDGE_UNAVAILABLE,
    R2_RESULT_CONFLICT,
    R42Error,
    SELECTION_REVISION_CONFLICT,
    SOURCE_STALE,
    SOURCE_UNAVAILABLE,
    TRIGGER_SOURCE_CONFLICT,
)
from .extension import r4_2_extension
from .r2_bridge import build_planner_input, invoke_planner, map_planner_outcome, planner_input_digest
from .source_adapters import SourceObservation, normalize_source_observation


def _source_position(revision: int, cursor: str | int | None) -> tuple[int, int, str]:
    if isinstance(cursor, int) and not isinstance(cursor, bool):
        return revision, 0, str(cursor)
    if isinstance(cursor, str):
        return revision, 1, cursor
    return revision, 2, ""


@dataclass(frozen=True)
class R42OperationResult:
    command_result: CommandResult
    entity: Any = None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code

    @property
    def first_seq(self) -> int | None:
        return self.command_result.first_seq

    @property
    def last_seq(self) -> int | None:
        return self.command_result.last_seq

    @property
    def duplicate_of(self) -> str | None:
        return self.command_result.duplicate_of

    def to_dict(self) -> dict[str, Any]:
        value = self.command_result.to_dict()
        value["entity"] = self.entity.to_dict() if hasattr(self.entity, "to_dict") else self.entity
        return value


@dataclass(frozen=True)
class R42ContinuationResult:
    assessment: ImpactAssessment | None = None
    selection_link: SelectionRevisionLink | None = None
    plan_revision_intent: PlanRevisionIntent | None = None
    bridge_receipt: PlanRevisionBridgeReceipt | None = None
    operations: tuple[R42OperationResult, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and all(item.ok for item in self.operations)

    @property
    def outcome(self) -> str:
        if self.bridge_receipt is not None:
            return self.bridge_receipt.bridge_status.value
        if self.selection_link is not None:
            return "SELECTION_LINKED"
        return "NO_MATERIAL_IMPACT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment": self.assessment.to_dict() if self.assessment else None,
            "selection_link": self.selection_link.to_dict() if self.selection_link else None,
            "plan_revision_intent": self.plan_revision_intent.to_dict() if self.plan_revision_intent else None,
            "bridge_receipt": self.bridge_receipt.to_dict() if self.bridge_receipt else None,
            "operations": [item.to_dict() for item in self.operations],
            "error": self.error,
        }


def compose_r4_2_runtime(
    db_path: str | Path,
    base_extensions: Iterable[Any] = (),
    *,
    clock: Any = None,
    failure_injector: Any = None,
) -> RuntimeService:
    """Explicit composition helper; the caller still owns the one RuntimeService."""
    extensions = tuple(base_extensions)
    if any(getattr(item, "extension_id", None) == r4_2_extension().extension_id for item in extensions):
        raise R42Error(ARCHITECTURE_BOUNDARY_VIOLATION, "R4.2 extension is already present in explicit composition")
    return RuntimeService(Path(db_path), clock=clock, failure_injector=failure_injector, extensions=extensions + (r4_2_extension(),))


class R42ApplicationService:
    """R4.2 application boundary over the injected shared runtime and frozen ports."""

    def __init__(
        self,
        runtime_service: RuntimeService,
        r41_service: R41ApplicationService,
        planner: Any,
        *,
        actor: ActorRef | None = None,
    ) -> None:
        if not hasattr(runtime_service, "execute") or not hasattr(runtime_service, "get_composed_state"):
            raise R42Error(ARCHITECTURE_BOUNDARY_VIOLATION, "R4.2 requires the existing RuntimeService")
        if not isinstance(r41_service, R41ApplicationService):
            raise R42Error(ARCHITECTURE_BOUNDARY_VIOLATION, "R4.2 requires the frozen R41ApplicationService")
        if r41_service.runtime_service is not runtime_service:
            raise R42Error(ARCHITECTURE_BOUNDARY_VIOLATION, "R4.1 service must share the existing RuntimeService")
        runtime_service.extension_registry.manifest(r4_2_extension().extension_id)
        if planner is None:
            raise R42Error(R2_BRIDGE_UNAVAILABLE, "PlannerOrchestrator boundary is unavailable")
        self.runtime_service = runtime_service
        self.runtime = runtime_service
        self.r41_service = r41_service
        self.planner = planner
        self.actor = actor or ActorRef("SYSTEM", "r4.2")

    @property
    def extension_id(self) -> str:
        return r4_2_extension().extension_id

    def state(self, mission_id: str) -> R42State:
        composed = self.runtime_service.get_composed_state(mission_id)
        value = composed.extension_state(self.extension_id)
        if not isinstance(value, R42State):
            raise R42Error(ARCHITECTURE_BOUNDARY_VIOLATION, "R4.2 extension state is invalid")
        return value

    def _rejected(self, mission_id: str, code: str, message: str, *, command_id: str = "") -> R42OperationResult:
        return R42OperationResult(CommandResult("REJECTED", command_id, mission_id, error=DurableRuntimeError(code, message)))

    def _execute(self, command_type: str, mission_id: str, entity_id: str, payload: Mapping[str, Any], *, expected_seq: int | None = None, correlation_id: str | None = None, idempotency_key: str | None = None) -> R42OperationResult:
        command_id = command_id_for(command_type, entity_id)
        result = self.runtime_service.execute({
            "command_id": command_id,
            "type": command_type,
            "mission_id": mission_id,
            "session_id": None,
            "expected_seq": self.runtime_service.get_head_seq(mission_id) if expected_seq is None else expected_seq,
            "actor": self.actor.to_dict(),
            "payload": dict(payload),
            "idempotency_key": idempotency_key or command_id,
            "correlation_id": correlation_id or command_id,
            "schema_version": 1,
        })
        entity = None
        if result.ok:
            current = self.state(mission_id)
            if command_type == R4_2_RECORD_TRIGGER_RECEIPT:
                entity = current.trigger(entity_id)
            elif command_type == R4_2_RECORD_IMPACT_ASSESSMENT:
                entity = current.assessment(entity_id)
            elif command_type == R4_2_LINK_SELECTION_REVISION:
                entity = current.selection_link(entity_id)
            else:
                entity = current.bridge_receipt(entity_id)
        return R42OperationResult(result, entity)

    def _current_campaign(self, mission_id: str, campaign_id: str) -> Any:
        r41_state = self.r41_service.state(mission_id)
        campaign = r41_state.campaign(campaign_id)
        if campaign is None:
            raise R42Error("NOT_FOUND", f"R4.1 TestCampaign is unavailable: {campaign_id}")
        return campaign

    def record_trigger(
        self,
        trigger: ContinuousTestTrigger | SourceObservation | TypedReference | Mapping[str, Any],
        *,
        stream_owner_mission_id: str | None = None,
        quality_version_ref: TypedReference | Mapping[str, Any] | None = None,
        campaign_ref: TypedReference | Mapping[str, Any] | None = None,
        trigger_kind: TriggerKind | str | None = None,
        received_at: str | None = None,
        correlation_id: str | None = None,
        current_selection_ref: TypedReference | Mapping[str, Any] | None = None,
        open_epoch: str | int = 0,
        expected_seq: int | None = None,
    ) -> R42OperationResult:
        try:
            if isinstance(trigger, ContinuousTestTrigger):
                value = trigger
            else:
                if stream_owner_mission_id is None or quality_version_ref is None or campaign_ref is None or trigger_kind is None or received_at is None or correlation_id is None:
                    raise R42Error(INVALID_TRIGGER, "normalization metadata is required for a transient source observation")
                value = normalize_source_observation(
                    trigger,
                    stream_owner_mission_id=stream_owner_mission_id,
                    quality_version_ref=quality_version_ref,
                    campaign_ref=campaign_ref,
                    trigger_kind=trigger_kind,
                    received_at=received_at,
                    correlation_id=correlation_id,
                    current_selection_ref=current_selection_ref,
                    open_epoch=open_epoch,
                )
            mission_id = value.stream_owner_mission_id
            current = self.state(mission_id)
            existing = current.trigger(value.trigger_id)
            if existing is not None and existing.trigger_digest != value.trigger_digest:
                return self._rejected(mission_id, TRIGGER_SOURCE_CONFLICT, "same trigger identity has a different source digest", command_id=command_id_for(R4_2_RECORD_TRIGGER_RECEIPT, value.trigger_id))
            if existing is not None:
                event = next((item for item in reversed(self.runtime_service.list_events(mission_id)) if item.event_type == "r4.2.trigger_recorded.v1" and item.entity_id == value.trigger_id), None)
                return R42OperationResult(
                    CommandResult("DUPLICATE", command_id_for(R4_2_RECORD_TRIGGER_RECEIPT, value.trigger_id), mission_id,
                                  first_seq=event.seq if event else None, last_seq=event.seq if event else None,
                                  duplicate_of=command_id_for(R4_2_RECORD_TRIGGER_RECEIPT, value.trigger_id)),
                    existing,
                )
            for prior in current.triggers:
                if prior.source_stream_key == value.source_stream_key and _source_position(prior.source_revision, prior.source_cursor) > _source_position(value.source_revision, value.source_cursor) and value.source_eligibility is SourceEligibility.ELIGIBLE:
                    return self._rejected(mission_id, SOURCE_STALE, "trigger source revision is older than the durable source cursor", command_id=command_id_for(R4_2_RECORD_TRIGGER_RECEIPT, value.trigger_id))
            result = self._execute(R4_2_RECORD_TRIGGER_RECEIPT, mission_id, value.trigger_id, value.to_dict(), expected_seq=expected_seq, correlation_id=value.correlation_id, idempotency_key=value.dedupe_key)
            return result
        except R42Error as exc:
            mission_id = stream_owner_mission_id or ""
            return self._rejected(mission_id, exc.code, exc.message)
        except DurableRuntimeError as exc:
            return self._rejected(stream_owner_mission_id or "", exc.code, exc.message)

    def record_impact_assessment(
        self,
        assessment: ImpactAssessment | None = None,
        *,
        stream_owner_mission_id: str | None = None,
        quality_version_ref: TypedReference | Mapping[str, Any] | None = None,
        campaign_ref: TypedReference | Mapping[str, Any] | None = None,
        trigger_refs: Iterable[TypedReference | Mapping[str, Any]] = (),
        r3_requirement_coverage_refs: Iterable[Any] = (),
        r3_change_impact_refs: Iterable[Any] = (),
        coalescing_key: str | None = None,
        assessment_policy_version: str = ASSESSMENT_POLICY_VERSION,
        created_at: str | None = None,
        correlation_id: str | None = None,
        expected_seq: int | None = None,
    ) -> R42OperationResult:
        try:
            if assessment is None:
                if stream_owner_mission_id is None or quality_version_ref is None or campaign_ref is None or created_at is None or correlation_id is None:
                    raise R42Error(IMPACT_INPUT_INVALID, "assessment construction metadata is incomplete")
                requested = tuple(trigger_refs)
                state = self.state(stream_owner_mission_id)
                durable_triggers = []
                for item in requested:
                    reference = item if isinstance(item, TypedReference) else TypedReference.from_dict(item)
                    trigger = state.trigger(reference.object_id)
                    if trigger is None or trigger.trigger_digest != reference.source_digest:
                        raise R42Error(IMPACT_INPUT_INVALID, "trigger_refs must identify exact durable trigger receipts")
                    if trigger.source_eligibility is not SourceEligibility.ELIGIBLE:
                        continue
                    durable_triggers.append(trigger)
                if not durable_triggers:
                    raise R42Error(SOURCE_UNAVAILABLE, "no eligible trigger receipts are available for this assessment")
                if coalescing_key is None:
                    coalescing_key = durable_triggers[0].coalescing_key
                if any(item.coalescing_key != coalescing_key for item in durable_triggers):
                    raise R42Error(IMPACT_INPUT_INVALID, "trigger receipts do not share one deterministic coalescing key")
                assessment = build_impact_assessment(
                    stream_owner_mission_id=stream_owner_mission_id,
                    quality_version_ref=quality_version_ref,
                    campaign_ref=campaign_ref,
                    trigger_refs=(ref_for("CONTINUOUS_TEST_TRIGGER", item.trigger_id, digest=item.trigger_digest, cursor=item.source_cursor, observed_at=item.received_at, correlation_id=item.correlation_id, origin="r4.2.trigger") for item in durable_triggers),
                    r3_requirement_coverage_refs=r3_requirement_coverage_refs,
                    r3_change_impact_refs=r3_change_impact_refs,
                    coalescing_key=coalescing_key,
                    source_digests=(item.source_ref.source_digest for item in durable_triggers),
                    assessment_policy_version=assessment_policy_version,
                    created_at=created_at,
                    correlation_id=correlation_id,
                )
            result = self._execute(R4_2_RECORD_IMPACT_ASSESSMENT, assessment.stream_owner_mission_id, assessment.impact_assessment_id, assessment.to_dict(), expected_seq=expected_seq, correlation_id=assessment.correlation_id, idempotency_key=assessment.impact_assessment_id)
            return result
        except R42Error as exc:
            return self._rejected(stream_owner_mission_id or (assessment.stream_owner_mission_id if assessment else ""), exc.code, exc.message)
        except DurableRuntimeError as exc:
            return self._rejected(stream_owner_mission_id or (assessment.stream_owner_mission_id if assessment else ""), exc.code, exc.message)

    def continue_selection_handoff(self, assessment_id: str, *, expected_seq: int | None = None) -> R42ContinuationResult:
        assessment = self.state(self._mission_for_assessment(assessment_id)).assessment(assessment_id)
        if assessment is None:
            return R42ContinuationResult(error="NOT_FOUND")
        if assessment.decision is ImpactDecision.NO_MATERIAL_IMPACT:
            return R42ContinuationResult(assessment=assessment)
        existing = next((item for item in self.state(assessment.stream_owner_mission_id).selection_links if item.impact_assessment_ref.object_id == assessment_id), None)
        if existing is not None:
            return R42ContinuationResult(assessment=assessment, selection_link=existing)
        try:
            campaign = self._current_campaign(assessment.stream_owner_mission_id, assessment.campaign_ref.object_id)
            supersedes = campaign.current_selection_revision_ref
            selected = tuple(assessment.affected_refs)
            source_refs = tuple(dict.fromkeys(assessment.trigger_refs + assessment.r3_requirement_coverage_refs + assessment.r3_change_impact_refs))
            payload: dict[str, Any] = {
                "selection_revision_id": f"r4.2:selection:{assessment.impact_assessment_id}",
                "stream_owner_mission_id": assessment.stream_owner_mission_id,
                "campaign_ref": assessment.campaign_ref.to_dict(),
                "supersedes_revision_ref": supersedes.to_dict() if supersedes else None,
                "selected_input_refs": [item.to_dict() for item in selected],
                "excluded_scope": {"refs": [item.to_dict() for item in assessment.unaffected_refs]},
                "unknown_scope": {"refs": [item.to_dict() for item in assessment.unknown_refs + assessment.unmapped_unresolved_refs]},
                "blocked_scope": {"refs": [item.to_dict() for item in assessment.blocked_refs]},
                "source_refs": [item.to_dict() for item in source_refs],
                "revision_digest": "0" * 64,
            }
            payload["revision_digest"] = selection_revision_digest(payload)
            r41_result = self.r41_service.record_campaign_selection_revision(payload, expected_seq=self.runtime_service.get_head_seq(assessment.stream_owner_mission_id) if expected_seq is None else expected_seq, correlation_id=assessment.correlation_id)
            if not r41_result.ok:
                return R42ContinuationResult(assessment=assessment, operations=(R42OperationResult(r41_result.command_result, r41_result.entity),), error=SELECTION_REVISION_CONFLICT)
            selection = r41_result.entity
            if selection is None:
                return R42ContinuationResult(assessment=assessment, error=SELECTION_REVISION_CONFLICT)
            selection_ref = ref_for("CAMPAIGN_SELECTION_REVISION", selection.selection_revision_id, digest=selection.revision_digest, cursor=r41_result.last_seq, observed_at=selection.created_at, correlation_id=selection.correlation_id, origin="r4.1.campaign_selection_revision")
            assessment_ref = ref_for("IMPACT_ASSESSMENT", assessment.impact_assessment_id, digest=assessment.assessment_digest, cursor=assessment.created_seq, observed_at=assessment.created_at, correlation_id=assessment.correlation_id)
            link_values: dict[str, Any] = {
                "selection_link_id": f"r4.2:selection-link:{assessment.impact_assessment_id}",
                "impact_assessment_ref": assessment_ref,
                "campaign_ref": assessment.campaign_ref,
                "r4_1_selection_revision_ref": selection_ref,
                "selection_revision_digest": selection.revision_digest,
                "correlation_id": assessment.correlation_id,
            }
            link_values["link_digest"] = selection_link_digest(link_values)
            link = SelectionRevisionLink(created_seq=1, created_at=selection.created_at, **link_values)
            operation = self._execute(R4_2_LINK_SELECTION_REVISION, assessment.stream_owner_mission_id, link.selection_link_id, link.to_dict(), correlation_id=assessment.correlation_id, idempotency_key=link.selection_link_id)
            return R42ContinuationResult(assessment=assessment, selection_link=operation.entity if operation.entity else link, operations=(operation,))
        except R42Error as exc:
            return R42ContinuationResult(assessment=assessment, error=exc.code)
        except DurableRuntimeError as exc:
            return R42ContinuationResult(assessment=assessment, error=SELECTION_REVISION_CONFLICT if exc.code in {"EXPECTED_SEQ_MISMATCH", "R4_1_SUPERSESSION_INVALID"} else exc.code)

    def _mission_for_assessment(self, assessment_id: str) -> str:
        # The shared stream is the lookup authority; no second index or store is created.
        for mission in self._known_missions():
            try:
                if self.state(mission).assessment(assessment_id) is not None:
                    return mission
            except Exception:
                continue
        raise R42Error("NOT_FOUND", f"ImpactAssessment is unavailable: {assessment_id}")

    def _known_missions(self) -> tuple[str, ...]:
        conn = None
        try:
            from aitest_runtime.durable_core.schema import connect
            conn = connect(self.runtime_service.db_path)
            rows = conn.execute("SELECT DISTINCT mission_id FROM events ORDER BY mission_id").fetchall()
            return tuple(str(row[0]) for row in rows)
        finally:
            if conn is not None:
                conn.close()

    def continue_r2_bridge(self, assessment_id: str, *, planner_input: Any = None, expected_seq: int | None = None) -> R42ContinuationResult:
        mission_id = self._mission_for_assessment(assessment_id)
        assessment = self.state(mission_id).assessment(assessment_id)
        if assessment is None:
            return R42ContinuationResult(error="NOT_FOUND")
        if assessment.decision is not ImpactDecision.SELECTION_REVISION_REQUIRED:
            return R42ContinuationResult(assessment=assessment)
        handoff = self.continue_selection_handoff(assessment_id, expected_seq=expected_seq)
        if handoff.error or handoff.selection_link is None:
            return handoff
        state = self.state(mission_id)
        existing = next((item for item in state.bridge_receipts if item.impact_assessment_ref.object_id == assessment_id), None)
        if existing is not None and existing.bridge_status is not BridgeStatus.R2_REQUESTED:
            existing_intent = state.intent(existing.plan_revision_intent_ref.object_id)
            if planner_input is not None and existing_intent is not None:
                candidate = build_planner_input(self.runtime_service, mission_id=mission_id, planner_request_id=existing_intent.planner_request_id, planner_input=planner_input)
                if planner_input_digest(candidate) != existing_intent.r2_planner_input_digest:
                    return R42ContinuationResult(assessment=assessment, selection_link=handoff.selection_link, plan_revision_intent=existing_intent, bridge_receipt=existing, error=R2_RESULT_CONFLICT)
            return R42ContinuationResult(assessment=assessment, selection_link=handoff.selection_link, plan_revision_intent=existing_intent, bridge_receipt=existing)
        intent = state.intent(existing.plan_revision_intent_ref.object_id) if existing is not None else None
        try:
            if intent is None:
                planner_request_id = f"r4.2:planner:{assessment_id}:{handoff.selection_link.r4_1_selection_revision_ref.object_id}"
                item = build_planner_input(self.runtime_service, mission_id=mission_id, planner_request_id=planner_request_id, planner_input=planner_input, planning_cursor=self.runtime_service.get_head_seq(mission_id) + 1)
                goal_ref = ref_for("R2_GOAL", item.active_goal_id, digest=item.goal_definition_digest, cursor=item.planning_cursor, observed_at=assessment.created_at, correlation_id=assessment.correlation_id, origin="r2.goal")
                scope_ref = ref_for("R2_SCOPE", f"scope:{item.scope_digest}", digest=item.scope_digest if len(item.scope_digest) == 64 else canonical_sha256(item.scope_digest), cursor=item.planning_cursor, observed_at=assessment.created_at, correlation_id=assessment.correlation_id, origin="r2.scope")
                mission_ref = ref_for("MISSION", mission_id, digest=canonical_sha256({"mission_id": mission_id}), cursor=item.planning_cursor, observed_at=assessment.created_at, correlation_id=assessment.correlation_id, origin="r2.mission")
                intent_values: dict[str, Any] = {
                    "plan_revision_intent_id": f"r4.2:intent:{assessment_id}",
                    "stream_owner_mission_id": mission_id,
                    "campaign_ref": assessment.campaign_ref,
                    "campaign_selection_revision_ref": handoff.selection_link.r4_1_selection_revision_ref,
                    "impact_assessment_ref": ref_for("IMPACT_ASSESSMENT", assessment_id, digest=assessment.assessment_digest, cursor=assessment.created_seq, observed_at=assessment.created_at, correlation_id=assessment.correlation_id),
                    "target_r2_mission_ref": mission_ref,
                    "goal_input_ref": goal_ref,
                    "scope_input_ref": scope_ref,
                    "planner_request_id": planner_request_id,
                    "r2_planner_input_digest": planner_input_digest(item),
                    "correlation_id": assessment.correlation_id,
                    "idempotency_key": planner_request_id,
                    "requested_at": assessment.created_at,
                    "provenance_refs": (assessment.trigger_refs + (handoff.selection_link.r4_1_selection_revision_ref,)),
                }
                intent_values["r4_intent_digest"] = plan_revision_intent_digest(intent_values)
                intent = PlanRevisionIntent(**intent_values)
                receipt_id = bridge_receipt_id_for(assessment_id, handoff.selection_link.r4_1_selection_revision_ref.object_id)
                request_digest = canonical_sha256({"bridge_receipt_id": receipt_id, "planner_request_id": planner_request_id, "r2_planner_input_digest": intent.r2_planner_input_digest, "status": BridgeStatus.R2_REQUESTED.value})
                receipt = PlanRevisionBridgeReceipt(
                    bridge_receipt_id=receipt_id, stream_owner_mission_id=mission_id, campaign_ref=assessment.campaign_ref,
                    impact_assessment_ref=intent.impact_assessment_ref, selection_revision_ref=handoff.selection_link.r4_1_selection_revision_ref,
                    plan_revision_intent_ref=ref_for("PLAN_REVISION_INTENT", intent.plan_revision_intent_id, digest=intent.r4_intent_digest, cursor=None, observed_at=assessment.created_at, correlation_id=assessment.correlation_id, origin="r4.2.intent"),
                    planner_request_id=planner_request_id, r2_planner_input_digest=intent.r2_planner_input_digest, r2_outcome="REQUESTED",
                    r2_plan_ref=None, r2_revision_ref=None, r2_content_hash=None, r2_result_digest=request_digest, bridge_status=BridgeStatus.R2_REQUESTED,
                    correlation_id=assessment.correlation_id, created_seq=1, created_at=assessment.created_at,
                )
                request = self._execute(R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE, mission_id, receipt.bridge_receipt_id, {"plan_revision_intent": intent.to_dict(), "bridge_receipt": receipt.to_dict()}, correlation_id=assessment.correlation_id, idempotency_key=receipt.bridge_receipt_id)
                if not request.ok and request.error_code not in {"IDEMPOTENCY_CONFLICT"}:
                    return R42ContinuationResult(assessment=assessment, selection_link=handoff.selection_link, plan_revision_intent=intent, operations=(request,), error=request.error_code)
                existing_receipt = self.state(mission_id).bridge_receipt(receipt.bridge_receipt_id)
            else:
                receipt = existing
                item = build_planner_input(self.runtime_service, mission_id=mission_id, planner_request_id=intent.planner_request_id, planner_input=planner_input, planning_cursor=intent.goal_input_ref.source_cursor if planner_input is None and isinstance(intent.goal_input_ref.source_cursor, int) else self.runtime_service.get_head_seq(mission_id))
                if planner_input is not None and planner_input_digest(item) != intent.r2_planner_input_digest:
                    conflict = PlanRevisionBridgeReceipt(
                        bridge_receipt_id=receipt.bridge_receipt_id,
                        stream_owner_mission_id=receipt.stream_owner_mission_id,
                        campaign_ref=receipt.campaign_ref,
                        impact_assessment_ref=receipt.impact_assessment_ref,
                        selection_revision_ref=receipt.selection_revision_ref,
                        plan_revision_intent_ref=receipt.plan_revision_intent_ref,
                        planner_request_id=receipt.planner_request_id,
                        r2_planner_input_digest=receipt.r2_planner_input_digest,
                        r2_outcome="RESULT_CONFLICT",
                        r2_plan_ref=None,
                        r2_revision_ref=None,
                        r2_content_hash=None,
                        r2_result_digest=canonical_sha256({
                            "planner_request_id": receipt.planner_request_id,
                            "expected_input_digest": receipt.r2_planner_input_digest,
                            "received_input_digest": planner_input_digest(item),
                            "outcome": "RESULT_CONFLICT",
                        }),
                        bridge_status=BridgeStatus.R2_RESULT_CONFLICT,
                        correlation_id=receipt.correlation_id,
                        created_seq=receipt.created_seq,
                        created_at=receipt.created_at,
                    )
                    operation = self._execute(
                        R4_2_RECORD_R2_BRIDGE_RESULT,
                        mission_id,
                        conflict.bridge_receipt_id,
                        {"bridge_receipt": conflict.to_dict()},
                        correlation_id=conflict.correlation_id,
                        idempotency_key=f"{conflict.bridge_receipt_id}:result",
                    )
                    return R42ContinuationResult(
                        assessment=assessment,
                        selection_link=handoff.selection_link,
                        plan_revision_intent=intent,
                        bridge_receipt=operation.entity if operation.entity else conflict,
                        operations=(operation,),
                        error=R2_RESULT_CONFLICT,
                    )
            result = invoke_planner(self.planner, item)
            outcome = map_planner_outcome(result, mission_id=mission_id, planner_input=item, observed_at=assessment.created_at, correlation_id=assessment.correlation_id)
        except R42Error as exc:
            if 'receipt' in locals() and receipt is not None and exc.code == R2_BRIDGE_UNAVAILABLE:
                outcome = {"r2_outcome": "UNAVAILABLE", "r2_plan_ref": None, "r2_revision_ref": None, "r2_content_hash": None, "bridge_status": BridgeStatus.R2_UNAVAILABLE, "r2_result_digest": canonical_sha256({"error": exc.code, "planner_request_id": receipt.planner_request_id})}
            elif 'receipt' in locals() and receipt is not None and exc.code == R2_BRIDGE_REJECTED:
                outcome = {"r2_outcome": "REJECTED", "r2_plan_ref": None, "r2_revision_ref": None, "r2_content_hash": None, "bridge_status": BridgeStatus.R2_REJECTED, "r2_result_digest": canonical_sha256({"error": exc.code, "planner_request_id": receipt.planner_request_id})}
            else:
                return R42ContinuationResult(assessment=assessment, selection_link=handoff.selection_link, plan_revision_intent=intent if 'intent' in locals() else None, error=exc.code)
        except Exception as exc:
            if 'receipt' not in locals() or receipt is None:
                return R42ContinuationResult(assessment=assessment, selection_link=handoff.selection_link, plan_revision_intent=intent if 'intent' in locals() else None, error=R2_BRIDGE_UNAVAILABLE)
            outcome = {"r2_outcome": "UNAVAILABLE", "r2_plan_ref": None, "r2_revision_ref": None, "r2_content_hash": None, "bridge_status": BridgeStatus.R2_UNAVAILABLE, "r2_result_digest": canonical_sha256({"error": type(exc).__name__, "planner_request_id": receipt.planner_request_id})}
        final = PlanRevisionBridgeReceipt(
            bridge_receipt_id=receipt.bridge_receipt_id, stream_owner_mission_id=receipt.stream_owner_mission_id, campaign_ref=receipt.campaign_ref,
            impact_assessment_ref=receipt.impact_assessment_ref, selection_revision_ref=receipt.selection_revision_ref, plan_revision_intent_ref=receipt.plan_revision_intent_ref,
            planner_request_id=receipt.planner_request_id, r2_planner_input_digest=receipt.r2_planner_input_digest, r2_outcome=outcome["r2_outcome"],
            r2_plan_ref=outcome["r2_plan_ref"], r2_revision_ref=outcome["r2_revision_ref"], r2_content_hash=outcome["r2_content_hash"], r2_result_digest=outcome["r2_result_digest"], bridge_status=outcome["bridge_status"], correlation_id=receipt.correlation_id, created_seq=receipt.created_seq, created_at=receipt.created_at,
        )
        operation = self._execute(R4_2_RECORD_R2_BRIDGE_RESULT, mission_id, final.bridge_receipt_id, {"bridge_receipt": final.to_dict()}, correlation_id=final.correlation_id, idempotency_key=f"{final.bridge_receipt_id}:result")
        return R42ContinuationResult(assessment=assessment, selection_link=handoff.selection_link, plan_revision_intent=intent, bridge_receipt=operation.entity if operation.entity else final, operations=(operation,))

    def record_r2_bridge_result(self, receipt: PlanRevisionBridgeReceipt, *, expected_seq: int | None = None) -> R42OperationResult:
        return self._execute(R4_2_RECORD_R2_BRIDGE_RESULT, receipt.stream_owner_mission_id, receipt.bridge_receipt_id, {"bridge_receipt": receipt.to_dict()}, expected_seq=expected_seq, correlation_id=receipt.correlation_id, idempotency_key=f"{receipt.bridge_receipt_id}:result")

    def resume(self, mission_id: str) -> tuple[R42ContinuationResult, ...]:
        results: list[R42ContinuationResult] = []
        for assessment in self.state(mission_id).assessments:
            if assessment.decision is ImpactDecision.SELECTION_REVISION_REQUIRED:
                results.append(self.continue_r2_bridge(assessment.impact_assessment_id))
            elif assessment.decision in {ImpactDecision.BLOCKED, ImpactDecision.INCONCLUSIVE}:
                results.append(self.continue_selection_handoff(assessment.impact_assessment_id))
        return tuple(results)


__all__ = ["R42ApplicationService", "R42ContinuationResult", "R42OperationResult", "compose_r4_2_runtime"]
