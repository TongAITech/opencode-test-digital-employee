from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.controlled_l3_execution import ControlledL3ClosedLoopExecutionService
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


TARGET_ID = "TARGET-CONTROLLED-L3"


class _Target:
    def __init__(self):
        self.hits = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or "0")
                body = self.rfile.read(length)
                owner.hits.append((self.path, body))
                response = json.dumps(
                    {"business_code": "OK", "decision": "ACCEPTED"}, sort_keys=True
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

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
        "tc_id": "TC-CONTROLLED-L3-1",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-CONTROLLED-L3",
        "requirement_id": "REQ-CONTROLLED-L3",
        "sst_id": "SST-CONTROLLED-L3",
        "layer": "L3",
        "preconditions": [],
        "steps": [{"order": 1, "action": "POST controlled rate request"}],
        "expected": "business_code=OK",
        "oracle": {
            "checks": [
                {
                    "id": "CHK-BUSINESS-CODE",
                    "type": "BUSINESS_RULE",
                    "actual_path": "business_code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
        "evidence_requirements": ["parent-api-receipt", "oracle-runtime"],
        "target_requirements": ["REQ-CONTROLLED-L3"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://controlled-l3"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _bundle(tmp_path: Path, source: str):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-CONTROLLED-L3",),
        test_data_refs=(),
        oracle_refs=("oracle://controlled-l3",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source_path = tmp_path / "test_controlled_l3_fixture.py"
    source_path.write_text(source, encoding="utf-8")
    script = ScriptArtifact(
        script_id="SCRIPT-CONTROLLED-L3",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source_path),
        test_symbol="test_controlled_l3",
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
        upstream_mission_id="MISSION-UPSTREAM-SCRIPT",
        upstream_task_id="TASK-UPSTREAM-SCRIPT",
        upstream_evaluation_id="EVAL-UPSTREAM-SCRIPT",
        upstream_result_ref="file://upstream-script-result.json",
        spec_ref="file://upstream-spec.json",
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256="fixture",
    )


def _prepared():
    return PreparedAttempt(
        status="PREPARED",
        attempt_id="ATT-CONTROLLED-L3-1",
        tc_id="TC-CONTROLLED-L3-1",
        case_version=1,
        target_id=TARGET_ID,
        precondition_evidence=(),
        initial_state_bindings={},
        input_data_bindings={},
        binding_evidence=(),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot=_case()["oracle"],
    )


def _broker():
    broker = ToolCapabilityBroker()
    broker.discover("api-runtime", "qualification://controlled-api-runtime")
    broker.mark_executable("api-runtime", "executable://controlled-api-runtime")
    broker.register("api-runtime", "registration://controlled-api-runtime")
    broker.record_probe(
        "api-runtime",
        success=True,
        tool_call_ref="probe://controlled-api-runtime",
        evidence_ref="probe-evidence://controlled-api-runtime",
    )
    broker.mark_target_ready(
        "api-runtime", TARGET_ID, "target-ready://controlled-api-runtime"
    )
    return broker


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id="MISSION-CONTROLLED-L3",
            release_id="RC7-CONTROLLED-L3",
            goal="prove parent-owned API receipts drive L3 acceptance",
        ),
    )
    task = Task(
        task_id="TASK-CONTROLLED-L3",
        mission_id="MISSION-CONTROLLED-L3",
        node="EXECUTION",
        task_type="EXECUTE",
        objective="run one controlled L3 case",
        required_capabilities=["test_execution"],
    )
    control.register_task(task)
    assert control.scheduler.task(task.task_id).state == TaskStatus.READY
    return truth, control, task.task_id


def _real_source():
    return r'''import json
import os
from urllib.request import Request, urlopen


def test_controlled_l3():
    payload = json.dumps({
        "method": "POST",
        "path": "/loan/rate/adjust",
        "body": {"loan_id": "L-100", "delta": 0.01},
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
'''


def _fake_source():
    return r'''import json
import os


def test_controlled_l3():
    with open(os.environ["RC6_EXECUTION_MANIFEST"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "type": "tool_call",
            "tool_id": "api-runtime",
            "call_ref": "api-runtime://FAKE",
            "evidence_ref": "api-evidence://FAKE",
        }) + "\n")
        handle.write(json.dumps({
            "type": "actual_result",
            "value": {"business_code": "OK"},
        }) + "\n")
    assert True
'''


def _execute(tmp_path: Path, base_url: str, source: str):
    truth, control, task_id = _control(tmp_path)
    result = ControlledL3ClosedLoopExecutionService(
        evidence_root=str(tmp_path / "execution-evidence"), timeout_seconds=20
    ).execute_task(
        control,
        task_id,
        bundle=_bundle(tmp_path, source),
        prepared=_prepared(),
        authority=RC7AuthorityRuntime(b"rc7-controlled-l3-signing-key"),
        tool_broker=_broker(),
        target_base_url=base_url,
        cwd=str(tmp_path),
    )
    return truth, control, result


def test_real_parent_proxy_call_can_reach_durable_l3_pass(tmp_path: Path):
    with _Target() as target:
        truth, control, result = _execute(tmp_path, target.base_url, _real_source())
        assert len(target.hits) == 1
        assert target.hits[0][0] == "/loan/rate/adjust"
    assert result.execution_record.status == "PASS"
    assert result.execution_record.integrity_passed is True
    assert result.execution_record.actual_result["business_code"] == "OK"
    assert result.execution_record.assertion_passed is True
    assert result.task_state == "PASS"
    assert any(ref.startswith("api-runtime://APIREC-") for ref in result.execution_record.tool_call_refs)
    task = control.scheduler.task("TASK-CONTROLLED-L3")
    assert task.state == TaskStatus.PASS
    evaluation = truth.query("rc7_evaluation", evaluation_id=task.evaluation_id)[0]
    assert evaluation["result"] == "PASS"
    evidence = truth.query("rc7_evidence", mission_id="MISSION-CONTROLLED-L3")
    receipt_rows = [
        row for row in evidence
        if "/api-runtime/" in str(row.get("content_ref", "")).replace("\\", "/")
    ]
    assert receipt_rows
    assert all(Path(row["content_ref"][len("file://"):]).is_file() for row in receipt_rows)


def test_manifest_only_fake_api_claim_is_repair_not_pass(tmp_path: Path):
    with _Target() as target:
        truth, control, result = _execute(tmp_path, target.base_url, _fake_source())
        assert target.hits == []
    assert result.execution_record.status == "FAIL"
    assert result.execution_record.integrity_passed is False
    assert result.execution_record.actual_result is None or result.execution_record.actual_result == {}
    assert "api-runtime://FAKE" not in result.execution_record.tool_call_refs
    assert result.task_state == "REPAIR_REQUIRED"
    task = control.scheduler.task("TASK-CONTROLLED-L3")
    assert task.state == TaskStatus.REPAIR_REQUIRED
    evaluation = truth.query("rc7_evaluation", evaluation_id=task.evaluation_id)[0]
    assert evaluation["result"] == "REPAIR_REQUIRED"
