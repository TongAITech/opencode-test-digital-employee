from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Evidence
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
    ReleaseBatch,
    TestObligation,
)
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_sufficiency import (
    SufficiencyGateService,
    SufficiencySnapshot,
)
from rc7_runtime.truth_overlay import append_entity


def _runtime(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    runtime = RC72StateMachine(truth, release_id="RC7.2")
    runtime.bootstrap_release_batch(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch 1",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1"],
        )
    )
    for evidence_id in (
        "EVD-REQ", "EVD-CODEGRAPH", "EVD-GIT", "EVD-DESIGN", "EVD-DATA", "EVD-EXEC",
    ):
        append_entity(
            truth,
            Evidence(
                evidence_id=evidence_id,
                mission_id="M-1",
                kind="RC72_SUFFICIENCY_PROOF",
                source_ref="test://phase3",
                content_ref="proof://%s" % evidence_id,
                subject_refs=["REQ-1", "SST-1"],
            ),
            release_id="RC7.2",
        )
    return truth, runtime, SufficiencyGateService(runtime)


def _prime_upstream(runtime: RC72StateMachine, node_type: AutonomousMissionNode):
    ordered = list(AutonomousMissionNode.ordered())
    for upstream_type in ordered[: ordered.index(node_type)]:
        upstream = runtime.node_by_type("M-1", upstream_type)
        if upstream["state"] == "PASS":
            continue
        if upstream["state"] == "NOT_STARTED":
            runtime.transition_state(
                upstream["mission_node_id"],
                MissionNodeState.READY,
                reason="phase3 canonical upstream precondition",
            )
        runtime.transition_state(
            upstream["mission_node_id"],
            MissionNodeState.RUNNING,
            reason="phase3 canonical upstream precondition",
        )
        delivery = NodeDelivery(
            delivery_id="UPSTREAM-%s" % upstream_type.value,
            mission_id="M-1",
            mission_node_id=upstream["mission_node_id"],
            node_type=upstream_type,
            version=1,
            producer_ref="test-fixture://%s" % upstream_type.value,
            artifact_refs=["artifact://upstream/%s" % upstream_type.value],
            evidence_refs=["EVD-REQ"],
            created_by_workitems=["WI-UPSTREAM-%s" % upstream_type.value],
        )
        runtime.submit_delivery(delivery)
        runtime.apply_gate(
            NodeGate(
                gate_id="GATE-UPSTREAM-%s" % upstream_type.value,
                mission_id="M-1",
                mission_node_id=upstream["mission_node_id"],
                node_type=upstream_type,
                delivery_id=delivery.delivery_id,
                decision=NodeGateDecision.PASS,
                reviewer_worker_id="fixture-reviewer",
                reviewer_session_id="fixture-review-session-%s" % upstream_type.value,
                criteria=["PHASE3_TEST_UPSTREAM_PRECONDITION"],
                passed=["PHASE3_TEST_UPSTREAM_PRECONDITION"],
                evidence_refs=["EVD-REQ"],
                reason="canonical upstream truth for isolated phase3 gate test",
            )
        )


def _prepare_node(runtime: RC72StateMachine, node_type: AutonomousMissionNode, version=1):
    _prime_upstream(runtime, node_type)
    node = runtime.node_by_type("M-1", node_type)
    runtime.transition_state(node["mission_node_id"], MissionNodeState.READY, reason="phase3 isolated gate test")
    runtime.transition_state(node["mission_node_id"], MissionNodeState.RUNNING, reason="analysis/design produced")
    delivery = NodeDelivery(
        delivery_id="ND-%s-V%d" % (node_type.value, version),
        mission_id="M-1",
        mission_node_id=node["mission_node_id"],
        node_type=node_type,
        version=version,
        producer_ref="worker://%s/%d" % (node_type.value, version),
        artifact_refs=["artifact://%s/%d" % (node_type.value, version)],
        evidence_refs=["EVD-REQ"],
        created_by_workitems=["WI-%s-%d" % (node_type.value, version)],
    )
    runtime.submit_delivery(delivery)
    return runtime.node(node["mission_node_id"]), delivery


