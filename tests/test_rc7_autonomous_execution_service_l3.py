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
from rc7_runtime.autonomous_execution_service import AutonomousClosedLoopExecutionService
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.execution_diagnosis import ExecutionTrustFacts
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


MISSION = "MISSION-AUTO-L3-SERVICE"
TASK = "TASK-AUTO-L3-SERVICE"
TARGET = "TARGET-AUTO-L3-SERVICE"


class _TransientThenHealthyTarget:
    def __init__(self):
        owner = self
        self.hits = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
                owner.hits.append((self.path, body))
                if len(owner.hits) == 1:
                    status = 503
                    payload = {"business_code": "TEMP_UNAVAILABLE"}
                else:
                    status = 200
                    payload = {"business_code": "OK"}
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(status)
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
        "tc_id": "TC-AUTO-L3-SERVICE",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-AUTO-L3-SERVICE",
        "requirement_id": "REQ-AUTO-L3-SERVICE",
        "sst_id": "SST-AUTO-L3-SERVICE",
        "layer": "L3",
        "preconditions": [],
        "steps": [{"order": 1, "action": "POST via parent runtime proxy"}],
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
        "target_requirements": ["REQ-AUTO-L3-SERVICE"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://auto-l3-service"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _bundle(tmp_path: Path):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-AUTO-L3-SERVICE",),
        test_data_refs=(),
        oracle_refs=("oracle://auto-l3-service",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    source = tmp_path / "test_auto_l3_service.py"
    source.write_text(
        r'''import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def test_auto_l3_service():
    payload = json.dumps({
        "method": "POST",
        "path": "/loan/rate/adjust",
        "body": {"loan_id": "L-300", "delta": 0.01},
        "capture_as": "actual_result",
    }).encode("utf-8")
    request = Request(
        os.environ["RC7_API_RUNTIME_PROXY_URL"],
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        response = urlopen(request, timeout=5)
        envelope = json.loads(response.read().decode("utf-8"))
        assert envelope["receipt_id"]
    except HTTPError as exc:
        envelope = json.loads(exc.read().decode("utf-8"))
        assert envelope["receipt_id"]
''',
        encoding="utf-8",
    )
    script = ScriptArtifact(
        script_id="SCRIPT-AUTO-L3-SERVICE",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source),
        test_symbol="test_auto_l3_service",
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
        attempt_id="ATT-AUTO-L3-ROOT",
        tc_id="TC-AUTO-L3-SERVICE",
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


def test_formal_l3_service_autonomously_retries_503_then_passes_and_resolves_gap(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7-AUTO-L3-SERVICE", goal="recover transient L3 failure"),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute real L3 request with bounded recovery",
            required_capabilities=["test_execution"],
        )
    )
    broker = _broker()
    authority = RC7AuthorityRuntime(b"rc7-auto-l3-service-signing-key")

    def cat_query(scope, context):
        return {
            "tool_call_ref": "toolcall://cat/%s" % context.attempt_id,
            "evidence_ref": "evidence://cat/%s" % context.attempt_id,
            "signals": {"trace_id": scope.trace_id, "status": context.http_status},
        }

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
            trace_id="trace-auto-l3-service",
        ),
    )

    with _TransientThenHealthyTarget() as target:
        result = AutonomousClosedLoopExecutionService(
            evidence_root=str(tmp_path / "execution-evidence"),
            timeout_seconds=20,
            max_cycles=3,
            max_transient_retries=2,
        ).execute_l3(
            control,
            TASK,
            bundle=_bundle(tmp_path),
            prepared=_prepared(),
            authority=authority,
            tool_broker=broker,
            target_base_url=target.base_url,
            cwd=str(tmp_path),
            diagnosis_trust=trust,
            cat_query=cat_query,
        )

    assert len(target.hits) == 2
    assert len(result.attempts) == 2
    assert len(result.authorizations) == 1
    assert result.attempts[0].execution_record.status == "FAIL"
    assert result.attempts[0].loop_result.evaluation.dimensions["failure_class"] == "TRANSIENT"
    assert result.attempts[0].loop_result.evaluation.dimensions["recovery_action"] == "RETRY_SAME_STEP"
    assert result.attempts[1].execution_record.status == "PASS"
    assert result.attempts[1].loop_result.test_result == "PASS"
    assert result.final_task_state == "PASS"
    assert result.converged is True
    assert control.scheduler.task(TASK).state == TaskStatus.PASS
    gaps = truth.query("rc7_gap", mission_id=MISSION)
    transient = [row for row in gaps if row["category"] == "TRANSIENT_FAILURE"]
    assert len(transient) == 1
    assert transient[0]["state"] == "RESOLVED"
    attempts = [item.execution_record.attempt_id for item in result.attempts]
    assert attempts[0] == "ATT-AUTO-L3-ROOT"
    assert attempts[1] == result.authorizations[0].successor_attempt_id
    assert attempts[1] != attempts[0]
