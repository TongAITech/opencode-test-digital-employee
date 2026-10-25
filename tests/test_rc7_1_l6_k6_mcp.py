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


RELEASE = "REL-L6-MCP"
MISSION = "MISSION-L6-MCP"
TASK = "TASK-L6-EXEC"
ATTEMPT = "ATTEMPT-L6-001"
RUNTIME_WORKER = "runtime-execution-l6"
SPECIALIST_WORKER = "dsh-specialist-l6"
TARGET = "target-bank-l6"


def _canonical_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_k6_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "k6_mcp_helper.py"
    helper.write_text(
        "import json, pathlib, sys\n"
        "mode = sys.argv[1]\n"
        "args = sys.argv[2:]\n"
        "idx = args.index('--summary-export')\n"
        "summary_path = pathlib.Path(args[idx + 1])\n"
        "script_path = pathlib.Path(args[idx + 2])\n"
        "if 'run' not in args or not script_path.is_file(): sys.exit(12)\n"
        "summary = {'metrics': {\n"
        " 'iterations': {'type': 'counter', 'contains': 'default', 'values': {'count': 5, 'rate': 1.0}},\n"
        " 'http_req_duration': {'type': 'trend', 'contains': 'time', 'values': {'avg': 100, 'p(95)': 180}, 'thresholds': {'p(95)<500': {'ok': mode != 'threshold-fail'}}}\n"
        "}}\n"
        "summary_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "summary_path.write_text(json.dumps(summary), encoding='utf-8')\n"
        "print('k6 completed')\n",
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
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="verify real L6 k6 execution"), release_id=RELEASE, artifact_version=1)
    append_entity(
        truth,
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute L6 performance scenario",
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
        "team_id": "TEAM-L6",
        "team_task_id": "TEAM-TASK-L6",
        "member_id": "MEMBER-L6",
        "worker_instance_id": SPECIALIST_WORKER,
        "worker_assignment_id": "ASSIGN-L6",
        "attempt_id": ATTEMPT,
        "lease_id": "LEASE-L6",
        "parent_worker_id": "MEMBER-L6",
        "scope": "task:%s" % TASK,
        "assignment_evidence_id": "EVD-ASSIGN-L6",
        "director_self_execution_forbidden": True,
        "local_execution_fallback_forbidden": True,
    }
    binding_dir = tmp_path / "bindings"
    binding_dir.mkdir(parents=True, exist_ok=True)
    binding_path = binding_dir / "l6-binding.json"
    body = _canonical_bytes(payload)
    binding_path.write_bytes(body)
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-BIND-L6",
            mission_id=MISSION,
            kind="DSH_AGENT_TEAMS_EXECUTION_BINDING",
            source_ref="dsh-agent-teams://TEAM-L6/TEAM-TASK-L6/execution",
            content_ref="file://" + str(binding_path),
            subject_refs=[TASK, "EXECUTION", "TEAM-L6", "TEAM-TASK-L6", "MEMBER-L6", SPECIALIST_WORKER, "ASSIGN-L6", ATTEMPT, "LEASE-L6"],
            content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    return truth


def _configure(monkeypatch, tmp_path: Path, helper: Path, mode: str = "success") -> Path:
    script = tmp_path / "perf.js"
    script.write_text("export default function () { /* controlled test */ }\n", encoding="utf-8")
    monkeypatch.setenv("PFC_K6_TARGET_ID", TARGET)
    monkeypatch.setenv("PFC_K6_BIN", sys.executable)
    monkeypatch.setenv("PFC_K6_ARGS_JSON", json.dumps([str(helper), mode]))
    return script


def _call(script: Path):
    return rc7_mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 91,
            "method": "tools/call",
            "params": {
                "name": "k6_execute",
                "arguments": {
                    "script_path": str(script),
                    "scenario_id": "publish-load",
                    "attempt_id": ATTEMPT,
                    "target_id": TARGET,
                    "timeout_seconds": 10,
                    "max_chars": 10000,
                    "mission_context": {"mission_id": MISSION, "task_id": TASK, "worker_id": RUNTIME_WORKER},
                },
            },
        }
    )


def _record() -> ExecutionRecord:
    return ExecutionRecord(
        attempt_id=ATTEMPT,
        tc_id="TC-L6-001",
        case_version=1,
        target_id=TARGET,
        layer="L6",
        worker_id=RUNTIME_WORKER,
        lease_id="RUNTIME-LEASE-L6",
        status="PASS",
        integrity_passed=True,
        actual_result={"ok": True},
        tool_call_refs=(),
        evidence_refs=(),
        assertion_ref="ASSERT-L6",
        assertion_passed=True,
        reason=None,
    )


def _real_invocations(truth: TruthRuntime):
    return [row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == "REAL_EXECUTOR_INVOCATION"]


def test_k6_execute_is_exposed_as_runtime_owned_mcp_tool() -> None:
    response = rc7_mcp.handle({"jsonrpc": "2.0", "id": 90, "method": "tools/list", "params": {}})
    names = {tool.get("name") for tool in response["result"]["tools"]}
    assert "k6_execute" in names


def test_k6_execute_success_auto_persists_current_attempt_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_k6_helper(tmp_path)
    script = _configure(monkeypatch, tmp_path, helper)

    response = _call(script)

    assert not response["result"].get("isError")
    result = json.loads(response["result"]["content"][0]["text"])
    assert result["tool"] == "k6"
    assert result["target_id"] == TARGET
    assert result["scenario_id"] == "publish-load"
    assert result["summary"]["iteration_count"] == 5
    assert result["summary"]["threshold_count"] == 1
    assert result["provenance_evidence_id"]

    truth = rc7_mcp.rc6._truth_runtime()
    rows = _real_invocations(truth)
    assert len(rows) == 1
    assert rows[0]["source_ref"] == "runtime-tool://pfc-aitest-rc7/k6"
    gate = RealExecutorProvenanceGate(truth).require_record(MISSION, TASK, _record())
    assert gate.status == "PASS"
    assert gate.observed_tools == ("k6",)


def test_k6_execute_failed_threshold_never_persists_success_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_k6_helper(tmp_path)
    script = _configure(monkeypatch, tmp_path, helper, mode="threshold-fail")

    response = _call(script)

    assert response["result"]["isError"] is True
    assert "K6_THRESHOLD_NOT_PASS" in response["result"]["content"][0]["text"]
    assert _real_invocations(rc7_mcp.rc6._truth_runtime()) == []
