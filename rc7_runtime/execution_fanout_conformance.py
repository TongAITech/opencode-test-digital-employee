"""Runtime-owned per-Case execution terminal receipts and aggregate barrier.

The accepted Test Design is the denominator. A top-level EXECUTION task is not
allowed to PASS because one Case ran successfully: every accepted Case must have
one current, immutable, runtime-backed terminal receipt tied to the same Design,
its Script-Ready receipt, durable Preparation truth, real execution record and
Oracle/diagnosis conclusion.

A trusted PRODUCT_DEFECT is terminal for its Case but is never dropped while
sibling Cases are still pending. The exact governed Gap and source execution
artifact are frozen into the Case terminal receipt and are rehydrated only when
the aggregate execution barrier is ready to hand defects to the Defect node.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime

from .case_fanout_conformance import (
    AcceptedCaseInventoryReader,
    SCRIPT_READY_KIND,
    contract_enabled,
)
from .case_runtime import PREPARED_ATTEMPT_KIND
from .execution_loop import ExecutionLoopResult
from .models import Evidence, EvaluationResult, Gap, GapSeverity
from .truth_overlay import append_entity


EXECUTION_TERMINAL_KIND = "CASE_EXECUTION_TERMINAL"
RUNTIME_EXECUTION_RECORD_KIND = "RUNTIME_EXECUTION_RECORD"
SCHEMA_VERSION = "pfc.aitest.rc7.case-execution-terminal.v1"
PASS_READY_OUTCOMES = {"PASS", "PRODUCT_DEFECT"}


class ExecutionFanoutConformanceError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _file_payload(row: Mapping[str, object], *, code: str) -> Mapping[str, object]:
    ref = str(row.get("content_ref") or "")
    if not ref.startswith("file://"):
        raise ExecutionFanoutConformanceError("%s_FILE_REQUIRED" % code)
    path = Path(ref[len("file://"):]).expanduser().resolve()
    if not path.is_file():
        raise ExecutionFanoutConformanceError("%s_FILE_MISSING" % code)
    raw = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != str(row.get("content_hash") or ""):
        raise ExecutionFanoutConformanceError("%s_HASH_MISMATCH" % code)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionFanoutConformanceError("%s_JSON_INVALID" % code) from exc
    if not isinstance(payload, dict):
        raise ExecutionFanoutConformanceError("%s_OBJECT_REQUIRED" % code)
    return payload


def load_execution_terminal_receipt(
    truth: TruthRuntime,
    *,
    mission_id: str,
    receipt_id: str,
) -> Mapping[str, object]:
    rows = truth.query("rc7_evidence", evidence_id=receipt_id)
    if len(rows) != 1:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_NOT_UNIQUE:%s" % receipt_id)
    row = rows[0]
    if row.get("mission_id") != mission_id or row.get("kind") != EXECUTION_TERMINAL_KIND:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_IDENTITY_MISMATCH:%s" % receipt_id)
    payload = _file_payload(row, code="CASE_EXECUTION_TERMINAL")
    if payload.get("mission_id") != mission_id:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_MISSION_MISMATCH:%s" % receipt_id)
    return payload


def _state_payload(row: Mapping[str, object], *, state_root: str, code: str) -> Mapping[str, object]:
    ref = str(row.get("content_ref") or "")
    if not ref.startswith("state://"):
        raise ExecutionFanoutConformanceError("%s_STATE_REF_REQUIRED" % code)
    path = Path(state_root).expanduser().resolve() / ref[len("state://"):]
    if not path.is_file():
        raise ExecutionFanoutConformanceError("%s_FILE_MISSING" % code)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    expected = str(row.get("content_hash") or "")
    if expected not in {digest, "sha256:" + digest}:
        raise ExecutionFanoutConformanceError("%s_HASH_MISMATCH" % code)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionFanoutConformanceError("%s_JSON_INVALID" % code) from exc
    if not isinstance(payload, dict):
        raise ExecutionFanoutConformanceError("%s_OBJECT_REQUIRED" % code)
    return payload


def _script_receipt(
    truth: TruthRuntime,
    *,
    mission_id: str,
    receipt_id: str,
    design_artifact_id: str,
    design_content_hash: str,
    tc_id: str,
    case_hash: str,
) -> Mapping[str, object]:
    rows = truth.query("rc7_evidence", evidence_id=receipt_id)
    if len(rows) != 1 or rows[0].get("mission_id") != mission_id or rows[0].get("kind") != SCRIPT_READY_KIND:
        raise ExecutionFanoutConformanceError("CASE_SCRIPT_READY_RECEIPT_NOT_DURABLE:%s" % receipt_id)
    payload = _file_payload(rows[0], code="CASE_SCRIPT_READY_RECEIPT")
    expected = {
        "mission_id": mission_id,
        "design_artifact_id": design_artifact_id,
        "design_content_hash": design_content_hash,
        "tc_id": tc_id,
        "case_hash": case_hash,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ExecutionFanoutConformanceError("CASE_SCRIPT_READY_RECEIPT_MISMATCH:%s:%s" % (tc_id, field))
    return payload


def _terminal_outcome(record: ExecutionRecord, loop_result: ExecutionLoopResult) -> str:
    if not loop_result.conclusive:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_NOT_CONCLUSIVE:%s" % record.tc_id)
    evaluation = loop_result.evaluation
    if loop_result.test_result == "PASS":
        if (
            record.status != "PASS"
            or not record.integrity_passed
            or record.assertion_passed is not True
            or evaluation.result != EvaluationResult.PASS
            or loop_result.gaps
        ):
            raise ExecutionFanoutConformanceError("CASE_EXECUTION_PASS_TRUTH_INVALID:%s" % record.tc_id)
        return "PASS"
    if loop_result.test_result == "FAIL":
        product = [
            gap for gap in loop_result.gaps
            if gap.category == "PRODUCT_DEFECT" and gap.target_node == "DEFECT"
        ]
        if (
            record.status != "FAIL"
            or not record.integrity_passed
            or record.assertion_passed is not False
            or evaluation.result != EvaluationResult.PASS
            or loop_result.recovery_action != "PRODUCT_DEFECT"
            or len(product) != 1
        ):
            raise ExecutionFanoutConformanceError("CASE_PRODUCT_DEFECT_TRUTH_INVALID:%s" % record.tc_id)
        return "PRODUCT_DEFECT"
    if evaluation.result == EvaluationResult.BLOCKED:
        return "BLOCKED"
    raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_OUTCOME_UNSUPPORTED:%s" % record.tc_id)


def _product_gap_snapshot(loop_result: ExecutionLoopResult, outcome: str) -> Optional[Dict[str, object]]:
    if outcome != "PRODUCT_DEFECT":
        return None
    product = [
        gap for gap in loop_result.gaps
        if gap.category == "PRODUCT_DEFECT" and gap.target_node == "DEFECT"
    ]
    if len(product) != 1:
        raise ExecutionFanoutConformanceError("PRODUCT_DEFECT_GAP_NOT_UNIQUE")
    gap = product[0]
    return {
        "gap_id": gap.gap_id,
        "mission_id": gap.mission_id,
        "source_node": gap.source_node,
        "category": gap.category,
        "severity": gap.severity.value,
        "target_node": gap.target_node,
        "description": gap.description,
        "subject_refs": list(gap.subject_refs),
        "evidence_refs": list(gap.evidence_refs),
        "root_gap_id": gap.root_gap_id,
        "acceptance_criteria": list(gap.acceptance_criteria),
    }


def record_execution_terminal(
    truth: TruthRuntime,
    *,
    mission_id: str,
    release_id: str,
    task_id: str,
    script_receipt_id: str,
    prepared_evidence_id: str,
    record_evidence_id: str,
    record: ExecutionRecord,
    loop_result: ExecutionLoopResult,
    state_root: str,
    evidence_root: str,
) -> str:
    if not contract_enabled(truth, mission_id):
        raise ExecutionFanoutConformanceError("CASE_FANOUT_CONTRACT_REQUIRED")
    inventory = AcceptedCaseInventoryReader().load(truth, mission_id)
    case = next((item for item in inventory.cases if item.tc_id == record.tc_id), None)
    if case is None:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_TC_NOT_ACCEPTED:%s" % record.tc_id)
    if record.case_version != case.case_version or record.layer != case.layer:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_IDENTITY_MISMATCH:%s" % record.tc_id)

    script_payload = _script_receipt(
        truth,
        mission_id=mission_id,
        receipt_id=script_receipt_id,
        design_artifact_id=inventory.design_artifact_id,
        design_content_hash=inventory.design_content_hash,
        tc_id=case.tc_id,
        case_hash=case.case_hash,
    )

    prepared_rows = truth.query("rc7_evidence", evidence_id=prepared_evidence_id)
    if len(prepared_rows) != 1 or prepared_rows[0].get("mission_id") != mission_id or prepared_rows[0].get("kind") != PREPARED_ATTEMPT_KIND:
        raise ExecutionFanoutConformanceError("CASE_PREPARED_ATTEMPT_NOT_DURABLE:%s" % case.tc_id)
    prepared_refs = list(prepared_rows[0].get("subject_refs") or [])
    if task_id not in prepared_refs or record.attempt_id not in prepared_refs or case.tc_id not in prepared_refs:
        raise ExecutionFanoutConformanceError("CASE_PREPARED_ATTEMPT_IDENTITY_MISMATCH:%s" % case.tc_id)
    prepared_payload = _state_payload(prepared_rows[0], state_root=state_root, code="CASE_PREPARED_ATTEMPT")
    if (
        prepared_payload.get("attempt_id") != record.attempt_id
        or prepared_payload.get("tc_id") != case.tc_id
        or prepared_payload.get("case_version") != case.case_version
        or prepared_payload.get("target_id") != record.target_id
        or prepared_payload.get("status") != "PREPARED"
    ):
        raise ExecutionFanoutConformanceError("CASE_PREPARED_ATTEMPT_PAYLOAD_MISMATCH:%s" % case.tc_id)

    record_rows = truth.query("rc7_evidence", evidence_id=record_evidence_id)
    if len(record_rows) != 1 or record_rows[0].get("mission_id") != mission_id or record_rows[0].get("kind") != RUNTIME_EXECUTION_RECORD_KIND:
        raise ExecutionFanoutConformanceError("CASE_RUNTIME_EXECUTION_RECORD_NOT_DURABLE:%s" % case.tc_id)
    record_refs = list(record_rows[0].get("subject_refs") or [])
    if task_id not in record_refs or record.attempt_id not in record_refs or case.tc_id not in record_refs:
        raise ExecutionFanoutConformanceError("CASE_RUNTIME_EXECUTION_RECORD_IDENTITY_MISMATCH:%s" % case.tc_id)
    persisted = _file_payload(record_rows[0], code="CASE_RUNTIME_EXECUTION_RECORD")
    persisted_record = persisted.get("record")
    if not isinstance(persisted_record, dict):
        raise ExecutionFanoutConformanceError("CASE_RUNTIME_EXECUTION_RECORD_PAYLOAD_REQUIRED:%s" % case.tc_id)
    for field, value in {
        "attempt_id": record.attempt_id,
        "tc_id": record.tc_id,
        "case_version": record.case_version,
        "target_id": record.target_id,
        "layer": record.layer,
        "status": record.status,
        "integrity_passed": record.integrity_passed,
        "assertion_ref": record.assertion_ref,
        "assertion_passed": record.assertion_passed,
    }.items():
        if persisted_record.get(field) != value:
            raise ExecutionFanoutConformanceError("CASE_RUNTIME_EXECUTION_RECORD_DRIFT:%s:%s" % (case.tc_id, field))

    artifact_refs = list(loop_result.evaluation.artifact_refs)
    if len(artifact_refs) != 1:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_SOURCE_ARTIFACT_REQUIRED:%s" % case.tc_id)
    execution_artifact_id = str(artifact_refs[0])
    artifacts = truth.query("rc7_artifact", artifact_id=execution_artifact_id)
    if len(artifacts) != 1:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_SOURCE_ARTIFACT_NOT_UNIQUE:%s" % case.tc_id)
    artifact = artifacts[0]
    if (
        artifact.get("mission_id") != mission_id
        or artifact.get("producer_task_id") != task_id
        or artifact.get("artifact_type_name") != "EXECUTION_CONCLUSION"
        or record_evidence_id not in list(artifact.get("evidence_refs") or [])
    ):
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_SOURCE_ARTIFACT_IDENTITY_MISMATCH:%s" % case.tc_id)

    outcome = _terminal_outcome(record, loop_result)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mission_id": mission_id,
        "design_artifact_id": inventory.design_artifact_id,
        "design_content_hash": inventory.design_content_hash,
        "case_hash": case.case_hash,
        "tc_id": case.tc_id,
        "case_version": case.case_version,
        "layer": case.layer,
        "target_id": record.target_id,
        "execution_task_id": task_id,
        "execution_artifact_id": execution_artifact_id,
        "attempt_id": record.attempt_id,
        "outcome": outcome,
        "script_receipt_id": script_receipt_id,
        "script_id": script_payload.get("script_id"),
        "spec_id": script_payload.get("spec_id"),
        "oracle_fingerprint": script_payload.get("oracle_fingerprint"),
        "prepared_evidence_id": prepared_evidence_id,
        "record_evidence_id": record_evidence_id,
        "evaluation_id": loop_result.evaluation.evaluation_id,
        "gap_ids": sorted(gap.gap_id for gap in loop_result.gaps),
        "product_defect_gap": _product_gap_snapshot(loop_result, outcome),
    }
    body = _canonical(payload)
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    receipt_id = _stable_id(
        "EVD-CASE-EXEC",
        mission_id,
        inventory.design_content_hash,
        case.tc_id,
        record.attempt_id,
        outcome,
    )
    folder = Path(evidence_root).expanduser().resolve() / "case-fanout" / mission_id / "execution-terminal"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (receipt_id + ".json")
    if path.exists() and path.read_bytes() != body:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_IMMUTABILITY_CONFLICT")
    if not path.exists():
        path.write_bytes(body)
    existing = truth.query("rc7_evidence", evidence_id=receipt_id)
    if not existing:
        append_entity(
            truth,
            Evidence(
                evidence_id=receipt_id,
                mission_id=mission_id,
                kind=EXECUTION_TERMINAL_KIND,
                source_ref="runtime://case-fanout/execution-terminal",
                content_ref="file://" + str(path),
                subject_refs=[
                    inventory.design_artifact_id,
                    inventory.design_content_hash,
                    case.tc_id,
                    record.attempt_id,
                    task_id,
                    execution_artifact_id,
                    script_receipt_id,
                    prepared_evidence_id,
                    record_evidence_id,
                ],
                content_hash=digest,
            ),
            release_id=release_id,
            artifact_version=1,
        )
    elif len(existing) != 1 or existing[0].get("content_hash") != digest:
        raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_EVIDENCE_CONFLICT")
    return receipt_id


@dataclass(frozen=True)
class ExecutionFanoutBarrierResult:
    status: str
    mission_id: str
    design_artifact_id: str
    required_tc_ids: Tuple[str, ...]
    pass_ready_tc_ids: Tuple[str, ...]
    blocked_tc_ids: Tuple[str, ...]
    missing_tc_ids: Tuple[str, ...]
    receipt_ids: Tuple[str, ...]


def check_execution_barrier(truth: TruthRuntime, mission_id: str) -> ExecutionFanoutBarrierResult:
    if not contract_enabled(truth, mission_id):
        raise ExecutionFanoutConformanceError("CASE_FANOUT_CONTRACT_REQUIRED")
    inventory = AcceptedCaseInventoryReader().load(truth, mission_id)
    required = set(inventory.tc_ids)
    by_case: Dict[str, list] = {tc_id: [] for tc_id in required}
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != EXECUTION_TERMINAL_KIND:
            continue
        payload = _file_payload(row, code="CASE_EXECUTION_TERMINAL")
        if payload.get("mission_id") != mission_id:
            raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_MISSION_MISMATCH")
        if payload.get("design_artifact_id") != inventory.design_artifact_id or payload.get("design_content_hash") != inventory.design_content_hash:
            continue
        tc_id = str(payload.get("tc_id") or "")
        if tc_id not in required:
            raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_UNKNOWN_TC:%s" % tc_id)
        case = next(item for item in inventory.cases if item.tc_id == tc_id)
        if payload.get("case_hash") != case.case_hash or payload.get("case_version") != case.case_version or payload.get("layer") != case.layer:
            raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_CASE_IDENTITY_DRIFT:%s" % tc_id)
        script_receipt_id = str(payload.get("script_receipt_id") or "")
        _script_receipt(
            truth,
            mission_id=mission_id,
            receipt_id=script_receipt_id,
            design_artifact_id=inventory.design_artifact_id,
            design_content_hash=inventory.design_content_hash,
            tc_id=tc_id,
            case_hash=case.case_hash,
        )
        outcome = str(payload.get("outcome") or "")
        if outcome not in PASS_READY_OUTCOMES | {"BLOCKED"}:
            raise ExecutionFanoutConformanceError("CASE_EXECUTION_TERMINAL_OUTCOME_INVALID:%s" % tc_id)
        if outcome == "PRODUCT_DEFECT":
            snapshot = payload.get("product_defect_gap")
            if not isinstance(snapshot, dict) or snapshot.get("category") != "PRODUCT_DEFECT" or snapshot.get("target_node") != "DEFECT":
                raise ExecutionFanoutConformanceError("CASE_PRODUCT_DEFECT_SNAPSHOT_REQUIRED:%s" % tc_id)
            if not isinstance(payload.get("execution_artifact_id"), str) or not payload.get("execution_artifact_id"):
                raise ExecutionFanoutConformanceError("CASE_PRODUCT_DEFECT_SOURCE_ARTIFACT_REQUIRED:%s" % tc_id)
        by_case[tc_id].append((int(row.get("created_at", 0)), str(row.get("evidence_id") or ""), outcome))

    pass_ready = []
    blocked = []
    selected_receipts = []
    for tc_id in sorted(required):
        candidates = sorted(by_case[tc_id], key=lambda item: (item[0], item[1]))
        successful = [item for item in candidates if item[2] in PASS_READY_OUTCOMES]
        if successful:
            chosen = successful[-1]
            pass_ready.append(tc_id)
            selected_receipts.append(chosen[1])
        elif candidates:
            blocked.append(tc_id)
    missing = tuple(sorted(required - set(pass_ready)))
    return ExecutionFanoutBarrierResult(
        status="PASS" if not missing else "INCOMPLETE",
        mission_id=mission_id,
        design_artifact_id=inventory.design_artifact_id,
        required_tc_ids=tuple(sorted(required)),
        pass_ready_tc_ids=tuple(pass_ready),
        blocked_tc_ids=tuple(blocked),
        missing_tc_ids=missing,
        receipt_ids=tuple(selected_receipts),
    )


def deferred_product_defect_gaps(
    truth: TruthRuntime,
    *,
    mission_id: str,
    receipt_ids: Sequence[str],
) -> Tuple[Gap, ...]:
    gaps = []
    seen = set()
    for receipt_id in receipt_ids:
        payload = load_execution_terminal_receipt(
            truth,
            mission_id=mission_id,
            receipt_id=str(receipt_id),
        )
        if payload.get("outcome") != "PRODUCT_DEFECT":
            continue
        snapshot = payload.get("product_defect_gap")
        if not isinstance(snapshot, dict):
            raise ExecutionFanoutConformanceError("DEFERRED_PRODUCT_DEFECT_SNAPSHOT_REQUIRED:%s" % receipt_id)
        gap_id = str(snapshot.get("gap_id") or "")
        if not gap_id or gap_id in seen:
            if gap_id in seen:
                continue
            raise ExecutionFanoutConformanceError("DEFERRED_PRODUCT_DEFECT_GAP_ID_REQUIRED:%s" % receipt_id)
        if snapshot.get("mission_id") != mission_id or snapshot.get("source_node") != "EXECUTION" or snapshot.get("category") != "PRODUCT_DEFECT" or snapshot.get("target_node") != "DEFECT":
            raise ExecutionFanoutConformanceError("DEFERRED_PRODUCT_DEFECT_IDENTITY_INVALID:%s" % receipt_id)
        try:
            severity = GapSeverity(str(snapshot.get("severity") or ""))
        except ValueError as exc:
            raise ExecutionFanoutConformanceError("DEFERRED_PRODUCT_DEFECT_SEVERITY_INVALID:%s" % receipt_id) from exc
        evidence_refs = [
            str(ref) for ref in list(snapshot.get("evidence_refs") or [])
            if isinstance(ref, str) and ref
        ]
        evidence_refs.append(str(receipt_id))
        gaps.append(
            Gap(
                gap_id=gap_id,
                mission_id=mission_id,
                source_node="EXECUTION",
                category="PRODUCT_DEFECT",
                severity=severity,
                target_node="DEFECT",
                description=str(snapshot.get("description") or "trusted product mismatch"),
                subject_refs=[
                    str(ref) for ref in list(snapshot.get("subject_refs") or [])
                    if isinstance(ref, str) and ref
                ],
                evidence_refs=list(dict.fromkeys(evidence_refs)),
                root_gap_id=snapshot.get("root_gap_id") if isinstance(snapshot.get("root_gap_id"), str) else None,
                acceptance_criteria=[
                    str(value) for value in list(snapshot.get("acceptance_criteria") or [])
                    if isinstance(value, str) and value
                ],
            )
        )
        seen.add(gap_id)
    return tuple(gaps)
