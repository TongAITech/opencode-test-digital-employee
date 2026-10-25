from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.controlled_l3_execution import ControlledL3ClosedLoopExecutionService
from rc7_runtime.models import Evidence, Mission, Task, TaskStatus
from rc7_runtime.real_executor_provenance import (
    RealExecutorProvenanceGate,
    persist_contract as persist_real_executor_contract,
)
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7-L3-PROVENANCE"
MISSION = "MISSION-L3-PROVENANCE"
TASK = "TASK-L3-PROVENANCE"
ATTEMPT = "ATT-L3-PROVENANCE-1"
TARGET = "TARGET-L3-PROVENANCE"
SPECIALIST = "dsh-specialist-l3"


class _Target:
    def __init__(self) -> None:
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
        "tc_id": "TC-L3-PROVENANCE-1",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": RELEASE,
        "requirement_id": "REQ-L3-PROVENANCE",
        "sst_id": "SST-L3-PROVENANCE",
        "layer": "L3",
        "preconditions": [],
        "steps": [{"order": 1, "action": "POST through parent API runtime"}],
        "expected": "business_code=OK",
        "oracle": {
            "checks": [
                {
                    "id": "CHK-L3-BUSINESS-CODE",
                    "type": "BUSINESS_RULE",
                    "actual_path": "business_code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
        "evidence_requirements": ["parent-api-receipt", "oracle-runtime"],
        "target_requirements": ["REQ-L3-PROVENANCE"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://l3-provenance"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _bundle(tmp_path: Path, source: str) -> VerifiedScriptExecutionBundle:
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-L3-PROVENANCE",),
        test_data_refs=(),
        oracle_refs=("oracle://l3-provenance",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source_path = tmp_path / "test_l3_provenance_fixture.py"
    source_path.write_text(source, encoding="utf-8")
    script = ScriptArtifact(
        script_id="SCRIPT-L3-PROVENANCE",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source_path),
        test_symbol="test_l3_provenance",
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
        upstream_mission_id="MISSION-UPSTREAM-L3",
        upstream_task_id="TASK-UPSTREAM-L3",
        upstream_evaluation_id="EVAL-UPSTREAM-L3",
        upstream_result_ref="file://upstream-l3-result.json",
        spec_ref="file://upstream-l3-spec.json",
        frozen_case=case,
        spec=spec,
        script=script,
        validation=validation,
        source_sha256="fixture",
    )


def _prepared() -> PreparedAttempt:
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=ATTEMPT,
        tc_id="TC-L3-PROVENANCE-1",
        case_version=1,
        target_id=TARGET,
        precondition_evidence=(),
        initial_state_bindings={},
        input_data_bindings={},
        binding_evidence=(),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot=_case()["oracle"],
    )


def _broker() -> ToolCapabilityBroker:
    broker = ToolCapabilityBroker()
    broker.discover("api-runtime", "qualification://parent-api-runtime")
    broker.mark_executable("api-runtime", "executable://parent-api-runtime")
    broker.register("api-runtime", "registration://parent-api-runtime")
    broker.record_probe(
        "api-runtime",
        success=True,
        tool_call_ref="probe://parent-api-runtime",
        evidence_ref="probe-evidence://parent-api-runtime",
    )
    broker.mark_target_ready("api-runtime", TARGET, "target-ready://parent-api-runtime")
    return broker


def _binding(truth: TruthRuntime, tmp_path: Path) -> None:
    payload = {
        "schema": "pfc.aitest.rc7.1.agent-teams-execution-binding.v1",
        "mission_id": MISSION,
        "task_id": TASK,
        "node": "EXECUTION",
        "team_id": "TEAM-L3",
        "team_task_id": "TEAM-TASK-L3",
        "member_id": "MEMBER-L3",
        "worker_instance_id": SPECIALIST,
        "worker_assignment_id": "ASSIGN-L3",
        "attempt_id": ATTEMPT,
        "lease_id": "LEASE-L3",
        "parent_worker_id": "MEMBER-L3",
        "scope": "task:%s" % TASK,
        "assignment_evidence_id": "EVD-ASSIGN-L3",
        "director_self_execution_forbidden": True,
        "local_execution_fallback_forbidden": True,
    }
    path = tmp_path / "l3-agent-teams-binding.json"
    body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(body)
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-BIND-L3",
            mission_id=MISSION,
            kind="DSH_AGENT_TEAMS_EXECUTION_BINDING",
            source_ref="dsh-agent-teams://TEAM-L3/TEAM-TASK-L3/execution",
            content_ref="file://" + str(path),
            subject_refs=[
                TASK,
                "EXECUTION",
                "TEAM-L3",
                "TEAM-TASK-L3",
                "MEMBER-L3",
                SPECIALIST,
                "ASSIGN-L3",
                ATTEMPT,
                "LEASE-L3",
            ],
            content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )


def _control(tmp_path: Path) -> ClosedLoopControlPlane:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="prove parent API provenance"),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="run one L3 API case",
            required_capabilities=["test_execution"],
        )
    )
    assert control.scheduler.task(TASK).state == TaskStatus.READY
    persist_real_executor_contract(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        execution_task_id=TASK,
    )
    _binding(truth, tmp_path)
    return control


