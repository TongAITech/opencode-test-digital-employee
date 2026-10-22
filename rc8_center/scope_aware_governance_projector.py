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
    GovernanceProjectionPending,
    _required,
    _strings,
)


class ScopeAwareGovernanceEventProjector(GovernanceEventProjector):
    """Preserve local sufficiency independence and global mission strictness."""

    def _sufficiency(self, event: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        evidence_refs = _strings(data.get("evidence_refs"), "evidence_refs")
        self._require_artifacts(evidence_refs)
        result = SufficiencyResult(str(data.get("result") or ""))
        scope = StatusScope(str(data.get("scope") or ""))
        unresolved = _strings(data.get("unresolved_gap_ids"), "unresolved_gap_ids")

        # The domain object also enforces this, but keeping it explicit here
        # produces a projection-level fail-closed reason before persistence.
        if result == SufficiencyResult.SUFFICIENT and unresolved:
            raise GovernanceProjectionPending(
                "SUFFICIENT_EVALUATION_HAS_UNRESOLVED_GAPS:%s" % ",".join(sorted(unresolved))
            )

        # Only the mission is a global release gate.  Stage/layer/case
        # evaluations are local facts and must not be contaminated by an
        # unrelated scope's gap.  The eventual Mission evaluation still sees
        # every OPEN/PARTIALLY_REPAIRED gap and therefore cannot fake release.
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
