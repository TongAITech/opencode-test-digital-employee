"""Bank-field conformance for Runtime-owned Actual Result and Oracle truth.

ExecutionRecoveryConformance proves the attempt/recovery sequence. This gate
proves a different invariant: a terminal test result is backed by the exact
runtime-observed actual result and deterministic assertion that decided it.
It is intentionally additive and does not change the frozen execution recovery
contract hash used by already persisted graph-v2 Missions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import rc6_runtime.execution_overlay  # noqa: F401 - register execution/assertion R1 types
from rc6_runtime.truth import TruthRuntime

from .case_runtime import PREPARED_ATTEMPT_KIND


# Keep literals local to avoid a runtime -> release dependency cycle.
RUNTIME_EXECUTION_RECORD_KIND = "RUNTIME_EXECUTION_RECORD"
RUNTIME_EXECUTION_SOURCE = "runtime://formal-execution"
CONTRACTED_RUNNER_SCHEMA = "pfc.aitest.rc7.contracted-runner.v1"


class OracleConformanceError(RuntimeError):
    pass


def _prepared_attempt_ids(truth: TruthRuntime, mission_id: str, task_id: str) -> Tuple[str, ...]:
    values: List[str] = []
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        refs = [str(value) for value in list(row.get("subject_refs") or [])]
        if row.get("kind") != PREPARED_ATTEMPT_KIND or task_id not in refs:
            continue
        # CasePreparationService writes [task, worker, attempt, tc, target].
        if len(refs) >= 3 and refs[2]:
            values.append(refs[2])
    return tuple(sorted(set(values)))


def _one(rows: Sequence[Mapping[str, Any]], code: str, violations: List[str]) -> Optional[Mapping[str, Any]]:
    if len(rows) != 1:
        violations.append("%s:%d" % (code, len(rows)))
        return None
    return rows[0]


def _load_runtime_record(evidence: Mapping[str, Any], violations: List[str], attempt_id: str) -> Optional[Dict[str, Any]]:
    source = str(evidence.get("source_ref") or "")
    if source != RUNTIME_EXECUTION_SOURCE:
        violations.append("FORMAL_EXECUTION_SOURCE_INVALID:%s" % attempt_id)
        return None
    ref = str(evidence.get("content_ref") or "")
    if not ref.startswith("file://"):
        violations.append("FORMAL_EXECUTION_CONTENT_REF_INVALID:%s" % attempt_id)
        return None
    path = Path(ref[len("file://"):])
    if not path.is_file():
        violations.append("FORMAL_EXECUTION_RECORD_FILE_MISSING:%s" % attempt_id)
        return None
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if str(evidence.get("content_hash") or "") != "sha256:" + digest:
        violations.append("FORMAL_EXECUTION_RECORD_HASH_MISMATCH:%s" % attempt_id)
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        violations.append("FORMAL_EXECUTION_RECORD_JSON_INVALID:%s" % attempt_id)
        return None
    if not isinstance(payload, dict):
        violations.append("FORMAL_EXECUTION_RECORD_NOT_OBJECT:%s" % attempt_id)
        return None
    if payload.get("schema_version") != CONTRACTED_RUNNER_SCHEMA:
        violations.append("FORMAL_EXECUTION_RECORD_SCHEMA_INVALID:%s" % attempt_id)
    return payload


@dataclass(frozen=True)
class ActualResultOracleConformanceResult:
    mission_id: str
    task_id: str
    status: str
    violations: Tuple[str, ...]
    prepared_attempt_ids: Tuple[str, ...]
    oracle_proven_attempt_ids: Tuple[str, ...]
    formal_evidence_ids: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "status": self.status,
            "violations": list(self.violations),
            "prepared_attempt_ids": list(self.prepared_attempt_ids),
            "oracle_proven_attempt_ids": list(self.oracle_proven_attempt_ids),
            "formal_evidence_ids": list(self.formal_evidence_ids),
        }


class ActualResultOracleConformanceChecker:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def check_task(self, mission_id: str, task_id: str) -> ActualResultOracleConformanceResult:
        tasks = self.truth.query("rc7_task", task_id=task_id)
        if len(tasks) != 1 or str(tasks[0].get("mission_id") or "") != mission_id:
            raise OracleConformanceError("ORACLE_CONFORMANCE_TASK_NOT_UNIQUE")
        if str(tasks[0].get("node") or "") != "EXECUTION":
            raise OracleConformanceError("ORACLE_CONFORMANCE_REQUIRES_EXECUTION_TASK")

        violations: List[str] = []
        prepared = _prepared_attempt_ids(self.truth, mission_id, task_id)
        if not prepared:
            violations.append("ORACLE_CONFORMANCE_PREPARED_ATTEMPT_REQUIRED")
        proven: List[str] = []
        evidence_ids: List[str] = []

        for attempt_id in prepared:
            execution = _one(
                self.truth.query("execution_attempt", attempt_id=attempt_id),
                "ORACLE_EXECUTION_ATTEMPT_NOT_UNIQUE:%s" % attempt_id,
                violations,
            )
            if execution is None:
                continue
            status = str(execution.get("status") or "").upper()
            actual = execution.get("actual_result")
            has_actual = isinstance(actual, dict) and bool(actual)
            assertions = self.truth.query("assertion", attempt_id=attempt_id)

            # A pre-run/runner failure may legitimately have no business actual
            # result. Recovery conformance owns that path. Any PASS, or any FAIL
            # that did observe an actual result/assertion, must be Oracle-proven.
            must_prove = status == "PASS" or has_actual or bool(assertions)
            if not must_prove:
                continue
            if not has_actual:
                violations.append("ORACLE_ACTUAL_RESULT_REQUIRED:%s" % attempt_id)
                continue

            assertion = _one(
                assertions,
                "ORACLE_ASSERTION_NOT_UNIQUE:%s" % attempt_id,
                violations,
            )
            if assertion is None:
                continue
            assertion_passed = assertion.get("passed")
            if not isinstance(assertion_passed, bool):
                violations.append("ORACLE_ASSERTION_RESULT_INVALID:%s" % attempt_id)
                continue
            if status == "PASS" and assertion_passed is not True:
                violations.append("EXECUTION_PASS_REQUIRES_ORACLE_PASS:%s" % attempt_id)
            if str(assertion.get("tc_id") or "") != str(execution.get("tc_id") or ""):
                violations.append("ORACLE_ASSERTION_TC_MISMATCH:%s" % attempt_id)
            if str(assertion.get("oracle_fingerprint") or "") != str(execution.get("oracle_fingerprint") or ""):
                violations.append("ORACLE_FINGERPRINT_MISMATCH:%s" % attempt_id)

            formal = [
                row
                for row in self.truth.query("rc7_evidence", mission_id=mission_id)
                if row.get("kind") == RUNTIME_EXECUTION_RECORD_KIND
                and task_id in list(row.get("subject_refs") or [])
                and attempt_id in list(row.get("subject_refs") or [])
            ]
            formal_row = _one(
                formal,
                "FORMAL_EXECUTION_RECORD_NOT_UNIQUE:%s" % attempt_id,
                violations,
            )
            if formal_row is None:
                continue
            payload = _load_runtime_record(formal_row, violations, attempt_id)
            if payload is None:
                continue
            if payload.get("mission_id") != mission_id or payload.get("task_id") != task_id:
                violations.append("FORMAL_EXECUTION_RECORD_SCOPE_MISMATCH:%s" % attempt_id)
            if str(payload.get("oracle_fingerprint") or "") != str(execution.get("oracle_fingerprint") or ""):
                violations.append("FORMAL_EXECUTION_ORACLE_FINGERPRINT_MISMATCH:%s" % attempt_id)
            record = payload.get("record")
            if not isinstance(record, dict):
                violations.append("FORMAL_EXECUTION_RECORD_BODY_MISSING:%s" % attempt_id)
                continue
            if str(record.get("attempt_id") or "") != attempt_id:
                violations.append("FORMAL_EXECUTION_ATTEMPT_MISMATCH:%s" % attempt_id)
            if str(record.get("tc_id") or "") != str(execution.get("tc_id") or ""):
                violations.append("FORMAL_EXECUTION_TC_MISMATCH:%s" % attempt_id)
            if str(record.get("target_id") or "") != str(execution.get("target_id") or ""):
                violations.append("FORMAL_EXECUTION_TARGET_MISMATCH:%s" % attempt_id)
            if str(record.get("status") or "").upper() != status:
                violations.append("FORMAL_EXECUTION_STATUS_MISMATCH:%s" % attempt_id)
            if record.get("actual_result") != actual:
                violations.append("FORMAL_EXECUTION_ACTUAL_RESULT_MISMATCH:%s" % attempt_id)
            if str(record.get("assertion_ref") or "") != str(assertion.get("id") or ""):
                violations.append("FORMAL_EXECUTION_ASSERTION_REF_MISMATCH:%s" % attempt_id)
            if record.get("assertion_passed") is not assertion_passed:
                violations.append("FORMAL_EXECUTION_ASSERTION_RESULT_MISMATCH:%s" % attempt_id)
            if status == "PASS" and record.get("integrity_passed") is not True:
                violations.append("FORMAL_EXECUTION_PASS_INTEGRITY_REQUIRED:%s" % attempt_id)

            if not any(attempt_id in violation for violation in violations):
                proven.append(attempt_id)
                evidence_ids.append(str(formal_row.get("evidence_id") or ""))

        if not proven:
            violations.append("AT_LEAST_ONE_RUNTIME_ORACLE_PROVEN_ATTEMPT_REQUIRED")
        deduped = tuple(sorted(dict.fromkeys(violations)))
        return ActualResultOracleConformanceResult(
            mission_id=mission_id,
            task_id=task_id,
            status="PASS" if not deduped else "FAIL",
            violations=deduped,
            prepared_attempt_ids=prepared,
            oracle_proven_attempt_ids=tuple(sorted(set(proven))),
            formal_evidence_ids=tuple(sorted(set(value for value in evidence_ids if value))),
        )
