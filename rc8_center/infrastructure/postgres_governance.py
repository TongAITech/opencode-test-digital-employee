"""PostgreSQL repositories implementing RC8 governance semantics.

These repositories intentionally mirror the proven JSON fallback invariants so
changing storage cannot weaken truth, append-only history or sufficiency gates.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from rc8_runtime.coverage import CoverageObservation
from rc8_runtime.governance import (
    AttemptRecord,
    AttemptStatus,
    CoverageDimension,
    CoverageMetric,
    FailureOwnership,
    GapRecord,
    GapSeverity,
    GapStatus,
    GapType,
    InvalidationRecord,
    ReleaseDecision,
    ReleaseDecisionRecord,
    StageInstance,
    StageState,
    StatusScope,
    SufficiencyEvaluation,
    SufficiencyResult,
)

from .postgres import (
    AttemptRow,
    CoverageObservationRow,
    GapRow,
    InvalidationRow,
    MissionStageRow,
    PostgresStore,
    ProjectionReceiptRow,
    ReleaseDecisionRow,
    SufficiencyEvaluationRow,
)


class PostgresGovernanceError(RuntimeError):
    pass


_TERMINAL_ATTEMPT_STATES = {
    AttemptStatus.COMPLETED,
    AttemptStatus.FAILED_RUNTIME,
    AttemptStatus.BLOCKED,
}


def _tuple(value: Any) -> tuple[str, ...]:
    return tuple(value or [])


def _same_or_error(previous: object, incoming: object, message: str) -> None:
    if previous != incoming:
        raise PostgresGovernanceError(message)


class PostgresGovernanceRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def upsert_stage(self, stage: StageInstance) -> None:
        now = int(time.time())
        with self.store.session() as session:
            row = session.get(MissionStageRow, stage.stage_instance_id)
            if row is None:
                session.add(
                    MissionStageRow(
                        stage_instance_id=stage.stage_instance_id,
                        test_run_id=stage.test_run_id,
                        stage_type=stage.stage_type,
                        scope_version=stage.scope_version,
                        attempt_no=stage.attempt_no,
                        state=stage.state.value,
                        input_refs=list(stage.input_refs),
                        output_refs=list(stage.output_refs),
                        gap_refs=list(stage.gap_refs),
                        invalidation_refs=list(stage.invalidation_refs),
                        predecessor_ids=list(stage.predecessor_ids),
                        successor_ids=list(stage.successor_ids),
                        assigned_worker=stage.assigned_worker,
                        evaluator_id=stage.evaluator_id,
                        policy_version=stage.policy_version,
                        started_at=stage.started_at,
                        finished_at=stage.finished_at,
                        created_at=now,
                        updated_at=now,
                        payload={},
                    )
                )
                return
            for name in ("test_run_id", "stage_type", "scope_version", "attempt_no"):
                _same_or_error(getattr(row, name), getattr(stage, name), "STAGE_IDENTITY_IMMUTABLE:%s" % name)
            previous_state = StageState(row.state)
            if previous_state in {StageState.INVALIDATED, StageState.SUPERSEDED} and previous_state != stage.state:
                raise PostgresGovernanceError("STAGE_TERMINAL_STATE_IMMUTABLE")
            for name in ("input_refs", "output_refs", "gap_refs", "invalidation_refs"):
                if not set(getattr(row, name) or []).issubset(set(getattr(stage, name))):
                    raise PostgresGovernanceError("STAGE_REFS_CANNOT_SHRINK:%s" % name)
            row.state = stage.state.value
            row.input_refs = list(stage.input_refs)
            row.output_refs = list(stage.output_refs)
            row.gap_refs = list(stage.gap_refs)
            row.invalidation_refs = list(stage.invalidation_refs)
            row.predecessor_ids = list(stage.predecessor_ids)
            row.successor_ids = list(stage.successor_ids)
            row.assigned_worker = stage.assigned_worker
            row.evaluator_id = stage.evaluator_id
            row.policy_version = stage.policy_version
            row.started_at = stage.started_at
            row.finished_at = stage.finished_at
            row.updated_at = now

    def upsert_attempt(self, attempt: AttemptRecord) -> None:
        with self.store.session() as session:
            row = session.get(AttemptRow, attempt.attempt_id)
            if row is None:
                if attempt.status in _TERMINAL_ATTEMPT_STATES:
                    if attempt.finished_at is None:
                        raise PostgresGovernanceError("TERMINAL_ATTEMPT_REQUIRES_FINISHED_AT")
                    if not attempt.evidence_refs:
                        raise PostgresGovernanceError("TERMINAL_ATTEMPT_REQUIRES_EVIDENCE")
                session.add(self._attempt_row(attempt))
                return
            existing = self._attempt_from_row(row)
            immutable = (
                "test_run_id", "stage_instance_id", "work_item_id", "producer_node_id",
                "producer_ref", "input_snapshot_ref", "case_id", "started_at",
            )
            for name in immutable:
                _same_or_error(getattr(existing, name), getattr(attempt, name), "ATTEMPT_IDENTITY_IMMUTABLE:%s" % name)
            if existing.status in _TERMINAL_ATTEMPT_STATES and existing.status != attempt.status:
                raise PostgresGovernanceError("ATTEMPT_TERMINAL_STATE_IMMUTABLE")
            if existing.status == AttemptStatus.STARTED and attempt.status not in {
                AttemptStatus.STARTED, AttemptStatus.COMPLETED, AttemptStatus.FAILED_RUNTIME, AttemptStatus.BLOCKED,
            }:
                raise PostgresGovernanceError("ATTEMPT_STATUS_REGRESSION")
            for name in ("action_refs", "assertion_refs", "evidence_refs", "coverage_refs", "gap_refs", "defect_refs"):
                if not set(getattr(existing, name)).issubset(set(getattr(attempt, name))):
                    raise PostgresGovernanceError("ATTEMPT_REFS_CANNOT_SHRINK:%s" % name)
            if existing.failure_ownership is not None and existing.failure_ownership != attempt.failure_ownership:
                raise PostgresGovernanceError("ATTEMPT_FAILURE_OWNERSHIP_IMMUTABLE")
            if existing.finished_at is not None and existing.finished_at != attempt.finished_at:
                raise PostgresGovernanceError("ATTEMPT_FINISHED_AT_IMMUTABLE")
            if attempt.status in _TERMINAL_ATTEMPT_STATES:
                if attempt.finished_at is None:
                    raise PostgresGovernanceError("TERMINAL_ATTEMPT_REQUIRES_FINISHED_AT")
                if not attempt.evidence_refs:
                    raise PostgresGovernanceError("TERMINAL_ATTEMPT_REQUIRES_EVIDENCE")
            row.status = attempt.status.value
            row.action_refs = list(attempt.action_refs)
            row.assertion_refs = list(attempt.assertion_refs)
            row.evidence_refs = list(attempt.evidence_refs)
            row.coverage_refs = list(attempt.coverage_refs)
            row.gap_refs = list(attempt.gap_refs)
            row.defect_refs = list(attempt.defect_refs)
            row.failure_ownership = attempt.failure_ownership.value if attempt.failure_ownership else None
            row.finished_at = attempt.finished_at

    def append_attempt(self, attempt: AttemptRecord) -> None:
        self.upsert_attempt(attempt)

    def upsert_gap(self, gap: GapRecord) -> None:
        with self.store.session() as session:
            row = session.get(GapRow, gap.gap_id)
            if row is None:
                session.add(self._gap_row(gap))
                return
            existing = self._gap_from_row(row)
            for name in (
                "test_run_id", "source_stage_instance_id", "gap_type", "source_attempt_id",
                "source_case_id", "source_assertion_id", "opened_at",
            ):
                _same_or_error(getattr(existing, name), getattr(gap, name), "GAP_IDENTITY_IMMUTABLE:%s" % name)
            if not set(existing.evidence_refs).issubset(set(gap.evidence_refs)):
                raise PostgresGovernanceError("GAP_EVIDENCE_CANNOT_SHRINK")
            if existing.status in {GapStatus.CLOSED, GapStatus.WAIVED} and existing.status != gap.status:
                raise PostgresGovernanceError("GAP_TERMINAL_STATE_IMMUTABLE")
            row.severity = gap.severity.value
            row.description = gap.description
            row.owner_stage = gap.owner_stage
            row.repair_strategy = gap.repair_strategy
            row.status = gap.status.value
            row.evidence_refs = list(gap.evidence_refs)
            row.invalidates = list(gap.invalidates)
            row.closure_evidence_refs = list(gap.closure_evidence_refs)
            row.closed_at = gap.closed_at

    def append_invalidation(self, value: InvalidationRecord) -> None:
        with self.store.session() as session:
            row = session.get(InvalidationRow, value.invalidation_id)
            if row is not None:
                _same_or_error(self._invalidation_from_row(row), value, "GOVERNANCE_ID_CONFLICT:invalidations:%s" % value.invalidation_id)
                return
            session.add(
                InvalidationRow(
                    invalidation_id=value.invalidation_id,
                    test_run_id=value.test_run_id,
                    source_ref=value.source_ref,
                    target_refs=list(value.target_refs),
                    reason=value.reason,
                    evidence_refs=list(value.evidence_refs),
                    created_at=value.created_at,
                )
            )

    def append_evaluation(self, value: SufficiencyEvaluation) -> None:
        with self.store.session() as session:
            row = session.get(SufficiencyEvaluationRow, value.evaluation_id)
            if row is not None:
                _same_or_error(self._evaluation_from_row(row), value, "GOVERNANCE_ID_CONFLICT:evaluations:%s" % value.evaluation_id)
                return
            session.add(self._evaluation_row(value))

    def append_release_decision(self, value: ReleaseDecisionRecord) -> None:
        with self.store.session() as session:
            row = session.get(ReleaseDecisionRow, value.release_decision_id)
            if row is not None:
                _same_or_error(self._release_from_row(row), value, "GOVERNANCE_ID_CONFLICT:release_decisions:%s" % value.release_decision_id)
                return
            session.add(self._release_row(value))

    def get_stage(self, stage_instance_id: str) -> Optional[StageInstance]:
        with self.store.session() as session:
            row = session.get(MissionStageRow, stage_instance_id)
            return self._stage_from_row(row) if row is not None else None

    def get_attempt(self, attempt_id: str) -> Optional[AttemptRecord]:
        with self.store.session() as session:
            row = session.get(AttemptRow, attempt_id)
            return self._attempt_from_row(row) if row is not None else None

    def get_gap(self, gap_id: str) -> Optional[GapRecord]:
        with self.store.session() as session:
            row = session.get(GapRow, gap_id)
            return self._gap_from_row(row) if row is not None else None

    def get_evaluation(self, evaluation_id: str) -> Optional[SufficiencyEvaluation]:
        with self.store.session() as session:
            row = session.get(SufficiencyEvaluationRow, evaluation_id)
            return self._evaluation_from_row(row) if row is not None else None

    def get_release_decision(self, release_decision_id: str) -> Optional[ReleaseDecisionRecord]:
        with self.store.session() as session:
            row = session.get(ReleaseDecisionRow, release_decision_id)
            return self._release_from_row(row) if row is not None else None

    def projection_receipt(self, event_id: str) -> Optional[Dict[str, Any]]:
        with self.store.session() as session:
            row = session.get(ProjectionReceiptRow, event_id)
            return self._receipt_dict(row) if row is not None else None

    def mark_projection(
        self, *, event_id: str, test_run_id: str, event_type: str, status: str,
        domain_ref: Optional[str] = None, detail: Optional[str] = None,
    ) -> None:
        if status not in {"PROJECTED", "PENDING", "IGNORED"}:
            raise PostgresGovernanceError("PROJECTION_STATUS_INVALID")
        with self.store.session() as session:
            row = session.get(ProjectionReceiptRow, event_id)
            incoming = {
                "event_id": event_id, "test_run_id": test_run_id, "event_type": event_type,
                "status": status, "domain_ref": domain_ref, "detail": detail,
            }
            if row is not None:
                previous = self._receipt_dict(row)
                if row.status == "PROJECTED" and previous != incoming:
                    raise PostgresGovernanceError("PROJECTED_EVENT_IMMUTABLE:%s" % event_id)
                row.test_run_id = test_run_id
                row.event_type = event_type
                row.status = status
                row.domain_ref = domain_ref
                row.detail = detail
                return
            session.add(ProjectionReceiptRow(**incoming))

    def list_projection_receipts(self, test_run_id: str) -> List[Dict[str, Any]]:
        with self.store.session() as session:
            rows = list(session.scalars(select(ProjectionReceiptRow).where(ProjectionReceiptRow.test_run_id == test_run_id).order_by(ProjectionReceiptRow.event_id)))
            return [self._receipt_dict(row) for row in rows]

    def list_stages(self, test_run_id: str) -> List[StageInstance]:
        with self.store.session() as session:
            rows = list(session.scalars(select(MissionStageRow).where(MissionStageRow.test_run_id == test_run_id).order_by(MissionStageRow.attempt_no, MissionStageRow.stage_instance_id)))
            return [self._stage_from_row(row) for row in rows]

    def list_attempts(self, test_run_id: str) -> List[AttemptRecord]:
        with self.store.session() as session:
            rows = list(session.scalars(select(AttemptRow).where(AttemptRow.test_run_id == test_run_id).order_by(AttemptRow.started_at, AttemptRow.attempt_id)))
            return [self._attempt_from_row(row) for row in rows]

    def list_gaps(self, test_run_id: str) -> List[GapRecord]:
        with self.store.session() as session:
            rows = list(session.scalars(select(GapRow).where(GapRow.test_run_id == test_run_id).order_by(GapRow.opened_at, GapRow.gap_id)))
            return [self._gap_from_row(row) for row in rows]

    def list_invalidations(self, test_run_id: str) -> List[InvalidationRecord]:
        with self.store.session() as session:
            rows = list(session.scalars(select(InvalidationRow).where(InvalidationRow.test_run_id == test_run_id).order_by(InvalidationRow.created_at, InvalidationRow.invalidation_id)))
            return [self._invalidation_from_row(row) for row in rows]

    def list_evaluations(self, test_run_id: str) -> List[SufficiencyEvaluation]:
        with self.store.session() as session:
            rows = list(session.scalars(select(SufficiencyEvaluationRow).where(SufficiencyEvaluationRow.test_run_id == test_run_id).order_by(SufficiencyEvaluationRow.evaluated_at, SufficiencyEvaluationRow.evaluation_id)))
            return [self._evaluation_from_row(row) for row in rows]

    def list_release_decisions(self, test_run_id: str) -> List[ReleaseDecisionRecord]:
        with self.store.session() as session:
            rows = list(session.scalars(select(ReleaseDecisionRow).where(ReleaseDecisionRow.test_run_id == test_run_id).order_by(ReleaseDecisionRow.recorded_at, ReleaseDecisionRow.release_decision_id)))
            return [self._release_from_row(row) for row in rows]

    def test_run_projection(self, test_run_id: str) -> Dict[str, Any]:
        stages = self.list_stages(test_run_id)
        attempts = self.list_attempts(test_run_id)
        gaps = self.list_gaps(test_run_id)
        evaluations = self.list_evaluations(test_run_id)
        invalidations = self.list_invalidations(test_run_id)
        releases = self.list_release_decisions(test_run_id)
        receipts = self.list_projection_receipts(test_run_id)
        active_gaps = [gap for gap in gaps if gap.status not in {GapStatus.CLOSED, GapStatus.WAIVED}]
        mission_evals = [item for item in evaluations if item.scope == StatusScope.MISSION]
        return {
            "schema_version": "rc8.governance-projection.v2",
            "test_run_id": test_run_id,
            "stage_count": len(stages),
            "attempt_count": len(attempts),
            "active_gap_count": len(active_gaps),
            "projection_pending_count": len([item for item in receipts if item.get("status") == "PENDING"]),
            "stages": [self._stage_dict(item) for item in stages],
            "attempts": [self._attempt_dict(item) for item in attempts],
            "gaps": [self._gap_dict(item) for item in gaps],
            "invalidations": [self._invalidation_dict(item) for item in invalidations],
            "evaluations": [self._evaluation_dict(item) for item in evaluations],
            "projection_receipts": receipts,
            "latest_mission_sufficiency": self._evaluation_dict(mission_evals[-1]) if mission_evals else None,
            "latest_release_decision": self._release_dict(releases[-1]) if releases else None,
            "truth_note": "Projection exposes recorded sufficiency/release facts; it never derives PASS from completed work or zero failures.",
        }

    @staticmethod
    def _attempt_row(value: AttemptRecord) -> AttemptRow:
        return AttemptRow(
            attempt_id=value.attempt_id, test_run_id=value.test_run_id, stage_instance_id=value.stage_instance_id,
            work_item_id=value.work_item_id, producer_node_id=value.producer_node_id, producer_ref=value.producer_ref,
            input_snapshot_ref=value.input_snapshot_ref, status=value.status.value, case_id=value.case_id,
            action_refs=list(value.action_refs), assertion_refs=list(value.assertion_refs), evidence_refs=list(value.evidence_refs),
            coverage_refs=list(value.coverage_refs), gap_refs=list(value.gap_refs), defect_refs=list(value.defect_refs),
            failure_ownership=value.failure_ownership.value if value.failure_ownership else None,
            started_at=value.started_at, finished_at=value.finished_at, payload={},
        )

    @staticmethod
    def _attempt_from_row(row: AttemptRow) -> AttemptRecord:
        return AttemptRecord(
            attempt_id=row.attempt_id, test_run_id=row.test_run_id, stage_instance_id=row.stage_instance_id,
            work_item_id=row.work_item_id, producer_node_id=row.producer_node_id, producer_ref=row.producer_ref,
            input_snapshot_ref=row.input_snapshot_ref, status=AttemptStatus(row.status), case_id=row.case_id,
            action_refs=_tuple(row.action_refs), assertion_refs=_tuple(row.assertion_refs), evidence_refs=_tuple(row.evidence_refs),
            coverage_refs=_tuple(row.coverage_refs), gap_refs=_tuple(row.gap_refs), defect_refs=_tuple(row.defect_refs),
            failure_ownership=FailureOwnership(row.failure_ownership) if row.failure_ownership else None,
            started_at=row.started_at, finished_at=row.finished_at,
        )

    @staticmethod
    def _stage_from_row(row: MissionStageRow) -> StageInstance:
        return StageInstance(
            stage_instance_id=row.stage_instance_id, test_run_id=row.test_run_id, stage_type=row.stage_type,
            scope_version=row.scope_version, attempt_no=int(row.attempt_no), state=StageState(row.state),
            input_refs=_tuple(row.input_refs), output_refs=_tuple(row.output_refs), gap_refs=_tuple(row.gap_refs),
            invalidation_refs=_tuple(row.invalidation_refs), predecessor_ids=_tuple(row.predecessor_ids), successor_ids=_tuple(row.successor_ids),
            assigned_worker=row.assigned_worker, evaluator_id=row.evaluator_id, policy_version=row.policy_version,
            started_at=row.started_at, finished_at=row.finished_at,
        )

    @staticmethod
    def _gap_row(value: GapRecord) -> GapRow:
        return GapRow(
            gap_id=value.gap_id, test_run_id=value.test_run_id, source_stage_instance_id=value.source_stage_instance_id,
            gap_type=value.gap_type.value, severity=value.severity.value, description=value.description,
            owner_stage=value.owner_stage, repair_strategy=value.repair_strategy, status=value.status.value,
            source_attempt_id=value.source_attempt_id, source_case_id=value.source_case_id, source_assertion_id=value.source_assertion_id,
            evidence_refs=list(value.evidence_refs), invalidates=list(value.invalidates), closure_evidence_refs=list(value.closure_evidence_refs),
            opened_at=value.opened_at, closed_at=value.closed_at, payload={},
        )

    @staticmethod
    def _gap_from_row(row: GapRow) -> GapRecord:
        return GapRecord(
            gap_id=row.gap_id, test_run_id=row.test_run_id, source_stage_instance_id=row.source_stage_instance_id,
            gap_type=GapType(row.gap_type), severity=GapSeverity(row.severity), description=row.description,
            owner_stage=row.owner_stage, repair_strategy=row.repair_strategy, status=GapStatus(row.status),
            source_attempt_id=row.source_attempt_id, source_case_id=row.source_case_id, source_assertion_id=row.source_assertion_id,
            evidence_refs=_tuple(row.evidence_refs), invalidates=_tuple(row.invalidates), closure_evidence_refs=_tuple(row.closure_evidence_refs),
            opened_at=row.opened_at, closed_at=row.closed_at,
        )

    @staticmethod
    def _invalidation_from_row(row: InvalidationRow) -> InvalidationRecord:
        return InvalidationRecord(
            invalidation_id=row.invalidation_id, test_run_id=row.test_run_id, source_ref=row.source_ref,
            target_refs=_tuple(row.target_refs), reason=row.reason, evidence_refs=_tuple(row.evidence_refs), created_at=row.created_at,
        )

    @staticmethod
    def _evaluation_row(value: SufficiencyEvaluation) -> SufficiencyEvaluationRow:
        return SufficiencyEvaluationRow(
            evaluation_id=value.evaluation_id, test_run_id=value.test_run_id, scope=value.scope.value,
            subject_id=value.subject_id, evaluator_id=value.evaluator_id, policy_version=value.policy_version,
            result=value.result.value, dimension_refs=list(value.dimension_refs), evidence_refs=list(value.evidence_refs),
            satisfied_requirement_refs=list(value.satisfied_requirement_refs), unsatisfied_requirement_refs=list(value.unsatisfied_requirement_refs),
            unresolved_gap_ids=list(value.unresolved_gap_ids), accepted_waiver_ids=list(value.accepted_waiver_ids),
            explanation=value.explanation, evaluated_at=value.evaluated_at,
        )

    @staticmethod
    def _evaluation_from_row(row: SufficiencyEvaluationRow) -> SufficiencyEvaluation:
        return SufficiencyEvaluation(
            evaluation_id=row.evaluation_id, test_run_id=row.test_run_id, scope=StatusScope(row.scope), subject_id=row.subject_id,
            evaluator_id=row.evaluator_id, policy_version=row.policy_version, result=SufficiencyResult(row.result),
            dimension_refs=_tuple(row.dimension_refs), evidence_refs=_tuple(row.evidence_refs),
            satisfied_requirement_refs=_tuple(row.satisfied_requirement_refs), unsatisfied_requirement_refs=_tuple(row.unsatisfied_requirement_refs),
            unresolved_gap_ids=_tuple(row.unresolved_gap_ids), accepted_waiver_ids=_tuple(row.accepted_waiver_ids),
            explanation=row.explanation, evaluated_at=row.evaluated_at,
        )

    @staticmethod
    def _release_row(value: ReleaseDecisionRecord) -> ReleaseDecisionRow:
        return ReleaseDecisionRow(
            release_decision_id=value.release_decision_id, test_run_id=value.test_run_id, decision=value.decision.value,
            mission_evaluation_ref=value.mission_evaluation_ref, evidence_refs=list(value.evidence_refs),
            blocking_defect_refs=list(value.blocking_defect_refs), explanation=value.explanation, recorded_at=value.recorded_at,
        )

    @staticmethod
    def _release_from_row(row: ReleaseDecisionRow) -> ReleaseDecisionRecord:
        return ReleaseDecisionRecord(
            release_decision_id=row.release_decision_id, test_run_id=row.test_run_id, decision=ReleaseDecision(row.decision),
            mission_evaluation_ref=row.mission_evaluation_ref, evidence_refs=_tuple(row.evidence_refs),
            blocking_defect_refs=_tuple(row.blocking_defect_refs), explanation=row.explanation, recorded_at=row.recorded_at,
        )

    @staticmethod
    def _receipt_dict(row: ProjectionReceiptRow) -> Dict[str, Any]:
        return {"event_id": row.event_id, "test_run_id": row.test_run_id, "event_type": row.event_type, "status": row.status, "domain_ref": row.domain_ref, "detail": row.detail}

    @staticmethod
    def _stage_dict(v: StageInstance) -> Dict[str, Any]:
        return {"stage_instance_id": v.stage_instance_id, "test_run_id": v.test_run_id, "stage_type": v.stage_type, "scope_version": v.scope_version, "attempt_no": v.attempt_no, "state": v.state.value, "input_refs": list(v.input_refs), "output_refs": list(v.output_refs), "gap_refs": list(v.gap_refs), "invalidation_refs": list(v.invalidation_refs), "predecessor_ids": list(v.predecessor_ids), "successor_ids": list(v.successor_ids), "assigned_worker": v.assigned_worker, "evaluator_id": v.evaluator_id, "policy_version": v.policy_version, "started_at": v.started_at, "finished_at": v.finished_at}

    @staticmethod
    def _attempt_dict(v: AttemptRecord) -> Dict[str, Any]:
        return {"attempt_id": v.attempt_id, "test_run_id": v.test_run_id, "stage_instance_id": v.stage_instance_id, "work_item_id": v.work_item_id, "producer_node_id": v.producer_node_id, "producer_ref": v.producer_ref, "input_snapshot_ref": v.input_snapshot_ref, "status": v.status.value, "case_id": v.case_id, "action_refs": list(v.action_refs), "assertion_refs": list(v.assertion_refs), "evidence_refs": list(v.evidence_refs), "coverage_refs": list(v.coverage_refs), "gap_refs": list(v.gap_refs), "defect_refs": list(v.defect_refs), "failure_ownership": v.failure_ownership.value if v.failure_ownership else None, "started_at": v.started_at, "finished_at": v.finished_at}

    @staticmethod
    def _gap_dict(v: GapRecord) -> Dict[str, Any]:
        return {"gap_id": v.gap_id, "test_run_id": v.test_run_id, "source_stage_instance_id": v.source_stage_instance_id, "gap_type": v.gap_type.value, "severity": v.severity.value, "description": v.description, "owner_stage": v.owner_stage, "repair_strategy": v.repair_strategy, "status": v.status.value, "source_attempt_id": v.source_attempt_id, "source_case_id": v.source_case_id, "source_assertion_id": v.source_assertion_id, "evidence_refs": list(v.evidence_refs), "invalidates": list(v.invalidates), "closure_evidence_refs": list(v.closure_evidence_refs), "opened_at": v.opened_at, "closed_at": v.closed_at}

    @staticmethod
    def _invalidation_dict(v: InvalidationRecord) -> Dict[str, Any]:
        return {"invalidation_id": v.invalidation_id, "test_run_id": v.test_run_id, "source_ref": v.source_ref, "target_refs": list(v.target_refs), "reason": v.reason, "evidence_refs": list(v.evidence_refs), "created_at": v.created_at}

    @staticmethod
    def _evaluation_dict(v: SufficiencyEvaluation) -> Dict[str, Any]:
        return {"evaluation_id": v.evaluation_id, "test_run_id": v.test_run_id, "scope": v.scope.value, "subject_id": v.subject_id, "evaluator_id": v.evaluator_id, "policy_version": v.policy_version, "result": v.result.value, "dimension_refs": list(v.dimension_refs), "evidence_refs": list(v.evidence_refs), "satisfied_requirement_refs": list(v.satisfied_requirement_refs), "unsatisfied_requirement_refs": list(v.unsatisfied_requirement_refs), "unresolved_gap_ids": list(v.unresolved_gap_ids), "accepted_waiver_ids": list(v.accepted_waiver_ids), "explanation": v.explanation, "evaluated_at": v.evaluated_at}

    @staticmethod
    def _release_dict(v: ReleaseDecisionRecord) -> Dict[str, Any]:
        return {"release_decision_id": v.release_decision_id, "test_run_id": v.test_run_id, "decision": v.decision.value, "mission_evaluation_ref": v.mission_evaluation_ref, "evidence_refs": list(v.evidence_refs), "blocking_defect_refs": list(v.blocking_defect_refs), "explanation": v.explanation, "recorded_at": v.recorded_at}


class PostgresCoverageRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def append(self, observation: CoverageObservation) -> None:
        with self.store.session() as session:
            row = session.get(CoverageObservationRow, observation.observation_id)
            if row is not None:
                if self._from_row(row) != observation:
                    raise PostgresGovernanceError("COVERAGE_OBSERVATION_ID_CONFLICT:%s" % observation.observation_id)
                return
            session.add(
                CoverageObservationRow(
                    observation_id=observation.observation_id, test_run_id=observation.test_run_id,
                    stage_instance_id=observation.stage_instance_id, attempt_id=observation.attempt_id,
                    case_id=observation.case_id, subject_ref=observation.subject_ref,
                    source_snapshot_ref=observation.source_snapshot_ref, source_tool=observation.source_tool,
                    metric_id=observation.metric.metric_id, dimension=observation.metric.dimension.value,
                    covered=observation.metric.covered, total=observation.metric.total, threshold=float(observation.metric.threshold),
                    critical=observation.metric.critical, evidence_refs=list(observation.metric.evidence_refs),
                    artifact_refs=list(observation.artifact_refs), observed_at=observation.observed_at, payload={},
                )
            )

    def get(self, observation_id: str) -> Optional[CoverageObservation]:
        with self.store.session() as session:
            row = session.get(CoverageObservationRow, observation_id)
            return self._from_row(row) if row is not None else None

    def list_for_test_run(self, test_run_id: str) -> List[CoverageObservation]:
        with self.store.session() as session:
            rows = list(session.scalars(select(CoverageObservationRow).where(CoverageObservationRow.test_run_id == test_run_id).order_by(CoverageObservationRow.observed_at, CoverageObservationRow.observation_id)))
            return [self._from_row(row) for row in rows]

    def list_for_attempt(self, test_run_id: str, attempt_id: str) -> List[CoverageObservation]:
        return [item for item in self.list_for_test_run(test_run_id) if item.attempt_id == attempt_id]

    @staticmethod
    def _from_row(row: CoverageObservationRow) -> CoverageObservation:
        metric = CoverageMetric(
            metric_id=row.metric_id, dimension=CoverageDimension(row.dimension), covered=int(row.covered), total=int(row.total),
            threshold=float(row.threshold), evidence_refs=_tuple(row.evidence_refs), critical=bool(row.critical),
        )
        return CoverageObservation(
            observation_id=row.observation_id, test_run_id=row.test_run_id, stage_instance_id=row.stage_instance_id,
            subject_ref=row.subject_ref, source_snapshot_ref=row.source_snapshot_ref, metric=metric,
            attempt_id=row.attempt_id, case_id=row.case_id, source_tool=row.source_tool,
            artifact_refs=_tuple(row.artifact_refs), observed_at=int(row.observed_at),
        )
