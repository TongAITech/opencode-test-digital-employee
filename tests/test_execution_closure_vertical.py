from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rc6_runtime import (
    AIScriptBuilder,
    AttemptHistory,
    AttemptHistoryEntry,
    AuthorityRuntime,
    AutomationReuseResolver,
    CorrelationScope,
    DiagnosisRuntime,
    ExecutableSpecBuilder,
    ExecutionConvergenceController,
    ExecutionRuntime,
    FailureContext,
    PreparedAttempt,
    PytestRunnerAdapter,
    RecoveryActionExecutor,
    RecoveryEngine,
    ScriptValidator,
    ToolCapabilityBroker,
)


TARGET = "TARGET-L3-LOCAL-HTTP"
TC_ID = "TC-L3-REAL-HTTP"
RELEASE = "BLOAN-PF1.2.0"
REQ = "STBB19-320"
SST = "STB915-7489"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/ok":
            status, payload = 200, {"code": "0000", "business": "accepted"}
        elif self.path == "/bad-product":
            status, payload = 200, {"code": "9999", "business": "wrong-product-result"}
        else:
            status, payload = 404, {"code": "ROUTE_NOT_FOUND", "business": "route-miss"}
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # noqa: A003
        return


class LocalApi:
    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = "http://%s:%s" % (host, port)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def frozen_case():
    return {
        "tc_id": TC_ID,
        "case_version": 1,
        "release_id": RELEASE,
        "requirement_id": REQ,
        "sst_id": SST,
        "condition_id": "COND-L3-HTTP",
        "objective": "verify cfg-data style service business code",
        "layer": "L3",
        "preconditions": [{"id": "target", "description": "local qualified HTTP target"}],
        "test_data": {"input": "none"},
        "steps": ["read authoritative route binding", "invoke real HTTP GET", "capture actual result"],
        "expected": "business code is 0000",
        "oracle": {"type": "field_equals", "field": "code", "value": "0000"},
        "evidence_requirements": ["http-call", "http-status", "actual-result", "oracle"],
        "status": "FROZEN",
    }


def oracle(snapshot, actual, context):
    field = snapshot["field"]
    expected = snapshot["value"]
    passed = actual.get(field) == expected
    return {
        "passed": passed,
        "assertion_ref": "assertion://%s/%s" % (context["attempt_id"], field),
        "evidence_refs": ["oracle-evidence://%s/%s" % (context["attempt_id"], "pass" if passed else "fail")],
        "details": {"field": field, "expected": expected, "actual": actual.get(field)},
    }


def build_artifacts(tmp_path: Path, route_file: Path, base_url: str):
    case = frozen_case()
    api_client = tmp_path / "api_client.py"
    api_client.write_text(
        "import json\n"
        "from urllib.error import HTTPError\n"
        "from urllib.request import urlopen\n"
        "def call_json(url):\n"
        "    try:\n"
        "        with urlopen(url, timeout=5) as response:\n"
        "            return int(response.status), json.loads(response.read().decode('utf-8'))\n"
        "    except HTTPError as exc:\n"
        "        return int(exc.code), json.loads(exc.read().decode('utf-8'))\n",
        encoding="utf-8",
    )
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=(TARGET, "api-runtime:READY"),
        test_data_refs=(),
        oracle_refs=("oracle://%s@1" % TC_ID,),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse_required": True},
    )
    resolution = AutomationReuseResolver().resolve(
        spec=spec,
        search_roots=(str(tmp_path),),
        extra_keywords=("api", "http"),
    )
    assert any(asset.category == "api_client" and asset.ref.endswith("api_client.py") for asset in resolution.assets)

    test_file = tmp_path / "test_l3_real_api.py"
    test_file.write_text(
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "from api_client import call_json\n"
        "from rc6_runtime.runner_manifest import record_actual_result, record_tool_call\n"
        "def test_l3_real_api():\n"
        "    route = Path(os.environ['RC6_ROUTE_FILE']).read_text(encoding='utf-8').strip()\n"
        "    status, body = call_json(os.environ['RC6_BASE_URL'] + route)\n"
        "    actual = {'http_status': status, 'code': body.get('code'), 'route': route}\n"
        "    if os.environ.get('RC6_EXECUTION_MANIFEST'):\n"
        "        record_tool_call('api-runtime', 'http-call://' + route.replace('/', '_'), 'http-evidence://' + str(status))\n"
        "        record_actual_result(actual)\n"
        "    assert isinstance(actual['code'], str)\n",
        encoding="utf-8",
    )
    script = AIScriptBuilder().build(
        spec=spec,
        resolution=resolution,
        generator=lambda spec_value, mapping: {
            "source_ref": "file://" + str(test_file),
            "test_symbol": "test_l3_real_api",
            "case_fingerprint": spec_value.case_fingerprint,
            "oracle_fingerprint": spec_value.oracle_fingerprint,
            "evidence_refs": ["builder://l3-real-api", "reuse://api-client"],
        },
    )
    repo_root = str(Path(__file__).resolve().parents[1])
    env = {
        "RC6_BASE_URL": base_url,
        "RC6_ROUTE_FILE": str(route_file),
        "PYTHONPATH": repo_root,
    }
    validation = ScriptValidator(timeout_seconds=60).validate(
        spec=spec,
        script=script,
        cwd=str(tmp_path),
        env=env,
        execute_target=True,
    )
    assert validation.ready
    return case, spec, script, validation, env


