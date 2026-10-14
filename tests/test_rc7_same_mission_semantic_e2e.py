from __future__ import annotations

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime
from rc7_runtime import (
    Artifact,
    ClosedLoopControlPlane,
    Evidence,
    Mission,
    MissionTaskGraphCompiler,
    TaskStatus,
)
from rc7_runtime.code_loop import CodeAnalysisClosedLoop
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_loop import ExecutionClosedLoop
from rc7_runtime.mission_sufficiency import MissionEvidenceSnapshot, MissionSufficiencyClosedLoop
from rc7_runtime.requirement_loop import RequirementClosedLoop
from rc7_runtime.script_readiness_loop import ScriptReadinessClosedLoop
from rc7_runtime.test_design_loop import TestDesignClosedLoop, TestObligation


MISSION = "MISSION-SEMANTIC-E2E"
TARGET = "TARGET-CFG-DATA"


def _produce(control, graph, compiler, node: str, worker: str):
    task = graph.task(node)
    leased = control.lease_next(
        worker_ref=worker,
        capabilities=compiler.REQUIRED_CAPABILITIES[node],
    )
    assert leased is not None and leased.task_id == task.task_id
    control.start(task.task_id, worker_ref=worker)
    evidence_id = "EVD-WORKER-%s" % node
    artifact_id = graph.artifact_ids[node]
    candidate = control.submit_worker_output(
        WorkerOutput(
            task_id=task.task_id,
            worker_ref=worker,
            evidence=(
                Evidence(
                    evidence_id=evidence_id,
                    mission_id=MISSION,
                    kind="NODE_OUTPUT_PROOF",
                    source_ref="worker://%s" % worker,
                    content_ref="evidence://%s" % evidence_id,
                ),
            ),
            artifacts=(
                Artifact(
                    artifact_id=artifact_id,
                    mission_id=MISSION,
                    artifact_type=compiler.OUTPUT_TYPES[node],
                    producer_task_id=task.task_id,
                    content_ref="artifact://%s" % artifact_id,
                    parent_refs=list(task.input_artifact_refs),
                    evidence_refs=[evidence_id],
                ),
            ),
        )
    )
    assert candidate.state == TaskStatus.OUTPUT_PRODUCED
    return task, artifact_id


def _requirement_analysis():
    return {
        "analysis_id": "REQ-AN-E2E",
        "release_id": "RC7",
        "requirement_id": "REQ-E2E-1",
        "analyzer_worker_id": "worker-requirement",
        "source_assertions": [{"id": "SRC-1", "text": "rate rule"}],
        "atomic_statements": [
            {
                "id": "A-1",
                "statement": "Rate adjustment obeys documented min/max rule",
                "testable": True,
                "source_ref": "SRC-1",
            }
        ],
        "trace_links": [
            {"source_id": "SRC-1", "atomic_id": "A-1", "evidence_ref": "EVD-REQ-SOURCE"}
        ],
        "evidence_refs": ["EVD-REQ-SOURCE"],
        "business_rules": [{"id": "BR-1"}],
        "roles": [{"id": "ROLE-1"}],
        "preconditions": [{"id": "PRE-1"}],
        "normal_paths": [{"id": "NP-1"}],
        "negative_paths": [{"id": "NEG-1"}],
        "boundaries": [{"id": "BOUNDARY-1", "rule": "min/max evidenced"}],
        "states": [{"id": "STATE-1"}],
        "data_constraints": [{"id": "DATA-1"}],
        "dependencies": [{"id": "DEP-1"}],
        "side_effects": [{"id": "SIDE-1"}],
    }


def _requirement_review():
    return {
        "id": "REQ-REVIEW-E2E",
        "review_id": "REQ-REVIEW-E2E",
        "release_id": "RC7",
        "requirement_id": "REQ-E2E-1",
        "subject_analysis_id": "REQ-AN-E2E",
        "reviewer_worker_id": "evaluator-requirement",
        "analyzer_worker_id": "worker-requirement",
        "decision": "PASS",
        "evidence_refs": ["EVD-REQ-REVIEW"],
        "gap_ids": [],
    }


