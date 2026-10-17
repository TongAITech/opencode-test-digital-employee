from __future__ import annotations

import hashlib
import json
from pathlib import Path

import rc6_runtime.execution_overlay  # noqa: F401
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.case_runtime import PREPARED_ATTEMPT_KIND
from rc7_runtime.models import Evidence, Mission, Task, TaskStatus
from rc7_runtime.oracle_conformance import ActualResultOracleConformanceChecker
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


MISSION = "MISSION-ORACLE-CONFORMANCE"
RELEASE = "REL-ORACLE-CONFORMANCE"
TASK = "TASK-ORACLE-EXEC"
ATTEMPT = "ATTEMPT-ORACLE-1"
TC = "TC-ORACLE-1"
TARGET = "TARGET-ORACLE-1"
ASSERTION = "assertion://oracle/1"
FINGERPRINT = "oracle-fingerprint-1"


def _seed(tmp_path: Path, *, assertion_passed: bool = True):
    install_rc7_truth_overlay()
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="oracle conformance"), release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="PRODUCE",
            objective="execute",
            state=TaskStatus.RUNNING,
            lease_owner="WORKER-EXEC",
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-PREPARED-1",
            mission_id=MISSION,
            kind=PREPARED_ATTEMPT_KIND,
            source_ref="runtime://case-preparation",
            content_ref="case-prepared://1",
            subject_refs=[TASK, "WORKER-EXEC", ATTEMPT, TC, TARGET],
        ),
        release_id=RELEASE,
    )
    actual = {"http": {"status": 200}, "body": {"business_code": "OK"}}
    status = "PASS" if assertion_passed else "FAIL"
    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": ATTEMPT,
            "release_id": RELEASE,
            "requirement_id": "REQ-1",
            "tc_id": TC,
            "case_version": 1,
            "target_id": TARGET,
            "layer": "L3",
            "status": status,
            "actual_result": actual,
            "tool_call_refs": ["tool://api/1"],
            "evidence_refs": ["evidence://api/1", "oracle-runtime://1"],
            "spec_id": "SPEC-1",
            "oracle_fingerprint": FINGERPRINT,
        },
    )
    truth.append_atomic(
        "ASSERTION_UPSERTED",
        {
            "id": ASSERTION,
            "release_id": RELEASE,
            "attempt_id": ATTEMPT,
            "tc_id": TC,
            "oracle_ref": "oracle://design/1",
            "passed": assertion_passed,
            "evidence_refs": ["oracle-runtime://1"],
            "spec_id": "SPEC-1",
            "oracle_fingerprint": FINGERPRINT,
        },
    )
    payload = {
        "schema_version": "pfc.aitest.rc7.contracted-runner.v1",
        "mission_id": MISSION,
        "release_id": RELEASE,
        "task_id": TASK,
        "spec_id": "SPEC-1",
        "oracle_fingerprint": FINGERPRINT,
        "runner_type": "PYTEST",
        "prepared_attempt_id": ATTEMPT,
        "oracle_snapshot": {"checks": [{"id": "C1", "actual_path": "body.business_code", "operator": "EQ", "expected": "OK"}]},
        "record": {
            "attempt_id": ATTEMPT,
            "tc_id": TC,
            "case_version": 1,
            "target_id": TARGET,
            "layer": "L3",
            "worker_id": "WORKER-EXEC",
            "lease_id": "LEASE-EXEC",
            "status": status,
            "integrity_passed": True,
            "actual_result": actual,
            "tool_call_refs": ["tool://api/1"],
            "evidence_refs": ["evidence://api/1", "oracle-runtime://1"],
            "assertion_ref": ASSERTION,
            "assertion_passed": assertion_passed,
            "reason": None if assertion_passed else "ORACLE_ASSERTION_FAILED",
        },
    }
    path = tmp_path / "formal.json"
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-FORMAL-ORACLE-1",
            mission_id=MISSION,
            kind="RUNTIME_EXECUTION_RECORD",
            source_ref="runtime://formal-execution",
            content_ref="file://" + str(path),
            subject_refs=[TASK, ATTEMPT, TC, TARGET, ASSERTION],
            content_hash="sha256:" + digest,
        ),
        release_id=RELEASE,
    )
    return truth, path


def test_actual_result_oracle_conformance_accepts_hash_bound_runtime_truth(tmp_path: Path):
    truth, _path = _seed(tmp_path)
    result = ActualResultOracleConformanceChecker(truth).check_task(MISSION, TASK)
    assert result.status == "PASS"
    assert result.oracle_proven_attempt_ids == (ATTEMPT,)
    assert result.formal_evidence_ids == ("EVD-FORMAL-ORACLE-1",)
    assert not result.violations


def test_actual_result_oracle_conformance_rejects_record_tampering(tmp_path: Path):
    truth, path = _seed(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["record"]["actual_result"]["body"]["business_code"] = "TAMPERED"
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    result = ActualResultOracleConformanceChecker(truth).check_task(MISSION, TASK)
    assert result.status == "FAIL"
    assert any(reason.startswith("FORMAL_EXECUTION_RECORD_HASH_MISMATCH:") for reason in result.violations)
    assert "AT_LEAST_ONE_RUNTIME_ORACLE_PROVEN_ATTEMPT_REQUIRED" in result.violations


def test_actual_result_oracle_conformance_rejects_pass_without_oracle_pass(tmp_path: Path):
    truth, path = _seed(tmp_path, assertion_passed=False)
    # Forge only the execution status to PASS while keeping assertion FAIL and
    # rebuild matching formal bytes/hash is intentionally not enough: R1
    # execution/assertion consistency must still fail.
    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": ATTEMPT,
            "release_id": RELEASE,
            "requirement_id": "REQ-1",
            "tc_id": TC,
            "case_version": 1,
            "target_id": TARGET,
            "layer": "L3",
            "status": "PASS",
            "actual_result": {"http": {"status": 200}, "body": {"business_code": "OK"}},
            "tool_call_refs": ["tool://api/1"],
            "evidence_refs": ["evidence://api/1", "oracle-runtime://1"],
            "spec_id": "SPEC-1",
            "oracle_fingerprint": FINGERPRINT,
        },
    )
    result = ActualResultOracleConformanceChecker(truth).check_task(MISSION, TASK)
    assert result.status == "FAIL"
    assert "EXECUTION_PASS_REQUIRES_ORACLE_PASS:%s" % ATTEMPT in result.violations
