from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_n10_governed import GovernedAutonomousN10Service
from rc7_runtime.autonomous_residual_risk import ResidualRiskRegistry
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_convergence_conformance import MissionConvergenceConformanceChecker
from rc7_runtime.models import Artifact, Evidence, Mission
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-RISK-HISTORY"
RELEASE = "RC7.1-RISK-HISTORY"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove current residual risk receipt selection across append-only history",
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
            source_ref="runtime://risk-history-test",
            content_ref="evidence://" + evidence_id,
            subject_refs=[MISSION],
        ),
        release_id=RELEASE,
    )


def _seed_current_risk(control: ClosedLoopControlPlane, tmp_path: Path):
    _evidence(control, "EVD-RISK-HISTORY-SOURCE")
    _evidence(control, "EVD-RISK-HISTORY-DISPOSITION")
    registry = ResidualRiskRegistry(evidence_root=str(tmp_path / "risk"))
    registry.record(
        control,
        risk_id="RISK-CURRENT",
        source="N7/L6",
        severity="MEDIUM",
        description="bounded performance profile remains as residual risk",
        reason="controlled environment cannot reproduce all bank traffic characteristics",
        evidence_refs=["EVD-RISK-HISTORY-SOURCE"],
        owner="risk-owner",
    )
    registry.disposition(
        control,
        risk_id="RISK-CURRENT",
        disposition="MONITOR",
        acceptance_ref="monitor://CAB/current-risk",
        evidence_refs=["EVD-RISK-HISTORY-DISPOSITION"],
    )
    return registry


def _persist_stale_history_receipt(control: ClosedLoopControlPlane, tmp_path: Path):
    payload = {
        "schema_version": "RC7_1_RESIDUAL_RISK_CONVERGENCE_V1",
        "mission_id": MISSION,
        "release_id": RELEASE,
        "run_id": "RUN-OLD-RISK-SET",
        "risk_count": 0,
        "all_dispositioned": True,
        "counts_by_disposition": {
            "ACCEPTED": 0,
            "DEFERRED": 0,
            "MONITOR": 0,
            "PENDING": 0,
        },
        "risks": [],
    }
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    path = tmp_path / "old-risk-governance.json"
    path.write_bytes(encoded)
    evidence_id = "EVD-RISK-GOV-OLD"
    artifact_id = "ART-RISK-GOV-OLD"
    append_entity(
        control.truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=MISSION,
            kind="RESIDUAL_RISK_CONVERGENCE_RECEIPT",
            source_ref="runtime://n10-residual-risk-governance",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, "RUN-OLD-RISK-SET"],
            content_hash="sha256:" + digest,
        ),
        release_id=RELEASE,
    )
    append_entity(
        control.truth,
        Artifact(
            artifact_id=artifact_id,
            mission_id=MISSION,
            artifact_type="RESIDUAL_RISK_CONVERGENCE_RECEIPT",
            producer_task_id="TASK-N10-OLD-RISK-SET",
            content_ref="file://" + str(path),
            evidence_refs=[evidence_id],
            content_hash="sha256:" + digest,
        ),
        release_id=RELEASE,
    )


def _json_native(value):
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def test_historical_stale_receipt_is_preserved_but_current_receipt_is_selected(tmp_path: Path):
    truth, control = _control(tmp_path)
    registry = _seed_current_risk(control, tmp_path)
    _persist_stale_history_receipt(control, tmp_path)
    service = GovernedAutonomousN10Service(evidence_root=str(tmp_path / "n10"))
    service._persist_risk_governance(
        control,
        run_id="RUN-CURRENT-RISK-SET",
        summary=_json_native(registry.summary(control)),
    )

    payload, violations = MissionConvergenceConformanceChecker(truth)._residual_risk_conformance(MISSION)

    assert violations == []
    assert payload["status"] == "PASS"
    assert payload["receipt_history_count"] == 2
    assert payload["valid_receipt_history_count"] == 2
    assert payload["current_match_count"] == 1
    assert payload["receipt_artifact_id"] != "ART-RISK-GOV-OLD"


def test_two_receipts_matching_current_risk_set_fail_closed(tmp_path: Path):
    truth, control = _control(tmp_path)
    registry = _seed_current_risk(control, tmp_path)
    summary = _json_native(registry.summary(control))
    service = GovernedAutonomousN10Service(evidence_root=str(tmp_path / "n10"))
    service._persist_risk_governance(control, run_id="RUN-CURRENT-A", summary=summary)
    service._persist_risk_governance(control, run_id="RUN-CURRENT-B", summary=summary)

    payload, violations = MissionConvergenceConformanceChecker(truth)._residual_risk_conformance(MISSION)

    assert payload["status"] == "FAIL"
    assert payload["receipt_history_count"] == 2
    assert payload["current_match_count"] == 2
    assert "RESIDUAL_RISK_GOVERNANCE_CURRENT_RECEIPT_NOT_UNIQUE:2" in violations
