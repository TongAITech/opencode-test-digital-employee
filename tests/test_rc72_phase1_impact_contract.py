from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    ExecutionTaskUnit,
    MissionNodeRecord,
    NodeDelivery,
    ReleaseBatch,
    TestObligation,
)
from rc7_runtime.rc72_impact import ImpactSet, ImpactStrategy
from rc7_runtime.rc72_impact_truth import append_impact_set
from rc7_runtime.rc72_repository import CanonicalRC72Repository


def _setup_truth(path: Path):
    truth = TruthRuntime(path)
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    batch = ReleaseBatch(
        release_batch_id="RB-1",
        mission_id="M-1",
        name="release batch 1",
        application_ids=["cfg-center"],
        requirement_ids=["REQ-1"],
    )
    repo.persist(batch)
    n3 = MissionNodeRecord(
        mission_node_id="MN-N3",
        mission_id="M-1",
        node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        scope_ref="release-batch://RB-1",
    )
    n4 = MissionNodeRecord(
        mission_node_id="MN-N4",
        mission_id="M-1",
        node_type=AutonomousMissionNode.N4_TEST_DESIGN,
        scope_ref="release-batch://RB-1",
    )
    repo.persist(n3)
    repo.persist(n4)
    delivery = NodeDelivery(
        delivery_id="ND-N3-V1",
        mission_id="M-1",
        mission_node_id="MN-N3",
        node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        version=1,
        producer_ref="worker://code-analysis/1",
        artifact_refs=["code-analysis://v1"],
        evidence_refs=["codegraph://evidence/1"],
    )
    repo.persist(delivery)
    obligation = TestObligation(
        obligation_id="TO-1",
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_id="REQ-1",
        sst_id="SST-1",
        application_id="cfg-center",
        business_scenario="scenario",
        business_rule="rule",
        risk_level="HIGH",
        test_level="L3",
        oracle_refs=["HTTP"],
    )
    repo.persist(obligation)
    etu = ExecutionTaskUnit(
        etu_id="ETU-1",
        mission_id="M-1",
        release_batch_id="RB-1",
        obligation_id="TO-1",
        case_ids=["TC-1"],
        primary_goal="goal",
        primary_code_slice="Service#method",
        test_level="L3",
        primary_oracle="HTTP",
        data_domain="domain",
        primary_tool_family="api",
        planning_snapshot_ref="snapshot://1",
        cohesion_score=1.0,
        cohesion_explanation="single obligation and code slice",
    )
    repo.persist(etu)
    return truth


def test_impact_set_persists_and_replays_in_same_r1(tmp_path: Path):
    event_path = tmp_path / "r1.jsonl"
    truth = _setup_truth(event_path)
    impact = ImpactSet(
        impact_set_id="IMPACT-1",
        mission_id="M-1",
        source_mission_node_id="MN-N3",
        source_node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        source_delivery_id="ND-N3-V1",
        changed_refs=["dto://GuarantorRequest#guarantorStatus"],
        affected_refs=["TO-1", "ETU-1"],
        stale_mission_node_ids=["MN-N4"],
        stale_obligation_ids=["TO-1"],
        stale_etu_ids=["ETU-1"],
        strategy=ImpactStrategy.EXPLICIT_DEPENDENCY,
        reason="DTO required field changed",
    )
    receipt = append_impact_set(truth, impact, release_id="RC7.2")
    assert receipt.status == "PERSISTENCE_VERIFIED"

    replayed = TruthRuntime(event_path)
    row = replayed.query("rc72_impact_set", impact_set_id="IMPACT-1")[0]
    assert row["source_delivery_id"] == "ND-N3-V1"
    assert row["stale_mission_node_ids"] == ["MN-N4"]
    assert row["stale_obligation_ids"] == ["TO-1"]
    assert row["stale_etu_ids"] == ["ETU-1"]
    assert row["strategy"] == "EXPLICIT_DEPENDENCY"


def test_impact_set_rejects_unknown_downstream_asset(tmp_path: Path):
    truth = _setup_truth(tmp_path / "r1.jsonl")
    impact = ImpactSet(
        impact_set_id="IMPACT-BAD",
        mission_id="M-1",
        source_mission_node_id="MN-N3",
        source_node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        source_delivery_id="ND-N3-V1",
        changed_refs=["dto://field"],
        stale_etu_ids=["ETU-NOT-EXIST"],
        strategy=ImpactStrategy.SAFE_FALLBACK,
        reason="fallback invalidation",
    )
    with pytest.raises(Exception, match="IMPACT_LINEAGE_PARENT_NOT_UNIQUE:rc72_etu"):
        append_impact_set(truth, impact, release_id="RC7.2")