def _real_source() -> str:
    return r'''import json
import os
from urllib.request import Request, urlopen


def test_l3_provenance():
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


def _fake_source() -> str:
    return r'''import json
import os


def test_l3_provenance():
    with open(os.environ["RC6_EXECUTION_MANIFEST"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "type": "tool_call",
            "tool_id": "api-runtime",
            "call_ref": "api-runtime://APIREC-FORGED",
            "evidence_ref": "api-evidence://FORGED",
        }) + "\n")
        handle.write(json.dumps({
            "type": "actual_result",
            "value": {"business_code": "OK"},
        }) + "\n")
    assert True
'''


def _execute(tmp_path: Path, base_url: str, source: str):
    control = _control(tmp_path)
    result = ControlledL3ClosedLoopExecutionService(
        evidence_root=str(tmp_path / "execution-evidence"), timeout_seconds=20
    ).execute_task(
        control,
        TASK,
        bundle=_bundle(tmp_path, source),
        prepared=_prepared(),
        authority=RC7AuthorityRuntime(b"rc7-l3-provenance-signing-key"),
        tool_broker=_broker(),
        target_base_url=base_url,
        cwd=str(tmp_path),
    )
    return control, result


def _real_invocations(truth: TruthRuntime):
    return [
        row
        for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "REAL_EXECUTOR_INVOCATION"
    ]


def test_real_parent_api_receipt_is_promoted_to_current_attempt_provenance(tmp_path: Path) -> None:
    with _Target() as target:
        control, result = _execute(tmp_path, target.base_url, _real_source())
        assert len(target.hits) == 1
        assert target.hits[0][0] == "/loan/rate/adjust"

    assert result.execution_record.status == "PASS"
    rows = _real_invocations(control.truth)
    assert len(rows) == 1
    assert rows[0]["source_ref"] == "runtime-tool://pfc-aitest-rc7/api-runtime"
    assert rows[0]["evidence_id"] in result.evidence_ids
    gate = RealExecutorProvenanceGate(control.truth).require_record(
        MISSION, TASK, result.execution_record
    )
    assert gate.status == "PASS"
    assert gate.observed_tools == ("api-runtime",)


def test_child_manifest_forgery_cannot_create_l3_real_executor_provenance(tmp_path: Path) -> None:
    with _Target() as target:
        control, result = _execute(tmp_path, target.base_url, _fake_source())
        assert target.hits == []

    assert result.execution_record.status == "FAIL"
    assert result.task_state == "REPAIR_REQUIRED"
    assert _real_invocations(control.truth) == []
