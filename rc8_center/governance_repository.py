"""Durable Center repository/projection for RC8 governance facts.

This is the dependency-free W-A fallback.  The same domain contract can later be
backed by PostgreSQL without changing Mission/Gap/Sufficiency semantics.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

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

from .json_repository import DurableRepositoryError, _AtomicJsonFile, _jsonable


class JsonFileGovernanceRepository:
    """Durable Center-side governance fact store.

    Attempts, coverage metrics, evaluations, invalidations and release decisions
    are append-only.  Stage/Gap records may advance state while preserving their
    stable identity and historical facts.
    """

    def __init__(self, path: str) -> None:
        self._file = _AtomicJsonFile(
            path,
            {
                "schema_version": 1,
                "stages": {},
                "attempts": {},
                "gaps": {},
                "coverage": {},
                "invalidations": {},
                "evaluations": {},
                "release_decisions": {},
            },
        )

    @staticmethod
    def _require_bucket(data: Dict[str, Any], name: str) -> Dict[str, Any]:
        value = data.setdefault(name, {})
        if not isinstance(value, dict):
            raise DurableRepositoryError("GOVERNANCE_BUCKET_INVALID:%s" % name)
        return value

    @staticmethod
    def _append(data: Dict[str, Any], bucket: str, key: str, value: Any) -> None:
        rows = JsonFileGovernanceRepository._require_bucket(data, bucket)
        if key in rows:
            raise DurableRepositoryError("GOVERNANCE_APPEND_ONLY:%s:%s" % (bucket, key))
        rows[key] = _jsonable(value)

    def upsert_stage(self, stage: StageInstance) -> None:
        def apply(data: Dict[str, Any]) -> None:
            rows = self._require_bucket(data, "stages")
            previous = rows.get(stage.stage_instance_id)
            if isinstance(previous, dict):
                if str(previous.get("test_run_id")) != stage.test_run_id or str(previous.get("stage_type")) != stage.stage_type:
                    raise DurableRepositoryError("STAGE_IDENTITY_IMMUTABLE")
                if int(previous.get("attempt_no") or 0) != stage.attempt_no:
                    raise DurableRepositoryError("STAGE_ATTEMPT_IDENTITY_IMMUTABLE")
            rows[stage.stage_instance_id] = _jsonable(stage)
        self._file.mutate(apply)

    def append_attempt(self, attempt: AttemptRecord) -> None:
        self._file.mutate(lambda data: self._append(data, "attempts", attempt.attempt_id, attempt))

    def upsert_gap(self, gap: GapRecord) -> None:
        def apply(data: Dict[str, Any]) -> None:
            rows = self._require_bucket(data, "gaps")
            previous = rows.get(gap.gap_id)
            if isinstance(previous, dict):
                immutable = ("test_run_id", "source_stage_instance_id", "gap_type", "opened_at")
                for key in immutable:
                    if previous.get(key) != _jsonable(gap).get(key):
                        raise DurableRepositoryError("GAP_IDENTITY_IMMUTABLE:%s" % key)
            rows[gap.gap_id] = _jsonable(gap)
        self._file.mutate(apply)

    def append_coverage(self, metric: CoverageMetric) -> None:
        self._file.mutate(lambda data: self._append(data, "coverage", metric.metric_id, metric))

    def append_invalidation(self, value: InvalidationRecord) -> None:
        self._file.mutate(lambda data: self._append(data, "invalidations", value.invalidation_id, value))

    def append_evaluation(self, value: SufficiencyEvaluation) -> None:
        self._file.mutate(lambda data: self._append(data, "evaluations", value.evaluation_id, value))

    def append_release_decision(self, value: ReleaseDecisionRecord) -> None:
        self._file.mutate(lambda data: self._append(data, "release_decisions", value.release_decision_id, value))

    def get_stage(self, stage_instance_id: str) -> Optional[StageInstance]:
        raw = self._file.read().get("stages", {}).get(stage_instance_id)
        return self._stage_from_raw(raw) if isinstance(raw, dict) else None

    def get_gap(self, gap_id: str) -> Optional[GapRecord]:
        raw = self._file.read().get("gaps", {}).get(gap_id)
        return self._gap_from_raw(raw) if isinstance(raw, dict) else None

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

    def list_coverage(self) -> List[CoverageMetric]:
        rows = self._bucket("coverage")
        return sorted([self._coverage_from_raw(raw) for raw in rows.values() if isinstance(raw, dict)], key=lambda item: item.metric_id)

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
        active_gaps = [gap for gap in gaps if gap.status not in {GapStatus.CLOSED, GapStatus.WAIVED}]
        mission_evals = [item for item in evaluations if item.scope == StatusScope.MISSION]
        latest_mission = mission_evals[-1] if mission_evals else None
        latest_release = releases[-1] if releases else None
        return {
            "schema_version": "rc8.governance-projection.v1",
            "test_run_id": test_run_id,
            "stage_count": len(stages),
            "attempt_count": len(attempts),
            "active_gap_count": len(active_gaps),
            "stages": [_jsonable(item) for item in stages],
            "attempts": [_jsonable(item) for item in attempts],
            "gaps": [_jsonable(item) for item in gaps],
            "invalidations": [_jsonable(item) for item in invalidations],
            "evaluations": [_jsonable(item) for item in evaluations],
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
    def _coverage_from_raw(raw: Dict[str, Any]) -> CoverageMetric:
        return CoverageMetric(
            metric_id=str(raw.get("metric_id") or ""),
            dimension=CoverageDimension(str(raw.get("dimension"))),
            covered=int(raw.get("covered") or 0),
            total=int(raw.get("total") or 0),
            threshold=float(raw.get("threshold") or 0.0),
            evidence_refs=tuple(raw.get("evidence_refs") or []),
            critical=bool(raw.get("critical", False)),
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
