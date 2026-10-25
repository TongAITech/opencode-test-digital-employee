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


RELEASE = "REL-L5-MCP"
MISSION = "MISSION-L5-MCP"
TASK = "TASK-L5-EXEC"
ATTEMPT = "ATTEMPT-L5-001"
RUNTIME_WORKER = "runtime-execution-l5"
SPECIALIST_WORKER = "dsh-specialist-l5"
TARGET = "target-bank-l5"


def _canonical_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_e2e_helper(tmp_path: Path, mode: str = "success") -> Path:
    helper = tmp_path / "e2e_mcp_helper.py"
    helper.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "mode = sys.argv[1]\n"
        "target = sys.argv[2]\n"
        "systems = ['cfg-admin', 'cfg-data'] if mode != 'same-system' else ['cfg-admin', 'cfg-admin']\n"
        "receipt = {\n"
        "  'journey_id': request.get('journey_id', 'J-L5-MCP'),\n"
        "  'target_id': target,\n"
        "  'hops': [\n"
        "    {'system_id': systems[0], 'tool_id': 'browser-skill', 'status': 'SUCCESS', 'invocation_ref': 'browser-skill://bank/hop1', 'result_sha256': 'a'*64},\n"
        "    {'system_id': systems[1], 'tool_id': 'api-runtime', 'status': 'SUCCESS', 'invocation_ref': 'api-runtime://bank/hop2', 'result_sha256': 'b'*64}\n"
        "  ],\n"
        "  'final_oracle': {\n"
        "    'oracle_id': 'ORACLE-L5-MCP',\n"
        "    'passed': True,\n"
        "    'expected': {'status': 'PUBLISHED'},\n"
        "    'actual': {'status': 'PUBLISHED'},\n"
        "    'evidence_ref': 'db://bank/final-state',\n"
        "    'evidence_sha256': 'c'*64\n"
        "  }\n"
        "}\n"
        "print(json.dumps(receipt, sort_keys=True))\n",
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
        Mission(mission_id=MISSION, release_id=RELEASE, goal="verify real L5 cross-system journey"),
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
            objective="execute L5 cross-system journey",
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
        "team_id": "TEAM-L5",
        "team_task_id": "TEAM-TASK-L5",
        "member_id": "MEMBER-L5",
        "worker_instance_id": SPECIALIST_WORKER,
        "worker_assignment_id": "ASSIGN-L5",
        "attempt_id": ATTEMPT,
        "lease_id": "LEASE-L5",
        "parent_worker_id": "MEMBER-L5",
        "scope": "task:%s" % TASK,
        "assignment_evidence_id": "EVD-ASSIGN-L5",
        "director_self_execution_forbidden": True,
        "local_execution_fallback_forbidden": True,
    }
    binding_dir = tmp_path / "bindings"
    binding_dir.mkdir(parents=True, exist_ok=True)
    binding_path = binding_dir / "l5-binding.json"
    body = _canonical_bytes(payload)
    binding_path.write_bytes(body)
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-BIND-L5",
            mission_id=MISSION,
            kind="DSH_AGENT_TEAMS_EXECUTION_BINDING",
            source_ref="dsh-agent-teams://TEAM-L5/TEAM-TASK-L5/execution",
            content_ref="file://" + str(binding_path),
            subject_refs=[TASK, "EXECUTION", "TEAM-L5", "TEAM-TASK-L5", "MEMBER-L5", SPECIALIST_WORKER, "ASSIGN-L5", ATTEMPT, "LEASE-L5"],
            content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    return truth


def _configure(monkeypatch, helper: Path, mode: str = "success") -> None:
    monkeypatch.setenv("PFC_E2E_TARGET_ID", TARGET)
    monkeypatch.setenv("PFC_E2E_CLIENT_BIN", sys.executable)
    monkeypatch.setenv("PFC_E2E_CLIENT_ARGS_JSON", json.dumps([str(helper), mode, TARGET]))


def _call():
    return rc7_mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 81,
            "method": "tools/call",
            "params": {
                "name": "e2e_execute",
                "arguments": {
                    "journey": {
                        "journey_id": "J-L5-MCP",
                        "steps": [
                            {"system": "cfg-admin", "action": "publish"},
                            {"system": "cfg-data", "action": "verify"},
                        ],
                        "oracle": {"expected": {"status": "PUBLISHED"}},
                    },
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
        tc_id="TC-L5-001",
        case_version=1,
        target_id=TARGET,
        layer="L5",
        worker_id=RUNTIME_WORKER,
        lease_id="RUNTIME-LEASE-L5",
        status="PASS",
        integrity_passed=True,
        actual_result={"ok": True},
        tool_call_refs=(),
        evidence_refs=(),
        assertion_ref="ASSERT-L5",
        assertion_passed=True,
        reason=None,
    )


def _real_invocations(truth: TruthRuntime):
    return [row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == "REAL_EXECUTOR_INVOCATION"]


def test_e2e_execute_is_exposed_as_runtime_owned_mcp_tool() -> None:
    response = rc7_mcp.handle({"jsonrpc": "2.0", "id": 80, "method": "tools/list", "params": {}})
    names = {tool.get("name") for tool in response["result"]["tools"]}
    assert "e2e_execute" in names


def test_e2e_execute_success_auto_persists_current_attempt_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_e2e_helper(tmp_path)
    _configure(monkeypatch, helper)

    response = _call()

    assert not response["result"].get("isError")
    result = json.loads(response["result"]["content"][0]["text"])
    assert result["tool"] == "e2e-orchestrator"
    assert result["target_id"] == TARGET
    assert result["journey_receipt"]["hop_count"] == 2
    assert len(set(result["journey_receipt"]["system_ids"])) == 2
    assert result["journey_receipt"]["final_oracle"]["passed"] is True
    assert result["provenance_evidence_id"]

    truth = rc7_mcp.rc6._truth_runtime()
    rows = _real_invocations(truth)
    assert len(rows) == 1
    assert rows[0]["source_ref"] == "runtime-tool://pfc-aitest-rc7/e2e-orchestrator"
    gate = RealExecutorProvenanceGate(truth).require_record(MISSION, TASK, _record())
    assert gate.status == "PASS"
    assert gate.observed_tools == ("e2e-orchestrator",)


def test_e2e_execute_invalid_same_system_receipt_never_persists_success_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_e2e_helper(tmp_path)
    _configure(monkeypatch, helper, mode="same-system")

    response = _call()

    assert response["result"]["isError"] is True
    assert "E2E_REQUIRES_DISTINCT_SYSTEMS" in response["result"]["content"][0]["text"]
    assert _real_invocations(rc7_mcp.rc6._truth_runtime()) == []
