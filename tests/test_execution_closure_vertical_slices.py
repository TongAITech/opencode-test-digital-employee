from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.automation import AIScriptBuilder, AutomationReuseResolver, PytestRunnerAdapter, ScriptValidator
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.diagnosis import (
    AttemptHistory,
    CATPolicy,
    CorrelationScope,
    DiagnosisRuntime,
    FailureContext,
    RecoveryEngine,
    history_entry_from_execution,
)
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.execution import ExecutionRuntime
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.recovery import ExecutionConvergenceController, RecoveryActionExecutor


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = "TARGET-RC6-L3-LINE-OF-FIRE"


def _case():
    return {
        "tc_id": "TC-L3-CLOSURE-001",
        "case_version": 1,
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": "STBB19-320",
        "sst_id": "STB915-7489",
        "condition_id": "COND-L3-CLOSURE",
        "objective": "verify governed API response through real pytest process",
        "layer": "L3",
        "preconditions": [{"id": "target", "state": "READY"}],
        "test_data": {},
        "steps": ["invoke configured API route", "capture actual response", "assert frozen oracle"],
        "expected": "business code is 0000",
        "oracle": {"type": "field_equals", "field": "code", "value": "0000"},
        "evidence_requirements": ["http call", "response", "oracle assertion"],
        "status": "FROZEN",
    }


def _prepared(attempt_id):
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id="TC-L3-CLOSURE-001",
        case_version=1,
        target_id=TARGET,
        precondition_evidence=("evidence://target/ready",),
        initial_state_bindings={},
        input_data_bindings={},
        binding_evidence=("evidence://prepared/%s" % attempt_id,),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot={"type": "field_equals", "field": "code", "value": "0000"},
    )


def _oracle(snapshot, actual, context):
    passed = actual.get("code") == snapshot.get("value")
    return {
        "passed": passed,
        "assertion_ref": "assertion://%s" % context["attempt_id"],
        "evidence_refs": ["oracle-evidence://%s" % context["attempt_id"]],
        "details": {"expected": snapshot.get("value"), "actual": actual.get("code")},
    }


def _ready_tool(broker, tool_id, worker_id):
    broker.discover(tool_id, "local://%s" % tool_id)
    broker.mark_executable(tool_id, "exec://%s" % tool_id)
    broker.register(tool_id, "runtime://%s" % tool_id)
    broker.bind_worker(tool_id, worker_id, visible=True, permitted=True)
    broker.record_probe(tool_id, success=True, tool_call_ref="probe://%s" % tool_id, evidence_ref="probe-evidence://%s" % tool_id)
    broker.mark_target_ready(tool_id, TARGET, "target-evidence://%s" % tool_id)


def _execution_worker(authority):
    worker = authority.issue_identity("L3_EXECUTE", "EXECUTION", "L3", 0, "session-l3")
    lease = authority.issue_lease(
        worker.worker_id,
        "case:TC-L3-CLOSURE-001@1",
        ["execution_attempt", "assertion", "evidence"],
        ["api-runtime"],
    )
    return worker, lease


def _diagnostic_worker(authority, attempt_id):
    worker = authority.issue_identity("FAILURE_DIAGNOSTIC", "DIAGNOSIS", None, 0, "session-diag-%s" % attempt_id)
    lease = authority.issue_lease(
        worker.worker_id,
        "attempt:%s" % attempt_id,
        ["failure_diagnosis", "recovery_decision", "recovery_action", "evidence", "defect"],
        ["cat"],
    )
    return worker, lease


