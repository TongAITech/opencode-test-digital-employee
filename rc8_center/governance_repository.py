"""Durable Center repository/projection for RC8 governance facts.

This dependency-free W-A repository is a storage-neutral fallback. PostgreSQL
will replace the JSON implementation without changing Mission/Gap/Sufficiency
semantics. Runtime history remains authoritative in R1; these records are
rebuildable projections/control-domain state.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from rc8_runtime.governance import (
    AttemptRecord,
    AttemptStatus,
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

from .json_repository import DurableRepositoryError, _AtomicJsonFile, _jsonable


_TERMINAL_ATTEMPT_STATES = {
    AttemptStatus.COMPLETED,
    AttemptStatus.FAILED_RUNTIME,
    AttemptStatus.BLOCKED,
}


class JsonFileGovernanceRepository:
    """Durable Center-side governance fact store.

    Different Attempt identities are append-only. A single Attempt projection is
    allowed to advance monotonically STARTED -> terminal because the underlying
    R1 events remain append-only and replayable. Evaluations, invalidations and
    release decisions are append-only/idempotent projections.
    """

    def __init__(self, path: str) -> None:
        self._file = _AtomicJsonFile(
            path,
            {
                "schema_version": 2,
                "stages": {},
                "attempts": {},
                "gaps": {},
                "invalidations": {},
                "evaluations": {},
                "release_decisions": {},
                "projected_events": {},
            },
        )
        self._migrate()

    def _migrate(self) -> None:
        def apply(data: Dict[str, Any]) -> None:
            data["schema_version"] = 2
            for name in (
                "stages",
                "attempts",
                "gaps",
                "invalidations",
                "evaluations",
                "release_decisions",
                "projected_events",
            ):
                if name not in data:
                    data[name] = {}
                if not isinstance(data[name], dict):
                    raise DurableRepositoryError("GOVERNANCE_BUCKET_INVALID:%s" % name)
            # Old W-A builds briefly carried a bare coverage bucket. Coverage is
            # now provenance-bound in JsonFileCoverageRepository and is ignored
            # here rather than promoted into product truth.
        self._file.mutate(apply)

    @staticmethod
    def _require_bucket(data: Dict[str, Any], name: str) -> Dict[str, Any]:
        value = data.setdefault(name, {})
        if not isinstance(value, dict):
            raise DurableRepositoryError("GOVERNANCE_BUCKET_INVALID:%s" % name)
        return value

    @staticmethod
    def _append_idempotent(data: Dict[str, Any], bucket: str, key: str, value: Any) -> bool:
        rows = JsonFileGovernanceRepository._require_bucket(data, bucket)
        encoded = _jsonable(value)
        previous = rows.get(key)
        if previous is not None:
            if previous != encoded:
                raise DurableRepositoryError("GOVERNANCE_ID_CONFLICT:%s:%s" % (bucket, key))
            return False
        rows[key] = encoded
        return True

    def upsert_stage(self, stage: StageInstance) -> None:
        encoded = _jsonable(stage)

        def apply(data: Dict[str, Any]) -> None:
            rows = self._require_bucket(data, "stages")
            previous = rows.get(stage.stage_instance_id)
            if isinstance(previous, dict):
                for key in ("test_run_id", "stage_type", "scope_version", "attempt_no"):
                    if previous.get(key) != encoded.get(key):
                        raise DurableRepositoryError("STAGE_IDENTITY_IMMUTABLE:%s" % key)
                previous_state = StageState(str(previous.get("state")))
                if previous_state in {StageState.INVALIDATED, StageState.SUPERSEDED} and previous_state != stage.state:
                    raise DurableRepositoryError("STAGE_TERMINAL_STATE_IMMUTABLE")
                for refs_key in ("input_refs", "output_refs", "gap_refs", "invalidation_refs"):
                    if not set(previous.get(refs_key) or []).issubset(set(encoded.get(refs_key) or [])):
                        raise DurableRepositoryError("STAGE_REFS_CANNOT_SHRINK:%s" % refs_key)
            rows[stage.stage_instance_id] = encoded
        self._file.mutate(apply)

    def upsert_attempt(self, attempt: AttemptRecord) -> None:
        encoded = _jsonable(attempt)

        def apply(data: Dict[str, Any]) -> None:
            rows = self._require_bucket(data, "attempts")
            previous = rows.get(attempt.attempt_id)
            if isinstance(previous, dict):
                immutable = (
                    "test_run_id",
                    "stage_instance_id",
                    "work_item_id",
                    "producer_node_id",
                    "producer_ref",
                    "input_snapshot_ref",
                    "case_id",
                    "started_at",
                )
                for key in immutable:
                    if previous.get(key) != encoded.get(key):
                        raise DurableRepositoryError("ATTEMPT_IDENTITY_IMMUTABLE:%s" % key)

                previous_status = AttemptStatus(str(previous.get("status")))
                if previous_status in _TERMINAL_ATTEMPT_STATES and previous_status != attempt.status:
                    raise DurableRepositoryError("ATTEMPT_TERMINAL_STATE_IMMUTABLE")
                if previous_status == AttemptStatus.STARTED and attempt.status not in {
                    AttemptStatus.STARTED,
                    AttemptStatus.COMPLETED,
                    AttemptStatus.FAILED_RUNTIME,
                    AttemptStatus.BLOCKED,
                }:
                    raise DurableRepositoryError("ATTEMPT_STATUS_REGRESSION")

                for refs_key in (
                    "action_refs",
                    "assertion_refs",
                    "evidence_refs",
                    "coverage_refs",
                    "gap_refs",
                    "defect_refs",
                ):
                    if not set(previous.get(refs_key) or []).issubset(set(encoded.get(refs_key) or [])):
                        raise DurableRepositoryError("ATTEMPT_REFS_CANNOT_SHRINK:%s" % refs_key)

                previous_owner = previous.get("failure_ownership")
                if previous_owner is not None and previous_owner != encoded.get("failure_ownership"):
                    raise DurableRepositoryError("ATTEMPT_FAILURE_OWNERSHIP_IMMUTABLE")
                previous_finished = previous.get("finished_at")
                if previous_finished is not None and previous_finished != encoded.get("finished_at"):
                    raise DurableRepositoryError("ATTEMPT_FINISHED_AT_IMMUTABLE")

            if attempt.status in _TERMINAL_ATTEMPT_STATES and attempt.finished_at is None:
                raise DurableRepositoryError("TERMINAL_ATTEMPT_REQUIRES_FINISHED_AT")
            if attempt.status in _TERMINAL_ATTEMPT_STATES and not attempt.evidence_refs:
                raise DurableRepositoryError("TERMINAL_ATTEMPT_REQUIRES_EVIDENCE")
            rows[attempt.attempt_id] = encoded
        self._file.mutate(apply)

    # Compatibility name retained for older W-A callers; semantics are now a
    # monotonic projection rather than 'one write ever'.
    def append_attempt(self, attempt: AttemptRecord) -> None:
        self.upsert_attempt(attempt)

    def upsert_gap(self, gap: GapRecord) -> None:
        encoded = _jsonable(gap)

        def apply(data: Dict[str, Any]) -> None:
            rows = self._require_bucket(data, "gaps")
            previous = rows.get(gap.gap_id)
            if isinstance(previous, dict):
                immutable = (
                    "test_run_id",
                    "source_stage_instance_id",
                    "gap_type",
                    "source_attempt_id",
                    "source_case_id",
                    "source_assertion_id",
                    "opened_at",
                )
                for key in immutable:
                    if previous.get(key) != encoded.get(key):
                        raise DurableRepositoryError("GAP_IDENTITY_IMMUTABLE:%s" % key)
                if not set(previous.get("evidence_refs") or []).issubset(set(encoded.get("evidence_refs") or [])):
                    raise DurableRepositoryError("GAP_EVIDENCE_CANNOT_SHRINK")
                previous_status = GapStatus(str(previous.get("status")))
                if previous_status in {GapStatus.CLOSED, GapStatus.WAIVED} and previous_status != gap.status:
                    raise DurableRepositoryError("GAP_TERMINAL_STATE_IMMUTABLE")
            rows[gap.gap_id] = encoded
        self._file.mutate(apply)

    def append_invalidation(self, value: InvalidationRecord) -> None:
        self._file.mutate(lambda data: self._append_idempotent(data, "invalidations", value.invalidation_id, value))

    def append_evaluation(self, value: SufficiencyEvaluation) -> None:
        self._file.mutate(lambda data: self._append_idempotent(data, "evaluations", value.evaluation_id, value))

    def append_release_decision(self, value: ReleaseDecisionRecord) -> None:
        self._file.mutate(lambda data: self._append_idempotent(data, "release_decisions", value.release_decision_id, value))

    def get_stage(self, stage_instance_id: str) -> Optional[StageInstance]:
        raw = self._file.read().get("stages", {}).get(stage_instance_id)
        return self._stage_from_raw(raw) if isinstance(raw, dict) else None

    def get_attempt(self, attempt_id: str) -> Optional[AttemptRecord]:
        raw = self._file.read().get("attempts", {}).get(attempt_id)
        return self._attempt_from_raw(raw) if isinstance(raw, dict) else None

    def get_gap(self, gap_id: str) -> Optional[GapRecord]:
        raw = self._file.read().get("gaps", {}).get(gap_id)
        return self._gap_from_raw(raw) if isinstance(raw, dict) else None

    def get_evaluation(self, evaluation_id: str) -> Optional[SufficiencyEvaluation]:
        raw = self._file.read().get("evaluations", {}).get(evaluation_id)
        return self._evaluation_from_raw(raw) if isinstance(raw, dict) else None

    def get_release_decision(self, release_decision_id: str) -> Optional[ReleaseDecisionRecord]:
        raw = self._file.read().get("release_decisions", {}).get(release_decision_id)
        return self._release_from_raw(raw) if isinstance(raw, dict) else None

    def projection_receipt(self, event_id: str) -> Optional[Dict[str, Any]]:
        raw = self._file.read().get("projected_events", {}).get(event_id)
        return dict(raw) if isinstance(raw, dict) else None

    def mark_projection(
        self,
        *,
        event_id: str,
        test_run_id: str,
        event_type: str,
        status: str,
        domain_ref: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        if status not in {"PROJECTED", "PENDING", "IGNORED"}:
            raise DurableRepositoryError("PROJECTION_STATUS_INVALID")
        value = {
            "event_id": event_id,
            "test_run_id": test_run_id,
            "event_type": event_type,
            "status": status,
            "domain_ref": domain_ref,
            "detail": detail,
        }

        def apply(data: Dict[str, Any]) -> None:
            rows = self._require_bucket(data, "projected_events")
            previous = rows.get(event_id)
            if isinstance(previous, dict) and previous.get("status") == "PROJECTED" and previous != value:
                raise DurableRepositoryError("PROJECTED_EVENT_IMMUTABLE:%s" % event_id)
            rows[event_id] = value
        self._file.mutate(apply)

    def list_projection_receipts(self, test_run_id: str) -> List[Dict[str, Any]]:
        rows = self._bucket("projected_events")
        found = [dict(raw) for raw in rows.values() if isinstance(raw, dict) and raw.get("test_run_id") == test_run_id]
        return sorted(found, key=lambda item: str(item.get("event_id") or ""))

    def list_stages(self, test_run_id: str) -> List[StageInstance]:
        rows = self._bucket("stages")
        return sorted(
            [self._stage_from_raw(raw) for raw in rows.values() if isinstance(raw, dict) and raw.get("test_run_id") == test_run_id],
            key=lambda item: (item.attempt_no, item.stage_instance_id),
        )

    def list_attempts(self, test_run_id: str) -> List[AttemptRecord]:
        rows = self._bucket("attempts")
        return sorted(
            [self._attempt_from_raw(raw) for raw in rows.values() if isinstance(raw, dict) and raw.get("test_run_id") == test_run_id],
            key=lambda item: (item.started_at, item.attempt_id),
        )

    def list_gaps(self, test_run_id: str) -> List[GapRecord]:
        rows = self._bucket("gaps")
        return sorted(
            [self._gap_from_raw(raw) for raw in rows.values() if isinstance(raw, dict) and raw.get("test_run_id") == test_run_id],
            key=lambda item: (item.opened_at, item.gap_id),
        )

    def list_invalidations(self, test_run_id: str) -> List[InvalidationRecord]:
        rows = self._bucket("invalidations")
        return sorted(
            [self._invalidation_from_raw(raw) for raw in rows.values() if isinstance(raw, dict) and raw.get("test_run_id") == test_run_id],
            key=lambda item: (item.created_at, item.invalidation_id),
        )

    def list_evaluations(self, test_run_id: str) -> List[SufficiencyEvaluation]:
        rows = self._bucket("evaluations")
        return sorted(
            [self._evaluation_from_raw(raw) for raw in rows.values() if isinstance(raw, dict) and raw.get("test_run_id") == test_run_id],
            key=lambda item: (item.evaluated_at, item.evaluation_id),
        )

    def list_release_decisions(self, test_run_id: str) -> List[ReleaseDecisionRecord]:
        rows = self._bucket("release_decisions")
        return sorted(
            [self._release_from_raw(raw) for raw in rows.values() if isinstance(raw, dict) and raw.get("test_run_id") == test_run_id],
            key=lambda item: (item.recorded_at, item.release_decision_id),
        )

    def test_run_projection(self, test_run_id: str) -> Dict[str, Any]:
        """Return a truthful product-ready projection without inventing PASS."""
        stages = self.list_stages(test_run_id)
        attempts = self.list_attempts(test_run_id)
        gaps = self.list_gaps(test_run_id)
        evaluations = self.list_evaluations(test_run_id)
        invalidations = self.list_invalidations(test_run_id)
        releases = self.list_release_decisions(test_run_id)
        projection_receipts = self.list_projection_receipts(test_run_id)
        active_gaps = [gap for gap in gaps if gap.status not in {GapStatus.CLOSED, GapStatus.WAIVED}]
        mission_evals = [item for item in evaluations if item.scope == StatusScope.MISSION]
        latest_mission = mission_evals[-1] if mission_evals else None
        latest_release = releases[-1] if releases else None
        return {
            "schema_version": "rc8.governance-projection.v2",
            "test_run_id": test_run_id,
            "stage_count": len(stages),
            "attempt_count": len(attempts),
            "active_gap_count": len(active_gaps),
            "projection_pending_count": len([item for item in projection_receipts if item.get("status") == "PENDING"]),
            "stages": [_jsonable(item) for item in stages],
            "attempts": [_jsonable(item) for item in attempts],
            "gaps": [_jsonable(item) for item in gaps],
            "invalidations": [_jsonable(item) for item in invalidations],
            "evaluations": [_jsonable(item) for item in evaluations],
            "projection_receipts": projection_receipts,
            "latest_mission_sufficiency": _jsonable(latest_mission) if latest_mission else None,
            "latest_release_decision": _jsonable(latest_release) if latest_release else None,
            "truth_note": "Projection exposes recorded sufficiency/release facts; it never derives PASS from completed work or zero failures.",
        }

    def _bucket(self, name: str) -> Dict[str, Any]:
        value = self._file.read().get(name, {})
        if not isinstance(value, dict):
            raise DurableRepositoryError("GOVERNANCE_BUCKET_INVALID:%s" % name)
        return value

    @staticmethod
    def _stage_from_raw(raw: Dict[str, Any]) -> StageInstance:
        return StageInstance(
            stage_instance_id=str(raw.get("stage_instance_id") or ""),
            test_run_id=str(raw.get("test_run_id") or ""),
            stage_type=str(raw.get("stage_type") or ""),
            scope_version=str(raw.get("scope_version") or ""),
            attempt_no=int(raw.get("attempt_no") or 0),
            state=StageState(str(raw.get("state"))),
            input_refs=tuple(raw.get("input_refs") or []),
            output_refs=tuple(raw.get("output_refs") or []),
            gap_refs=tuple(raw.get("gap_refs") or []),
            invalidation_refs=tuple(raw.get("invalidation_refs") or []),
            predecessor_ids=tuple(raw.get("predecessor_ids") or []),
            successor_ids=tuple(raw.get("successor_ids") or []),
            assigned_worker=str(raw["assigned_worker"]) if raw.get("assigned_worker") is not None else None,
            evaluator_id=str(raw["evaluator_id"]) if raw.get("evaluator_id") is not None else None,
            policy_version=str(raw["policy_version"]) if raw.get("policy_version") is not None else None,
            started_at=int(raw["started_at"]) if raw.get("started_at") is not None else None,
            finished_at=int(raw["finished_at"]) if raw.get("finished_at") is not None else None,
        )

    @staticmethod
    def _attempt_from_raw(raw: Dict[str, Any]) -> AttemptRecord:
        ownership = raw.get("failure_ownership")
        return AttemptRecord(
            attempt_id=str(raw.get("attempt_id") or ""),
            test_run_id=str(raw.get("test_run_id") or ""),
            stage_instance_id=str(raw.get("stage_instance_id") or ""),
            work_item_id=str(raw.get("work_item_id") or ""),
            producer_node_id=str(raw.get("producer_node_id") or ""),
            producer_ref=str(raw.get("producer_ref") or ""),
            input_snapshot_ref=str(raw.get("input_snapshot_ref") or ""),
            status=AttemptStatus(str(raw.get("status"))),
            case_id=str(raw["case_id"]) if raw.get("case_id") is not None else None,
            action_refs=tuple(raw.get("action_refs") or []),
            assertion_refs=tuple(raw.get("assertion_refs") or []),
            evidence_refs=tuple(raw.get("evidence_refs") or []),
            coverage_refs=tuple(raw.get("coverage_refs") or []),
            gap_refs=tuple(raw.get("gap_refs") or []),
            defect_refs=tuple(raw.get("defect_refs") or []),
            failure_ownership=FailureOwnership(str(ownership)) if ownership is not None else None,
            started_at=int(raw.get("started_at") or 0),
            finished_at=int(raw["finished_at"]) if raw.get("finished_at") is not None else None,
        )

    @staticmethod
    def _gap_from_raw(raw: Dict[str, Any]) -> GapRecord:
        return GapRecord(
            gap_id=str(raw.get("gap_id") or ""),
            test_run_id=str(raw.get("test_run_id") or ""),
            source_stage_instance_id=str(raw.get("source_stage_instance_id") or ""),
            gap_type=GapType(str(raw.get("gap_type"))),
            severity=GapSeverity(str(raw.get("severity"))),
            description=str(raw.get("description") or ""),
            owner_stage=str(raw.get("owner_stage") or ""),
            repair_strategy=str(raw.get("repair_strategy") or ""),
            status=GapStatus(str(raw.get("status"))),
            source_attempt_id=str(raw["source_attempt_id"]) if raw.get("source_attempt_id") is not None else None,
            source_case_id=str(raw["source_case_id"]) if raw.get("source_case_id") is not None else None,
            source_assertion_id=str(raw["source_assertion_id"]) if raw.get("source_assertion_id") is not None else None,
            evidence_refs=tuple(raw.get("evidence_refs") or []),
            invalidates=tuple(raw.get("invalidates") or []),
            closure_evidence_refs=tuple(raw.get("closure_evidence_refs") or []),
            opened_at=int(raw.get("opened_at") or 0),
            closed_at=int(raw["closed_at"]) if raw.get("closed_at") is not None else None,
        )

    @staticmethod
    def _invalidation_from_raw(raw: Dict[str, Any]) -> InvalidationRecord:
        return InvalidationRecord(
            invalidation_id=str(raw.get("invalidation_id") or ""),
            test_run_id=str(raw.get("test_run_id") or ""),
            source_ref=str(raw.get("source_ref") or ""),
            target_refs=tuple(raw.get("target_refs") or []),
            reason=str(raw.get("reason") or ""),
            evidence_refs=tuple(raw.get("evidence_refs") or []),
            created_at=int(raw.get("created_at") or 0),
        )

    @staticmethod
    def _evaluation_from_raw(raw: Dict[str, Any]) -> SufficiencyEvaluation:
        return SufficiencyEvaluation(
            evaluation_id=str(raw.get("evaluation_id") or ""),
            test_run_id=str(raw.get("test_run_id") or ""),
            scope=StatusScope(str(raw.get("scope"))),
            subject_id=str(raw.get("subject_id") or ""),
            evaluator_id=str(raw.get("evaluator_id") or ""),
            policy_version=str(raw.get("policy_version") or ""),
            result=SufficiencyResult(str(raw.get("result"))),
            dimension_refs=tuple(raw.get("dimension_refs") or []),
            evidence_refs=tuple(raw.get("evidence_refs") or []),
            satisfied_requirement_refs=tuple(raw.get("satisfied_requirement_refs") or []),
            unsatisfied_requirement_refs=tuple(raw.get("unsatisfied_requirement_refs") or []),
            unresolved_gap_ids=tuple(raw.get("unresolved_gap_ids") or []),
            accepted_waiver_ids=tuple(raw.get("accepted_waiver_ids") or []),
            explanation=str(raw.get("explanation") or ""),
            evaluated_at=int(raw.get("evaluated_at") or 0),
        )

    @staticmethod
    def _release_from_raw(raw: Dict[str, Any]) -> ReleaseDecisionRecord:
        return ReleaseDecisionRecord(
            release_decision_id=str(raw.get("release_decision_id") or ""),
            test_run_id=str(raw.get("test_run_id") or ""),
            decision=ReleaseDecision(str(raw.get("decision"))),
            mission_evaluation_ref=str(raw.get("mission_evaluation_ref") or ""),
            evidence_refs=tuple(raw.get("evidence_refs") or []),
            blocking_defect_refs=tuple(raw.get("blocking_defect_refs") or []),
            explanation=str(raw.get("explanation") or ""),
            recorded_at=int(raw.get("recorded_at") or 0),
        )
