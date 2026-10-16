from __future__ import annotations

import json
import sys
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_release import mcp_server
from rc7_runtime.case_runtime import (
    HUMAN_GATE_APPROVAL_KIND,
    HUMAN_GATE_REQUEST_KIND,
    PREPARED_ATTEMPT_KIND,
    PROVIDER_CALL_KIND,
    CasePreparationService,
    HumanGateService,
)
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.node_tool_conformance import persist_contract
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-CASE-RUNTIME"
RELEASE = "REL-CASE-RUNTIME"
TASK = "TASK-EXECUTION"
WORKER = "WORKER-EXECUTION"
ATTEMPT = "ATTEMPT-001"


def _seed(r1: Path) -> TruthRuntime:
    truth = TruthRuntime(r1)
    append_entity(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="real case preparation"),
        release_id=RELEASE,
        artifact_version=1,
    )
    append_entity(
        truth,
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="PRODUCE",
            objective="execute prepared case",
            state=TaskStatus.RUNNING,
            required_capabilities=["execution"],
            lease_owner=WORKER,
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    persist_contract(truth, mission_id=MISSION, release_id=RELEASE, task_ids=[TASK])
    return truth


def _case(*, db: bool = False):
    requirement = {
        "id": "loan-state",
        "selectors": {"status": "PENDING", "amount_min": 1000000},
        "allowed_strategies": ["DB_CREATE"] if db else ["REUSE_EXISTING"],
    }
    return {
        "status": "FROZEN",
        "tc_id": "TC-001",
        "case_version": 1,
        "layer": "L4",
        "preconditions": [
            {"id": "auth-ready", "type": "AUTH", "requirement": "authenticated bank session"},
        ],
        "test_data": {
            "initial_state": [requirement],
            "input_data": [],
            "cleanup_policy": {"mode": "NONE"},
        },
        "oracle": {"type": "field_equals", "field": "status", "value": "APPROVED"},
    }


def _provider_config(tmp_path: Path, *, log_path: Path) -> Path:
    provider = tmp_path / "provider.py"
    provider_source = (
        "import json, os, sys\n"
        "payload=json.loads(sys.stdin.read())\n"
        "cap=payload['capability']\n"
        "with open(os.environ['CALL_LOG'], 'a', encoding='utf-8') as h: h.write(cap+'\\n')\n"
        "if cap.startswith('PRECONDITION_'):\n"
        "    out={'success': True, 'detail': 'ready'}\n"
        "elif cap.startswith('DATA_') and cap != 'DATA_VERIFY':\n"
        "    out={'success': True, 'binding': {'business_id': 'BIZ-001', 'status': 'PENDING'}}\n"
        "elif cap == 'DATA_VERIFY':\n"
        "    out={'success': True}\n"
        "else:\n"
        "    out={'success': False, 'reason': 'unsupported'}\n"
        "print(json.dumps(out))\n"
    )
    provider.write_text(provider_source, encoding="utf-8")
    command = [sys.executable, str(provider)]
    config = {
        "providers": {
            "PRECONDITION_AUTH": {"provider_id": "auth-fixture", "command": command, "environment": {"CALL_LOG": str(log_path)}},
            "DATA_REUSE_EXISTING": {"provider_id": "data-fixture", "command": command, "environment": {"CALL_LOG": str(log_path)}},
            "DATA_DB_CREATE": {"provider_id": "db-fixture", "command": command, "environment": {"CALL_LOG": str(log_path)}},
            "DATA_VERIFY": {"provider_id": "verify-fixture", "command": command, "environment": {"CALL_LOG": str(log_path)}},
        }
    }
    path = tmp_path / "providers.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_missing_real_field_provider_never_becomes_prepared(tmp_path: Path) -> None:
    r1 = tmp_path / "state" / "r1" / "event-stream.jsonl"
    truth = _seed(r1)
    service = CasePreparationService(truth, tmp_path / "state")
    result = service.prepare(
        mission_id=MISSION,
        task_id=TASK,
        worker_id=WORKER,
        case=_case(),
        attempt_id=ATTEMPT,
        target_id="PFC-SIT",
    )
    assert result["status"] == "FIELD_REQUIRED"
    assert result["field_required_capability"] == "PRECONDITION_AUTH"
    assert not [row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == PREPARED_ATTEMPT_KIND]


def test_db_create_requires_human_gate_then_prepares_with_real_provider_evidence(tmp_path: Path) -> None:
    state = tmp_path / "state"
    r1 = state / "r1" / "event-stream.jsonl"
    truth = _seed(r1)
    log_path = tmp_path / "calls.log"
    config = _provider_config(tmp_path, log_path=log_path)
    service = CasePreparationService(truth, state, provider_config=config)

    blocked = service.prepare(
        mission_id=MISSION,
        task_id=TASK,
        worker_id=WORKER,
        case=_case(db=True),
        attempt_id=ATTEMPT,
        target_id="PFC-SIT",
    )
    assert blocked["status"] == "HUMAN_GATE_REQUIRED"
    assert len(blocked["gate_request_ids"]) == 1
    request_id = blocked["gate_request_ids"][0]
    calls_before = log_path.read_text(encoding="utf-8").splitlines()
    assert calls_before == ["PRECONDITION_AUTH"]
    assert len([row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == HUMAN_GATE_REQUEST_KIND]) == 1
    assert not [row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == HUMAN_GATE_APPROVAL_KIND]

    gate = HumanGateService(truth, state, mission_id=MISSION, task_id=TASK, attempt_id=ATTEMPT)
    approval_id = gate.approve(request_id, actor_ref="tester-001", reason="approved SIT data construction")
    assert approval_id.startswith("EVD-HGAPP-")

    prepared = service.prepare(
        mission_id=MISSION,
        task_id=TASK,
        worker_id=WORKER,
        case=_case(db=True),
        attempt_id=ATTEMPT,
        target_id="PFC-SIT",
    )
    assert prepared["status"] == "PREPARED"
    assert prepared["prepared_attempt"]["status"] == "PREPARED"
    assert prepared["prepared_attempt"]["initial_state_bindings"]["loan-state"]["business_id"] == "BIZ-001"
    calls_after = log_path.read_text(encoding="utf-8").splitlines()
    assert calls_after == ["PRECONDITION_AUTH", "DATA_DB_CREATE", "DATA_VERIFY"]
    kinds = [row.get("kind") for row in TruthRuntime(r1).query("rc7_evidence", mission_id=MISSION)]
    assert PROVIDER_CALL_KIND in kinds
    assert PREPARED_ATTEMPT_KIND in kinds
    assert HUMAN_GATE_APPROVAL_KIND in kinds

    recreated = CasePreparationService(TruthRuntime(r1), state, provider_config=config)
    replay = recreated.prepare(
        mission_id=MISSION,
        task_id=TASK,
        worker_id=WORKER,
        case=_case(db=True),
        attempt_id=ATTEMPT,
        target_id="PFC-SIT",
    )
    assert replay["status"] == "PREPARED"
    assert replay["replayed"] is True
    assert log_path.read_text(encoding="utf-8").splitlines() == calls_after


def test_runner_execute_rejects_agent_fabricated_prepared_attempt(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    _seed(state / "r1" / "event-stream.jsonl")
    monkeypatch.setenv("PFC_AITEST_HOME", str(tmp_path))
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state))
    response = mcp_server.handle(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "runner_execute",
                "arguments": {
                    "worker_id": WORKER,
                    "lease_id": "LEASE-001",
                    "case": {},
                    "spec": {},
                    "script": {},
                    "validation": {},
                    "prepared_attempt": {"status": "PREPARED", "attempt_id": ATTEMPT},
                    "cwd": ".",
                    "mission_context": {"mission_id": MISSION, "task_id": TASK, "worker_id": WORKER},
                },
            },
        }
    )
    assert response["result"]["isError"] is True
    assert "DURABLE_PREPARED_ATTEMPT_REQUIRED" in response["result"]["content"][0]["text"]