def _snapshot(node, delivery, node_type, facts, evidence_refs):
    return SufficiencySnapshot(
        snapshot_id="SSF-%s" % node_type.value,
        mission_id="M-1",
        mission_node_id=node["mission_node_id"],
        node_type=node_type,
        delivery_id=delivery.delivery_id,
        source_artifact_refs=list(delivery.artifact_refs),
        evidence_refs=evidence_refs,
        facts=facts,
    )


def _review(service, snapshot):
    return service.evaluate_and_apply(
        snapshot,
        reviewer_worker_id="fresh-reviewer-%s" % snapshot.node_type.value,
        reviewer_session_id="fresh-review-session-%s" % snapshot.node_type.value,
    )


def test_n2_missing_business_dimensions_cannot_pass_even_with_reviewer_identity(tmp_path: Path):
    truth, runtime, service = _runtime(tmp_path)
    node, delivery = _prepare_node(runtime, AutonomousMissionNode.N2_REQUIREMENT)
    snapshot = _snapshot(
        node,
        delivery,
        AutonomousMissionNode.N2_REQUIREMENT,
        {
            "requirement_id": "REQ-1",
            "sst_id": "SST-1",
            "br": ["BR-1"],
            "sr": ["SR-1"],
            "tr": ["TR-1"],
            "business_rules": ["RULE-1"],
            "roles": [],
            "states": [],
            "state_transitions": [],
            "negative_rules": [],
            "boundary_rules": [],
            "permission_rules": [],
            "data_rules": [],
            "unresolved_unknowns": [],
        },
        ["EVD-REQ"],
    )
    result = _review(service, snapshot)
    assert result.decision == "NEEDS_REVISION"
    assert "N2_ROLES_REQUIRED" in result.failed_codes
    assert "N2_NEGATIVE_RULES_REQUIRED" in result.failed_codes
    assert runtime.node(node["mission_node_id"])["state"] == "NEEDS_REVISION"
    gaps = truth.query("rc7_gap", mission_id="M-1")
    assert any(row["category"] == "N2_ROLES_REQUIRED" for row in gaps)


def test_n2_explicit_not_applicable_is_auditable_not_silent_empty(tmp_path: Path):
    _, runtime, service = _runtime(tmp_path)
    node, delivery = _prepare_node(runtime, AutonomousMissionNode.N2_REQUIREMENT)
    snapshot = _snapshot(
        node,
        delivery,
        AutonomousMissionNode.N2_REQUIREMENT,
        {
            "requirement_id": "REQ-1",
            "sst_id": "SST-1",
            "br": ["BR-1"],
            "sr": ["SR-1"],
            "tr": ["TR-1"],
            "business_rules": ["RULE-1"],
            "roles": ["maker"],
            "states": ["DRAFT", "ACTIVE"],
            "state_transitions": ["DRAFT->ACTIVE"],
            "negative_rules": ["duplicate rejected"],
            "boundary_rules": ["max length"],
            "permission_rules": [],
            "data_rules": ["unique code"],
            "unresolved_unknowns": [],
            "not_applicable": {
                "permission_rules": {
                    "reason": "SST has no role-dependent authorization branch",
                    "evidence_refs": ["EVD-REQ"],
                }
            },
        },
        ["EVD-REQ"],
    )
    result = _review(service, snapshot)
    assert result.decision == "PASS"


def test_n3_codegraph_and_impact_dimensions_are_mandatory(tmp_path: Path):
    _, runtime, service = _runtime(tmp_path)
    node, delivery = _prepare_node(runtime, AutonomousMissionNode.N3_CODE_ANALYSIS)
    snapshot = _snapshot(
        node,
        delivery,
        AutonomousMissionNode.N3_CODE_ANALYSIS,
        {
            "requirement_ids": ["REQ-1"],
            "sst_ids": ["SST-1"],
            "changed_refs": ["GuarantorServiceImpl#create"],
            "api_contracts": ["POST /guarantor"],
            "dto_constraints": ["guarantorStatus NOT NULL"],
            "service_impacts": ["GuarantorServiceImpl#create"],
            "db_constraints": ["guarantor_status NOT NULL"],
            "dependency_impacts": [],
            "reverse_mappings": ["GuarantorServiceImpl#create->REQ-1/SST-1"],
            "graph_evidence_refs": [],
            "git_evidence_refs": ["EVD-GIT"],
            "uncertainties": [],
        },
        ["EVD-GIT"],
    )
    result = _review(service, snapshot)
    assert result.decision == "NEEDS_REVISION"
    assert "N3_CODEGRAPH_EVIDENCE_REQUIRED" in result.failed_codes
    assert "N3_DEPENDENCY_IMPACT_REQUIRED" in result.failed_codes