def _code_analysis():
    return {
        "analysis_id": "CODE-AN-E2E",
        "release_id": "RC7",
        "analyzer_worker_id": "worker-code",
        "requirement_ids": ["REQ-E2E-1"],
        "source_revisions": {"cfg-data": "abc123..def456"},
        "changed_files": ["RateService.java"],
        "changed_symbols": [{"id": "SYM-1", "symbol": "RateService.adjustRate"}],
        "symbol_explanations": [
            {"symbol_id": "SYM-1", "evidence_refs": ["EVD-GIT-E2E"]}
        ],
        "reverse_requirement_mappings": [
            {"requirement_id": "REQ-E2E-1", "symbol_id": "SYM-1", "evidence_ref": "EVD-GIT-E2E"}
        ],
        "tool_calls": [
            {
                "tool_id": "git",
                "call_ref": "git://diff/abc123..def456",
                "evidence_ref": "EVD-GIT-E2E",
                "target_id": TARGET,
            },
            {
                "tool_id": "codegraph",
                "call_ref": "codegraph://callers/RateService.adjustRate",
                "evidence_ref": "EVD-CODEGRAPH-E2E",
                "target_id": TARGET,
            },
        ],
        "evidence_refs": ["EVD-GIT-E2E", "EVD-CODEGRAPH-E2E"],
        "codegraph_required": True,
    }


def _code_review():
    return {
        "review_id": "CODE-REVIEW-E2E",
        "subject_analysis_id": "CODE-AN-E2E",
        "reviewer_worker_id": "evaluator-code",
        "analyzer_worker_id": "worker-code",
        "decision": "PASS",
        "evidence_refs": ["EVD-CODE-REVIEW"],
        "gap_ids": [],
    }


def _obligations():
    return [
        TestObligation(
            obligation_id="OBL-RULE-E2E",
            kind="BUSINESS_RULE",
            layer="L3",
            risk="HIGH",
            evidence_refs=("EVD-RULE-E2E",),
        ),
        TestObligation(
            obligation_id="OBL-BOUNDARY-E2E",
            kind="BOUNDARY",
            layer="L3",
            risk="CRITICAL",
            evidence_refs=("EVD-BOUNDARY-E2E",),
        ),
    ]


def _case(tc_id: str, obligation_id: str):
    return {
        "tc_id": tc_id,
        "layer": "L3",
        "risk": "HIGH",
        "status": "CANDIDATE",
        "coverage_links": [
            {"subject_id": obligation_id, "evidence_ref": "EVD-%s-COVERAGE" % tc_id}
        ],
        "action_semantics": {
            "state_changing": False,
            "negative": False,
            "authorization_sensitive": False,
        },
        "oracle": {
            "checks": [
                {"type": "API_RESPONSE", "evidence_ref": "EVD-%s-API" % tc_id},
                {"type": "BUSINESS_RULE", "evidence_ref": "EVD-%s-RULE" % tc_id},
                {"type": "EVIDENCE_CORRELATION", "evidence_ref": "EVD-%s-CORR" % tc_id},
            ]
        },
    }


def _frozen_case():
    return {
        "tc_id": "TC-RATE-E2E",
        "case_version": 1,
        "release_id": "RC7",
        "requirement_id": "REQ-E2E-1",
        "sst_id": "SST-E2E-1",
        "layer": "L3",
        "status": "FROZEN",
        "preconditions": ["loan exists"],
        "steps": ["submit rate adjustment"],
        "expected": "rate adjustment accepted",
        "oracle": {
            "checks": [
                {"type": "API_RESPONSE", "expected": "ACCEPTED"},
                {"type": "BUSINESS_RULE", "expected": "RATE_UPDATED"},
            ]
        },
        "evidence_requirements": ["api-response", "db-before-after"],
    }


