from __future__ import annotations

import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.diagnosis import CorrelationScope
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.controlled_l3_execution import ControlledL3ClosedLoopExecutionService
from rc7_runtime.defect_loop import RootCauseHypothesis
from rc7_runtime.defect_qualification_control import DefectQualificationControl
from rc7_runtime.defect_reproduction import DefectReproductionExecutionService
from rc7_runtime.defect_resolution_control import DefectResolutionControl
from rc7_runtime.execution_diagnosis import ExecutionDiagnosisCoordinator, ExecutionTrustFacts
from rc7_runtime.final_report import RC7FinalReportBuilder
from rc7_runtime.mission_evaluation_runtime import MissionEvaluationRuntime
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Mission, Task, TaskStatus
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-PRODUCT-DEFECT-E2E"
RELEASE = "RC7-PRODUCT-DEFECT-E2E"
ORIGINAL_TASK = "TASK-EXEC-PRODUCT-DEFECT-E2E"
ORIGINAL_TC = "TC-PRODUCT-DEFECT-E2E"
REGRESSION_TC = "TC-PRODUCT-DEFECT-REGRESSION"
TARGET = "TARGET-PRODUCT-DEFECT-E2E"
DESIGN_TASK = "TASK-DESIGN-PRODUCT-DEFECT-E2E"
DESIGN_ARTIFACT = "ART-DESIGN-PRODUCT-DEFECT-E2E"


