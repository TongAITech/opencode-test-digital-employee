from __future__ import annotations

import pytest

from rc7_runtime import Mission, MissionStatus
from rc7_runtime.mission_sufficiency import (
    MissionEvidenceSnapshot,
    MissionSufficiencyClosedLoop,
    MissionSufficiencyError,
    ResidualRisk,
)


def _snapshot(**overrides):
    values = dict(
        mission_id="MISSION-1",
        release_id="RC7",
        snapshot_ref="ART-MISSION-SNAPSHOT-1",
        evidence_refs=("EVD-MISSION-1",),
        critical_requirements_total=2,
        critical_requirements_verified=2,
        unverified_requirement_refs=(),
        critical_obligations_total=3,
        critical_obligations_verified=3,
        unverified_obligation_refs=(),
        critical_branches_total=2,
        critical_branches_verified=2,
        unverified_branch_refs=(),
        critical_executions_total=3,
        critical_executions_conclusive=3,
        inconclusive_execution_refs=(),
    )
    values.update(overrides)
    return MissionEvidenceSnapshot(**values)


def _evaluating_mission():
    return Mission(
        mission_id="MISSION-1",
        release_id="RC7",
        goal="Reach trustworthy test sufficiency",
        state=MissionStatus.EVALUATING,
    )


def test_workflow_cannot_converge_when_one_critical_branch_is_unverified() -> None:
    loop = MissionSufficiencyClosedLoop()
    snapshot = _snapshot(
        critical_branches_verified=1,
        unverified_branch_refs=("BR-CRITICAL-2",),
    )
    result = loop.evaluate(snapshot)

    assert result.evaluation.result.value == "REPAIR_REQUIRED"
    assert result.sufficiency_state == "NOT_SUFFICIENT"
    assert result.release_recommendation == "NOT_RECOMMENDED"
    assert any(
        gap.category == "CRITICAL_BRANCH_UNVERIFIED" and gap.target_node == "EXECUTION"
        for gap in result.gaps
    )

    mission = loop.apply_to_mission(_evaluating_mission(), snapshot, result)
    assert mission.state == MissionStatus.REPAIRING
    assert mission.sufficiency_state == "NOT_SUFFICIENT"
    with pytest.raises(MissionSufficiencyError, match="FINAL_REPORT_REQUIRES_CONVERGED_MISSION"):
        loop.build_final_report_projection(mission, snapshot, result)


def test_open_high_defect_blocks_technical_sufficiency() -> None:
    result = MissionSufficiencyClosedLoop().evaluate(
        _snapshot(open_high_defect_refs=("DEFECT-HIGH-1",))
    )
    assert result.evaluation.result.value == "REPAIR_REQUIRED"
    assert any(gap.category == "OPEN_HIGH_DEFECT" for gap in result.gaps)
    assert result.release_recommendation == "NOT_RECOMMENDED"


def test_pending_residual_risk_requires_acceptance_and_cannot_publish_final_report() -> None:
    loop = MissionSufficiencyClosedLoop()
    risk = ResidualRisk(
        risk_id="RR-CONCURRENCY-1",
        severity="MEDIUM",
        description="production-scale concurrency is not fully reproduced",
        evidence_refs=("EVD-CONCURRENCY-1",),
        disposition="PENDING",
    )
    snapshot = _snapshot(residual_risks=(risk,))
    result = loop.evaluate(snapshot)

    assert result.evaluation.result.value == "HUMAN_REQUIRED"
    assert result.sufficiency_state == "RISK_ACCEPTANCE_REQUIRED"
    assert result.release_recommendation == "RISK_ACCEPTANCE_REQUIRED"
    assert any(gap.category == "RESIDUAL_RISK_REQUIRES_ACCEPTANCE" for gap in result.gaps)

    mission = loop.apply_to_mission(_evaluating_mission(), snapshot, result)
    assert mission.state == MissionStatus.WAITING_HUMAN
    with pytest.raises(MissionSufficiencyError):
        loop.build_final_report_projection(mission, snapshot, result)


def test_accepted_residual_risk_can_converge_but_release_is_conditional() -> None:
    loop = MissionSufficiencyClosedLoop()
    risk = ResidualRisk(
        risk_id="RR-CONCURRENCY-1",
        severity="MEDIUM",
        description="production-scale concurrency is not fully reproduced",
        evidence_refs=("EVD-CONCURRENCY-1",),
        disposition="ACCEPTED",
        acceptance_ref="HUMAN-GATE-ACCEPT-1",
    )
    snapshot = _snapshot(residual_risks=(risk,))
    result = loop.evaluate(snapshot)

    assert result.evaluation.result.value == "PASS"
    assert result.sufficiency_state == "SUFFICIENT_WITH_RESIDUAL_RISK"
    assert result.release_recommendation == "CONDITIONAL"
    assert result.report_ready is True

    mission = loop.apply_to_mission(_evaluating_mission(), snapshot, result)
    assert mission.state == MissionStatus.CONVERGED
    assert mission.sufficiency_state == "SUFFICIENT_WITH_RESIDUAL_RISK"

    report = loop.build_final_report_projection(mission, snapshot, result)
    assert report["source"] == "R1_EVENT_STREAM_PROJECTION"
    assert report["test_sufficiency"] == "SUFFICIENT_WITH_RESIDUAL_RISK"
    assert report["release_recommendation"] == "CONDITIONAL"
    assert report["mission_evaluation_id"] == result.evaluation.evaluation_id


def test_zero_gaps_and_zero_residual_risk_is_sufficient_and_recommended() -> None:
    loop = MissionSufficiencyClosedLoop()
    snapshot = _snapshot()
    result = loop.evaluate(snapshot)
    assert result.evaluation.result.value == "PASS"
    assert result.sufficiency_state == "SUFFICIENT"
    assert result.release_recommendation == "RECOMMENDED"
    mission = loop.apply_to_mission(_evaluating_mission(), snapshot, result)
    assert mission.state == MissionStatus.CONVERGED
