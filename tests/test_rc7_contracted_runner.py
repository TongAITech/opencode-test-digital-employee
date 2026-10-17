from __future__ import annotations

from types import SimpleNamespace

from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime
from rc7_release import contracted_runner
from rc7_release import mcp_server
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


MISSION = "MISSION-CONTRACTED-RUNNER"
RELEASE = "REL-CONTRACTED-RUNNER"
TASK = "TASK-CONTRACTED-EXEC"
ATTEMPT = "ATTEMPT-CONTRACTED-1"


def _truth(tmp_path):
    install_rc7_truth_overlay()
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="contracted runner"), release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="PRODUCE",
            objective="execute with deterministic oracle",
            state=TaskStatus.RUNNING,
            lease_owner="WORKER-EXEC",
        ),
        release_id=RELEASE,
    )
    return truth


def test_contracted_runner_uses_all_deterministic_oracle_checks_and_persists_formal_record(tmp_path, monkeypatch):
    truth = _truth(tmp_path)
    spec = SimpleNamespace(
        release_id=RELEASE,
        spec_id="SPEC-1",
        oracle_fingerprint="oracle-fingerprint-1",
        runner_type="PYTEST",
    )
    script = SimpleNamespace(runner_type="PYTEST")
    validation = SimpleNamespace()
    oracle_snapshot = {
        "checks": [
            {"id": "CHK-1", "type": "BUSINESS_RULE", "actual_path": "body.code", "operator": "EQ", "expected": "OK"},
            {"id": "CHK-2", "type": "BUSINESS_RULE", "actual_path": "body.limit", "operator": "LTE", "expected": 5},
        ]
    }
    prepared = SimpleNamespace(attempt_id=ATTEMPT, oracle_snapshot=oracle_snapshot)

    monkeypatch.setattr(contracted_runner.closure, "_spec", lambda _value: spec)
    monkeypatch.setattr(contracted_runner.closure, "_script", lambda _value: script)
    monkeypatch.setattr(contracted_runner.closure, "_validation", lambda _value: validation)
    monkeypatch.setattr(contracted_runner.closure, "_prepared", lambda _value: prepared)
    monkeypatch.setattr(contracted_runner.closure, "_record_execution_truth", lambda *_args: {"attempt": "r1-attempt", "assertion": "r1-assertion", "evidence": []})
    monkeypatch.setattr(contracted_runner, "PytestRunnerAdapter", lambda: object())

    class FakeRuntime:
        def __init__(self, *, oracle_evaluator, **_kwargs):
            self.oracle_evaluator = oracle_evaluator

        def execute_with_runner(self, **_kwargs):
            actual = {"body": {"code": "OK", "limit": 9}}
            assertion = self.oracle_evaluator(oracle_snapshot, actual, {"attempt_id": ATTEMPT})
            # First check passes, second fails. A first-check-only adapter would
            # incorrectly return PASS here; the RC7 deterministic Oracle must not.
            assert assertion["passed"] is False
            assert len(assertion["details"]["checks"]) == 2
            return ExecutionRecord(
                attempt_id=ATTEMPT,
                tc_id="TC-1",
                case_version=1,
                target_id="TARGET-1",
                layer="L3",
                worker_id="WORKER-EXEC",
                lease_id="LEASE-EXEC",
                status="FAIL",
                integrity_passed=True,
                actual_result=actual,
                tool_call_refs=("tool://api",),
                evidence_refs=tuple(assertion["evidence_refs"]),
                assertion_ref=assertion["assertion_ref"],
                assertion_passed=False,
                reason="ORACLE_ASSERTION_FAILED",
            )

    monkeypatch.setattr(contracted_runner, "ExecutionRuntime", FakeRuntime)
    result = contracted_runner.execute_contracted_runner(
        {
            "spec": {}, "script": {}, "validation": {}, "prepared_attempt": {},
            "case": {}, "worker_id": "WORKER-EXEC", "lease_id": "LEASE-EXEC", "cwd": str(tmp_path),
        },
        authority=object(),
        truth=truth,
        broker=object(),
        state_root=tmp_path,
        mission_id=MISSION,
        task_id=TASK,
    )

    assert result["execution"]["status"] == "FAIL"
    assert result["execution"]["assertion_passed"] is False
    assert result["oracle_runtime"] == "RC7_DETERMINISTIC_ACTUAL_PATH_OPERATOR_EXPECTED"
    evidence = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "RUNTIME_EXECUTION_RECORD"
    ]
    assert len(evidence) == 1
    assert ATTEMPT in evidence[0]["subject_refs"]
    assert evidence[0]["content_hash"].startswith("sha256:")


def test_graph_v2_runner_execute_routes_to_rc7_bridge_not_legacy_rc6(monkeypatch, tmp_path):
    truth = _truth(tmp_path)
    called = {}

    monkeypatch.setattr(mcp_server.rc6, "_truth_runtime", lambda: truth)
    monkeypatch.setattr(mcp_server.rc6, "_authority_runtime", lambda: object())
    monkeypatch.setattr(mcp_server.rc6, "_capability_broker", lambda: object())
    monkeypatch.setattr(mcp_server.rc6, "_state_root", lambda: tmp_path)
    monkeypatch.setattr(mcp_server, "validate_call_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(mcp_server, "contract_enabled", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(mcp_server, "_record_tool_call", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mcp_server,
        "_case_service",
        lambda: SimpleNamespace(require_prepared=lambda **_kwargs: {"status": "PASS"}),
    )

    def bridge(arguments, **kwargs):
        called["arguments"] = arguments
        called["kwargs"] = kwargs
        return {"execution": {"status": "PASS"}, "oracle_runtime": "RC7_DETERMINISTIC_ACTUAL_PATH_OPERATOR_EXPECTED"}

    monkeypatch.setattr(mcp_server, "execute_contracted_runner", bridge)
    monkeypatch.setattr(
        mcp_server.rc6,
        "handle",
        lambda _message: (_ for _ in ()).throw(AssertionError("legacy RC6 runner must not execute")),
    )

    response = mcp_server._call_base_with_context(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "runner_execute",
                "arguments": {
                    "worker_id": "WORKER-EXEC",
                    "lease_id": "LEASE-EXEC",
                    "prepared_attempt": {"attempt_id": ATTEMPT},
                    "mission_context": {"mission_id": MISSION, "task_id": TASK, "worker_id": "WORKER-EXEC"},
                },
            },
        },
        "runner_execute",
    )
    assert response["result"].get("isError") is not True
    assert called["kwargs"]["mission_id"] == MISSION
    assert called["kwargs"]["task_id"] == TASK
    assert "mission_context" not in called["arguments"]
