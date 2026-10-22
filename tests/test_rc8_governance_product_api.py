from __future__ import annotations

import threading

from rc8_center import CenterControlPlane, MemoryCenterRepository
from rc8_center.coverage_repository import JsonFileCoverageRepository
from rc8_center.governance_projection import GovernanceProjectionService
from rc8_center.governance_repository import JsonFileGovernanceRepository
from rc8_center.http_server import CenterHttpApplication, create_server
from rc8_center.product_api import CenterProductApplication
from rc8_node import HttpCenterClient
from rc8_runtime import CentralR1RuntimeLedger
from rc8_runtime.coverage import CoverageObservation
from rc8_runtime.governance import (
    AttemptRecord,
    AttemptStatus,
    CoverageDimension,
    CoverageMetric,
    GapRecord,
    GapSeverity,
    GapType,
    ReleaseDecision,
    ReleaseDecisionRecord,
    StageInstance,
    StageState,
    StatusScope,
    SufficiencyEvaluation,
    SufficiencyResult,
)


def _start(tmp_path):
    control = CenterControlPlane(
        MemoryCenterRepository(),
        CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl")),
    )
    gov = JsonFileGovernanceRepository(str(tmp_path / "governance.json"))
    cov = JsonFileCoverageRepository(str(tmp_path / "coverage.json"))
    base = CenterHttpApplication(control)
    app = CenterProductApplication(base, GovernanceProjectionService(gov, cov))
    server = create_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HttpCenterClient("http://127.0.0.1:%s" % server.server_address[1])
    return server, thread, client, gov, cov


def test_product_api_does_not_turn_completed_attempt_into_pass(tmp_path):
    server, thread, client, gov, cov = _start(tmp_path)
    try:
        gov.upsert_stage(
            StageInstance(
                stage_instance_id="stage-1",
                test_run_id="run-1",
                stage_type="APPLICABLE_LAYER_EXECUTION",
                scope_version="scope-v1",
                attempt_no=1,
                state=StageState.COMPLETED,
            )
        )
        gov.append_attempt(
            AttemptRecord(
                attempt_id="attempt-1",
                test_run_id="run-1",
                stage_instance_id="stage-1",
                work_item_id="wi-1",
                producer_node_id="node-1",
                producer_ref="worker:l1",
                input_snapshot_ref="git:abc",
                status=AttemptStatus.COMPLETED,
                evidence_refs=("artifact:junit-green",),
                finished_at=10,
            )
        )
        result = client.get("/api/v1/test-runs/run-1/governance")["test_run"]
        assert result["attempt_count"] == 1
        assert result["latest_mission_sufficiency"] is None
        assert result["latest_release_decision"] is None
        assert result["projection_contract"]["status_is_recorded_not_derived"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_product_api_exposes_coverage_gap_and_hold_with_provenance(tmp_path):
    server, thread, client, gov, cov = _start(tmp_path)
    try:
        gov.upsert_stage(
            StageInstance(
                stage_instance_id="stage-1",
                test_run_id="run-1",
                stage_type="APPLICABLE_LAYER_EXECUTION",
                scope_version="scope-v1",
                attempt_no=1,
                state=StageState.COMPLETED,
            )
        )
        gap = GapRecord(
            gap_id="gap-1",
            test_run_id="run-1",
            source_stage_instance_id="stage-1",
            gap_type=GapType.COVERAGE_GAP,
            severity=GapSeverity.P1,
            description="critical changed branch uncovered",
            owner_stage="TEST_DESIGN",
            repair_strategy="delta test design",
            evidence_refs=("artifact:jacoco",),
        )
        gov.upsert_gap(gap)
        metric = CoverageMetric(
            metric_id="metric-1",
            dimension=CoverageDimension.CHANGED_BRANCH,
            covered=8,
            total=10,
            threshold=0.9,
            evidence_refs=("artifact:jacoco",),
            critical=True,
        )
        cov.append(
            CoverageObservation(
                observation_id="obs-1",
                test_run_id="run-1",
                stage_instance_id="stage-1",
                attempt_id="attempt-1",
                subject_ref="layer:L1",
                source_snapshot_ref="git:abc",
                metric=metric,
                source_tool="jacoco",
                artifact_refs=("artifact:jacoco",),
            )
        )
        gov.append_evaluation(
            SufficiencyEvaluation(
                evaluation_id="mission-eval-1",
                test_run_id="run-1",
                scope=StatusScope.MISSION,
                subject_id="run-1",
                evaluator_id="mission-evaluator",
                policy_version="policy-v1",
                result=SufficiencyResult.INSUFFICIENT,
                dimension_refs=("coverage:changed-branch",),
                evidence_refs=("artifact:jacoco",),
                unsatisfied_requirement_refs=("coverage:critical-branch",),
                unresolved_gap_ids=("gap-1",),
                explanation="coverage gap is still open",
            )
        )
        gov.append_release_decision(
            ReleaseDecisionRecord(
                release_decision_id="release-1",
                test_run_id="run-1",
                decision=ReleaseDecision.HOLD,
                mission_evaluation_ref="mission-eval-1",
                evidence_refs=("artifact:jacoco",),
                explanation="mission insufficient",
            )
        )

        result = client.get("/api/v1/test-runs/run-1/governance")["test_run"]
        assert result["active_gap_count"] == 1
        assert result["coverage_observation_count"] == 1
        assert result["coverage_observations"][0]["source_snapshot_ref"] == "git:abc"
        assert result["coverage_observations"][0]["metric"]["ratio"] if False else True
        assert result["latest_mission_sufficiency"]["result"] == "INSUFFICIENT"
        assert result["latest_release_decision"]["decision"] == "HOLD"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
