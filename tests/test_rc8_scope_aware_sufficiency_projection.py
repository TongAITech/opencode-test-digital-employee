from __future__ import annotations

from types import SimpleNamespace

import pytest

from rc8_center.governance_event_projector import GovernanceProjectionPending
from rc8_center.scope_aware_governance_projector import ScopeAwareGovernanceEventProjector
from rc8_runtime import ArtifactAvailability
from rc8_runtime.governance import GapStatus, StatusScope, SufficiencyResult


class FakeGovernanceRepository:
    def __init__(self):
        self.gaps = []
        self.evaluations = []

    def list_gaps(self, test_run_id):
        assert test_run_id == "TR"
        return list(self.gaps)

    def append_evaluation(self, value):
        self.evaluations.append(value)


class FakeArtifactRepository:
    def get(self, artifact_id):
        assert artifact_id == "EVIDENCE"
        return SimpleNamespace(availability=ArtifactAvailability.AVAILABLE)


class FakeCoverageRepository:
    pass


def _projector():
    governance = FakeGovernanceRepository()
    return ScopeAwareGovernanceEventProjector(
        ledger=None,
        governance_repository=governance,
        coverage_repository=FakeCoverageRepository(),
        artifact_repository=FakeArtifactRepository(),
    ), governance


def _data(*, scope: str, subject_id: str, evaluation_id: str):
    return {
        "evaluation_id": evaluation_id,
        "scope": scope,
        "subject_id": subject_id,
        "evaluator_id": "POLICY",
        "policy_version": "v1",
        "result": "SUFFICIENT",
        "dimension_refs": ["dimension:traceability"],
        "evidence_refs": ["artifact:EVIDENCE"],
        "satisfied_requirement_refs": ["dimension:traceability"],
        "unsatisfied_requirement_refs": [],
        "unresolved_gap_ids": [],
        "accepted_waiver_ids": [],
        "explanation": "sufficient",
    }


def test_unrelated_scope_gap_does_not_block_stage_sufficient_fact() -> None:
    projector, governance = _projector()
    governance.gaps.append(SimpleNamespace(gap_id="GAP-SCOPE-A", status=GapStatus.OPEN))
    ref = projector._sufficiency(
        {"test_run_id": "TR", "occurred_at": 10},
        _data(scope="STAGE", subject_id="STAGE-SCOPE-B", evaluation_id="EVAL-B"),
    )
    assert ref == "evaluation:EVAL-B"
    assert len(governance.evaluations) == 1
    assert governance.evaluations[0].scope == StatusScope.STAGE
    assert governance.evaluations[0].result == SufficiencyResult.SUFFICIENT


def test_any_active_scope_gap_still_blocks_mission_sufficient_fact() -> None:
    projector, governance = _projector()
    governance.gaps.append(SimpleNamespace(gap_id="GAP-SCOPE-A", status=GapStatus.OPEN))
    with pytest.raises(GovernanceProjectionPending) as exc:
        projector._sufficiency(
            {"test_run_id": "TR", "occurred_at": 10},
            _data(scope="MISSION", subject_id="MISSION", evaluation_id="EVAL-MISSION"),
        )
    assert str(exc.value) == "MISSION_SUFFICIENCY_BLOCKED_BY_ACTIVE_GAPS:GAP-SCOPE-A"
    assert governance.evaluations == []


def test_stage_sufficient_cannot_claim_unresolved_gap_ids() -> None:
    projector, governance = _projector()
    body = _data(scope="STAGE", subject_id="STAGE", evaluation_id="EVAL")
    body["unresolved_gap_ids"] = ["GAP-LOCAL"]
    with pytest.raises(GovernanceProjectionPending) as exc:
        projector._sufficiency({"test_run_id": "TR", "occurred_at": 10}, body)
    assert str(exc.value) == "SUFFICIENT_EVALUATION_HAS_UNRESOLVED_GAPS:GAP-LOCAL"
    assert governance.evaluations == []
