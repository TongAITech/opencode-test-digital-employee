from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.execution_recovery_conformance import (
    ExecutionRecoveryConformanceChecker,
    ExecutionRecoveryConformanceError,
    persist_contract as persist_execution_recovery_contract,
)
from rc7_runtime.models import Evidence, Mission, Task
from rc7_runtime.node_tool_conformance import NODE_TOOL_CALL_KIND
from rc7_runtime.real_executor_provenance import (
    persist_contract as persist_real_executor_contract,
    record_successful_execution_invocation,
)
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-REAL-EXEC-PASS-GATE"
RELEASE = "REL-REAL-EXEC-PASS-GATE"
TASK = "TASK-REAL-EXEC"
ATTEMPT = "ATTEMPT-REAL-001"
TC = "TC-REAL-001"
TARGET = "TARGET-BANK"
RUNTIME_WORKER = "runtime-execution-real-001"
SPECIALIST_WORKER = "dsh-specialist-real-001"


def _write_json(path: Path, payload) -> str:
    body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _append_evidence(truth: TruthRuntime, evidence: Evidence) -> None:
    append_entity(truth, evidence, release_id=RELEASE, artifact_version=1)


def _seed_pass_ready_truth(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="real executor terminal pass gate"),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute one real L2 case",
            required_capabilities=["test_execution"],
        )
    )
    persist_execution_recovery_contract(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        execution_task_id=TASK,
    )
    persist_real_executor_contract(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        execution_task_id=TASK,
    )
    leased = control.lease_next(worker_ref=RUNTIME_WORKER, capabilities=("test_execution",))
    assert leased is not None and leased.task_id == TASK
    control.start(TASK, worker_ref=RUNTIME_WORKER)

    _append_evidence(
        truth,
        Evidence(
            evidence_id="EVD-PREPARED-REAL-001",
            mission_id=MISSION,
            kind="CASE_PREPARED_ATTEMPT",
            source_ref="runtime://case-preparation",
            content_ref="prepared-attempt://%s" % ATTEMPT,
            subject_refs=[TASK, RUNTIME_WORKER, ATTEMPT, TC, TARGET],
            content_hash="prepared-real-001",
        ),
    )
    for tool in ("runner_execute", "execution_convergence"):
        _append_evidence(
            truth,
            Evidence(
                evidence_id="EVD-NODE-TOOL-" + tool.upper().replace("_", "-"),
                mission_id=MISSION,
                kind=NODE_TOOL_CALL_KIND,
                source_ref="mcp://pfc-aitest-rc7/%s" % tool,
                content_ref="tool-call://%s" % tool,
                subject_refs=[TASK, RUNTIME_WORKER, tool],
                content_hash="node-tool-%s" % tool,
            ),
        )

    binding_payload = {
        "schema": "pfc.aitest.rc7.1.agent-teams-execution-binding.v1",
        "mission_id": MISSION,
        "task_id": TASK,
        "node": "EXECUTION",
        "team_id": "TEAM-REAL-001",
        "team_task_id": "TEAM-TASK-REAL-001",
        "member_id": "MEMBER-REAL-001",
        "worker_instance_id": SPECIALIST_WORKER,
        "worker_assignment_id": "ASSIGN-REAL-001",
        "attempt_id": ATTEMPT,
        "lease_id": "SPECIALIST-LEASE-001",
        "parent_worker_id": "MEMBER-REAL-001",
        "scope": "task:%s" % TASK,
        "assignment_evidence_id": "EVD-ASSIGN-REAL-001",
        "director_self_execution_forbidden": True,
        "local_execution_fallback_forbidden": True,
    }
    binding_path = tmp_path / "binding.json"
    binding_hash = _write_json(binding_path, binding_payload)
    _append_evidence(
        truth,
        Evidence(
            evidence_id="EVD-BIND-REAL-001",
            mission_id=MISSION,
            kind="DSH_AGENT_TEAMS_EXECUTION_BINDING",
            source_ref="dsh-agent-teams://TEAM-REAL-001/TEAM-TASK-REAL-001/execution",
            content_ref="file://" + str(binding_path),
            subject_refs=[
                TASK, "EXECUTION", "TEAM-REAL-001", "TEAM-TASK-REAL-001",
                "MEMBER-REAL-001", SPECIALIST_WORKER, "ASSIGN-REAL-001",
                ATTEMPT, "SPECIALIST-LEASE-001",
            ],
            content_hash=binding_hash,
        ),
    )

    record_payload = {
        "record": {
            "attempt_id": ATTEMPT,
            "tc_id": TC,
            "case_version": 1,
            "target_id": TARGET,
            "layer": "L2",
            "worker_id": RUNTIME_WORKER,
            "lease_id": "RUNTIME-LEASE-001",
            "status": "PASS",
            "integrity_passed": True,
            "actual_result": {"business_code": "OK"},
            "tool_call_refs": ["tool-call://database/script-self-report"],
            "evidence_refs": ["EVD-RUNTIME-REAL-001"],
            "assertion_ref": "ASSERT-REAL-001",
            "assertion_passed": True,
            "reason": None,
        }
    }
    record_path = tmp_path / "runtime-record.json"
    record_hash = _write_json(record_path, record_payload)
    _append_evidence(
        truth,
        Evidence(
            evidence_id="EVD-RUNTIME-RECORD-REAL-001",
            mission_id=MISSION,
            kind="RUNTIME_EXECUTION_RECORD",
            source_ref="runtime://formal-execution",
            content_ref="file://" + str(record_path),
            subject_refs=[TASK, ATTEMPT, TC],
            content_hash=record_hash,
        ),
    )

    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": ATTEMPT,
            "release_id": RELEASE,
            "requirement_id": "REQ-REAL-001",
            "tc_id": TC,
            "case_version": 1,
            "target_id": TARGET,
            "layer": "L2",
            "status": "PASS",
            "actual_result": {"business_code": "OK"},
            "tool_call_refs": ["tool-call://database/script-self-report"],
            "evidence_refs": ["EVD-RUNTIME-RECORD-REAL-001"],
            "spec_id": "SPEC-REAL-001",
            "oracle_fingerprint": "oracle-real-001",
        },
    )
    truth.append_atomic(
        "EXECUTION_CONVERGENCE_UPSERTED",
        {
            "convergence_id": "CONV-REAL-001",
            "release_id": RELEASE,
            "attempt_id": ATTEMPT,
            "status": "PASS",
            "reason": "deterministic oracle passed",
            "evidence_refs": ["EVD-RUNTIME-RECORD-REAL-001"],
        },
    )
    return truth, control.scheduler.task(TASK)


