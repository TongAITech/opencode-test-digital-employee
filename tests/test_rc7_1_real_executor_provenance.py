from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Evidence, Mission, Task, TaskStatus
from rc7_runtime.real_executor_provenance import (
    RealExecutorProvenanceError,
    RealExecutorProvenanceGate,
    record_successful_execution_invocation,
)
from rc7_runtime.truth_overlay import append_entity


RELEASE = "REL-REAL-EXEC"
MISSION = "MISSION-REAL-EXEC"
TASK = "TASK-EXEC"
RUNTIME_WORKER = "runtime-execution-001"
SPECIALIST_WORKER = "dsh-specialist-001"
TARGET = "target-bank-test"


def _canonical_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _seed(tmp_path: Path, *, attempt_id: str = "ATTEMPT-001") -> TruthRuntime:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="real executor provenance"),
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
            objective="execute case",
            state=TaskStatus.RUNNING,
            required_capabilities=["test_execution"],
            lease_owner=RUNTIME_WORKER,
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    _binding(truth, tmp_path, attempt_id=attempt_id)
    return truth


def _binding(truth: TruthRuntime, tmp_path: Path, *, attempt_id: str) -> Evidence:
    payload = {
        "schema": "pfc.aitest.rc7.1.agent-teams-execution-binding.v1",
        "mission_id": MISSION,
        "task_id": TASK,
        "node": "EXECUTION",
        "team_id": "TEAM-001",
        "team_task_id": "TEAM-TASK-001",
        "member_id": "MEMBER-001",
        "worker_instance_id": SPECIALIST_WORKER,
        "worker_assignment_id": "ASSIGN-%s" % attempt_id,
        "attempt_id": attempt_id,
        "lease_id": "LEASE-%s" % attempt_id,
        "parent_worker_id": "MEMBER-001",
        "scope": "task:%s" % TASK,
        "assignment_evidence_id": "EVD-ASSIGN-%s" % attempt_id,
        "director_self_execution_forbidden": True,
        "local_execution_fallback_forbidden": True,
    }
    root = tmp_path / "bindings"
    root.mkdir(parents=True, exist_ok=True)
    path = root / (attempt_id + ".json")
    body = _canonical_bytes(payload)
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    evidence = Evidence(
        evidence_id="EVD-BIND-%s" % attempt_id,
        mission_id=MISSION,
        kind="DSH_AGENT_TEAMS_EXECUTION_BINDING",
        source_ref="dsh-agent-teams://TEAM-001/TEAM-TASK-001/execution",
        content_ref="file://" + str(path),
        subject_refs=[
            TASK,
            "EXECUTION",
            "TEAM-001",
            "TEAM-TASK-001",
            "MEMBER-001",
            SPECIALIST_WORKER,
            "ASSIGN-%s" % attempt_id,
            attempt_id,
            "LEASE-%s" % attempt_id,
        ],
        content_hash="sha256:" + digest,
    )
    append_entity(truth, evidence, release_id=RELEASE, artifact_version=1)
    return evidence


def _record(*, attempt_id: str, layer: str, tool_refs=()) -> ExecutionRecord:
    return ExecutionRecord(
        attempt_id=attempt_id,
        tc_id="TC-001",
        case_version=1,
        target_id=TARGET,
        layer=layer,
        worker_id=RUNTIME_WORKER,
        lease_id="RUNTIME-LEASE-001",
        status="PASS",
        integrity_passed=True,
        actual_result={"ok": True},
        tool_call_refs=tuple(tool_refs),
        evidence_refs=("EVD-RUNTIME-001",),
        assertion_ref="ASSERT-001",
        assertion_passed=True,
        reason=None,
    )


def test_l2_current_attempt_trusted_invocation_passes(tmp_path: Path) -> None:
    truth = _seed(tmp_path)
    evidence = record_successful_execution_invocation(
        truth,
        evidence_root=str(tmp_path / "evidence"),
        mission_id=MISSION,
        task_id=TASK,
        attempt_id="ATTEMPT-001",
        runtime_worker_id=RUNTIME_WORKER,
        layer="L2",
        target_id=TARGET,
        tool_name="database",
        invocation_ref="database://tdsql/query/42",
        result={"rows": 1, "status": "PASS"},
    )
    result = RealExecutorProvenanceGate(truth).require_record(
        MISSION, TASK, _record(attempt_id="ATTEMPT-001", layer="L2")
    )
    assert result.status == "PASS"
    assert result.observed_tools == ("database",)
    assert evidence.evidence_id in result.evidence_ids


