"""Scope-aware sufficiency projection for multi-scope TestRounds.

A TestRound can contain several independent RequirementDeliveryScopes.  An
active gap owned by scope A must not prevent scope B from recording its own
STAGE-level SUFFICIENT evaluation.  Global release truth remains fail-closed:
MISSION-level SUFFICIENT is blocked by any active gap in the TestRun.
"""
from __future__ import annotations

from typing import Any, Mapping

from rc8_runtime.governance import GapStatus, StatusScope, SufficiencyEvaluation, SufficiencyResult

from .governance_event_projector import (
    GovernanceEventProjector,
    GovernanceProjectionInvalid,
    GovernanceProjectionPending,
    _required,
    _strings,
)


class ScopeAwareGovernanceEventProjector(GovernanceEventProjector):
    """Preserve local sufficiency independence and global mission strictness."""

    def _attempt(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        attempt_id = _required(event.get("attempt_id"), "attempt_id")
        existing = self.governance_repository.get_attempt(attempt_id)
        if existing is None:
            return super()._attempt(event, data)

        if _required(event.get("test_run_id"), "test_run_id") != existing.test_run_id:
            raise GovernanceProjectionInvalid("ATTEMPT_TEST_RUN_AUTHORITY_MISMATCH")
        if _required(event.get("work_item_id"), "work_item_id") != existing.work_item_id:
            raise GovernanceProjectionInvalid("ATTEMPT_WORK_ITEM_AUTHORITY_MISMATCH")
        if _required(event.get("node_id"), "node_id") != existing.producer_node_id:
            raise GovernanceProjectionInvalid("ATTEMPT_NODE_AUTHORITY_MISMATCH")

        supplied_stage = data.get("stage_instance_id")
        if supplied_stage is not None and _required(supplied_stage, "stage_instance_id") != existing.stage_instance_id:
            raise GovernanceProjectionInvalid("ATTEMPT_STAGE_AUTHORITY_MISMATCH")
        supplied_snapshot = data.get("input_snapshot_ref")
        if supplied_snapshot is not None and _required(supplied_snapshot, "input_snapshot_ref") != existing.input_snapshot_ref:
            raise GovernanceProjectionInvalid("ATTEMPT_INPUT_SNAPSHOT_AUTHORITY_MISMATCH")
        supplied_case = event.get("case_id")
        if supplied_case is not None and str(supplied_case) != str(existing.case_id):
            raise GovernanceProjectionInvalid("ATTEMPT_CASE_AUTHORITY_MISMATCH")

        normalized_event = dict(event)
        normalized_event["producer_ref"] = existing.producer_ref
        normalized_event["case_id"] = existing.case_id
        normalized_data = dict(data)
        normalized_data["stage_instance_id"] = existing.stage_instance_id
        normalized_data["input_snapshot_ref"] = existing.input_snapshot_ref
        normalized_data["started_at"] = existing.started_at
        return super()._attempt(normalized_event, normalized_data)

    def _sufficiency(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        evidence_refs = _strings(data.get("evidence_refs"), "evidence_refs")
        self._require_artifacts(evidence_refs)
        result = SufficiencyResult(str(data.get("result") or ""))
        scope = StatusScope(str(data.get("scope") or ""))
        unresolved = _strings(data.get("unresolved_gap_ids"), "unresolved_gap_ids")

        if result == SufficiencyResult.SUFFICIENT and unresolved:
            raise GovernanceProjectionPending(
                "SUFFICIENT_EVALUATION_HAS_UNRESOLVED_GAPS:%s" % ",".join(sorted(unresolved))
            )

        if result == SufficiencyResult.SUFFICIENT and scope == StatusScope.MISSION:
            active = [
                gap.gap_id
                for gap in self.governance_repository.list_gaps(str(event.get("test_run_id") or ""))
                if gap.status not in {GapStatus.CLOSED, GapStatus.WAIVED}
            ]
            if active:
                raise GovernanceProjectionPending(
                    "MISSION_SUFFICIENCY_BLOCKED_BY_ACTIVE_GAPS:%s" % ",".join(sorted(active))
                )

        evaluation = SufficiencyEvaluation(
            evaluation_id=_required(data.get("evaluation_id"), "evaluation_id"),
            test_run_id=_required(event.get("test_run_id"), "test_run_id"),
            scope=scope,
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