def test_manifest_self_report_cannot_pass_real_executor_contract(tmp_path: Path) -> None:
    truth, task = _seed_pass_ready_truth(tmp_path)
    with pytest.raises(ExecutionRecoveryConformanceError, match="REAL_EXECUTOR_PROVENANCE_FAILED:L2:database"):
        ExecutionRecoveryConformanceChecker(truth).require_task_pass_ready(task)


def test_current_attempt_trusted_database_invocation_unlocks_terminal_pass(tmp_path: Path) -> None:
    truth, task = _seed_pass_ready_truth(tmp_path)
    record_successful_execution_invocation(
        truth,
        evidence_root=str(tmp_path / "trusted-invocations"),
        mission_id=MISSION,
        task_id=TASK,
        attempt_id=ATTEMPT,
        runtime_worker_id=RUNTIME_WORKER,
        layer="L2",
        target_id=TARGET,
        tool_name="database",
        invocation_ref="database://tdsql/query/real-001",
        result={"rows": 1, "business_code": "OK"},
    )
    result = ExecutionRecoveryConformanceChecker(truth).require_task_pass_ready(task)
    assert result.status == "PASS"
    assert result.terminal_statuses == ("PASS",)


def test_new_bank_graph_v2_mission_enables_real_executor_contract(tmp_path: Path) -> None:
    result = start_or_resume(
        r1_path=str(tmp_path / "bank-r1.jsonl"),
        mission_id="MISSION-BANK-REAL-EXEC-CONTRACT",
        release_id="REL-BANK-REAL-EXEC-CONTRACT",
        goal="prove new Bank mission cannot accept manifest-only L2-L7 execution",
        graph_version="v2",
    )
    assert result["status"] == "STARTED"
    assert result["graph_version"] == "v2"
    assert result["real_executor_provenance_contract_enabled"] is True
