"""Durable multi-Case fan-out contract for RC7 graph-v2 Missions.

A sufficient Test Design may contain many accepted Cases.  The canonical graph
keeps one top-level SCRIPT_READINESS and one EXECUTION task, but those nodes are
not allowed to silently shrink the accepted Case inventory to a single Case.

This module freezes the denominator from the accepted TEST_DESIGN candidate and
records immutable per-Case runtime receipts in canonical R1 Evidence.  It is an
additive contract: new graph-v2 Bank Missions opt in at bootstrap; old Missions
without the contract remain resumable and are never silently upgraded.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.automation import ScriptArtifact, ScriptValidation
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .models import Evidence
from .script_contract import CompiledScriptContract
from .truth_overlay import append_entity


CONTRACT_KIND = "CASE_FANOUT_CONTRACT"
CONTRACT_VERSION = "pfc.aitest.rc7.case-fanout.v1"
SCRIPT_READY_KIND = "CASE_SCRIPT_READY"


class CaseFanoutConformanceError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def contract_payload(*, script_task_id: str, execution_task_id: str) -> Dict[str, object]:
    return {
        "schema_version": CONTRACT_VERSION,
        "script_task_id": str(script_task_id),
        "execution_task_id": str(execution_task_id),
        "denominator": "ACCEPTED_TEST_DESIGN_CASES",
        "script_barrier": "EVERY_ACCEPTED_CASE_REQUIRES_CASE_SCRIPT_READY",
        "execution_barrier": "EVERY_ACCEPTED_CASE_REQUIRES_TERMINAL_EXECUTION",
        "top_level_graph_unchanged": True,
    }


def persist_contract(
    truth: TruthRuntime,
    *,
    mission_id: str,
    release_id: str,
    script_task_id: str,
    execution_task_id: str,
) -> str:
    payload = contract_payload(script_task_id=script_task_id, execution_task_id=execution_task_id)
    digest = _sha(payload)
    evidence_id = _stable_id("EVD-CASE-FANOUT", mission_id, digest)
    existing = truth.query("rc7_evidence", evidence_id=evidence_id)
    if existing:
        if len(existing) != 1 or existing[0].get("content_hash") != digest:
            raise CaseFanoutConformanceError("CASE_FANOUT_CONTRACT_CONFLICT")
        return evidence_id
    append_entity(
        truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=mission_id,
            kind=CONTRACT_KIND,
            source_ref="runtime://case-fanout-contract/v1",
            content_ref="case-fanout://contract/%s" % digest.split(":", 1)[1],
            subject_refs=[script_task_id, execution_task_id],
            content_hash=digest,
        ),
        release_id=release_id,
        artifact_version=1,
    )
    return evidence_id


def contract_row(truth: TruthRuntime, mission_id: str) -> Optional[Mapping[str, object]]:
    rows = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == CONTRACT_KIND
    ]
    if not rows:
        return None
    if len(rows) != 1:
        raise CaseFanoutConformanceError("CASE_FANOUT_CONTRACT_NOT_UNIQUE")
    return rows[0]


def contract_enabled(truth: TruthRuntime, mission_id: str) -> bool:
    return contract_row(truth, mission_id) is not None


@dataclass(frozen=True)
class AcceptedCase:
    tc_id: str
    case_version: int
    layer: str
    case_hash: str


@dataclass(frozen=True)
class AcceptedCaseInventory:
    mission_id: str
    design_task_id: str
    design_artifact_id: str
    design_content_hash: str
    cases: Tuple[AcceptedCase, ...]

    @property
    def tc_ids(self) -> Tuple[str, ...]:
        return tuple(item.tc_id for item in self.cases)


class AcceptedCaseInventoryReader:
    def __init__(self) -> None:
        self.reader = CandidatePayloadReader()

    def load(self, truth: TruthRuntime, mission_id: str) -> AcceptedCaseInventory:
        tasks = [
            row for row in truth.query("rc7_task", mission_id=mission_id)
            if row.get("node") == "TEST_DESIGN" and row.get("task_type") == "PRODUCE"
        ]
        if len(tasks) != 1:
            raise CaseFanoutConformanceError("TEST_DESIGN_TASK_NOT_UNIQUE")
        task = tasks[0]
        if task.get("state") != "PASS":
            raise CaseFanoutConformanceError("TEST_DESIGN_PASS_REQUIRED_FOR_CASE_INVENTORY")
        refs = task.get("output_artifact_refs")
        if not isinstance(refs, list) or len(refs) != 1:
            raise CaseFanoutConformanceError("TEST_DESIGN_ACCEPTED_ARTIFACT_REQUIRED")
        artifact_id = str(refs[0])
        candidate = self.reader.load(
            truth,
            artifact_id,
            expected_mission_id=mission_id,
            expected_task_id=str(task["task_id"]),
        )
        if candidate.artifact_type != "TEST_DESIGN_MODEL":
            raise CaseFanoutConformanceError("TEST_DESIGN_MODEL_REQUIRED")
        raw_cases = candidate.semantic_payload.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise CaseFanoutConformanceError("ACCEPTED_TEST_DESIGN_CASES_REQUIRED")
        cases = []
        seen = set()
        for raw in raw_cases:
            if not isinstance(raw, dict):
                raise CaseFanoutConformanceError("ACCEPTED_CASE_OBJECT_REQUIRED")
            tc_id = raw.get("tc_id")
            if not isinstance(tc_id, str) or not tc_id.strip():
                raise CaseFanoutConformanceError("ACCEPTED_CASE_TC_ID_REQUIRED")
            tc_id = tc_id.strip()
            if tc_id in seen:
                raise CaseFanoutConformanceError("ACCEPTED_CASE_TC_ID_DUPLICATE:%s" % tc_id)
            seen.add(tc_id)
            version = raw.get("case_version", 1)
            if not isinstance(version, int) or version < 1:
                raise CaseFanoutConformanceError("ACCEPTED_CASE_VERSION_INVALID:%s" % tc_id)
            layer = str(raw.get("layer") or "").strip().upper()
            if not layer:
                raise CaseFanoutConformanceError("ACCEPTED_CASE_LAYER_REQUIRED:%s" % tc_id)
            cases.append(
                AcceptedCase(
                    tc_id=tc_id,
                    case_version=version,
                    layer=layer,
                    case_hash=_sha(raw),
                )
            )
        return AcceptedCaseInventory(
            mission_id=mission_id,
            design_task_id=str(task["task_id"]),
            design_artifact_id=artifact_id,
            design_content_hash=candidate.content_hash,
            cases=tuple(cases),
        )


@dataclass(frozen=True)
class ScriptFanoutBarrierResult:
    status: str
    mission_id: str
    design_artifact_id: str
    required_tc_ids: Tuple[str, ...]
    ready_tc_ids: Tuple[str, ...]
    missing_tc_ids: Tuple[str, ...]
    receipt_ids: Tuple[str, ...]


def _receipt_file(row: Mapping[str, object]) -> Mapping[str, object]:
    ref = str(row.get("content_ref") or "")
    if not ref.startswith("file://"):
        raise CaseFanoutConformanceError("CASE_SCRIPT_READY_RECEIPT_FILE_REQUIRED")
    path = Path(ref[len("file://"):]).expanduser().resolve()
    if not path.is_file():
        raise CaseFanoutConformanceError("CASE_SCRIPT_READY_RECEIPT_MISSING")
    raw = path.read_bytes()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != str(row.get("content_hash") or ""):
        raise CaseFanoutConformanceError("CASE_SCRIPT_READY_RECEIPT_HASH_MISMATCH")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaseFanoutConformanceError("CASE_SCRIPT_READY_RECEIPT_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise CaseFanoutConformanceError("CASE_SCRIPT_READY_RECEIPT_OBJECT_REQUIRED")
    return payload


def record_script_ready(
    truth: TruthRuntime,
    *,
    mission_id: str,
    release_id: str,
    task_id: str,
    artifact_id: str,
    contract: CompiledScriptContract,
    script: ScriptArtifact,
    validation: ScriptValidation,
    evidence_root: str,
) -> str:
    if not contract_enabled(truth, mission_id):
        raise CaseFanoutConformanceError("CASE_FANOUT_CONTRACT_REQUIRED")
    inventory = AcceptedCaseInventoryReader().load(truth, mission_id)
    if contract.design_artifact_id != inventory.design_artifact_id:
        raise CaseFanoutConformanceError("CASE_SCRIPT_DESIGN_ARTIFACT_MISMATCH")
    if contract.design_content_hash != inventory.design_content_hash:
        raise CaseFanoutConformanceError("CASE_SCRIPT_DESIGN_HASH_MISMATCH")
    case = next((item for item in inventory.cases if item.tc_id == contract.spec.tc_id), None)
    if case is None:
        raise CaseFanoutConformanceError("CASE_SCRIPT_TC_NOT_ACCEPTED:%s" % contract.spec.tc_id)
    if script.tc_id != case.tc_id or script.case_version != case.case_version:
        raise CaseFanoutConformanceError("CASE_SCRIPT_IDENTITY_MISMATCH:%s" % case.tc_id)
    if script.case_fingerprint != contract.spec.case_fingerprint or script.oracle_fingerprint != contract.spec.oracle_fingerprint:
        raise CaseFanoutConformanceError("CASE_SCRIPT_FINGERPRINT_MISMATCH:%s" % case.tc_id)
    if not bool(getattr(validation, "ready", False)):
        raise CaseFanoutConformanceError("CASE_SCRIPT_VALIDATION_NOT_READY:%s" % case.tc_id)
    validation_refs = tuple(str(ref) for ref in validation.evidence_refs if isinstance(ref, str) and ref)
    if not validation_refs:
        raise CaseFanoutConformanceError("CASE_SCRIPT_VALIDATION_EVIDENCE_REQUIRED:%s" % case.tc_id)
    for evidence_id in validation_refs:
        rows = truth.query("rc7_evidence", evidence_id=evidence_id)
        if len(rows) != 1 or rows[0].get("mission_id") != mission_id or rows[0].get("kind") != "SCRIPT_READINESS_VALIDATION_PROOF":
            raise CaseFanoutConformanceError("CASE_SCRIPT_VALIDATION_EVIDENCE_NOT_DURABLE:%s" % evidence_id)

    payload = {
        "schema_version": CONTRACT_VERSION,
        "mission_id": mission_id,
        "design_artifact_id": inventory.design_artifact_id,
        "design_content_hash": inventory.design_content_hash,
        "case_hash": case.case_hash,
        "tc_id": case.tc_id,
        "case_version": case.case_version,
        "layer": case.layer,
        "script_task_id": task_id,
        "script_candidate_artifact_id": artifact_id,
        "spec_id": contract.spec.spec_id,
        "case_fingerprint": contract.spec.case_fingerprint,
        "oracle_fingerprint": contract.spec.oracle_fingerprint,
        "script_id": script.script_id,
        "validation_id": validation.validation_id,
        "validation_evidence_refs": list(validation_refs),
    }
    body = _canonical(payload)
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    receipt_id = _stable_id(
        "EVD-CASE-SCRIPT",
        mission_id,
        inventory.design_content_hash,
        case.tc_id,
        script.script_id,
        validation.validation_id,
    )
    folder = Path(evidence_root).expanduser().resolve() / "case-fanout" / mission_id / "script-ready"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (receipt_id + ".json")
    if path.exists() and path.read_bytes() != body:
        raise CaseFanoutConformanceError("CASE_SCRIPT_READY_RECEIPT_IMMUTABILITY_CONFLICT")
    if not path.exists():
        path.write_bytes(body)
    existing = truth.query("rc7_evidence", evidence_id=receipt_id)
    if not existing:
        append_entity(
            truth,
            Evidence(
                evidence_id=receipt_id,
                mission_id=mission_id,
                kind=SCRIPT_READY_KIND,
                source_ref="runtime://case-fanout/script-ready",
                content_ref="file://" + str(path),
                subject_refs=[
                    inventory.design_artifact_id,
                    inventory.design_content_hash,
                    case.tc_id,
                    contract.spec.spec_id,
                    script.script_id,
                    validation.validation_id,
                    task_id,
                    artifact_id,
                ],
                content_hash=digest,
            ),
            release_id=release_id,
            artifact_version=1,
        )
    elif len(existing) != 1 or existing[0].get("content_hash") != digest:
        raise CaseFanoutConformanceError("CASE_SCRIPT_READY_EVIDENCE_CONFLICT")
    return receipt_id


def check_script_barrier(truth: TruthRuntime, mission_id: str) -> ScriptFanoutBarrierResult:
    if not contract_enabled(truth, mission_id):
        raise CaseFanoutConformanceError("CASE_FANOUT_CONTRACT_REQUIRED")
    inventory = AcceptedCaseInventoryReader().load(truth, mission_id)
    required = set(inventory.tc_ids)
    ready = set()
    receipt_ids = []
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != SCRIPT_READY_KIND:
            continue
        payload = _receipt_file(row)
        if payload.get("mission_id") != mission_id:
            raise CaseFanoutConformanceError("CASE_SCRIPT_READY_MISSION_MISMATCH")
        if payload.get("design_artifact_id") != inventory.design_artifact_id or payload.get("design_content_hash") != inventory.design_content_hash:
            continue  # receipt belongs to a superseded accepted Design
        tc_id = str(payload.get("tc_id") or "")
        if tc_id not in required:
            raise CaseFanoutConformanceError("CASE_SCRIPT_READY_UNKNOWN_TC:%s" % tc_id)
        case = next(item for item in inventory.cases if item.tc_id == tc_id)
        if payload.get("case_hash") != case.case_hash or payload.get("case_version") != case.case_version:
            raise CaseFanoutConformanceError("CASE_SCRIPT_READY_CASE_IDENTITY_DRIFT:%s" % tc_id)
        ready.add(tc_id)
        receipt_ids.append(str(row.get("evidence_id") or ""))
    missing = tuple(sorted(required - ready))
    return ScriptFanoutBarrierResult(
        status="PASS" if not missing else "INCOMPLETE",
        mission_id=mission_id,
        design_artifact_id=inventory.design_artifact_id,
        required_tc_ids=tuple(sorted(required)),
        ready_tc_ids=tuple(sorted(ready)),
        missing_tc_ids=missing,
        receipt_ids=tuple(sorted(set(receipt_ids))),
    )
