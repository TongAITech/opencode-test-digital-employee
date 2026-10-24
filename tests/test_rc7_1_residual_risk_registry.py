from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_residual_risk import (
    ResidualRiskRegistry,
    ResidualRiskRegistryError,
)
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Evidence, Mission
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-RISK-REGISTRY"
RELEASE = "RC7.1-RISK-REGISTRY"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove residual risk is durable governed truth",
        ),
    )
    return truth, control


def _evidence(control: ClosedLoopControlPlane, evidence_id: str):
    append_entity(
        control.truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=MISSION,
            kind="RISK_SOURCE_EVIDENCE",
            source_ref="runtime://risk-test",
            content_ref="evidence://" + evidence_id,
            subject_refs=[MISSION],
        ),
        release_id=RELEASE,
    )


def test_residual_risk_is_append_only_and_requires_explicit_disposition(tmp_path: Path):
    truth, control = _control(tmp_path)
    _evidence(control, "EVD-RISK-SOURCE")
    _evidence(control, "EVD-RISK-ACCEPT")
    registry = ResidualRiskRegistry(evidence_root=str(tmp_path / "risk"))

    pending = registry.record(
        control,
        risk_id="RISK-001",
        source="N7/L6 performance observation",
        severity="HIGH",
        description="peak load has limited production-like duration evidence",
        reason="field traffic profile unavailable in controlled engineering",
        evidence_refs=["EVD-RISK-SOURCE"],
        owner="release-risk-owner",
    )
    assert pending.record.disposition == "PENDING"
    assert pending.record.revision == 1
    assert registry.summary(control)["all_dispositioned"] is False

    with pytest.raises(ResidualRiskRegistryError, match="RESIDUAL_RISK_ACCEPTANCE_REF_REQUIRED"):
        registry.disposition(
            control,
            risk_id="RISK-001",
            disposition="ACCEPTED",
            acceptance_ref="",
            evidence_refs=["EVD-RISK-ACCEPT"],
        )

    accepted = registry.disposition(
        control,
        risk_id="RISK-001",
        disposition="ACCEPTED",
        acceptance_ref="risk-acceptance://CAB-123",
        evidence_refs=["EVD-RISK-ACCEPT"],
    )
    assert accepted.record.revision == 2
    assert accepted.record.disposition == "ACCEPTED"
    assert accepted.record.acceptance_ref == "risk-acceptance://CAB-123"
    current = registry.current(control)["RISK-001"]
    assert current.artifact_id == accepted.artifact_id
    assert registry.summary(control)["all_dispositioned"] is True

    history = [
        row
        for row in truth.query("rc7_artifact", mission_id=MISSION)
        if row.get("artifact_type_name") == "RESIDUAL_RISK_RECORD"
    ]
    assert len(history) == 2
    assert pending.artifact_id != accepted.artifact_id
    events = [
        row.get("event_type_name")
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("subject_type") == "RESIDUAL_RISK"
    ]
    # Projection query order is not an R1 sequencing contract.  Lifecycle
    # ordering is preserved by the append-only raw stream; this assertion only
    # proves each canonical lifecycle event is durable and unique.
    assert sorted(events) == ["RESIDUAL_RISK_DISPOSITIONED", "RESIDUAL_RISK_RECORDED"]
    assert events.count("RESIDUAL_RISK_RECORDED") == 1
    assert events.count("RESIDUAL_RISK_DISPOSITIONED") == 1


def test_residual_risk_rejects_non_durable_or_cross_mission_evidence(tmp_path: Path):
    _, control = _control(tmp_path)
    registry = ResidualRiskRegistry(evidence_root=str(tmp_path / "risk"))

    with pytest.raises(ResidualRiskRegistryError, match="RESIDUAL_RISK_EVIDENCE_NOT_UNIQUE"):
        registry.record(
            control,
            risk_id="RISK-MISSING",
            source="N7",
            severity="MEDIUM",
            description="missing evidence must fail closed",
            reason="test",
            evidence_refs=["EVD-NOT-THERE"],
            owner="owner",
        )


def test_residual_risk_cannot_be_silently_replaced_or_redispositioned(tmp_path: Path):
    _, control = _control(tmp_path)
    _evidence(control, "EVD-RISK-1")
    _evidence(control, "EVD-RISK-2")
    registry = ResidualRiskRegistry(evidence_root=str(tmp_path / "risk"))
    registry.record(
        control,
        risk_id="RISK-STABLE",
        source="N10",
        severity="LOW",
        description="known residual limitation",
        reason="accepted scope boundary",
        evidence_refs=["EVD-RISK-1"],
        owner="risk-owner",
    )
    with pytest.raises(ResidualRiskRegistryError, match="RESIDUAL_RISK_ALREADY_EXISTS"):
        registry.record(
            control,
            risk_id="RISK-STABLE",
            source="N10",
            severity="LOW",
            description="attempt to overwrite",
            reason="bad mutation",
            evidence_refs=["EVD-RISK-1"],
            owner="risk-owner",
        )
    registry.disposition(
        control,
        risk_id="RISK-STABLE",
        disposition="MONITOR",
        acceptance_ref="monitor://risk-owner/1",
        evidence_refs=["EVD-RISK-2"],
    )
    with pytest.raises(ResidualRiskRegistryError, match="RESIDUAL_RISK_ALREADY_DISPOSITIONED"):
        registry.disposition(
            control,
            risk_id="RISK-STABLE",
            disposition="DEFERRED",
            acceptance_ref="defer://2",
            evidence_refs=["EVD-RISK-2"],
        )