def test_real_semantic_gates_compose_inside_one_r1_mission(tmp_path) -> None:
    path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(path)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7", goal="semantic full path"),
    )
    compiler = MissionTaskGraphCompiler()
    graph = compiler.install(control, MISSION)

    # 1. Requirement Analysis: inherited independent sufficiency gate.
    req_task, req_artifact = _produce(control, graph, compiler, "REQUIREMENT_ANALYSIS", "worker-requirement")
    req_result = RequirementClosedLoop().evaluate(
        mission_id=MISSION,
        artifact_ref=req_artifact,
        analysis=_requirement_analysis(),
        review=_requirement_review(),
    )
    assert req_result.evaluation.result == EvaluationResult.PASS
    control.accept_evaluation(req_task.task_id, evaluation=req_result.evaluation)

    # 2. Code Analysis: real Git + CodeGraph evidence is required by the gate.
    code_task, code_artifact = _produce(control, graph, compiler, "CODE_ANALYSIS", "worker-code")
    code_result = CodeAnalysisClosedLoop().evaluate(
        mission_id=MISSION,
        artifact_ref=code_artifact,
        target_id=TARGET,
        analysis=_code_analysis(),
        review=_code_review(),
    )
    assert code_result.evaluation.result == EvaluationResult.PASS
    assert code_result.evaluation.dimensions["metrics"]["codegraph_evidence_calls"] == 1
    control.accept_evaluation(code_task.task_id, evaluation=code_result.evaluation)

    # 3. Test Design: semantic obligation coverage, not case count, decides PASS.
    design_task, design_artifact = _produce(control, graph, compiler, "TEST_DESIGN", "worker-design")
    design_result = TestDesignClosedLoop().evaluate(
        mission_id=MISSION,
        artifact_ref=design_artifact,
        obligations=_obligations(),
        cases=[
            _case("TC-RULE-E2E", "OBL-RULE-E2E"),
            _case("TC-BOUNDARY-E2E", "OBL-BOUNDARY-E2E"),
        ],
    )
    assert design_result.evaluation.result == EvaluationResult.PASS
    assert design_result.semantic_coverage == 1.0
    control.accept_evaluation(design_task.task_id, evaluation=design_result.evaluation)

    # 4. Script Readiness: compile/collect/fixture readiness only; no product verdict.
    script_task, script_artifact = _produce(control, graph, compiler, "SCRIPT_READINESS", "worker-script")
    script_loop = ScriptReadinessClosedLoop(validation_timeout_seconds=60)
    spec = script_loop.compile_execution_contract(
        case=_frozen_case(),
        target_requirements=("REQ-E2E-1",),
        test_data_refs=("data://loan-e2e",),
        oracle_refs=("oracle://rate-accepted",),
        cleanup_policy={"required": False},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source = tmp_path / "test_semantic_e2e_generated.py"
    source.write_text("def test_generated_case():\n    assert True\n", encoding="utf-8")
    script = ScriptArtifact(
        script_id="SCRIPT-E2E",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source),
        test_symbol="test_generated_case",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("EVD-SCRIPT-BUILD-E2E",),
        revision=1,
    )
    validation = script_loop.validate_script(spec=spec, script=script, cwd=str(tmp_path))
    script_result = script_loop.evaluate(
        mission_id=MISSION,
        artifact_ref=script_artifact,
        spec=spec,
        script=script,
        validation=validation,
    )
    assert script_result.evaluation.result == EvaluationResult.PASS
    assert script_result.evaluation.dimensions["business_assertion_executed"] is False
    control.accept_evaluation(script_task.task_id, evaluation=script_result.evaluation)

    # 5. Execution: product PASS is a separate trusted execution conclusion.
    exec_task, exec_artifact = _produce(control, graph, compiler, "EXECUTION", "worker-execution")
    record = ExecutionRecord(
        attempt_id="ATT-E2E-1",
        tc_id="TC-RATE-E2E",
        case_version=1,
        target_id=TARGET,
        layer="L3",
        worker_id="worker-execution",
        lease_id="lease-execution-e2e",
        status="PASS",
        integrity_passed=True,
        actual_result={"business_code": "ACCEPTED"},
        tool_call_refs=("call://api/rate-adjustment",),
        evidence_refs=("EVD-EXEC-E2E",),
        assertion_ref="assertion://rate-accepted",
        assertion_passed=True,
        reason="ORACLE_PASS",
    )
    exec_result = ExecutionClosedLoop().evaluate(
        mission_id=MISSION,
        artifact_ref=exec_artifact,
        record=record,
    )
    assert exec_result.test_result == "PASS"
    assert exec_result.evaluation.result == EvaluationResult.PASS
    control.accept_evaluation(exec_task.task_id, evaluation=exec_result.evaluation)

    # 6. Mission Sufficiency: workflow completion alone is not the final gate.
    snapshot = MissionEvidenceSnapshot(
        mission_id=MISSION,
        release_id="RC7",
        snapshot_ref="SNAPSHOT-SEMANTIC-E2E",
        evidence_refs=("EVD-MISSION-E2E",),
        critical_requirements_total=1,
        critical_requirements_verified=1,
        critical_obligations_total=2,
        critical_obligations_verified=2,
        critical_branches_total=1,
        critical_branches_verified=1,
        critical_executions_total=1,
        critical_executions_conclusive=1,
    )
    sufficiency = MissionSufficiencyClosedLoop().evaluate(snapshot)
    assert sufficiency.evaluation.result == EvaluationResult.PASS
    assert sufficiency.sufficiency_state == "SUFFICIENT"
    mission = control.converge_mission(sufficiency.evaluation)
    assert mission.state.value == "CONVERGED"

    # Fresh process replay proves the entire semantic chain is durable R1 truth.
    replay = TruthRuntime(path)
    recovered = ClosedLoopControlPlane(replay, "RC7", MISSION)
    assert recovered.snapshot()["mission_state"] == "CONVERGED"
    assert len(replay.query("rc7_evaluation", mission_id=MISSION)) == 6
    assert all(
        recovered.scheduler.task(graph.task(node).task_id).state == TaskStatus.PASS
        for node in compiler.NODE_ORDER
    )