def test_forged_specialist_identity_cannot_satisfy_current_attempt(tmp_path: Path) -> None:
    truth = _seed(tmp_path)
    binding = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "DSH_AGENT_TEAMS_EXECUTION_BINDING"
    ][0]
    payload = {
        "schema": "pfc.aitest.rc7.1.real-executor-invocation.v1",
        "invocation_id": "EXEC-INV-FORGED",
        "mission_id": MISSION,
        "task_id": TASK,
        "attempt_id": "ATTEMPT-001",
        "layer": "L2",
        "target_id": TARGET,
        "tool_id": "database",
        "runtime_worker_id": RUNTIME_WORKER,
        "specialist_worker_id": "dsh-specialist-forged",
        "team_id": "TEAM-001",
        "team_task_id": "TEAM-TASK-001",
        "member_id": "MEMBER-001",
        "execution_binding_evidence_id": str(binding.get("evidence_id") or ""),
        "invocation_ref": "database://tdsql/query/forged",
        "result_sha256": hashlib.sha256(b"forged").hexdigest(),
        "status": "SUCCESS",
        "runner_manifest_is_not_authority": True,
    }
    path = tmp_path / "forged-invocation.json"
    body = _canonical_bytes(payload)
    path.write_bytes(body)
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-REAL-EXEC-FORGED",
            mission_id=MISSION,
            kind="REAL_EXECUTOR_INVOCATION",
            source_ref="runtime-tool://pfc-aitest-rc7/database",
            content_ref="file://" + str(path),
            subject_refs=[TASK, "ATTEMPT-001", "L2", TARGET, "database", RUNTIME_WORKER],
            content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    with pytest.raises(RealExecutorProvenanceError, match="REAL_EXECUTOR_PROVENANCE_FAILED:L2:database"):
        RealExecutorProvenanceGate(truth).require_record(
            MISSION, TASK, _record(attempt_id="ATTEMPT-001", layer="L2")
        )


def test_runner_manifest_tool_call_alone_cannot_prove_real_executor(tmp_path: Path) -> None:
    truth = _seed(tmp_path)
    record = _record(
        attempt_id="ATTEMPT-001",
        layer="L6",
        tool_refs=("tool-call://k6/script-self-report",),
    )
    with pytest.raises(RealExecutorProvenanceError, match="REAL_EXECUTOR_PROVENANCE_FAILED:L6:k6"):
        RealExecutorProvenanceGate(truth).require_record(MISSION, TASK, record)


def test_stale_prior_attempt_invocation_cannot_satisfy_successor(tmp_path: Path) -> None:
    truth = _seed(tmp_path, attempt_id="ATTEMPT-OLD")
    record_successful_execution_invocation(
        truth,
        evidence_root=str(tmp_path / "evidence"),
        mission_id=MISSION,
        task_id=TASK,
        attempt_id="ATTEMPT-OLD",
        runtime_worker_id=RUNTIME_WORKER,
        layer="L7",
        target_id=TARGET,
        tool_name="zap",
        invocation_ref="zap://scan/old",
        result={"scan": "old"},
    )
    _binding(truth, tmp_path, attempt_id="ATTEMPT-NEW")
    with pytest.raises(RealExecutorProvenanceError, match="REAL_EXECUTOR_PROVENANCE_FAILED:L7:zap"):
        RealExecutorProvenanceGate(truth).require_record(
            MISSION, TASK, _record(attempt_id="ATTEMPT-NEW", layer="L7")
        )


def test_fixture_invocation_cannot_be_promoted_to_trusted_provenance(tmp_path: Path) -> None:
    truth = _seed(tmp_path)
    with pytest.raises(RealExecutorProvenanceError, match="REAL_EXECUTOR_FIXTURE_INVOCATION_FORBIDDEN"):
        record_successful_execution_invocation(
            truth,
            evidence_root=str(tmp_path / "evidence"),
            mission_id=MISSION,
            task_id=TASK,
            attempt_id="ATTEMPT-001",
            runtime_worker_id=RUNTIME_WORKER,
            layer="L4",
            target_id=TARGET,
            tool_name="browser-skill",
            invocation_ref="engineering-fixture://browser/pass",
            result={"status": "PASS"},
        )


def test_wrong_layer_tool_is_rejected(tmp_path: Path) -> None:
    truth = _seed(tmp_path)
    with pytest.raises(RealExecutorProvenanceError, match="REAL_EXECUTOR_TOOL_LAYER_MISMATCH:L3:database"):
        record_successful_execution_invocation(
            truth,
            evidence_root=str(tmp_path / "evidence"),
            mission_id=MISSION,
            task_id=TASK,
            attempt_id="ATTEMPT-001",
            runtime_worker_id=RUNTIME_WORKER,
            layer="L3",
            target_id=TARGET,
            tool_name="database",
            invocation_ref="database://wrong-layer",
            result={"status": "PASS"},
        )


def test_l1_does_not_require_external_executor_provenance(tmp_path: Path) -> None:
    truth = _seed(tmp_path)
    result = RealExecutorProvenanceGate(truth).require_record(
        MISSION, TASK, _record(attempt_id="ATTEMPT-001", layer="L1")
    )
    assert result.status == "NOT_REQUIRED"