class _MutableBusinessTarget:
    def __init__(self):
        owner = self
        self.business_code = "BAD"
        self.hits = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
                owner.hits.append((self.path, body, owner.business_code))
                raw = json.dumps(
                    {
                        "business_code": owner.business_code,
                        "decision": "APPROVED" if owner.business_code == "OK" else "REJECTED",
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = "http://%s:%s" % (host, port)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _case(tc_id: str, path: str):
    return {
        "tc_id": tc_id,
        "case_version": 1,
        "status": "FROZEN",
        "release_id": RELEASE,
        "requirement_id": "REQ-PRODUCT-DEFECT-E2E",
        "sst_id": "SST-PRODUCT-DEFECT-E2E",
        "layer": "L3",
        "preconditions": [],
        "steps": [{"order": 1, "action": "POST %s through parent-controlled API runtime" % path}],
        "expected": "business_code=OK",
        "oracle": {
            "checks": [
                {
                    "id": "CHK-BUSINESS",
                    "type": "BUSINESS_RULE",
                    "actual_path": "business_code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
        "evidence_requirements": ["parent-api-receipt", "oracle-runtime"],
        "target_requirements": ["REQ-PRODUCT-DEFECT-E2E"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://%s" % tc_id.lower()],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _bundle(tmp_path: Path, tc_id: str, path: str):
    case = _case(tc_id, path)
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-PRODUCT-DEFECT-E2E",),
        test_data_refs=(),
        oracle_refs=("oracle://%s" % tc_id.lower(),),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source = tmp_path / ("test_%s.py" % tc_id.lower().replace("-", "_"))
    source.write_text(
        r'''import json
import os
from urllib.request import Request, urlopen


def test_controlled_business_call():
    payload = json.dumps({
        "method": "POST",
        "path": %r,
        "body": {"loan_id": "L-900", "delta": 0.01},
        "capture_as": "actual_result",
    }).encode("utf-8")
    request = Request(
        os.environ["RC7_API_RUNTIME_PROXY_URL"],
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        envelope = json.loads(response.read().decode("utf-8"))
    assert envelope["status_code"] == 200
''' % path,
        encoding="utf-8",
    )
    script = ScriptArtifact(
        script_id="SCRIPT-%s" % tc_id,
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source),
        test_symbol="test_controlled_business_call",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("evidence://script-builder/%s" % tc_id,),
        revision=1,
    )
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / ("readiness-" + tc_id)),
        timeout_seconds=20,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
    return VerifiedScriptExecutionBundle(
        upstream_mission_id=MISSION,
        upstream_task_id=DESIGN_TASK,
        upstream_evaluation_id="EVAL-DESIGN-PRODUCT-DEFECT-E2E",
        upstream_result_ref="file://design-result.json",
        spec_ref="file://%s-spec.json" % tc_id,
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )


def _prepared(tc_id: str, attempt_id: str):
    case = _case(tc_id, "/loan/rate/adjust" if tc_id == ORIGINAL_TC else "/loan/rate/regression")
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id=tc_id,
        case_version=1,
        target_id=TARGET,
        precondition_evidence=(),
        initial_state_bindings={},
        input_data_bindings={},
        binding_evidence=(),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot=case["oracle"],
    )


def _broker():
    broker = ToolCapabilityBroker()
    for tool_id in ("api-runtime", "cat"):
        broker.discover(tool_id, "qualification://%s" % tool_id)
        broker.mark_executable(tool_id, "executable://%s" % tool_id)
        broker.register(tool_id, "registration://%s" % tool_id)
        broker.record_probe(
            tool_id,
            success=True,
            tool_call_ref="probe://%s" % tool_id,
            evidence_ref="probe-evidence://%s" % tool_id,
        )
        broker.mark_target_ready(tool_id, TARGET, "target-ready://%s" % tool_id)
    return broker


def _write_json(path: Path, payload):
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _append_design_truth(tmp_path: Path, truth: TruthRuntime):
    path = tmp_path / "design.json"
    payload = {
        "artifact": {"artifact_id": DESIGN_ARTIFACT, "artifact_type": "TEST_DESIGN_MODEL"},
        "semantic_payload": {
            "obligations": [
                {
                    "obligation_id": "OBL-PRODUCT-RULE",
                    "kind": "BUSINESS_RULE",
                    "layer": "L3",
                    "risk": "HIGH",
                    "required": True,
                },
                {
                    "obligation_id": "OBL-PRODUCT-CODE",
                    "kind": "CODE_IMPACT",
                    "layer": "L3",
                    "risk": "CRITICAL",
                    "required": True,
                },
                {
                    "obligation_id": "OBL-PRODUCT-REGRESSION",
                    "kind": "BUSINESS_RULE",
                    "layer": "L3",
                    "risk": "HIGH",
                    "required": True,
                },
            ],
            "cases": [
                {
                    "tc_id": ORIGINAL_TC,
                    "risk": "HIGH",
                    "coverage_links": [
                        {"subject_id": "OBL-PRODUCT-RULE", "evidence_ref": "evidence://design-rule"},
                        {"subject_id": "OBL-PRODUCT-CODE", "evidence_ref": "evidence://design-code"},
                    ],
                },
                {
                    "tc_id": REGRESSION_TC,
                    "risk": "HIGH",
                    "coverage_links": [
                        {"subject_id": "OBL-PRODUCT-REGRESSION", "evidence_ref": "evidence://design-regression"},
                    ],
                },
            ],
        },
    }
    digest = _write_json(path, payload)
    evidence = Evidence(
        evidence_id="EVD-DESIGN-PRODUCT-DEFECT-E2E",
        mission_id=MISSION,
        kind="TEST_DESIGN_PROOF",
        source_ref="runtime://test-design",
        content_ref="file://" + str(path),
        subject_refs=[DESIGN_TASK, DESIGN_ARTIFACT],
        content_hash=digest,
    )
    append_entity(truth, evidence, release_id=RELEASE)
    append_entity(
        truth,
        Artifact(
            artifact_id=DESIGN_ARTIFACT,
            mission_id=MISSION,
            artifact_type="TEST_DESIGN_MODEL",
            producer_task_id=DESIGN_TASK,
            content_ref="file://" + str(path),
            evidence_refs=[evidence.evidence_id],
            content_hash=digest,
        ),
        release_id=RELEASE,
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-DESIGN-PRODUCT-DEFECT-E2E",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[DESIGN_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-test-design-gate",
        dimensions={"gate_status": "SUFFICIENT"},
        evidence_refs=[evidence.evidence_id],
    )
    append_entity(truth, evaluation, release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=DESIGN_TASK,
            mission_id=MISSION,
            node="TEST_DESIGN",
            task_type="ANALYZE",
            objective="accepted critical design for product-defect mission",
            state=TaskStatus.PASS,
            output_artifact_refs=[DESIGN_ARTIFACT],
            evaluation_id=evaluation.evaluation_id,
        ),
        release_id=RELEASE,
    )


def _append_resolution_evidence(truth: TruthRuntime, *, evidence_id: str, kind: str, subjects):
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind=kind,
        source_ref="runtime://product-defect-e2e/%s" % kind.lower(),
        content_ref="evidence://%s" % evidence_id,
        subject_refs=list(subjects),
    )
    append_entity(truth, evidence, release_id=RELEASE)
    return evidence


def test_product_fail_reproduces_closes_after_fix_and_converges_with_historical_fail(tmp_path: Path):
    r1_path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(r1_path)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="find a real product defect, verify its fix, regress impact and converge from R1 truth",
        ),
    )
    _append_design_truth(tmp_path, truth)
    control.register_task(
        Task(
            task_id=ORIGINAL_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute the designed critical business case",
            required_capabilities=["test_execution"],
            input_artifact_refs=[DESIGN_ARTIFACT],
        )
    )

    original_bundle = _bundle(tmp_path, ORIGINAL_TC, "/loan/rate/adjust")
    regression_bundle = _bundle(tmp_path, REGRESSION_TC, "/loan/rate/regression")
    broker = _broker()
    authority = RC7AuthorityRuntime(b"rc7-product-defect-e2e-signing-key")

    def cat_query(scope, context):
        return {
            "tool_call_ref": "toolcall://cat/%s" % context.attempt_id,
            "evidence_ref": "evidence://cat/%s" % context.attempt_id,
            "signals": {"trace_id": scope.trace_id, "application": "cfg-data", "product_error": True},
        }

    coordinator = ExecutionDiagnosisCoordinator(
        authority=authority,
        tool_broker=broker,
        evidence_root=str(tmp_path / "execution-evidence"),
        cat_query=cat_query,
    )
    trust = ExecutionTrustFacts(
        auth_verified=True,
        route_verified=True,
        tool_verified=True,
        environment_verified=True,
        dependency_verified=True,
        correlation=CorrelationScope(
            applications=("cfg-center", "cfg-data"),
            window_start=1000,
            window_end=1060,
            trace_id="trace-product-defect-e2e",
        ),
    )

    with _MutableBusinessTarget() as target:
        original = ControlledL3ClosedLoopExecutionService(
            evidence_root=str(tmp_path / "execution-evidence"), timeout_seconds=20
        ).execute_task(
            control,
            ORIGINAL_TASK,
            bundle=original_bundle,
            prepared=_prepared(ORIGINAL_TC, "ATT-ORIGINAL-PRODUCT-FAIL"),
            authority=authority,
            tool_broker=broker,
            target_base_url=target.base_url,
            cwd=str(tmp_path),
            diagnosis_coordinator=coordinator,
            diagnosis_trust=trust,
        )
        assert original.execution_record.status == "FAIL"
        assert original.loop_result.test_result == "FAIL"
        assert original.loop_result.evaluation.dimensions["failure_class"] == "PRODUCT"
        assert original.task_state == "PASS"

        product_gap = next(
            row for row in truth.query("rc7_gap", mission_id=MISSION)
            if row.get("category") == "PRODUCT_DEFECT"
        )
        reproduction_task = next(
            row for row in truth.query("rc7_task", mission_id=MISSION)
            if row.get("task_type") == "DEFECT_REPRODUCTION"
        )
        defect_task = next(
            row for row in truth.query("rc7_task", mission_id=MISSION)
            if row.get("task_type") == "QUALIFY_DEFECT"
        )
        assert reproduction_task["state"] == "READY"
        assert defect_task["state"] == "REGISTERED"

        reproduction = DefectReproductionExecutionService(
            evidence_root=str(tmp_path / "reproduction-evidence"), timeout_seconds=20
        ).execute_task(
            control,
            str(reproduction_task["task_id"]),
            source_product_gap_id=str(product_gap["gap_id"]),
            bundle=original_bundle,
            prepared=_prepared(ORIGINAL_TC, "ATT-PRODUCT-REPRODUCTION"),
            authority=authority,
            tool_broker=broker,
            cwd=str(tmp_path),
            target_base_url=target.base_url,
        )
        assert reproduction.reproduced is True
        assert reproduction.conclusive is True
        assert reproduction.task_state == "PASS"
        assert control.scheduler.task(str(defect_task["task_id"])).state == TaskStatus.READY

        qualification = DefectQualificationControl(
            evidence_root=str(tmp_path / "defect-evidence")
        ).qualify(
            control,
            str(defect_task["task_id"]),
            product_gap_id=str(product_gap["gap_id"]),
            bundle=original_bundle,
            reproduction=reproduction,
        )
        assert qualification.qualified is True
        assert qualification.defect_state == "EVIDENCE_READY"
        defect_id = qualification.defect_id

        rca = _append_resolution_evidence(
            truth,
            evidence_id="EVD-RCA-PRODUCT-DEFECT-E2E",
            kind="ROOT_CAUSE_EVIDENCE",
            subjects=[defect_id, "RateDecisionService.apply"],
        )
        resolution = DefectResolutionControl()
        confirmed = resolution.confirm_root_cause(
            control,
            defect_id,
            hypothesis=RootCauseHypothesis(
                hypothesis_id="RCA-PRODUCT-DEFECT-E2E",
                statement="RateDecisionService returned the wrong business code after a valid request",
                suspected_symbols=("RateDecisionService.apply",),
                evidence_refs=(rca.evidence_id,),
                confidence=0.95,
            ),
        )
        assert confirmed.state.value == "FIX_PENDING"

        fix_revision = "fix-product-defect-e2e-sha"
        fix_evidence = _append_resolution_evidence(
            truth,
            evidence_id="EVD-FIX-PRODUCT-DEFECT-E2E",
            kind="FIX_REVISION_EVIDENCE",
            subjects=[defect_id, fix_revision, "RateDecisionService.apply"],
        )
        detected = resolution.detect_fix(
            control,
            defect_id,
            fix_revision=fix_revision,
            fix_evidence_id=fix_evidence.evidence_id,
        )
        assert detected.state.value == "FIX_DETECTED"
        verification_task = next(
            task for task in control.scheduler.ready_tasks(MISSION)
            if task.task_type == resolution.FIX_VERIFICATION_TASK_TYPE
        )

        target.business_code = "OK"
        verification = ControlledL3ClosedLoopExecutionService(
            evidence_root=str(tmp_path / "verification-evidence"), timeout_seconds=20
        ).execute_task(
            control,
            verification_task.task_id,
            bundle=original_bundle,
            prepared=_prepared(ORIGINAL_TC, "ATT-FIX-VERIFICATION"),
            authority=authority,
            tool_broker=broker,
            target_base_url=target.base_url,
            cwd=str(tmp_path),
        )
        assert verification.execution_record.status == "PASS"
        fixed = resolution.accept_fix_verification(
            control,
            defect_id,
            verification_artifact_id=verification.record_artifact_id,
        )
        assert fixed.state.value == "REGRESSION_TESTING"

        regression_task = next(
            task for task in control.scheduler.ready_tasks(MISSION)
            if task.task_type == resolution.IMPACT_REGRESSION_TASK_TYPE
        )
        regression = ControlledL3ClosedLoopExecutionService(
            evidence_root=str(tmp_path / "regression-evidence"), timeout_seconds=20
        ).execute_task(
            control,
            regression_task.task_id,
            bundle=regression_bundle,
            prepared=_prepared(REGRESSION_TC, "ATT-IMPACT-REGRESSION"),
            authority=authority,
            tool_broker=broker,
            target_base_url=target.base_url,
            cwd=str(tmp_path),
        )
        assert regression.execution_record.status == "PASS"

        closed = resolution.close_after_verification(
            control,
            defect_id,
            verification_artifact_id=verification.record_artifact_id,
            regression_artifact_ids=[regression.record_artifact_id],
        )
        assert closed.defect_state == "CLOSED"
        assert closed.product_gap_state == "RESOLVED"
        assert closed.defect_task_state == "PASS"

    mission = MissionEvaluationRuntime(
        evidence_root=str(tmp_path / "mission-evidence")
    ).run(control)
    assert mission.evaluation_result == "PASS"
    assert mission.sufficiency_state == "SUFFICIENT"
    assert mission.release_recommendation == "RECOMMENDED"
    assert mission.mission_state == "CONVERGED"

    snapshot_row = truth.query("rc7_artifact", artifact_id=mission.snapshot_artifact_id)[0]
    snapshot_path = Path(snapshot_row["content_ref"][len("file://"):])
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["critical_requirement_refs"] == ["OBL-PRODUCT-REGRESSION", "OBL-PRODUCT-RULE"]
    assert snapshot["verified_requirement_refs"] == ["OBL-PRODUCT-REGRESSION", "OBL-PRODUCT-RULE"]
    assert snapshot["critical_obligation_refs"] == [
        "OBL-PRODUCT-CODE",
        "OBL-PRODUCT-REGRESSION",
        "OBL-PRODUCT-RULE",
    ]
    assert snapshot["verified_obligation_refs"] == [
        "OBL-PRODUCT-CODE",
        "OBL-PRODUCT-REGRESSION",
        "OBL-PRODUCT-RULE",
    ]
    assert snapshot["critical_branch_refs"] == ["OBL-PRODUCT-CODE"]
    assert snapshot["verified_branch_refs"] == ["OBL-PRODUCT-CODE"]
    assert snapshot["critical_execution_refs"] == [ORIGINAL_TC, REGRESSION_TC]
    assert snapshot["conclusive_execution_refs"] == [ORIGINAL_TC, REGRESSION_TC]

    report = RC7FinalReportBuilder(truth).build(
        MISSION,
        str(tmp_path / "final-report"),
    )
    assert report["mission_state"] == "CONVERGED"
    assert report["sufficiency_state"] == "SUFFICIENT"
    assert report["defect_status"].get("CLOSED") == 1
    assert report["gap_status"].get("RESOLVED") == 1
    assert any(
        row.get("test_result") == "FAIL" and row.get("failure_class") == "PRODUCT"
        for row in report["execution_results"]
    )
    assert sum(1 for row in report["execution_results"] if row.get("test_result") == "PASS") >= 2
    assert RC7FinalReportBuilder(truth).reconcile(report)["status"] == "PASS"

    # R1 truth retains all attempts: original product failure, reproduction,
    # post-fix original-case verification and distinct impact regression.
    execution_evaluations = [
        row for row in truth.query("rc7_evaluation", mission_id=MISSION)
        if row.get("node") == "EXECUTION"
    ]
    purposes = [row.get("dimensions", {}).get("purpose") for row in execution_evaluations]
    assert "DEFECT_REPRODUCTION" in purposes
    normal_results = [
        row.get("dimensions", {}).get("test_result")
        for row in execution_evaluations
        if row.get("dimensions", {}).get("purpose") != "DEFECT_REPRODUCTION"
    ]
    assert "FAIL" in normal_results
    assert "PASS" in normal_results

    replay = TruthRuntime(r1_path)
    recovered = ClosedLoopControlPlane(replay, RELEASE, MISSION)
    assert recovered.snapshot()["mission_state"] == "CONVERGED"
    replay_report = RC7FinalReportBuilder(replay).snapshot(MISSION)
    assert replay_report["truth_digest"] == report["truth_digest"]
    assert replay_report["execution_results"] == report["execution_results"]
