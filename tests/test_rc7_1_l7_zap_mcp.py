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


RELEASE = "REL-L7-MCP"
MISSION = "MISSION-L7-MCP"
TASK = "TASK-L7-EXEC"
ATTEMPT = "ATTEMPT-L7-001"
RUNTIME_WORKER = "runtime-execution-l7"
SPECIALIST_WORKER = "dsh-specialist-l7"
TARGET = "target-bank-l7"
TARGET_URL = "https://bank.example/cfg-admin"


def _canonical_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_zap_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "zap_mcp_helper.py"
    helper.write_text(
        "import json, os, pathlib, sys\n"
        "mode = sys.argv[1]\n"
        "args = sys.argv[2:]\n"
        "if '-cmd' not in args or '-autorun' not in args: sys.exit(31)\n"
        "report = pathlib.Path(os.environ['PFC_ZAP_REPORT_PATH'])\n"
        "if mode == 'no-report': sys.exit(0)\n"
        "site = 'https://other.example/' if mode == 'wrong-target' else os.environ['PFC_ZAP_TARGET_URL']\n"
        "alerts = [{'pluginid': '10020', 'alertRef': '10020', 'alert': 'Header Missing', 'riskcode': '2', 'confidence': '2', 'instances': [{'uri': site}]}]\n"
        "payload = {'@version': 'controlled-zap-protocol', 'site': [{'@name': site, 'alerts': alerts}]}\n"
        "report.parent.mkdir(parents=True, exist_ok=True)\n"
        "report.write_text(json.dumps(payload), encoding='utf-8')\n"
        "print('zap completed')\n",
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
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="verify real L7 ZAP execution"), release_id=RELEASE, artifact_version=1)
    append_entity(
        truth,
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute L7 security scan",
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
        "team_id": "TEAM-L7",
        "team_task_id": "TEAM-TASK-L7",
        "member_id": "MEMBER-L7",
        "worker_instance_id": SPECIALIST_WORKER,
        "worker_assignment_id": "ASSIGN-L7",
        "attempt_id": ATTEMPT,
        "lease_id": "LEASE-L7",
        "parent_worker_id": "MEMBER-L7",
        "scope": "task:%s" % TASK,
        "assignment_evidence_id": "EVD-ASSIGN-L7",
        "director_self_execution_forbidden": True,
        "local_execution_fallback_forbidden": True,
    }
    binding_dir = tmp_path / "bindings"
    binding_dir.mkdir(parents=True, exist_ok=True)
    binding_path = binding_dir / "l7-binding.json"
    body = _canonical_bytes(payload)
    binding_path.write_bytes(body)
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-BIND-L7",
            mission_id=MISSION,
            kind="DSH_AGENT_TEAMS_EXECUTION_BINDING",
            source_ref="dsh-agent-teams://TEAM-L7/TEAM-TASK-L7/execution",
            content_ref="file://" + str(binding_path),
            subject_refs=[TASK, "EXECUTION", "TEAM-L7", "TEAM-TASK-L7", "MEMBER-L7", SPECIALIST_WORKER, "ASSIGN-L7", ATTEMPT, "LEASE-L7"],
            content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    return truth


def _configure(monkeypatch, tmp_path: Path, helper: Path, mode: str = "finding") -> Path:
    plan = tmp_path / "zap-plan.yaml"
    plan.write_text("env:\n  contexts: []\njobs: []\n", encoding="utf-8")
    monkeypatch.setenv("PFC_ZAP_TARGET_ID", TARGET)
    monkeypatch.setenv("PFC_ZAP_TARGET_URL", TARGET_URL)
    monkeypatch.setenv("PFC_ZAP_BIN", sys.executable)
    monkeypatch.setenv("PFC_ZAP_ARGS_JSON", json.dumps([str(helper), mode]))
    monkeypatch.setenv("PFC_ZAP_REPORT_PATH", str(tmp_path / "zap-report.json"))
    return plan


def _call(plan: Path):
    return rc7_mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "zap_execute",
                "arguments": {
                    "plan_path": str(plan),
                    "scan_id": "security-baseline",
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
        tc_id="TC-L7-001",
        case_version=1,
        target_id=TARGET,
        layer="L7",
        worker_id=RUNTIME_WORKER,
        lease_id="RUNTIME-LEASE-L7",
        status="PASS",
        integrity_passed=True,
        actual_result={"ok": True},
        tool_call_refs=(),
        evidence_refs=(),
        assertion_ref="ASSERT-L7",
        assertion_passed=True,
        reason=None,
    )


def _real_invocations(truth: TruthRuntime):
    return [row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == "REAL_EXECUTOR_INVOCATION"]


def test_zap_execute_is_exposed_as_runtime_owned_mcp_tool() -> None:
    response = rc7_mcp.handle({"jsonrpc": "2.0", "id": 100, "method": "tools/list", "params": {}})
    names = {tool.get("name") for tool in response["result"]["tools"]}
    assert "zap_execute" in names


def test_zap_execute_valid_scan_with_finding_persists_current_attempt_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_zap_helper(tmp_path)
    plan = _configure(monkeypatch, tmp_path, helper, mode="finding")

    response = _call(plan)

    assert not response["result"].get("isError")
    result = json.loads(response["result"]["content"][0]["text"])
    assert result["tool"] == "zap"
    assert result["target_id"] == TARGET
    assert result["summary"]["finding_count"] == 1
    assert result["summary"]["risk_counts"]["medium"] == 1
    assert result["summary"]["findings_are_product_security_actual_not_executor_failure"] is True
    assert result["provenance_evidence_id"]

    truth = rc7_mcp.rc6._truth_runtime()
    rows = _real_invocations(truth)
    assert len(rows) == 1
    assert rows[0]["source_ref"] == "runtime-tool://pfc-aitest-rc7/zap"
    gate = RealExecutorProvenanceGate(truth).require_record(MISSION, TASK, _record())
    assert gate.status == "PASS"
    assert gate.observed_tools == ("zap",)


def test_zap_execute_wrong_target_report_never_persists_success_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_zap_helper(tmp_path)
    plan = _configure(monkeypatch, tmp_path, helper, mode="wrong-target")

    response = _call(plan)

    assert response["result"]["isError"] is True
    assert "ZAP_REPORT_TARGET_SITE_NOT_FOUND" in response["result"]["content"][0]["text"]
    assert _real_invocations(rc7_mcp.rc6._truth_runtime()) == []


def test_zap_execute_missing_fresh_report_never_persists_success_provenance(tmp_path: Path, monkeypatch) -> None:
    _seed_runtime(tmp_path, monkeypatch)
    helper = _write_zap_helper(tmp_path)
    plan = _configure(monkeypatch, tmp_path, helper, mode="no-report")

    response = _call(plan)

    assert response["result"]["isError"] is True
    assert "ZAP_FRESH_REPORT_NOT_PRODUCED" in response["result"]["content"][0]["text"]
    assert _real_invocations(rc7_mcp.rc6._truth_runtime()) == []