def _write_real_pytest_script(folder):
    script = folder / "test_l3_line_of_fire.py"
    script.write_text(
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "from urllib.error import HTTPError\n"
        "from urllib.request import urlopen\n"
        "from rc6_runtime.runner_manifest import record_actual_result, record_note, record_tool_call\n\n"
        "def test_real_l3_api():\n"
        "    route = Path(os.environ['RC6_ROUTE_FILE']).read_text(encoding='utf-8').strip()\n"
        "    url = os.environ['RC6_TEST_BASE_URL'] + route\n"
        "    try:\n"
        "        with urlopen(url, timeout=5) as response:\n"
        "            status = int(response.status)\n"
        "            body = json.loads(response.read().decode('utf-8'))\n"
        "    except HTTPError as exc:\n"
        "        status = int(exc.code)\n"
        "        body = json.loads(exc.read().decode('utf-8'))\n"
        "    record_tool_call('api-runtime', 'http-call://%s%s' % (status, route), 'http-evidence://%s%s' % (status, route))\n"
        "    record_actual_result({'http_status': status, 'code': body.get('code'), 'business': body.get('business'), 'route': route})\n"
        "    record_note('route', 'route-evidence://' + route)\n"
        "    assert status == 200\n",
        encoding="utf-8",
    )
    return script


def _write_sut(folder):
    sut = folder / "l3_sut.py"
    sut.write_text(
        "import json\n"
        "import sys\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "from pathlib import Path\n\n"
        "port_file = Path(sys.argv[1])\n"
        "mode_file = Path(sys.argv[2])\n\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def log_message(self, fmt, *args):\n"
        "        return\n"
        "    def do_GET(self):\n"
        "        if self.path != '/api/apply':\n"
        "            status, payload = 404, {'code': 'ROUTE_NOT_FOUND', 'business': 'NOT_FOUND'}\n"
        "        else:\n"
        "            mode = mode_file.read_text(encoding='utf-8').strip()\n"
        "            if mode == 'PRODUCT_ERROR':\n"
        "                status, payload = 200, {'code': '9999', 'business': 'ERROR'}\n"
        "            else:\n"
        "                status, payload = 200, {'code': '0000', 'business': 'OK'}\n"
        "        body = json.dumps(payload).encode('utf-8')\n"
        "        self.send_response(status)\n"
        "        self.send_header('Content-Type', 'application/json')\n"
        "        self.send_header('Content-Length', str(len(body)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(body)\n\n"
        "server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)\n"
        "port_file.write_text(str(server.server_port), encoding='utf-8')\n"
        "server.serve_forever()\n",
        encoding="utf-8",
    )
    return sut


