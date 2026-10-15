from __future__ import annotations

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
from rc7_runtime.execution_diagnosis import ExecutionDiagnosisCoordinator, ExecutionTrustFacts
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


MISSION = "MISSION-L3-AUTO-DIAG"
TASK = "TASK-L3-AUTO-DIAG"
TARGET = "TARGET-L3-AUTO-DIAG"


class _BadBusinessTarget:
    def __init__(self):
        owner = self
        self.hits = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
                owner.hits.append((self.path, body))
                raw = json.dumps({"business_code": "BAD", "decision": "REJECTED"}).encode("utf-8")
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


def _case():
    return {
        "tc_id": "TC-L3-AUTO-DIAG",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-L3-AUTO-DIAG",
        "requirement_id": "REQ-L3-AUTO-DIAG",
        "sst_id": "SST-L3-AUTO-DIAG",
        "layer": "L3",
        "preconditions": [],
        "steps": [{"order": 1, "action": "POST controlled request"}],
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
        "evidence_requirements": ["parent-api-receipt", "oracle-runtime", "cat-correlation"],
        "target_requirements": ["REQ-L3-AUTO-DIAG"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://l3-auto-diag"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _bundle(tmp_path: Path):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-L3-AUTO-DIAG",),
        test_data_refs=(),
        oracle_refs=("oracle://l3-auto-diag",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source = tmp_path / "test_l3_auto_diag.py"
    source.write_text(
        r'''import json
import os
from urllib.request import Request, urlopen


def test_l3_auto_diag():
    payload = json.dumps({
        "method": "POST",
        "path": "/loan/rate/adjust",
        "body": {"loan_id": "L-200", "delta": 0.01},
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
''',
        encoding="utf-8",
    )
    script = ScriptArtifact(
        script_id="SCRIPT-L3-AUTO-DIAG",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source),
        test_symbol="test_l3_auto_diag",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("evidence://script-builder",),
        revision=1,
    )
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "readiness"), timeout_seconds=20
    ).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
    return VerifiedScriptExecutionBundle(
        upstream_mission_id="MISSION-SCRIPT-UPSTREAM",
        upstream_task_id="TASK-SCRIPT-UPSTREAM",
        upstream_evaluation_id="EVAL-SCRIPT-UPSTREAM",
        upstream_result_ref="file://script-result.json",
        spec_ref="file://script-spec.json",
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256="fixture",
    )


def _prepared():
    return PreparedAttempt(
        status="PREPARED",
        attempt_id="ATT-L3-AUTO-DIAG",
        tc_id="TC-L3-AUTO-DIAG",
        case_version=1,
        target_id=TARGET,
        precondition_evidence=(),
        initial_state_bindings={},
        input_data_bindings={},
        binding_evidence=(),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot=_case()["oracle"],
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


def test_controlled_l3_oracle_fail_auto_diagnoses_product_and_hands_off_defect(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7-L3-AUTO-DIAG", goal="auto diagnose real L3 failure"),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute and classify one real L3 failure",
            required_capabilities=["test_execution"],
        )
    )
    broker = _broker()
    authority = RC7AuthorityRuntime(b"rc7-l3-auto-diagnosis-signing-key")

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
            trace_id="trace-l3-auto-diag",
        ),
    )

    with _BadBusinessTarget() as target:
        result = ControlledL3ClosedLoopExecutionService(
            evidence_root=str(tmp_path / "execution-evidence"), timeout_seconds=20
        ).execute_task(
            control,
            TASK,
            bundle=_bundle(tmp_path),
            prepared=_prepared(),
            authority=authority,
            tool_broker=broker,
            target_base_url=target.base_url,
            cwd=str(tmp_path),
            diagnosis_coordinator=coordinator,
            diagnosis_trust=trust,
        )
        assert len(target.hits) == 1

    assert result.execution_record.status == "FAIL"
    assert result.execution_record.assertion_passed is False
    assert result.loop_result.test_result == "FAIL"
    assert result.loop_result.conclusive is True
    assert result.loop_result.evaluation.result.value == "PASS"
    assert result.loop_result.evaluation.dimensions["failure_class"] == "PRODUCT"
    assert result.loop_result.evaluation.dimensions["recovery_action"] == "PRODUCT_DEFECT"
    assert result.task_state == "PASS"
    assert any(gap.category == "PRODUCT_DEFECT" and gap.target_node == "DEFECT" for gap in result.loop_result.gaps)

    execution_task = control.scheduler.task(TASK)
    assert execution_task.state == TaskStatus.PASS
    gaps = truth.query("rc7_gap", mission_id=MISSION)
    product_gap = next(row for row in gaps if row["category"] == "PRODUCT_DEFECT")
    assert product_gap["state"] == "PLANNED"

    reproduction_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row["node"] == "EXECUTION" and row["task_type"] == "DEFECT_REPRODUCTION"
    ]
    defect_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row["node"] == "DEFECT" and row["task_type"] == "QUALIFY_DEFECT"
    ]
    assert len(reproduction_tasks) == 1
    assert len(defect_tasks) == 1
    reproduction_task = reproduction_tasks[0]
    defect_task = defect_tasks[0]
    assert reproduction_task["state"] == "READY"
    assert reproduction_task["gap_refs"] == [product_gap["gap_id"]]
    assert reproduction_task["dependency_task_ids"] == [TASK]
    assert reproduction_task["input_artifact_refs"] == [result.record_artifact_id]
    assert defect_task["state"] == "REGISTERED"
    assert defect_task["gap_refs"] == [product_gap["gap_id"]]
    assert defect_task["dependency_task_ids"] == [reproduction_task["task_id"]]
    assert defect_task["input_artifact_refs"] == [result.record_artifact_id]

    diagnosis_evidence = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "RUNTIME_FAILURE_DIAGNOSIS"
    ]
    assert len(diagnosis_evidence) == 1
    path = Path(diagnosis_evidence[0]["content_ref"][len("file://"):])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["diagnosis"]["failure_class"] == "PRODUCT"
    assert payload["recovery"]["action"] == "PRODUCT_DEFECT"