def execution_runtime():
    authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
    broker = ToolCapabilityBroker()
    worker = authority.issue_identity("L3_EXECUTE", "EXECUTION", "L3", 0, "dsh://l3-exec/1")
    lease = authority.issue_lease(
        worker.worker_id,
        "case:%s@1" % TC_ID,
        ["execution_attempt", "assertion", "evidence", "coverage_observation"],
        ["api-runtime"],
    )
    broker.discover("api-runtime", "stdlib://urllib")
    broker.mark_executable("api-runtime", "python://urllib.request")
    broker.register("api-runtime", "runner-manifest://api-runtime")
    broker.bind_worker("api-runtime", worker.worker_id, visible=True, permitted=True)
    broker.record_probe(
        "api-runtime",
        success=True,
        tool_call_ref="probe://api-runtime",
        evidence_ref="evidence://api-runtime/probe",
    )
    broker.mark_target_ready("api-runtime", TARGET, "evidence://target/l3-http")
    return authority, broker, worker, lease, ExecutionRuntime(authority=authority, tool_broker=broker, oracle_evaluator=oracle)


def prepared(attempt_id):
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id=TC_ID,
        case_version=1,
        target_id=TARGET,
        precondition_evidence=("precondition://target-ready",),
        initial_state_bindings={},
        input_data_bindings={},
        binding_evidence=("binding://none",),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot={"type": "field_equals", "field": "code", "value": "0000"},
    )


def ready_cat(authority, broker, attempt_id):
    worker = authority.issue_identity("FAILURE_DIAGNOSTIC", "DIAGNOSIS", None, 0, "dsh://diag/%s" % attempt_id)
    lease = authority.issue_lease(
        worker.worker_id,
        "attempt:%s" % attempt_id,
        ["failure_diagnosis", "root_cause_candidate", "recovery_decision", "recovery_action", "execution_convergence", "evidence", "defect"],
        ["cat", "codegraph", "git"],
    )
    broker.discover("cat", "mcp://cat")
    broker.mark_executable("cat", "mcp-exec://cat")
    broker.register("cat", "mcp://cat")
    broker.bind_worker("cat", worker.worker_id, visible=True, permitted=True)
    broker.record_probe("cat", success=True, tool_call_ref="probe://cat", evidence_ref="evidence://cat/probe")
    broker.mark_target_ready("cat", TARGET, "evidence://cat/target")
    return worker, lease


def route_context(record, *, route_verified):
    return FailureContext(
        attempt_id=record.attempt_id,
        tc_id=record.tc_id,
        case_version=record.case_version,
        target_id=record.target_id,
        layer=record.layer,
        execution_status=record.status,
        preparation_verified=True,
        real_action_executed=True,
        assertion_failed=record.assertion_passed is False,
        execution_evidence_refs=record.evidence_refs,
        correlation=CorrelationScope(
            applications=("cfg-center", "cfg-data"),
            window_start=1000,
            window_end=1060,
            request_id="request-%s" % record.attempt_id,
        ),
        case_oracle_verified=True,
        executable_spec_verified=True,
        script_validated=True,
        data_verified=True,
        auth_verified=True,
        route_verified=route_verified,
        tool_verified=True,
        environment_verified=True,
        dependency_verified=True,
        exception_type="AssertionError",
        root_stack_frame="test_l3_real_api:test_l3_real_api",
        http_status=int(record.actual_result["http_status"]),
        business_error_code=str(record.actual_result["code"]),
        route=str(record.actual_result["route"]),
        assertion_identity=record.assertion_ref,
        runner_log_refs=tuple(ref for ref in record.evidence_refs if ref.startswith(("stdout://", "stderr://"))),
    )


