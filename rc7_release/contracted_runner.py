"""RC7 graph-v2 runner bridge with deterministic Oracle and durable evidence.

Legacy/non-contracted MCP execution remains owned by the frozen RC6 adapter.
Only a graph-v2 Mission carrying the RC7 node/tool contract is routed here by
``rc7_release.mcp_server``.  The bridge deliberately reuses the proven RC6
runner/spec/R1 serializers while replacing the compatibility Oracle with the
RC7 deterministic ``actual_path + operator + expected`` runtime.

The result is written to both inherited execution_attempt/assertion/evidence R1
truth and one content-addressed RC7 RUNTIME_EXECUTION_RECORD.  Bank Final can
therefore verify the exact actual result and assertion that drove execution
status instead of accepting an Agent-authored PASS claim.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from rc6_release import execution_closure_mcp as closure
from rc6_runtime import ExecutionRuntime, JUnitRunnerAdapter, PytestRunnerAdapter
from rc6_runtime.truth import TruthRuntime

from rc7_runtime.models import Evidence
from rc7_runtime.oracle_runtime import DeterministicOracleRuntime
from rc7_runtime.truth_overlay import append_entity


SCHEMA_VERSION = "pfc.aitest.rc7.contracted-runner.v1"
RUNTIME_EVIDENCE_KIND = "RUNTIME_EXECUTION_RECORD"
RUNTIME_EVIDENCE_SOURCE = "runtime://formal-execution"


class ContractedRunnerError(RuntimeError):
    pass


def _safe(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return text[:120] or "unknown"


def _oracle(snapshot: Dict[str, Any], actual: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    # DeterministicOracleRuntime is callable and returns the exact shape
    # ExecutionRuntime requires: passed/assertion_ref/evidence_refs/details.
    return DeterministicOracleRuntime().evaluate(snapshot, actual, context)


def _identity_rows(truth: TruthRuntime, *, mission_id: str, task_id: str, release_id: str) -> None:
    missions = truth.query("rc7_mission", mission_id=mission_id)
    if len(missions) != 1:
        raise ContractedRunnerError("CONTRACTED_RUNNER_MISSION_NOT_UNIQUE")
    if str(missions[0].get("release_id") or "") != release_id:
        raise ContractedRunnerError("CONTRACTED_RUNNER_RELEASE_MISMATCH")
    tasks = truth.query("rc7_task", task_id=task_id)
    if len(tasks) != 1 or str(tasks[0].get("mission_id") or "") != mission_id:
        raise ContractedRunnerError("CONTRACTED_RUNNER_TASK_NOT_UNIQUE")
    if str(tasks[0].get("node") or "") != "EXECUTION":
        raise ContractedRunnerError("CONTRACTED_RUNNER_REQUIRES_EXECUTION_TASK")


def _persist_runtime_record(
    truth: TruthRuntime,
    *,
    state_root: Path,
    mission_id: str,
    task_id: str,
    spec: Any,
    prepared: Any,
    record: Any,
) -> Dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mission_id": mission_id,
        "release_id": spec.release_id,
        "task_id": task_id,
        "spec_id": spec.spec_id,
        "oracle_fingerprint": spec.oracle_fingerprint,
        "runner_type": spec.runner_type,
        "prepared_attempt_id": prepared.attempt_id,
        "oracle_snapshot": prepared.oracle_snapshot,
        "record": asdict(record),
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    folder = Path(state_root).resolve() / "formal-execution" / _safe(mission_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("%s-%s.json" % (_safe(record.attempt_id), digest[:16]))
    if path.exists() and path.read_bytes() != encoded:
        raise ContractedRunnerError("CONTRACTED_RUNNER_RECORD_HASH_COLLISION")
    path.write_bytes(encoded)

    evidence_id = "EVD-EXEC-RECORD-" + hashlib.sha256(
        (mission_id + "\x1f" + task_id + "\x1f" + record.attempt_id + "\x1f" + digest).encode("utf-8")
    ).hexdigest()[:24]
    subject_refs = [task_id, record.attempt_id, record.tc_id, record.target_id]
    if record.assertion_ref:
        subject_refs.append(record.assertion_ref)
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=mission_id,
        kind=RUNTIME_EVIDENCE_KIND,
        source_ref=RUNTIME_EVIDENCE_SOURCE,
        content_ref="file://" + str(path),
        subject_refs=subject_refs,
        content_hash="sha256:" + digest,
    )
    existing = truth.query("rc7_evidence", evidence_id=evidence_id)
    if existing:
        row = existing[0]
        if len(existing) != 1 or row.get("content_hash") != evidence.content_hash or row.get("content_ref") != evidence.content_ref:
            raise ContractedRunnerError("CONTRACTED_RUNNER_EVIDENCE_IDENTITY_CONFLICT")
    else:
        append_entity(truth, evidence, release_id=spec.release_id, artifact_version=1)
    return {
        "evidence_id": evidence_id,
        "content_ref": evidence.content_ref,
        "sha256": digest,
        "assertion_ref": record.assertion_ref,
        "assertion_passed": record.assertion_passed,
        "actual_result_sha256": hashlib.sha256(
            json.dumps(record.actual_result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest(),
    }


def execute_contracted_runner(
    arguments: Dict[str, Any],
    *,
    authority: Any,
    truth: TruthRuntime,
    broker: Any,
    state_root: Path,
    mission_id: str,
    task_id: str,
) -> Dict[str, Any]:
    spec = closure._spec(arguments["spec"])
    script = closure._script(arguments["script"])
    validation = closure._validation(arguments["validation"])
    prepared = closure._prepared(arguments["prepared_attempt"])
    _identity_rows(truth, mission_id=mission_id, task_id=task_id, release_id=spec.release_id)

    runner_type = script.runner_type.upper()
    if runner_type == "PYTEST":
        runner = PytestRunnerAdapter()
    elif runner_type == "JUNIT":
        runner = JUnitRunnerAdapter()
    else:
        raise ContractedRunnerError("RUNNER_ADAPTER_NOT_AVAILABLE:%s" % runner_type)

    runtime = ExecutionRuntime(
        authority=authority,
        tool_broker=broker,
        oracle_evaluator=_oracle,
    )
    record = runtime.execute_with_runner(
        case=arguments["case"],
        executable_spec=spec,
        script=script,
        validation=validation,
        prepared=prepared,
        worker_id=arguments["worker_id"],
        lease_id=arguments["lease_id"],
        runner=runner,
        cwd=arguments["cwd"],
        env=arguments.get("env") or None,
    )
    inherited_receipts = closure._record_execution_truth(truth, spec, record)
    runtime_evidence = _persist_runtime_record(
        truth,
        state_root=state_root,
        mission_id=mission_id,
        task_id=task_id,
        spec=spec,
        prepared=prepared,
        record=record,
    )
    return {
        "execution": asdict(record),
        "r1_receipts": inherited_receipts,
        "rc7_runtime_evidence": runtime_evidence,
        "oracle_runtime": "RC7_DETERMINISTIC_ACTUAL_PATH_OPERATOR_EXPECTED",
    }
