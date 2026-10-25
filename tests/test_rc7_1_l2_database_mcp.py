from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime
from rc7_release import mcp_server as rc7_mcp
from rc7_runtime.models import Evidence, Mission, Task, TaskStatus
from rc7_runtime.real_executor_provenance import RealExecutorProvenanceGate
from rc7_runtime.truth_overlay import append_entity


RELEASE = "REL-L2-MCP"
MISSION = "MISSION-L2-MCP"
TASK = "TASK-L2-EXEC"
ATTEMPT = "ATTEMPT-L2-001"
RUNTIME_WORKER = "runtime-execution-l2"
SPECIALIST_WORKER = "dsh-specialist-l2"
TARGET = "target-bank-l2"


def _canonical_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_db_helper(tmp_path: Path, exit_code: int = 0) -> Path:
    helper = tmp_path / "db_client_helper.py"
    helper.write_text(
        "import hashlib, json, sys\n"
        "sql = sys.stdin.read()\n"
        "print(json.dumps({'sql_sha256': hashlib.sha256(sql.encode('utf-8')).hexdigest(), 'stdin_chars': len(sql), 'argv': sys.argv[1:]}, sort_keys=True))\n"
        "sys.exit(%d)\n" % exit_code,
        encoding="utf-8",
    )
    return helper


def _seed_runtime(tmp_path: Path, monkeypatch) -> TruthRuntime:
    state_root = tmp_path / "runtime-state"
    truth_path = state_root / "r1" / "event-stream.jsonl"
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state_root))
    monkeypatch.setenv("PFC_AITEST_HOME", str(tmp_path))
    monkeypatch.setenv("PFC_WORKSPACE", str(tmp_path))
    truth = TruthRuntime(truth_path)
    append_entity(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="verify real L2 MCP execution"),
        release_id=RELEASE,
        artifact_version=1,
    )
    append_entity(
        truth,
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute L2 database case",
            state=TaskStatus.RUNNING,
            required_capabilities=["test_execution"],
            lease_owner=RUNTIME_WORKER,
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    payload = {
        "schema": "pfc.aitest.rc7.1.agent-teams-execution-binding.v1",
        "mission_id": MISSION,
        "task_id": TASK,
        "node": "EXECUTION",
        "team_id": "TEAM-L2",
        "team_task_id": "TEAM-TASK-L2",
        "member_id": "MEMBER-L2",
        "worker_instance_id": SPECIALIST_WORKER,
        "worker_assignment_id": "ASSIGN-L2",
        "attempt_id": ATTEMPT,
        "lease_id": "LEASE-L2",
        "parent_worker_id": "MEMBER-L2",
        "scope": "task:%s" % TASK,
        "assignment_evidence_id": "EVD-ASSIGN-L2",
        "director_self_execution_forbidden": True,
        "local_execution_fallback_forbidden": True,
    }
    binding_dir = tmp_path / "bindings"
    binding_dir.mkdir(parents=True, exist_ok=True)
    binding_path = binding_dir / "l2-binding.json"
    body = _canonical_bytes(payload)
    binding_path.write_bytes(body)
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-BIND-L2",
            mission_id=MISSION,
            kind="DSH_AGENT_TEAMS_EXECUTION_BINDING",
            source_ref="dsh-agent-teams://TEAM-L2/TEAM-TASK-L2/execution",
            content_ref="file://" + str(binding_path),
            subject_refs=[
                TASK,
                "EXECUTION",
                "TEAM-L2",
                "TEAM-TASK-L2",
                "MEMBER-L2",
                SPECIALIST_WORKER,
                "ASSIGN-L2",
                ATTEMPT,
                "LEASE-L2",
            ],
            content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    return truth


def _configure_client(monkeypatch, helper: Path, target_id: str = TARGET) -> None:
    monkeypatch.setenv("PFC_DB_TARGET_ID", target_id)
    monkeypatch.setenv("PFC_DB_CLIENT_BIN", sys.executable)
    monkeypatch.setenv("PFC_DB_CLIENT_ARGS_JSON", json.dumps([str(helper)]))


def _call(sql: str):
    return rc7_mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {
                "name": "database_execute",
                "arguments": {
                    "sql": sql,
                    "attempt_id": ATTEMPT,
                    "target_id": TARGET,
                    "timeout_seconds": 10,
                    "max_chars": 10000,
                    "mission_context": {
                        "mission_id": MISSION,
                        "task_id": TASK,
                        "worker_id": RUNTIME_WORKER,
                    },
                },
            },
        }
    )


def _record() -> ExecutionRecord:
    return ExecutionRecord(
        attempt_id=ATTEMPT,
        tc_id="TC-L2-001",
        case_version=1,
        target_id=TARGET,
        layer="L2",
        worker_id=RUNTIME_WORKER,
        lease_id="RUNTIME-LEASE-L2",
        status="PASS",
        integrity_passed=True,
        actual_result={"ok": True},
        tool_call_refs=(),
        evidence_refs=(),
        assertion_ref="ASSERT-L2",
        assertion_passed=True,
        reason=None,
    )


def _real_invocations(truth: TruthRuntime):
    return [
        row
        for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "REAL_EXECUTOR_INVOCATION"
    ]


def test_database_execute_is_exposed_as_runtime_owned_mcp_tool() -> None:
    response = rc7_mcp.handle({"jsonrpc": "2.0", "id": 50, "method": "tools/list", "params": {}})
    names = {tool.get("name") for tool in response["result"]["tools"]}
    assert "database_execute" in names


def test_database_execute_success_auto_persists_current_attempt_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_db_helper(tmp_path)
    _configure_client(monkeypatch, helper)

    response = _call("select 42")

    assert not response["result"].get("isError")
    result = json.loads(response["result"]["content"][0]["text"])
    assert result["tool"] == "database"
    assert result["target_id"] == TARGET
    assert result["provenance_evidence_id"]
    assert result["sql_transport"] == "STDIN"
    assert result["shell"] is False

    truth = rc7_mcp.rc6._truth_runtime()
    rows = _real_invocations(truth)
    assert len(rows) == 1
    assert rows[0]["evidence_id"] == result["provenance_evidence_id"]
    assert rows[0]["source_ref"] == "runtime-tool://pfc-aitest-rc7/database"
    gate = RealExecutorProvenanceGate(truth).require_record(MISSION, TASK, _record())
    assert gate.status == "PASS"
    assert gate.observed_tools == ("database",)


def test_database_execute_target_mismatch_is_error_without_success_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_db_helper(tmp_path)
    _configure_client(monkeypatch, helper, target_id="different-target")

    response = _call("select 42")

    assert response["result"]["isError"] is True
    assert "DATABASE_TARGET_MISMATCH" in response["result"]["content"][0]["text"]
    assert _real_invocations(rc7_mcp.rc6._truth_runtime()) == []


def test_database_execute_nonzero_client_is_error_without_success_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_db_helper(tmp_path, exit_code=9)
    _configure_client(monkeypatch, helper)

    response = _call("select 42")

    assert response["result"]["isError"] is True
    assert "DATABASE_CLIENT_EXIT_NONZERO" in response["result"]["content"][0]["text"]
    assert _real_invocations(rc7_mcp.rc6._truth_runtime()) == []