def test_vertical_a_real_l3_pytest_http_execution_passes(tmp_path):
    route_file = tmp_path / "route.txt"
    route_file.write_text("/ok", encoding="utf-8")
    with LocalApi() as api:
        case, spec, script, validation, env = build_artifacts(tmp_path, route_file, api.base_url)
        authority, broker, worker, lease, runtime = execution_runtime()
        record = runtime.execute_with_runner(
            case=case,
            executable_spec=spec,
            script=script,
            validation=validation,
            prepared=prepared("ATT-A1"),
            worker_id=worker.worker_id,
            lease_id=lease.lease_id,
            runner=PytestRunnerAdapter(timeout_seconds=60),
            cwd=str(tmp_path),
            env=env,
        )
        assert record.status == "PASS"
        assert record.integrity_passed is True
        assert record.actual_result == {"http_status": 200, "code": "0000", "route": "/ok"}
        assert record.assertion_passed is True
        assert any(ref.startswith("http-call://") for ref in record.tool_call_refs)
        assert any(ref.startswith("http-evidence://200") for ref in record.evidence_refs)


def test_vertical_b_route_failure_recovers_with_new_attempt_and_reruns_pass(tmp_path):
    route_file = tmp_path / "route.txt"
    route_file.write_text("/wrong", encoding="utf-8")
    with LocalApi() as api:
        case, spec, script, validation, env = build_artifacts(tmp_path, route_file, api.base_url)
        authority, broker, exec_worker, exec_lease, runtime = execution_runtime()
        first = runtime.execute_with_runner(
            case=case,
            executable_spec=spec,
            script=script,
            validation=validation,
            prepared=prepared("ATT-B1"),
            worker_id=exec_worker.worker_id,
            lease_id=exec_lease.lease_id,
            runner=PytestRunnerAdapter(timeout_seconds=60),
            cwd=str(tmp_path),
            env=env,
        )
        assert first.status == "FAIL"
        assert first.integrity_passed is True
        assert first.actual_result["http_status"] == 404
        assert first.reason == "ORACLE_ASSERTION_FAILED"

        diag_worker, diag_lease = ready_cat(authority, broker, first.attempt_id)
        ctx = route_context(first, route_verified=False)
        diagnosis = DiagnosisRuntime(
            authority=authority,
            tool_broker=broker,
            classifier=lambda _ctx, _signals: {
                "failure_class": "ROUTE",
                "classifier_ref": "classifier://route/v1",
                "rationale": "404 plus authoritative route mismatch",
                "evidence_refs": ["route-check://wrong-binding"],
            },
            cat_query=lambda scope, _ctx: {
                "tool_call_ref": "cat-call://%s" % scope.request_id,
                "evidence_ref": "cat-evidence://404/%s" % first.attempt_id,
                "signals": {"http_status": 404, "business_error_code": "ROUTE_NOT_FOUND", "request_id": scope.request_id},
            },
            rca_resolver=lambda _ctx, _signals, _cls: {
                "symbol": "CfgCenterRouteBinding.resolve",
                "call_path": ["cfg-center.gateway", "CfgCenterRouteBinding.resolve", "cfg-data"],
                "git_change_refs": ["git://diff/route-binding"],
                "requirement_refs": [REQ, SST],
                "evidence_refs": ["codegraph://CfgCenterRouteBinding.resolve", "git://diff/route-binding"],
                "confidence": 0.93,
            },
        ).diagnose(context=ctx, worker_id=diag_worker.worker_id, lease_id=diag_lease.lease_id)
        assert diagnosis.failure_class == "ROUTE"
        assert diagnosis.cat_queried is True
        assert diagnosis.root_cause_candidate.symbol == "CfgCenterRouteBinding.resolve"
        assert diagnosis.failure_signature.http_status == 404

        history = AttemptHistory()
        history.append(AttemptHistoryEntry(
            first.attempt_id, None, first.tc_id, first.case_version, first.target_id, first.layer,
            first.status, first.evidence_refs, 1000, diagnosis.failure_signature.signature_id,
        ))
        decision = RecoveryEngine(history).decide(ctx, diagnosis)
        assert decision.action == "RECONCILE_ROUTE_BINDING"
        assert decision.next_attempt_id

        def real_route_recovery(_ctx, _diag, _decision):
            route_file.write_text("/ok", encoding="utf-8")
            verified = route_file.read_text(encoding="utf-8").strip() == "/ok"
            return {
                "verified": verified,
                "evidence_refs": ["route-evidence://authoritative-reconcile"],
                "output_refs": ["route-binding://cfg-data/ok"],
            }

        recovery = RecoveryActionExecutor(
            history=history,
            adapters={"RECONCILE_ROUTE_BINDING": real_route_recovery},
            convergence=ExecutionConvergenceController(history),
        ).execute(context=ctx, diagnosis=diagnosis, decision=decision)
        assert recovery.status == "RECOVERY_EXECUTED"
        assert recovery.next_attempt_id == decision.next_attempt_id
        assert route_file.read_text(encoding="utf-8").strip() == "/ok"
        assert history.get(recovery.next_attempt_id).parent_attempt_id == first.attempt_id

        second = runtime.execute_with_runner(
            case=case,
            executable_spec=spec,
            script=script,
            validation=validation,
            prepared=prepared(recovery.next_attempt_id),
            worker_id=exec_worker.worker_id,
            lease_id=exec_lease.lease_id,
            runner=PytestRunnerAdapter(timeout_seconds=60),
            cwd=str(tmp_path),
            env=env,
        )
        assert second.attempt_id != first.attempt_id
        assert second.status == "PASS"
        assert second.actual_result["code"] == "0000"
        assert spec.oracle_fingerprint == script.oracle_fingerprint