def _start_sut(folder, mode="OK"):
    mode_file = folder / "mode.txt"
    mode_file.write_text(mode, encoding="utf-8")
    port_file = folder / "port.txt"
    sut = _write_sut(folder)
    process = subprocess.Popen(
        [sys.executable, str(sut), str(port_file), str(mode_file)],
        cwd=str(folder),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    while time.time() < deadline and not port_file.is_file():
        if process.poll() is not None:
            raise AssertionError("L3 SUT process terminated before binding")
        time.sleep(0.05)
    if not port_file.is_file():
        process.terminate()
        raise AssertionError("L3 SUT did not publish its port")
    return process, "http://127.0.0.1:%s" % port_file.read_text(encoding="utf-8").strip(), mode_file


def _build_chain(folder, base_url, route_file):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("TARGET-QUALIFIED", "api-runtime:READY"),
        test_data_refs=(),
        oracle_refs=("oracle://TC-L3-CLOSURE-001@1",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse_refs": []},
    )
    script_path = _write_real_pytest_script(folder)
    resolution = AutomationReuseResolver().resolve(spec=spec, search_roots=(str(folder), str(REPO_ROOT)))
    script = AIScriptBuilder().build(
        spec=spec,
        resolution=resolution,
        generator=lambda value, mapping: {
            "source_ref": "file://" + str(script_path),
            "test_symbol": "test_real_l3_api",
            "case_fingerprint": value.case_fingerprint,
            "oracle_fingerprint": value.oracle_fingerprint,
            "evidence_refs": ["builder-evidence://l3-line-of-fire"],
        },
    )
    env = {
        "PYTHONPATH": str(REPO_ROOT) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
        "RC6_TEST_BASE_URL": base_url,
        "RC6_ROUTE_FILE": str(route_file),
    }
    validation = ScriptValidator(timeout_seconds=60).validate(
        spec=spec,
        script=script,
        cwd=str(folder),
        env=env,
        execute_target=True,
    )
    assert validation.ready
    return case, spec, script, validation, env


def _runtime():
    authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
    broker = ToolCapabilityBroker()
    worker, lease = _execution_worker(authority)
    _ready_tool(broker, "api-runtime", worker.worker_id)
    runtime = ExecutionRuntime(authority=authority, tool_broker=broker, oracle_evaluator=_oracle)
    return authority, broker, worker, lease, runtime


def _cat_ready(broker, worker_id):
    _ready_tool(broker, "cat", worker_id)


def _diagnose_route(authority, broker, attempt_id, execution):
    worker, lease = _diagnostic_worker(authority, attempt_id)
    _cat_ready(broker, worker.worker_id)
    ctx = FailureContext(
        attempt_id=attempt_id,
        tc_id=execution.tc_id,
        case_version=execution.case_version,
        target_id=execution.target_id,
        layer="L3",
        execution_status=execution.status,
        preparation_verified=True,
        real_action_executed=True,
        assertion_failed=True,
        execution_evidence_refs=execution.evidence_refs,
        correlation=CorrelationScope(("cfg-center", "cfg-data"), 1000, 1060, trace_id="trace-route-1"),
        exception_type="HTTPError",
        root_stack_frame="urllib.request.urlopen",
        http_status=404,
        business_error_code="ROUTE_NOT_FOUND",
        route="/wrong-route",
        assertion_identity=execution.assertion_ref,
        runner_log_refs=tuple(ref for ref in execution.evidence_refs if ref.startswith(("stdout://", "stderr://"))),
    )
    diagnosis = DiagnosisRuntime(
        authority=authority,
        tool_broker=broker,
        classifier=lambda _ctx, _signals: {
            "failure_class": "ROUTE",
            "classifier_ref": "classifier://execution-closure/route-v1",
            "rationale": "runner actual shows authoritative route mismatch",
            "evidence_refs": ["classifier-evidence://route-404"],
        },
        cat_query=lambda _scope, _ctx: {
            "tool_call_ref": "cat-call://trace-route-1",
            "evidence_ref": "cat-evidence://trace-route-1",
            "signals": {"http_status": 404, "route": "/wrong-route", "trace_id": "trace-route-1"},
        },
        cat_policy=CATPolicy(max_window_seconds=900),
        rca_resolver=lambda _ctx, _signals, _cls: {
            "symbol": "CfgDataController.apply",
            "call_path": ["cfg-center.gateway", "CfgDataController.apply"],
            "git_change_refs": ["git-diff://cfg-data/current"],
            "requirement_refs": ["STBB19-320", "STB915-7489"],
            "evidence_refs": ["codegraph://symbol/CfgDataController.apply", "git-diff://cfg-data/current"],
            "confidence": 0.93,
        },
    ).diagnose(context=ctx, worker_id=worker.worker_id, lease_id=lease.lease_id)
    return ctx, diagnosis


def test_vertical_slice_a_real_l3_pytest_process_api_execution_to_pass():
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        route_file = folder / "route.txt"
        route_file.write_text("/api/apply", encoding="utf-8")
        process, base_url, _mode_file = _start_sut(folder, "OK")
        try:
            case, spec, script, validation, env = _build_chain(folder, base_url, route_file)
            authority, broker, worker, lease, runtime = _runtime()
            record = runtime.execute_with_runner(
                case=case,
                executable_spec=spec,
                script=script,
                validation=validation,
                prepared=_prepared("ATT-L3-A1"),
                worker_id=worker.worker_id,
                lease_id=lease.lease_id,
                runner=PytestRunnerAdapter(timeout_seconds=60),
                cwd=str(folder),
                env=env,
            )
            assert record.status == "PASS"
            assert record.integrity_passed
            assert record.actual_result["code"] == "0000"
            assert record.actual_result["route"] == "/api/apply"
            assert any(ref.startswith("http-call://") for ref in record.tool_call_refs)
            assert any(ref.startswith("http-evidence://") for ref in record.evidence_refs)
            assert record.assertion_passed is True
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_vertical_slice_b_route_failure_diagnosis_recovery_new_attempt_rerun_pass():
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        route_file = folder / "route.txt"
        route_file.write_text("/api/apply", encoding="utf-8")
        process, base_url, _mode_file = _start_sut(folder, "OK")
        try:
            case, spec, script, validation, env = _build_chain(folder, base_url, route_file)
            # Inject drift only after SCRIPT_READY: script is valid, route binding is now wrong.
            route_file.write_text("/wrong-route", encoding="utf-8")
            authority, broker, worker, lease, runtime = _runtime()
            first = runtime.execute_with_runner(
                case=case,
                executable_spec=spec,
                script=script,
                validation=validation,
                prepared=_prepared("ATT-L3-B1"),
                worker_id=worker.worker_id,
                lease_id=lease.lease_id,
                runner=PytestRunnerAdapter(timeout_seconds=60),
                cwd=str(folder),
                env=env,
            )
            assert first.status == "FAIL"
            assert first.actual_result["http_status"] == 404

            ctx, diagnosis = _diagnose_route(authority, broker, "ATT-L3-B1", first)
            assert diagnosis.failure_class == "ROUTE"
            assert diagnosis.failure_signature is not None
            assert diagnosis.root_cause_candidate is not None
            assert diagnosis.root_cause_candidate.symbol == "CfgDataController.apply"
            assert diagnosis.root_cause_candidate.evidence_refs

            history = AttemptHistory()
            history.append(history_entry_from_execution(first, recorded_at=1))
            decision = RecoveryEngine(history).decide(ctx, diagnosis)
            assert decision.action == "RECONCILE_ROUTE_BINDING"
            controller = ExecutionConvergenceController(history)

            def repair_route(_context, _diagnosis, _decision):
                route_file.write_text("/api/apply", encoding="utf-8")
                return {
                    "verified": route_file.read_text(encoding="utf-8").strip() == "/api/apply",
                    "evidence_refs": ["route-reconcile-evidence://authoritative-binding"],
                    "output_refs": ["route-binding://cfg-data/api-apply"],
                }

            recovered = RecoveryActionExecutor(
                history=history,
                convergence=controller,
                adapters={"RECONCILE_ROUTE_BINDING": repair_route},
            ).execute(context=ctx, diagnosis=diagnosis, decision=decision)
            assert recovered.status == "RECOVERY_EXECUTED"
            assert recovered.next_attempt_id == decision.next_attempt_id
            assert history.get(recovered.next_attempt_id).parent_attempt_id == "ATT-L3-B1"

            second = runtime.execute_with_runner(
                case=case,
                executable_spec=spec,
                script=script,
                validation=validation,
                prepared=_prepared(recovered.next_attempt_id),
                worker_id=worker.worker_id,
                lease_id=lease.lease_id,
                runner=PytestRunnerAdapter(timeout_seconds=60),
                cwd=str(folder),
                env=env,
            )
            assert second.status == "PASS"
            assert second.actual_result["code"] == "0000"
            assert controller.pass_result().terminal_status == "PASS"
            assert len(history.entries()) == 2
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_product_defect_protection_does_not_repair_script_or_oracle_to_green():
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        route_file = folder / "route.txt"
        route_file.write_text("/api/apply", encoding="utf-8")
        process, base_url, _mode_file = _start_sut(folder, "PRODUCT_ERROR")
        try:
            case, spec, script, validation, env = _build_chain(folder, base_url, route_file)
            frozen_oracle_fp = spec.oracle_fingerprint
            frozen_script_oracle_fp = script.oracle_fingerprint
            authority, broker, worker, lease, runtime = _runtime()
            record = runtime.execute_with_runner(
                case=case,
                executable_spec=spec,
                script=script,
                validation=validation,
                prepared=_prepared("ATT-L3-P1"),
                worker_id=worker.worker_id,
                lease_id=lease.lease_id,
                runner=PytestRunnerAdapter(timeout_seconds=60),
                cwd=str(folder),
                env=env,
            )
            assert record.status == "FAIL"
            assert record.integrity_passed
            assert record.assertion_passed is False
            assert record.actual_result["http_status"] == 200
            assert record.actual_result["code"] == "9999"

            diag_worker, diag_lease = _diagnostic_worker(authority, "ATT-L3-P1")
            _cat_ready(broker, diag_worker.worker_id)
            ctx = FailureContext(
                attempt_id="ATT-L3-P1",
                tc_id=record.tc_id,
                case_version=record.case_version,
                target_id=record.target_id,
                layer="L3",
                execution_status="FAIL",
                preparation_verified=True,
                real_action_executed=True,
                assertion_failed=True,
                execution_evidence_refs=record.evidence_refs,
                correlation=CorrelationScope(("cfg-center", "cfg-data"), 2000, 2060, business_id="BIZ-PRODUCT-1"),
                case_oracle_verified=True,
                executable_spec_verified=True,
                script_validated=True,
                data_verified=True,
                auth_verified=True,
                route_verified=True,
                tool_verified=True,
                environment_verified=True,
                dependency_verified=True,
                http_status=200,
                business_error_code="9999",
                route="/api/apply",
                assertion_identity=record.assertion_ref,
            )
            diagnosis = DiagnosisRuntime(
                authority=authority,
                tool_broker=broker,
                classifier=lambda _ctx, _signals: {
                    "failure_class": "PRODUCT",
                    "classifier_ref": "classifier://execution-closure/product-v1",
                    "rationale": "all test-side ownership candidates excluded by evidence",
                    "evidence_refs": ["ownership-evidence://all-test-side-verified"],
                },
                cat_query=lambda _scope, _ctx: {
                    "tool_call_ref": "cat-call://biz-product-1",
                    "evidence_ref": "cat-evidence://biz-product-1",
                    "signals": {"business_error_code": "9999", "business_id": "BIZ-PRODUCT-1"},
                },
                rca_resolver=lambda _ctx, _signals, _cls: {
                    "symbol": "CfgDataService.apply",
                    "call_path": ["CfgDataController.apply", "CfgDataService.apply"],
                    "git_change_refs": ["git-diff://cfg-data/product-change"],
                    "requirement_refs": ["STBB19-320", "STB915-7489"],
                    "evidence_refs": ["codegraph://symbol/CfgDataService.apply", "git-diff://cfg-data/product-change"],
                    "confidence": 0.97,
                },
            ).diagnose(context=ctx, worker_id=diag_worker.worker_id, lease_id=diag_lease.lease_id)
            assert diagnosis.failure_class == "PRODUCT"

            history = AttemptHistory()
            history.append(history_entry_from_execution(record, recorded_at=1))
            decision = RecoveryEngine(history).decide(ctx, diagnosis)
            assert decision.action == "PRODUCT_DEFECT"
            assert decision.terminal
            terminal = RecoveryActionExecutor(history=history).execute(context=ctx, diagnosis=diagnosis, decision=decision)
            assert terminal.terminal_status == "PRODUCT_DEFECT_CONFIRMED"
            assert terminal.next_attempt_id is None
            assert len(history.entries()) == 1
            assert spec.oracle_fingerprint == frozen_oracle_fp
            assert script.oracle_fingerprint == frozen_script_oracle_fp == frozen_oracle_fp
            assert script.revision == 1
        finally:
            process.terminate()
            process.wait(timeout=10)