def test_n3_complete_code_analysis_passes_with_real_graph_and_git_evidence(tmp_path: Path):
    _, runtime, service = _runtime(tmp_path)
    node, delivery = _prepare_node(runtime, AutonomousMissionNode.N3_CODE_ANALYSIS)
    snapshot = _snapshot(
        node,
        delivery,
        AutonomousMissionNode.N3_CODE_ANALYSIS,
        {
            "requirement_ids": ["REQ-1"],
            "sst_ids": ["SST-1"],
            "changed_refs": ["GuarantorServiceImpl#create"],
            "api_contracts": ["POST /guarantor"],
            "dto_constraints": ["guarantorStatus required"],
            "service_impacts": ["GuarantorServiceImpl#create"],
            "db_constraints": ["guarantor_status NOT NULL"],
            "dependency_impacts": ["cfg-data guarantor table"],
            "reverse_mappings": ["GuarantorServiceImpl#create->REQ-1/SST-1"],
            "graph_evidence_refs": ["EVD-CODEGRAPH"],
            "git_evidence_refs": ["EVD-GIT"],
            "uncertainties": [],
        },
        ["EVD-CODEGRAPH", "EVD-GIT"],
    )
    assert _review(service, snapshot).decision == "PASS"


def test_n4_orphan_case_tbd_missing_oracle_and_high_risk_depth_block_pass(tmp_path: Path):
    truth, runtime, service = _runtime(tmp_path)
    runtime.repository.persist(
        TestObligation(
            obligation_id="TO-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            requirement_id="REQ-1",
            sst_id="SST-1",
            application_id="cfg-center",
            business_scenario="guarantor creation",
            business_rule="required fields persist",
            risk_level="HIGH",
            test_level="L3",
            code_slice_refs=["GuarantorServiceImpl#create"],
            oracle_refs=["HTTP", "DB"],
        )
    )
    node, delivery = _prepare_node(runtime, AutonomousMissionNode.N4_TEST_DESIGN)
    snapshot = _snapshot(
        node,
        delivery,
        AutonomousMissionNode.N4_TEST_DESIGN,
        {
            "cases": [
                {
                    "case_id": "TC-1",
                    "obligation_id": "TO-NOT-EXIST",
                    "requirement_id": "REQ-1",
                    "sst_id": "SST-1",
                    "test_level": "L3",
                    "case_kind": "POSITIVE",
                    "preconditions": ["TBD"],
                    "steps": ["POST /guarantor"],
                    "oracle": {},
                    "evidence_requirements": ["request", "response"],
                }
            ]
        },
        ["EVD-DESIGN"],
    )
    result = _review(service, snapshot)
    assert result.decision == "NEEDS_REVISION"
    assert "N4_ORPHAN_CASE" in result.failed_codes
    assert "N4_UNRESOLVED_TBD_UNKNOWN" in result.failed_codes
    assert "N4_ORACLE_REQUIRED" in result.failed_codes
    assert "N4_HIGH_RISK_NEGATIVE_REQUIRED" in result.failed_codes
    assert "N4_HIGH_RISK_BOUNDARY_REQUIRED" in result.failed_codes
    assert truth.query("rc72_sufficiency_snapshot", snapshot_id=snapshot.snapshot_id)


def test_n5_requires_resolved_verified_reserved_data_or_explicit_none_required(tmp_path: Path):
    _, runtime, service = _runtime(tmp_path)
    node, delivery = _prepare_node(runtime, AutonomousMissionNode.N5_TEST_DATA)
    bad = _snapshot(
        node,
        delivery,
        AutonomousMissionNode.N5_TEST_DATA,
        {
            "case_data": [
                {
                    "case_id": "TC-1",
                    "strategy": "DISCOVER_EXISTING",
                    "data_refs": [],
                    "precondition_refs": ["precondition://1"],
                    "verified": False,
                    "reserved": False,
                    "cleanup_policy": "release",
                }
            ]
        },
        ["EVD-DATA"],
    )
    result = _review(service, bad)
    assert result.decision == "NEEDS_REVISION"
    assert "N5_DATA_REF_REQUIRED" in result.failed_codes
    assert "N5_DATA_VERIFY_REQUIRED" in result.failed_codes
    assert "N5_DATA_RESERVE_REQUIRED" in result.failed_codes


