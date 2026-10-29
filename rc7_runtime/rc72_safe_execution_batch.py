"""RC7.2 safe ExecutionBatch admission and per-WorkItem result separation.

ExecutionBatch is only a context-reuse unit. This service never creates or
updates business WorkItem/Attempt state. Before a multi-WorkItem semantic batch
can run, every member must already have its own canonical WorkItemAttemptBinding
and Attempt identity, with resolved MissionNode lineage. Batch results are then
accepted only when they can be separated back to every admitted WorkItem and
Attempt with independent actual/assertion/evidence/gap refs.

The durable R1 receipt is control-plane evidence for batching; it is not a
replacement business truth root.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_context_economy import ExecutionBatch
from .rc72_truth import install_rc72_truth_overlay


_ARTIFACT = "rc72_execution_batch_receipt"
_EVENT = "RC72_EXECUTION_BATCH_RECEIPT_UPSERTED"
_BUCKET = "rc72_execution_batch_receipts"
_BINDING = "rc72_workitem_attempt_binding"
_ALLOWED_BINDING_STATES = {"RESERVED", "PREPARED", "RUNNING", "EVIDENCE_READY", "COMPLETED"}
_RECEIPT_STATES = {"ADMITTED", "RESULTS_RECORDED"}


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("EXECUTION_BATCH_%s_REQUIRED" % name.upper())
    return value.strip()


def _string_tuple(values: Iterable[str], name: str, *, required: bool = False) -> Tuple[str, ...]:
    if isinstance(values, str):
        raise ContractError("EXECUTION_BATCH_%s_MUST_BE_SEQUENCE" % name.upper())
    try:
        sequence = tuple(values)
    except TypeError as exc:
        raise ContractError("EXECUTION_BATCH_%s_MUST_BE_SEQUENCE" % name.upper()) from exc
    if required and not sequence:
        raise ContractError("EXECUTION_BATCH_%s_REQUIRED" % name.upper())
    out = []
    seen = set()
    for value in sequence:
        normalized = _required(value, name)
        if normalized in seen:
            raise ContractError("EXECUTION_BATCH_%s_DUPLICATE" % name.upper())
        seen.add(normalized)
        out.append(normalized)
    return tuple(out)


def _validate_string_list(value: Any, name: str, *, required: bool = False) -> list:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("EXECUTION_BATCH_%s_INVALID" % name.upper())
    if required and not value:
        raise _contracts.DomainValidationError("EXECUTION_BATCH_%s_REQUIRED" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("EXECUTION_BATCH_%s_DUPLICATE" % name.upper())
    return list(value)


def _validate_member(member: Any) -> Dict[str, Any]:
    if not isinstance(member, dict):
        raise _contracts.DomainValidationError("EXECUTION_BATCH_MEMBER_INVALID")
    out = dict(member)
    for name in (
        "workitem_id", "attempt_id", "binding_id", "etu_id", "case_id",
        "mission_node_id", "mission_node_type",
    ):
        out[name] = _contracts._require_str(out, name)
    return out


def _validate_result(result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise _contracts.DomainValidationError("EXECUTION_BATCH_RESULT_INVALID")
    out = dict(result)
    for name in ("workitem_id", "attempt_id", "actual_result_ref", "assertion_result"):
        out[name] = _contracts._require_str(out, name)
    out["evidence_refs"] = _validate_string_list(out.get("evidence_refs"), "RESULT_EVIDENCE_REFS", required=True)
    out["gap_refs"] = _validate_string_list(out.get("gap_refs"), "RESULT_GAP_REFS")
    return out


def validate_rc72_execution_batch_receipt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "batch_receipt_id", "release_id", "mission_id", "batch_id", "node", "stage",
        "context_envelope_id", "context_sha256", "mission_node_id", "mission_node_type", "state",
    ):
        out[name] = _contracts._require_str(out, name)
    out["state"] = out["state"].upper()
    if out["state"] not in _RECEIPT_STATES:
        raise _contracts.DomainValidationError("EXECUTION_BATCH_STATE_INVALID")
    if len(out["context_sha256"]) != 64:
        raise _contracts.DomainValidationError("EXECUTION_BATCH_CONTEXT_DIGEST_INVALID")
    for name in ("member_count", "result_count", "created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("EXECUTION_BATCH_%s_INVALID" % name.upper())
    if out["member_count"] < 1:
        raise _contracts.DomainValidationError("EXECUTION_BATCH_MEMBER_COUNT_INVALID")
    members = out.get("members")
    if not isinstance(members, list):
        raise _contracts.DomainValidationError("EXECUTION_BATCH_MEMBERS_INVALID")
    out["members"] = [_validate_member(member) for member in members]
    if len(out["members"]) != out["member_count"]:
        raise _contracts.DomainValidationError("EXECUTION_BATCH_MEMBER_COUNT_MISMATCH")
    for identity in ("workitem_id", "attempt_id", "binding_id"):
        values = [member[identity] for member in out["members"]]
        if len(set(values)) != len(values):
            raise _contracts.DomainValidationError("EXECUTION_BATCH_MEMBER_%s_NOT_UNIQUE" % identity.upper())
    node_pairs = {(member["mission_node_id"], member["mission_node_type"]) for member in out["members"]}
    if len(node_pairs) != 1 or node_pairs.pop() != (out["mission_node_id"], out["mission_node_type"]):
        raise _contracts.DomainValidationError("EXECUTION_BATCH_CANONICAL_NODE_MISMATCH")

    results = out.get("results")
    if not isinstance(results, list):
        raise _contracts.DomainValidationError("EXECUTION_BATCH_RESULTS_INVALID")
    out["results"] = [_validate_result(result) for result in results]
    if len(out["results"]) != out["result_count"]:
        raise _contracts.DomainValidationError("EXECUTION_BATCH_RESULT_COUNT_MISMATCH")
    if out["state"] == "ADMITTED" and (out["result_count"] != 0 or out["results"]):
        raise _contracts.DomainValidationError("EXECUTION_BATCH_ADMITTED_CANNOT_HAVE_RESULTS")
    if out["state"] == "RESULTS_RECORDED":
        if out["result_count"] != out["member_count"]:
            raise _contracts.DomainValidationError("EXECUTION_BATCH_RESULTS_INCOMPLETE")
        member_pairs = {(member["workitem_id"], member["attempt_id"]) for member in out["members"]}
        result_pairs = {(result["workitem_id"], result["attempt_id"]) for result in out["results"]}
        if len(result_pairs) != len(out["results"]) or result_pairs != member_pairs:
            raise _contracts.DomainValidationError("EXECUTION_BATCH_RESULTS_NOT_MEMBER_SEPARABLE")
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("EXECUTION_BATCH_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_safe_execution_batch_overlay() -> None:
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_execution_batch_receipt
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "batch_receipt_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "batch_receipt_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


@dataclass(frozen=True)
class ExecutionBatchMemberResult:
    workitem_id: str
    attempt_id: str
    actual_result_ref: str
    assertion_result: str
    evidence_refs: Tuple[str, ...]
    gap_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("workitem_id", "attempt_id", "actual_result_ref", "assertion_result"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "evidence_refs", _string_tuple(self.evidence_refs, "evidence_refs", required=True))
        object.__setattr__(self, "gap_refs", _string_tuple(self.gap_refs, "gap_refs"))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "workitem_id": self.workitem_id,
            "attempt_id": self.attempt_id,
            "actual_result_ref": self.actual_result_ref,
            "assertion_result": self.assertion_result,
            "evidence_refs": list(self.evidence_refs),
            "gap_refs": list(self.gap_refs),
        }


class SafeExecutionBatchService:
    """Fail-closed boundary between a context batch and canonical WorkItem truth."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_safe_execution_batch_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")

    @staticmethod
    def _receipt_id(batch: ExecutionBatch, attempt_ids: Sequence[str]) -> str:
        raw = "\x1f".join((batch.mission_id, batch.batch_id, *attempt_ids))
        return "EXECBATCH-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _binding(self, mission_id: str, workitem_id: str, attempt_id: str) -> Dict[str, Any]:
        rows = self.truth.query(
            _BINDING,
            mission_id=mission_id,
            workitem_id=workitem_id,
            attempt_id=attempt_id,
        )
        if len(rows) != 1:
            raise ContractError(
                "EXECUTION_BATCH_CANONICAL_BINDING_NOT_UNIQUE:%s:%s:%d"
                % (workitem_id, attempt_id, len(rows))
            )
        binding = rows[0]
        if binding.get("release_id") != self.release_id:
            raise ContractError("EXECUTION_BATCH_BINDING_RELEASE_MISMATCH:%s" % workitem_id)
        if binding.get("mission_node_lineage_status") != "RESOLVED":
            raise ContractError("EXECUTION_BATCH_CANONICAL_NODE_UNRESOLVED:%s" % workitem_id)
        if not binding.get("mission_node_id") or not binding.get("mission_node_type"):
            raise ContractError("EXECUTION_BATCH_CANONICAL_NODE_MISSING:%s" % workitem_id)
        if binding.get("state") not in _ALLOWED_BINDING_STATES:
            raise ContractError("EXECUTION_BATCH_BINDING_STATE_UNSAFE:%s:%s" % (workitem_id, binding.get("state")))
        return binding

    def admit(self, batch: ExecutionBatch, *, attempt_ids_by_workitem: Mapping[str, str]) -> Dict[str, Any]:
        if not isinstance(batch, ExecutionBatch):
            raise ContractError("EXECUTION_BATCH_OBJECT_REQUIRED")
        if not isinstance(attempt_ids_by_workitem, Mapping):
            raise ContractError("EXECUTION_BATCH_ATTEMPT_MAP_REQUIRED")
        if batch.context_envelope.mission_id != batch.mission_id:
            raise ContractError("EXECUTION_BATCH_CONTEXT_MISSION_MISMATCH")
        if tuple(batch.context_envelope.workitem_ids) != tuple(batch.workitem_ids):
            raise ContractError("EXECUTION_BATCH_CONTEXT_MEMBERS_MISMATCH")

        expected = tuple(batch.workitem_ids)
        provided = set(attempt_ids_by_workitem)
        if provided != set(expected) or len(provided) != len(expected):
            raise ContractError("EXECUTION_BATCH_ATTEMPT_MAP_NOT_EXACT")
        attempt_ids = tuple(_required(attempt_ids_by_workitem[workitem_id], "attempt_id") for workitem_id in expected)
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ContractError("EXECUTION_BATCH_ATTEMPTS_MUST_BE_INDEPENDENT")

        members = []
        canonical_nodes = set()
        for workitem_id, attempt_id in zip(expected, attempt_ids):
            binding = self._binding(batch.mission_id, workitem_id, attempt_id)
            node_pair = (str(binding["mission_node_id"]), str(binding["mission_node_type"]))
            canonical_nodes.add(node_pair)
            members.append({
                "workitem_id": workitem_id,
                "attempt_id": attempt_id,
                "binding_id": str(binding["binding_id"]),
                "etu_id": str(binding["etu_id"]),
                "case_id": str(binding["case_id"]),
                "mission_node_id": node_pair[0],
                "mission_node_type": node_pair[1],
            })
        if len(canonical_nodes) != 1:
            raise ContractError("EXECUTION_BATCH_CROSS_CANONICAL_NODE_FORBIDDEN")
        mission_node_id, mission_node_type = next(iter(canonical_nodes))
        receipt_id = self._receipt_id(batch, attempt_ids)
        existing = self.truth.query(_ARTIFACT, batch_receipt_id=receipt_id)
        if len(existing) > 1:
            raise ContractError("EXECUTION_BATCH_RECEIPT_NOT_UNIQUE")
        if existing:
            current = existing[0]
            expected_signature = {
                "batch_id": batch.batch_id,
                "context_sha256": batch.context_envelope.context_sha256,
                "members": members,
            }
            actual_signature = {
                "batch_id": current.get("batch_id"),
                "context_sha256": current.get("context_sha256"),
                "members": current.get("members"),
            }
            if actual_signature != expected_signature:
                raise ContractError("EXECUTION_BATCH_RECEIPT_ID_COLLISION")
            return current

        now = _now()
        payload = {
            "batch_receipt_id": receipt_id,
            "release_id": self.release_id,
            "mission_id": batch.mission_id,
            "batch_id": batch.batch_id,
            "node": batch.node,
            "stage": batch.stage,
            "context_envelope_id": batch.context_envelope.envelope_id,
            "context_sha256": batch.context_envelope.context_sha256,
            "mission_node_id": mission_node_id,
            "mission_node_type": mission_node_type,
            "state": "ADMITTED",
            "member_count": len(members),
            "result_count": 0,
            "members": members,
            "results": [],
            "created_at": now,
            "updated_at": now,
            "artifact_version": 1,
        }
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, batch_receipt_id=receipt_id)
        if len(rows) != 1:
            raise ContractError("EXECUTION_BATCH_ADMISSION_PERSISTENCE_FAILED")
        return rows[0]

    def record_results(
        self,
        batch_receipt_id: str,
        results: Sequence[ExecutionBatchMemberResult],
    ) -> Dict[str, Any]:
        receipt_id = _required(batch_receipt_id, "batch_receipt_id")
        rows = self.truth.query(_ARTIFACT, batch_receipt_id=receipt_id)
        if len(rows) != 1:
            raise ContractError("EXECUTION_BATCH_RECEIPT_NOT_UNIQUE")
        current = rows[0]
        if current.get("release_id") != self.release_id:
            raise ContractError("EXECUTION_BATCH_RECEIPT_RELEASE_MISMATCH")
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            raise ContractError("EXECUTION_BATCH_RESULTS_REQUIRED")
        by_workitem: Dict[str, ExecutionBatchMemberResult] = {}
        for result in results:
            if not isinstance(result, ExecutionBatchMemberResult):
                raise ContractError("EXECUTION_BATCH_MEMBER_RESULT_REQUIRED")
            if result.workitem_id in by_workitem:
                raise ContractError("EXECUTION_BATCH_DUPLICATE_MEMBER_RESULT:%s" % result.workitem_id)
            by_workitem[result.workitem_id] = result

        admitted = {member["workitem_id"]: member for member in current["members"]}
        if set(by_workitem) != set(admitted):
            raise ContractError("EXECUTION_BATCH_RESULTS_NOT_EXACT")
        ordered_results = []
        for member in current["members"]:
            result = by_workitem[member["workitem_id"]]
            if result.attempt_id != member["attempt_id"]:
                raise ContractError("EXECUTION_BATCH_RESULT_ATTEMPT_MISMATCH:%s" % result.workitem_id)
            binding = self._binding(current["mission_id"], result.workitem_id, result.attempt_id)
            if binding.get("binding_id") != member["binding_id"]:
                raise ContractError("EXECUTION_BATCH_RESULT_BINDING_CHANGED:%s" % result.workitem_id)
            ordered_results.append(result.as_dict())

        if current.get("state") == "RESULTS_RECORDED":
            if current.get("results") != ordered_results:
                raise ContractError("EXECUTION_BATCH_RESULTS_ALREADY_RECORDED_DIFFERENTLY")
            return current
        payload = dict(current)
        payload.update({
            "state": "RESULTS_RECORDED",
            "result_count": len(ordered_results),
            "results": ordered_results,
            "updated_at": _now(),
            "artifact_version": int(current.get("artifact_version", 1)) + 1,
        })
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, batch_receipt_id=receipt_id)
        if len(rows) != 1 or rows[0].get("state") != "RESULTS_RECORDED":
            raise ContractError("EXECUTION_BATCH_RESULT_PERSISTENCE_FAILED")
        return rows[0]