def test_product_defect_protection_never_repairs_script_or_oracle_to_green(tmp_path):
    route_file = tmp_path / "route.txt"
    route_file.write_text("/bad-product", encoding="utf-8")
    with LocalApi() as api:
        case, spec, script, validation, env = build_artifacts(tmp_path, route_file, api.base_url)
        original_oracle_fp = spec.oracle_fingerprint
        original_case_fp = spec.case_fingerprint
        original_script_id = script.script_id
        authority, broker, exec_worker, exec_lease, runtime = execution_runtime()
        record = runtime.execute_with_runner(
            case=case, executable_spec=spec, script=script, validation=validation,
            prepared=prepared("ATT-P1"), worker_id=exec_worker.worker_id, lease_id=exec_lease.lease_id,
            runner=PytestRunnerAdapter(timeout_seconds=60), cwd=str(tmp_path), env=env,
        )
        assert record.status == "FAIL"
        assert record.integrity_passed is True
        assert record.actual_result["http_status"] == 200
        assert record.actual_result["code"] == "9999"

        diag_worker, diag_lease = ready_cat(authority, broker, record.attempt_id)
        ctx = route_context(record, route_verified=True)
        diagnosis = DiagnosisRuntime(
            authority=authority,
            tool_broker=broker,
            classifier=lambda _ctx, _signals: {
                "failure_class": "PRODUCT",
                "classifier_ref": "classifier://product-protection/v1",
                "rationale": "all test-side ownership domains verified; SUT business result violates immutable oracle",
                "evidence_refs": ["ownership-proof://all-test-side-correct"],
            },
            cat_query=lambda scope, _ctx: {
                "tool_call_ref": "cat-call://product/%s" % scope.request_id,
                "evidence_ref": "cat-evidence://product/%s" % record.attempt_id,
                "signals": {"http_status": 200, "business_error_code": "9999", "request_id": scope.request_id},
            },
            rca_resolver=lambda _ctx, _signals, _cls: {
                "symbol": "CfgDataService.apply",
                "call_path": ["cfg-center", "CfgDataController.apply", "CfgDataService.apply"],
                "git_change_refs": ["git://diff/cfg-data-service"],
                "requirement_refs": [REQ, SST],
                "evidence_refs": ["codegraph://CfgDataService.apply", "git://diff/cfg-data-service"],
                "confidence": 0.97,
            },
        ).diagnose(context=ctx, worker_id=diag_worker.worker_id, lease_id=diag_lease.lease_id)
        assert diagnosis.failure_class == "PRODUCT"

        history = AttemptHistory()
        history.append(AttemptHistoryEntry(
            record.attempt_id, None, record.tc_id, record.case_version, record.target_id, record.layer,
            record.status, record.evidence_refs, 1000, diagnosis.failure_signature.signature_id,
        ))
        decision = RecoveryEngine(history).decide(ctx, diagnosis)
        assert decision.action == "PRODUCT_DEFECT"
        assert decision.terminal is True
        assert decision.retry_allowed is False
        assert decision.next_attempt_id is None
        terminal = RecoveryActionExecutor(history=history).execute(context=ctx, diagnosis=diagnosis, decision=decision)
        assert terminal.terminal_status == "PRODUCT_DEFECT_CONFIRMED"
        assert len(history.entries()) == 1
        assert spec.oracle_fingerprint == original_oracle_fp
        assert spec.case_fingerprint == original_case_fp
        assert script.oracle_fingerprint == original_oracle_fp
        assert script.script_id == original_script_id