def test_n6_requires_executable_contract_not_executor_guessing(tmp_path: Path):
    _, runtime, service = _runtime(tmp_path)
    node, delivery = _prepare_node(runtime, AutonomousMissionNode.N6_EXECUTABLE_READINESS)
    snapshot = _snapshot(
        node,
        delivery,
        AutonomousMissionNode.N6_EXECUTABLE_READINESS,
        {
            "contracts": [
                {
                    "case_id": "TC-1",
                    "execution_target": "FAT1",
                    "tool_route": "api",
                    "input_bindings": {"guarantorStatus": "TBD"},
                    "data_refs": ["data://guarantor/1"],
                    "assertions": [],
                    "oracle": {"checks": [{"actual_path": "$.status", "operator": "eq", "expected": 200}]},
                    "evidence_requirements": ["request", "response", "db", "cat"],
                    "required_capabilities": [],
                    "required_resources": [],
                    "cleanup": "release data",
                }
            ]
        },
        ["EVD-EXEC"],
    )
    result = _review(service, snapshot)
    assert result.decision == "NEEDS_REVISION"
    assert "N6_UNRESOLVED_TBD_UNKNOWN" in result.failed_codes
    assert "N6_ASSERTIONS_REQUIRED" in result.failed_codes
    assert "N6_CAPABILITIES_REQUIRED" in result.failed_codes
    assert "N6_RESOURCES_REQUIRED" in result.failed_codes


def test_failed_deterministic_gate_cannot_be_overridden_to_pass_by_reviewer(tmp_path: Path):
    _, runtime, service = _runtime(tmp_path)
    node, delivery = _prepare_node(runtime, AutonomousMissionNode.N2_REQUIREMENT)
    snapshot = _snapshot(
        node,
        delivery,
        AutonomousMissionNode.N2_REQUIREMENT,
        {
            "requirement_id": "REQ-1",
            "sst_id": "SST-1",
            "br": [], "sr": [], "tr": [],
            "business_rules": [], "roles": [], "states": [], "state_transitions": [],
            "negative_rules": [], "boundary_rules": [], "permission_rules": [], "data_rules": [],
            "unresolved_unknowns": [],
        },
        ["EVD-REQ"],
    )
    result = service.evaluate_and_apply(
        snapshot,
        reviewer_worker_id="reviewer-says-pass",
        reviewer_session_id="reviewer-session-says-pass",
        reviewer_recommendation="PASS",
    )
    assert result.decision == "NEEDS_REVISION"
    assert runtime.node(node["mission_node_id"])["state"] == "NEEDS_REVISION"


def test_sufficiency_snapshot_and_gate_survive_r1_replay(tmp_path: Path):
    truth, runtime, service = _runtime(tmp_path)
    node, delivery = _prepare_node(runtime, AutonomousMissionNode.N3_CODE_ANALYSIS)
    snapshot = _snapshot(
        node,
        delivery,
        AutonomousMissionNode.N3_CODE_ANALYSIS,
        {
            "requirement_ids": ["REQ-1"], "sst_ids": ["SST-1"],
            "changed_refs": ["Service#m"], "api_contracts": ["POST /x"],
            "dto_constraints": ["field required"], "service_impacts": ["Service#m"],
            "db_constraints": ["field NOT NULL"], "dependency_impacts": ["table x"],
            "reverse_mappings": ["Service#m->REQ-1/SST-1"],
            "graph_evidence_refs": ["EVD-CODEGRAPH"], "git_evidence_refs": ["EVD-GIT"],
            "uncertainties": [],
        },
        ["EVD-CODEGRAPH", "EVD-GIT"],
    )
    result = _review(service, snapshot)
    assert result.decision == "PASS"

    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    ss = replayed.query("rc72_sufficiency_snapshot", snapshot_id=snapshot.snapshot_id)[0]
    assert ss["node_type"] == "N3_CODE_ANALYSIS"
    gate = replayed.query("rc72_node_gate", gate_id=result.gate_id)[0]
    assert gate["decision"] == "PASS"
