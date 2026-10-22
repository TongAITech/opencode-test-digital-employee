"""Replayable R1 -> governance/coverage projection engine.

Nodes never write Center governance state directly. They append authorized
runtime facts to R1. This projector consumes the persisted ledger and builds
rebuildable product/domain projections. Projection can be retried after Center
restart or after referenced artifacts become AVAILABLE.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rc8_runtime import ArtifactAvailability, CentralR1RuntimeLedger
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
    StatusScope,
    SufficiencyEvaluation,
    SufficiencyResult,
    route_gap,
)

from .coverage_repository import JsonFileCoverageRepository
from .governance_repository import JsonFileGovernanceRepository
from .json_repository import JsonFileArtifactRepository


class GovernanceProjectionPending(RuntimeError):
    pass


class GovernanceProjectionInvalid(RuntimeError):
    pass


_PROJECTED_EVENT_TYPES = {
    "ATTEMPT_STARTED",
    "ATTEMPT_COMPLETED",
    "ATTEMPT_FAILED_RUNTIME",
    "ATTEMPT_BLOCKED",
    "COVERAGE_COLLECTED",
    "GAP_OPENED",
    "GAP_CLOSED",
    "INVALIDATION_RECORDED",
    "SUFFICIENCY_EVALUATED",
    "RELEASE_DECISION_RECORDED",
}


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GovernanceProjectionInvalid("%s_REQUIRED" % name.upper())
    return value.strip()


def _strings(value: Any, name: str) -> Tuple[str, ...]:
    if value is None:
        return tuple()
    if not isinstance(value, (list, tuple)):
        raise GovernanceProjectionInvalid("%s_MUST_BE_LIST" % name.upper())
    result: List[str] = []
    for item in value:
        result.append(_required(item, name))
    return tuple(result)


def _int(value: Any, name: str) -> int:
    if not isinstance(value, int):
        raise GovernanceProjectionInvalid("%s_MUST_BE_INT" % name.upper())
    return value


def _artifact_id(ref: str) -> str:
    value = _required(ref, "artifact_ref")
    return value.split(":", 1)[1] if value.startswith("artifact:") else value


class GovernanceEventProjector:
    def __init__(
        self,
        ledger: CentralR1RuntimeLedger,
        governance_repository: JsonFileGovernanceRepository,
        coverage_repository: JsonFileCoverageRepository,
        artifact_repository: JsonFileArtifactRepository,
    ) -> None:
        self.ledger = ledger
        self.governance_repository = governance_repository
        self.coverage_repository = coverage_repository
        self.artifact_repository = artifact_repository

    def ingest(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        """Project only after the caller has already persisted the event to R1.

        The body is used only to identify the just-submitted event receipt; the
        actual projection source is the canonical ledger replay.
        """
        event_id = _required(body.get("event_id"), "event_id")
        summary = self.replay()
        receipt = self.governance_repository.projection_receipt(event_id)
        return {
            "event_id": event_id,
            "projection": receipt or {"status": "PENDING", "detail": "R1_EVENT_NOT_PROJECTED"},
            "replay": summary,
        }

    def replay(self) -> Dict[str, Any]:
        projected = 0
        pending = 0
        ignored = 0
        errors: List[Dict[str, str]] = []
        for event in self.ledger.runtime_events():
            event_id = str(event.get("event_id") or "")
            event_type = str(event.get("event_type") or "")
            test_run_id = str(event.get("test_run_id") or "")
            previous = self.governance_repository.projection_receipt(event_id)
            if previous and previous.get("status") in {"PROJECTED", "IGNORED"}:
                continue
            if event_type not in _PROJECTED_EVENT_TYPES:
                self.governance_repository.mark_projection(
                    event_id=event_id,
                    test_run_id=test_run_id,
                    event_type=event_type,
                    status="IGNORED",
                    detail="EVENT_TYPE_NOT_GOVERNANCE_PROJECTION",
                )
                ignored += 1
                continue
            try:
                domain_ref = self._project(event)
            except GovernanceProjectionPending as exc:
                self.governance_repository.mark_projection(
                    event_id=event_id,
                    test_run_id=test_run_id,
                    event_type=event_type,
                    status="PENDING",
                    detail=str(exc),
                )
                pending += 1
                continue
            except Exception as exc:
                # R1 remains truth even when the projection contract is invalid.
                # Fail closed by leaving a visible pending projection; never
                # manufacture a domain PASS from malformed runtime data.
                detail = "PROJECTION_CONTRACT_ERROR:%s" % str(exc)
                self.governance_repository.mark_projection(
                    event_id=event_id,
                    test_run_id=test_run_id,
                    event_type=event_type,
                    status="PENDING",
                    detail=detail,
                )
                errors.append({"event_id": event_id, "error": detail})
                pending += 1
                continue
            self.governance_repository.mark_projection(
                event_id=event_id,
                test_run_id=test_run_id,
                event_type=event_type,
                status="PROJECTED",
                domain_ref=domain_ref,
            )
            projected += 1
        return {
            "status": "REPLAY_COMPLETE" if not errors else "REPLAY_WITH_PROJECTION_ERRORS",
            "projected": projected,
            "pending": pending,
            "ignored": ignored,
            "errors": errors,
        }

    def _project(self, event: Mapping[str, Any]) -> str:
        event_type = _required(event.get("event_type"), "event_type")
        data = event.get("data")
        if not isinstance(data, dict):
            raise GovernanceProjectionInvalid("EVENT_DATA_OBJECT_REQUIRED")
        if event_type.startswith("ATTEMPT_"):
            return self._attempt(event, data)
        if event_type == "COVERAGE_COLLECTED":
            return self._coverage(event, data)
        if event_type == "GAP_OPENED":
            return self._gap_open(event, data)
        if event_type == "GAP_CLOSED":
            return self._gap_close(event, data)
        if event_type == "INVALIDATION_RECORDED":
            return self._invalidation(event, data)
        if event_type == "SUFFICIENCY_EVALUATED":
            return self._sufficiency(event, data)
        if event_type == "RELEASE_DECISION_RECORDED":
            return self._release(event, data)
        raise GovernanceProjectionInvalid("EVENT_TYPE_UNSUPPORTED:%s" % event_type)

    def _require_stage(self, stage_instance_id: str):
        stage = self.governance_repository.get_stage(stage_instance_id)
        if stage is None:
            raise GovernanceProjectionPending("STAGE_NOT_YET_REGISTERED:%s" % stage_instance_id)
        return stage

    def _require_artifacts(self, refs: Sequence[str]) -> None:
        for ref in refs:
            artifact_id = _artifact_id(ref)
            manifest = self.artifact_repository.get(artifact_id)
            if manifest is None:
                raise GovernanceProjectionPending("ARTIFACT_NOT_FOUND:%s" % artifact_id)
            if manifest.availability != ArtifactAvailability.AVAILABLE:
                raise GovernanceProjectionPending("ARTIFACT_NOT_AVAILABLE:%s" % artifact_id)

    def _attempt(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        event_type = str(event["event_type"])
        attempt_id = _required(event.get("attempt_id"), "attempt_id")
        stage_id = _required(data.get("stage_instance_id"), "stage_instance_id")
        self._require_stage(stage_id)
        status = {
            "ATTEMPT_STARTED": AttemptStatus.STARTED,
            "ATTEMPT_COMPLETED": AttemptStatus.COMPLETED,
            "ATTEMPT_FAILED_RUNTIME": AttemptStatus.FAILED_RUNTIME,
            "ATTEMPT_BLOCKED": AttemptStatus.BLOCKED,
        }[event_type]
        evidence_refs = _strings(data.get("evidence_refs"), "evidence_refs")
        if status != AttemptStatus.STARTED:
            self._require_artifacts(evidence_refs)
        existing = self.governance_repository.get_attempt(attempt_id)
        started_at = int(data.get("started_at") if data.get("started_at") is not None else event.get("occurred_at") or 0)
        if existing is not None:
            started_at = existing.started_at
        finished_at = None
        if status != AttemptStatus.STARTED:
            finished_at = int(data.get("finished_at") if data.get("finished_at") is not None else event.get("occurred_at") or 0)
        ownership_raw = data.get("failure_ownership")
        ownership = FailureOwnership(str(ownership_raw)) if ownership_raw is not None else (existing.failure_ownership if existing else None)
        record = AttemptRecord(
            attempt_id=attempt_id,
            test_run_id=_required(event.get("test_run_id"), "test_run_id"),
            stage_instance_id=stage_id,
            work_item_id=_required(event.get("work_item_id"), "work_item_id"),
            producer_node_id=_required(event.get("node_id"), "node_id"),
            producer_ref=_required(event.get("producer_ref"), "producer_ref"),
            input_snapshot_ref=_required(data.get("input_snapshot_ref"), "input_snapshot_ref"),
            status=status,
            case_id=str(event["case_id"]) if event.get("case_id") is not None else None,
            action_refs=_strings(data.get("action_refs"), "action_refs"),
            assertion_refs=_strings(data.get("assertion_refs"), "assertion_refs"),
            evidence_refs=evidence_refs,
            coverage_refs=_strings(data.get("coverage_refs"), "coverage_refs"),
            gap_refs=_strings(data.get("gap_refs"), "gap_refs"),
            defect_refs=_strings(data.get("defect_refs"), "defect_refs"),
            failure_ownership=ownership,
            started_at=started_at,
            finished_at=finished_at,
        )
        # Preserve previously accumulated refs when a terminal event carries only
        # the delta; projection is monotonic, never destructive.
        if existing is not None:
            record = replace(
                record,
                action_refs=tuple(dict.fromkeys(existing.action_refs + record.action_refs)),
                assertion_refs=tuple(dict.fromkeys(existing.assertion_refs + record.assertion_refs)),
                evidence_refs=tuple(dict.fromkeys(existing.evidence_refs + record.evidence_refs)),
                coverage_refs=tuple(dict.fromkeys(existing.coverage_refs + record.coverage_refs)),
                gap_refs=tuple(dict.fromkeys(existing.gap_refs + record.gap_refs)),
                defect_refs=tuple(dict.fromkeys(existing.defect_refs + record.defect_refs)),
            )
        self.governance_repository.upsert_attempt(record)
        return "attempt:%s" % attempt_id

    def _coverage(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        stage_id = _required(data.get("stage_instance_id"), "stage_instance_id")
        self._require_stage(stage_id)
        metric_raw = data.get("metric")
        if not isinstance(metric_raw, dict):
            raise GovernanceProjectionInvalid("COVERAGE_METRIC_OBJECT_REQUIRED")
        evidence_refs = _strings(metric_raw.get("evidence_refs"), "metric.evidence_refs")
        artifact_refs = _strings(data.get("artifact_refs"), "artifact_refs")
        self._require_artifacts(tuple(dict.fromkeys(evidence_refs + artifact_refs)))
        metric = CoverageMetric(
            metric_id=_required(metric_raw.get("metric_id"), "metric_id"),
            dimension=CoverageDimension(str(metric_raw.get("dimension") or "")),
            covered=_int(metric_raw.get("covered"), "covered"),
            total=_int(metric_raw.get("total"), "total"),
            threshold=float(metric_raw.get("threshold")),
            evidence_refs=evidence_refs,
            critical=bool(metric_raw.get("critical", False)),
        )
        observation = CoverageObservation(
            observation_id=_required(data.get("observation_id"), "observation_id"),
            test_run_id=_required(event.get("test_run_id"), "test_run_id"),
            stage_instance_id=stage_id,
            subject_ref=_required(data.get("subject_ref"), "subject_ref"),
            source_snapshot_ref=_required(data.get("source_snapshot_ref"), "source_snapshot_ref"),
            metric=metric,
            attempt_id=str(event["attempt_id"]) if event.get("attempt_id") is not None else None,
            case_id=str(event["case_id"]) if event.get("case_id") is not None else None,
            source_tool=str(data["source_tool"]) if data.get("source_tool") is not None else None,
            artifact_refs=artifact_refs,
            observed_at=int(event.get("occurred_at") or 0),
        )
        self.coverage_repository.append(observation)
        return "coverage:%s" % observation.observation_id

    def _gap_open(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        stage_id = _required(data.get("source_stage_instance_id"), "source_stage_instance_id")
        self._require_stage(stage_id)
        gap_type = GapType(str(data.get("gap_type") or ""))
        owner_stage = _required(data.get("owner_stage"), "owner_stage")
        expected_owner = route_gap(gap_type)
        if owner_stage != expected_owner:
            raise GovernanceProjectionInvalid("GAP_OWNER_ROUTE_MISMATCH:%s!=%s" % (owner_stage, expected_owner))
        evidence_refs = _strings(data.get("evidence_refs"), "evidence_refs")
        self._require_artifacts(evidence_refs)
        record = GapRecord(
            gap_id=_required(data.get("gap_id"), "gap_id"),
            test_run_id=_required(event.get("test_run_id"), "test_run_id"),
            source_stage_instance_id=stage_id,
            gap_type=gap_type,
            severity=GapSeverity(str(data.get("severity") or "")),
            description=_required(data.get("description"), "description"),
            owner_stage=owner_stage,
            repair_strategy=_required(data.get("repair_strategy"), "repair_strategy"),
            status=GapStatus.OPEN,
            source_attempt_id=str(event["attempt_id"]) if event.get("attempt_id") is not None else None,
            source_case_id=str(event["case_id"]) if event.get("case_id") is not None else None,
            source_assertion_id=str(data["source_assertion_id"]) if data.get("source_assertion_id") is not None else None,
            evidence_refs=evidence_refs,
            invalidates=_strings(data.get("invalidates"), "invalidates"),
            opened_at=int(event.get("occurred_at") or 0),
        )
        self.governance_repository.upsert_gap(record)
        return "gap:%s" % record.gap_id

    def _gap_close(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        gap_id = _required(data.get("gap_id"), "gap_id")
        current = self.governance_repository.get_gap(gap_id)
        if current is None:
            raise GovernanceProjectionPending("GAP_NOT_YET_OPEN:%s" % gap_id)
        closure_refs = _strings(data.get("closure_evidence_refs"), "closure_evidence_refs")
        self._require_artifacts(closure_refs)
        updated = replace(
            current,
            status=GapStatus.CLOSED,
            closure_evidence_refs=tuple(dict.fromkeys(current.closure_evidence_refs + closure_refs)),
            closed_at=int(event.get("occurred_at") or 0),
        )
        self.governance_repository.upsert_gap(updated)
        return "gap:%s" % gap_id

    def _invalidation(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        evidence_refs = _strings(data.get("evidence_refs"), "evidence_refs")
        self._require_artifacts(evidence_refs)
        record = InvalidationRecord(
            invalidation_id=_required(data.get("invalidation_id"), "invalidation_id"),
            test_run_id=_required(event.get("test_run_id"), "test_run_id"),
            source_ref=_required(data.get("source_ref"), "source_ref"),
            target_refs=_strings(data.get("target_refs"), "target_refs"),
            reason=_required(data.get("reason"), "reason"),
            evidence_refs=evidence_refs,
            created_at=int(event.get("occurred_at") or 0),
        )
        self.governance_repository.append_invalidation(record)
        return "invalidation:%s" % record.invalidation_id

    def _sufficiency(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        evidence_refs = _strings(data.get("evidence_refs"), "evidence_refs")
        self._require_artifacts(evidence_refs)
        result = SufficiencyResult(str(data.get("result") or ""))
        unresolved = _strings(data.get("unresolved_gap_ids"), "unresolved_gap_ids")
        if result == SufficiencyResult.SUFFICIENT:
            active = [
                gap.gap_id
                for gap in self.governance_repository.list_gaps(str(event.get("test_run_id") or ""))
                if gap.status not in {GapStatus.CLOSED, GapStatus.WAIVED}
            ]
            if active:
                raise GovernanceProjectionPending("SUFFICIENCY_BLOCKED_BY_ACTIVE_GAPS:%s" % ",".join(sorted(active)))
        evaluation = SufficiencyEvaluation(
            evaluation_id=_required(data.get("evaluation_id"), "evaluation_id"),
            test_run_id=_required(event.get("test_run_id"), "test_run_id"),
            scope=StatusScope(str(data.get("scope") or "")),
            subject_id=_required(data.get("subject_id"), "subject_id"),
            evaluator_id=_required(data.get("evaluator_id"), "evaluator_id"),
            policy_version=_required(data.get("policy_version"), "policy_version"),
            result=result,
            dimension_refs=_strings(data.get("dimension_refs"), "dimension_refs"),
            evidence_refs=evidence_refs,
            satisfied_requirement_refs=_strings(data.get("satisfied_requirement_refs"), "satisfied_requirement_refs"),
            unsatisfied_requirement_refs=_strings(data.get("unsatisfied_requirement_refs"), "unsatisfied_requirement_refs"),
            unresolved_gap_ids=unresolved,
            accepted_waiver_ids=_strings(data.get("accepted_waiver_ids"), "accepted_waiver_ids"),
            explanation=_required(data.get("explanation"), "explanation"),
            evaluated_at=int(event.get("occurred_at") or 0),
        )
        self.governance_repository.append_evaluation(evaluation)
        return "evaluation:%s" % evaluation.evaluation_id

    def _release(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        evidence_refs = _strings(data.get("evidence_refs"), "evidence_refs")
        self._require_artifacts(evidence_refs)
        decision = ReleaseDecision(str(data.get("decision") or ""))
        mission_eval_ref = _required(data.get("mission_evaluation_ref"), "mission_evaluation_ref")
        mission_eval = self.governance_repository.get_evaluation(mission_eval_ref)
        if mission_eval is None:
            raise GovernanceProjectionPending("MISSION_EVALUATION_NOT_FOUND:%s" % mission_eval_ref)
        if decision == ReleaseDecision.PASS:
            if mission_eval.scope != StatusScope.MISSION or mission_eval.result != SufficiencyResult.SUFFICIENT:
                raise GovernanceProjectionPending("RELEASE_PASS_REQUIRES_SUFFICIENT_MISSION")
        record = ReleaseDecisionRecord(
            release_decision_id=_required(data.get("release_decision_id"), "release_decision_id"),
            test_run_id=_required(event.get("test_run_id"), "test_run_id"),
            decision=decision,
            mission_evaluation_ref=mission_eval_ref,
            evidence_refs=evidence_refs,
            blocking_defect_refs=_strings(data.get("blocking_defect_refs"), "blocking_defect_refs"),
            explanation=_required(data.get("explanation"), "explanation"),
            recorded_at=int(event.get("occurred_at") or 0),
        )
        self.governance_repository.append_release_decision(record)
        return "release:%s" % record.release_decision_id
