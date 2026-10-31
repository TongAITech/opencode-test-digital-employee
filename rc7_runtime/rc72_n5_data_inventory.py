"""RC7.2 N5 canonical data-requirement inventory.

N5 must not begin by asking a data worker to "find some usable data".  Its
business denominator comes from the exact PASS N4 TestCase set, with active PASS
N3 constraints kept in lineage.  This module materializes that denominator as
R1 truth before any discovery/construction worker is allowed to run.

This slice deliberately does NOT create or guess a DataRef, reserve data,
construct records, verify data, PASS N5, release N6, or make Field/BANK_FINAL
claims.  It only converts every canonical Case.data_requirements entry into one
stable, auditable N5 DataRequirement.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadError, CandidatePayloadReader
from .models import ContractError
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_REQUIREMENT_ARTIFACT = "rc72_n5_data_requirement"
_REQUIREMENT_EVENT = "RC72_N5_DATA_REQUIREMENT_UPSERTED"
_REQUIREMENT_BUCKET = "rc72_n5_data_requirements"
_SNAPSHOT_ARTIFACT = "rc72_n5_data_inventory_snapshot"
_SNAPSHOT_EVENT = "RC72_N5_DATA_INVENTORY_SNAPSHOT_UPSERTED"
_SNAPSHOT_BUCKET = "rc72_n5_data_inventory_snapshots"
_NODE = AutonomousMissionNode.N5_TEST_DATA
_NEXT_NODE = AutonomousMissionNode.N6_EXECUTABLE_READINESS
_STATUS = "UNRESOLVED"
_SNAPSHOT_STATUS = "MATERIALIZED"
_INSTALLED = False


class N5DataInventoryError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataInventoryError("RC72_N5_DATA_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _strings(value: Any, name: str, *, allow_empty: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise N5DataInventoryError("RC72_N5_DATA_%s_LIST_REQUIRED" % name.upper())
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(result) != len(value):
        raise N5DataInventoryError("RC72_N5_DATA_%s_INVALID" % name.upper())
    if not allow_empty and not result:
        raise N5DataInventoryError("RC72_N5_DATA_%s_REQUIRED" % name.upper())
    return result


def _normalized_requirement(value: str) -> str:
    return " ".join(value.split())


def _validate_string_list_field(
    out: Dict[str, Any], name: str, *, allow_empty: bool = False
) -> None:
    value = out.get(name)
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_%s_INVALID" % name.upper()
        )
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_%s_DUPLICATE" % name.upper()
        )
    if not allow_empty and not value:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_%s_REQUIRED" % name.upper()
        )


def validate_rc72_n5_data_requirement(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "data_requirement_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "source_commit",
        "mission_node_id",
        "requirement_id",
        "sst_id",
        "obligation_id",
        "case_id",
        "test_level",
        "requirement_text",
        "normalized_requirement",
        "source_case_sha256",
        "source_n4_artifact_id",
        "source_n4_evaluation_id",
        "source_n4_delivery_id",
        "source_n4_gate_id",
        "source_n3_delivery_id",
        "source_n3_gate_id",
        "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N5_DATA_STATUS_INVALID")
    if not out["source_case_sha256"].startswith("sha256:"):
        raise _contracts.DomainValidationError("RC72_N5_DATA_CASE_HASH_INVALID")
    for name in (
        "source_n3_artifact_refs",
        "case_preconditions",
        "case_code_trace",
        "case_evidence_requirements",
    ):
        _validate_string_list_field(out, name)
    action = out.get("case_action_semantics")
    if not isinstance(action, dict):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_CASE_ACTION_SEMANTICS_INVALID"
        )
    for forbidden in (
        "data_ref",
        "source_or_constructor",
        "verification",
        "reservation_owner",
        "validity_window",
        "cleanup_policy",
        "verified",
        "lease_id",
        "attempt_id",
        "worker_id",
        "n5_pass",
        "n6_ready",
        "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_PREMATURE_RESOLUTION_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _REQUIREMENT_ARTIFACT
    return out


def validate_rc72_n5_data_inventory_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "snapshot_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "source_commit",
        "mission_node_id",
        "source_n4_delivery_id",
        "source_n4_gate_id",
        "source_n3_delivery_id",
        "source_n3_gate_id",
        "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["status"] != _SNAPSHOT_STATUS:
        raise _contracts.DomainValidationError("RC72_N5_DATA_SNAPSHOT_STATUS_INVALID")
    for name in (
        "source_n4_artifact_refs",
        "source_n3_artifact_refs",
        "data_requirement_ids",
        "case_ids",
    ):
        _validate_string_list_field(out, name)
    for name in ("case_count", "data_requirement_count"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_SNAPSHOT_%s_INVALID" % name.upper()
            )
    for forbidden in (
        "data_refs",
        "resolved_data_refs",
        "verified",
        "n5_pass",
        "n6_ready",
        "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_SNAPSHOT_PREMATURE_CLAIM_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_SNAPSHOT_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_SNAPSHOT_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _SNAPSHOT_ARTIFACT
    return out


def install_rc72_n5_data_inventory_overlay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[_REQUIREMENT_ARTIFACT] = validate_rc72_n5_data_requirement
    _truth.BUCKETS[_REQUIREMENT_ARTIFACT] = _REQUIREMENT_BUCKET
    _truth.IDENTITY_FIELDS[_REQUIREMENT_ARTIFACT] = "data_requirement_id"
    _truth.EVENT_TYPES[_REQUIREMENT_EVENT] = (
        _REQUIREMENT_ARTIFACT,
        "data_requirement_id",
    )
    _contracts.VALIDATORS[_SNAPSHOT_ARTIFACT] = validate_rc72_n5_data_inventory_snapshot
    _truth.BUCKETS[_SNAPSHOT_ARTIFACT] = _SNAPSHOT_BUCKET
    _truth.IDENTITY_FIELDS[_SNAPSHOT_ARTIFACT] = "snapshot_id"
    _truth.EVENT_TYPES[_SNAPSHOT_EVENT] = (_SNAPSHOT_ARTIFACT, "snapshot_id")
    _INSTALLED = True


def _ensure_bucket(truth: TruthRuntime, bucket: str, artifact_type: str) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, bucket):
        setattr(projection, bucket, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(artifact_type, {})


class N5DataRequirementInventoryService:
    """Materialize exact N4 Case data needs before N5 discovery/construction."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n5_data_inventory_overlay()
        _ensure_bucket(truth, _REQUIREMENT_BUCKET, _REQUIREMENT_ARTIFACT)
        _ensure_bucket(truth, _SNAPSHOT_BUCKET, _SNAPSHOT_ARTIFACT)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataInventoryError(
                "RC72_N5_DATA_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _active_pass_delivery(
        self,
        *,
        mission_id: str,
        node_type: AutonomousMissionNode,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=node_type.value
        )
        if node.get("state") != MissionNodeState.PASS.value:
            raise N5DataInventoryError(
                "RC72_N5_DATA_PARENT_NOT_PASS:%s:%s"
                % (node_type.value, str(node.get("state") or "UNKNOWN"))
            )
        version = node.get("active_delivery_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise N5DataInventoryError(
                "RC72_N5_DATA_PARENT_DELIVERY_REQUIRED:%s" % node_type.value
            )
        deliveries = [
            row
            for row in self.truth.query(
                "rc72_node_delivery", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("version") == version
            and row.get("delivery_id") in list(node.get("delivery_refs") or [])
        ]
        if len(deliveries) != 1:
            raise N5DataInventoryError(
                "RC72_N5_DATA_PARENT_DELIVERY_NOT_UNIQUE:%s:%d"
                % (node_type.value, len(deliveries))
            )
        delivery = deliveries[0]
        gates = [
            row
            for row in self.truth.query(
                "rc72_node_gate", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("delivery_id") == delivery.get("delivery_id")
            and row.get("gate_id") in list(node.get("gate_refs") or [])
            and row.get("decision") == "PASS"
        ]
        if len(gates) != 1 or list(gates[0].get("failed") or []):
            raise N5DataInventoryError(
                "RC72_N5_DATA_PARENT_PASS_GATE_REQUIRED:%s" % node_type.value
            )
        if not list(delivery.get("artifact_refs") or []):
            raise N5DataInventoryError(
                "RC72_N5_DATA_PARENT_ARTIFACTS_REQUIRED:%s" % node_type.value
            )
        return node, delivery, gates[0]

    def _n3_artifacts_by_requirement(
        self,
        *,
        mission_id: str,
        artifact_refs: Sequence[str],
    ) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for artifact_id in artifact_refs:
            row = self._one("rc7_artifact", artifact_id=str(artifact_id))
            if (
                row.get("mission_id") != mission_id
                or row.get("artifact_type_name") != "CODE_ANALYSIS_CANDIDATE"
                or row.get("state") != "VALID"
            ):
                raise N5DataInventoryError(
                    "RC72_N5_DATA_N3_ARTIFACT_INVALID:%s" % artifact_id
                )
            try:
                durable = self.reader.load(
                    self.truth,
                    str(artifact_id),
                    expected_mission_id=mission_id,
                )
            except CandidatePayloadError as exc:
                raise N5DataInventoryError(
                    "RC72_N5_DATA_N3_PAYLOAD_INVALID:%s:%s" % (artifact_id, exc)
                ) from exc
            requirement_ids = _strings(
                durable.semantic_payload.get("requirement_ids"),
                "n3_requirement_ids",
            )
            for requirement_id in requirement_ids:
                result.setdefault(requirement_id, []).append(str(artifact_id))
        return {key: sorted(set(value)) for key, value in result.items()}

    def _expected(
        self, *, release_batch_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        n5 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        n6 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if n5.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N5DataInventoryError("RC72_N5_DATA_NODE_SCOPE_MISMATCH")
        if n5.get("state") not in {
            MissionNodeState.READY.value,
            MissionNodeState.RUNNING.value,
        }:
            raise N5DataInventoryError(
                "RC72_N5_DATA_N5_NOT_ADMITTED:%s"
                % str(n5.get("state") or "UNKNOWN")
            )
        if n6.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N5DataInventoryError("RC72_N5_DATA_N6_PREMATURELY_RELEASED")

        _n4_node, n4_delivery, n4_gate = self._active_pass_delivery(
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N4_TEST_DESIGN,
        )
        _n3_node, n3_delivery, n3_gate = self._active_pass_delivery(
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        )
        n3_refs = [str(ref) for ref in list(n3_delivery.get("artifact_refs") or [])]
        n3_by_requirement = self._n3_artifacts_by_requirement(
            mission_id=mission_id,
            artifact_refs=n3_refs,
        )

        rows: List[Dict[str, Any]] = []
        seen_cases: Set[str] = set()
        seen_requirement_ids: Set[str] = set()
        n4_artifact_refs = [
            str(ref) for ref in list(n4_delivery.get("artifact_refs") or [])
        ]
        for artifact_id in n4_artifact_refs:
            artifact = self._one("rc7_artifact", artifact_id=artifact_id)
            if (
                artifact.get("mission_id") != mission_id
                or artifact.get("artifact_type_name") != "TEST_DESIGN_CANDIDATE"
                or artifact.get("state") != "VALID"
                or not str(artifact.get("content_hash") or "").startswith("sha256:")
            ):
                raise N5DataInventoryError(
                    "RC72_N5_DATA_N4_ARTIFACT_INVALID:%s" % artifact_id
                )
            try:
                durable = self.reader.load(
                    self.truth,
                    artifact_id,
                    expected_mission_id=mission_id,
                )
            except CandidatePayloadError as exc:
                raise N5DataInventoryError(
                    "RC72_N5_DATA_N4_PAYLOAD_INVALID:%s:%s" % (artifact_id, exc)
                ) from exc
            runtime_lineage = durable.envelope.get("runtime_lineage")
            if not isinstance(runtime_lineage, Mapping) or runtime_lineage.get(
                "source_commit"
            ) != self.source_commit:
                raise N5DataInventoryError(
                    "RC72_N5_DATA_SOURCE_COMMIT_MISMATCH:%s" % artifact_id
                )
            task_id = _required(artifact.get("producer_task_id"), "producer_task_id")
            task = self._one("rc7_task", task_id=task_id)
            if task.get("state") != "PASS":
                raise N5DataInventoryError(
                    "RC72_N5_DATA_N4_TASK_NOT_PASS:%s" % task_id
                )
            evaluation_id = _required(task.get("evaluation_id"), "evaluation_id")
            evaluation = self._one("rc7_evaluation", evaluation_id=evaluation_id)
            if evaluation.get("result") != "PASS" or artifact_id not in list(
                evaluation.get("artifact_refs") or []
            ):
                raise N5DataInventoryError(
                    "RC72_N5_DATA_N4_EVALUATION_NOT_PASS:%s" % evaluation_id
                )
            semantic = dict(durable.semantic_payload)
            if semantic.get("candidate_kind") != "TEST_DESIGN_CANDIDATE":
                raise N5DataInventoryError(
                    "RC72_N5_DATA_N4_CANDIDATE_KIND_INVALID:%s" % artifact_id
                )
            if list(semantic.get("candidate_unknowns") or []) or list(
                semantic.get("candidate_gaps") or []
            ):
                raise N5DataInventoryError(
                    "RC72_N5_DATA_N4_CANDIDATE_NOT_CLOSED:%s" % artifact_id
                )
            cases = semantic.get("cases")
            if not isinstance(cases, list) or not cases:
                raise N5DataInventoryError(
                    "RC72_N5_DATA_N4_CASE_SET_EMPTY:%s" % artifact_id
                )
            for case in cases:
                if not isinstance(case, Mapping):
                    raise N5DataInventoryError("RC72_N5_DATA_CASE_INVALID")
                case_id = _required(case.get("tc_id"), "case_id")
                if case_id in seen_cases:
                    raise N5DataInventoryError(
                        "RC72_N5_DATA_CASE_ID_DUPLICATE:%s" % case_id
                    )
                seen_cases.add(case_id)
                requirement_id = _required(case.get("requirement_id"), "requirement_id")
                sst_id = _required(case.get("sst_id"), "sst_id")
                obligation_id = _required(case.get("obligation_id"), "obligation_id")
                test_level = _required(case.get("layer"), "test_level")
                if case.get("release_batch_id") != release_batch_id:
                    raise N5DataInventoryError(
                        "RC72_N5_DATA_CASE_BATCH_MISMATCH:%s" % case_id
                    )
                relevant_n3 = n3_by_requirement.get(requirement_id, [])
                if not relevant_n3:
                    raise N5DataInventoryError(
                        "RC72_N5_DATA_N3_REQUIREMENT_CONSTRAINTS_REQUIRED:%s"
                        % requirement_id
                    )
                data_requirements = _strings(
                    case.get("data_requirements"), "case_data_requirements"
                )
                normalized_seen: Set[str] = set()
                for requirement_text in data_requirements:
                    normalized = _normalized_requirement(requirement_text)
                    if normalized in normalized_seen:
                        raise N5DataInventoryError(
                            "RC72_N5_DATA_CASE_REQUIREMENT_DUPLICATE:%s:%s"
                            % (case_id, normalized)
                        )
                    normalized_seen.add(normalized)
                    data_requirement_id = _stable_id(
                        "N5DATAREQ",
                        mission_id,
                        release_batch_id,
                        requirement_id,
                        sst_id,
                        obligation_id,
                        case_id,
                        normalized,
                    )
                    if data_requirement_id in seen_requirement_ids:
                        raise N5DataInventoryError(
                            "RC72_N5_DATA_REQUIREMENT_ID_DUPLICATE:%s"
                            % data_requirement_id
                        )
                    seen_requirement_ids.add(data_requirement_id)
                    rows.append(
                        {
                            "data_requirement_id": data_requirement_id,
                            "release_id": release_id,
                            "mission_id": mission_id,
                            "release_batch_id": release_batch_id,
                            "source_commit": self.source_commit,
                            "mission_node_id": str(n5["mission_node_id"]),
                            "requirement_id": requirement_id,
                            "sst_id": sst_id,
                            "obligation_id": obligation_id,
                            "case_id": case_id,
                            "test_level": test_level,
                            "requirement_text": requirement_text,
                            "normalized_requirement": normalized,
                            "source_case_sha256": _canonical_sha256(dict(case)),
                            "source_n4_artifact_id": artifact_id,
                            "source_n4_evaluation_id": evaluation_id,
                            "source_n4_delivery_id": str(n4_delivery["delivery_id"]),
                            "source_n4_gate_id": str(n4_gate["gate_id"]),
                            "source_n3_delivery_id": str(n3_delivery["delivery_id"]),
                            "source_n3_gate_id": str(n3_gate["gate_id"]),
                            "source_n3_artifact_refs": list(relevant_n3),
                            "case_preconditions": _strings(
                                case.get("preconditions"), "case_preconditions"
                            ),
                            "case_code_trace": _strings(
                                case.get("code_trace"), "case_code_trace"
                            ),
                            "case_evidence_requirements": _strings(
                                case.get("evidence_requirements"),
                                "case_evidence_requirements",
                            ),
                            "case_action_semantics": dict(
                                case.get("action_semantics") or {}
                            ),
                            "status": _STATUS,
                        }
                    )
        if not rows or not seen_cases:
            raise N5DataInventoryError("RC72_N5_DATA_INVENTORY_EMPTY")
        rows = sorted(
            rows,
            key=lambda row: (
                row["requirement_id"],
                row["sst_id"],
                row["case_id"],
                row["data_requirement_id"],
            ),
        )
        signature = [
            str(n4_delivery["delivery_id"]),
            str(n4_gate["gate_id"]),
            str(n3_delivery["delivery_id"]),
            str(n3_gate["gate_id"]),
        ] + [
            "%s=%s" % (row["data_requirement_id"], row["source_case_sha256"])
            for row in rows
        ]
        snapshot_id = _stable_id(
            "N5DATASNAP", mission_id, release_batch_id, self.source_commit, *signature
        )
        snapshot = {
            "snapshot_id": snapshot_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "mission_node_id": str(n5["mission_node_id"]),
            "source_n4_delivery_id": str(n4_delivery["delivery_id"]),
            "source_n4_gate_id": str(n4_gate["gate_id"]),
            "source_n3_delivery_id": str(n3_delivery["delivery_id"]),
            "source_n3_gate_id": str(n3_gate["gate_id"]),
            "source_n4_artifact_refs": list(n4_artifact_refs),
            "source_n3_artifact_refs": list(n3_refs),
            "data_requirement_ids": [row["data_requirement_id"] for row in rows],
            "case_ids": sorted(seen_cases),
            "case_count": len(seen_cases),
            "data_requirement_count": len(rows),
            "status": _SNAPSHOT_STATUS,
        }
        return batch, n5, n6, rows, snapshot

    @staticmethod
    def _requirement_signature(row: Mapping[str, Any]) -> Dict[str, Any]:
        names = (
            "release_id",
            "mission_id",
            "release_batch_id",
            "source_commit",
            "mission_node_id",
            "requirement_id",
            "sst_id",
            "obligation_id",
            "case_id",
            "test_level",
            "requirement_text",
            "normalized_requirement",
            "source_case_sha256",
            "source_n4_artifact_id",
            "source_n4_evaluation_id",
            "source_n4_delivery_id",
            "source_n4_gate_id",
            "source_n3_delivery_id",
            "source_n3_gate_id",
            "status",
        )
        result = {name: row.get(name) for name in names}
        for name in (
            "source_n3_artifact_refs",
            "case_preconditions",
            "case_code_trace",
            "case_evidence_requirements",
        ):
            result[name] = list(row.get(name) or [])
        result["case_action_semantics"] = dict(row.get("case_action_semantics") or {})
        return result

    @staticmethod
    def _snapshot_signature(row: Mapping[str, Any]) -> Dict[str, Any]:
        names = (
            "release_id",
            "mission_id",
            "release_batch_id",
            "source_commit",
            "mission_node_id",
            "source_n4_delivery_id",
            "source_n4_gate_id",
            "source_n3_delivery_id",
            "source_n3_gate_id",
            "case_count",
            "data_requirement_count",
            "status",
        )
        result = {name: row.get(name) for name in names}
        for name in (
            "source_n4_artifact_refs",
            "source_n3_artifact_refs",
            "data_requirement_ids",
            "case_ids",
        ):
            result[name] = list(row.get(name) or [])
        return result

    def materialize(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, n5, n6, expected_rows, expected_snapshot = self._expected(
            release_batch_id=release_batch_id
        )
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        existing_requirements = self.truth.query(
            _REQUIREMENT_ARTIFACT, release_batch_id=release_batch_id
        )
        existing_snapshots = self.truth.query(
            _SNAPSHOT_ARTIFACT, release_batch_id=release_batch_id
        )
        if existing_requirements or existing_snapshots:
            if (
                len(existing_requirements) != len(expected_rows)
                or len(existing_snapshots) != 1
            ):
                raise N5DataInventoryError("RC72_N5_DATA_EXISTING_SET_INCOMPLETE")
            by_id = {
                str(row["data_requirement_id"]): row
                for row in existing_requirements
            }
            for expected in expected_rows:
                current = by_id.get(str(expected["data_requirement_id"]))
                if current is None or self._requirement_signature(
                    current
                ) != self._requirement_signature(expected):
                    raise N5DataInventoryError(
                        "RC72_N5_DATA_EXISTING_REQUIREMENT_CONFLICT"
                    )
            if self._snapshot_signature(
                existing_snapshots[0]
            ) != self._snapshot_signature(expected_snapshot):
                raise N5DataInventoryError(
                    "RC72_N5_DATA_EXISTING_SNAPSHOT_CONFLICT"
                )
            if n5.get("state") == MissionNodeState.READY.value:
                RC72StateMachine(self.truth, release_id=release_id).transition_state(
                    str(n5["mission_node_id"]),
                    MissionNodeState.RUNNING,
                    reason="canonical N5 Case data-requirement inventory rehydrated",
                )
            elif n5.get("state") != MissionNodeState.RUNNING.value:
                raise N5DataInventoryError(
                    "RC72_N5_DATA_EXISTING_SET_NODE_STATE_INVALID:%s"
                    % str(n5.get("state") or "UNKNOWN")
                )
            current_n6 = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )
            if current_n6.get("state") != MissionNodeState.NOT_STARTED.value:
                raise N5DataInventoryError(
                    "RC72_N5_DATA_REPLAY_CANNOT_RELEASE_N6"
                )
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "mission_node_id": str(n5["mission_node_id"]),
                "node_state": MissionNodeState.RUNNING.value,
                "snapshot_id": str(expected_snapshot["snapshot_id"]),
                "case_count": int(expected_snapshot["case_count"]),
                "data_requirement_count": int(
                    expected_snapshot["data_requirement_count"]
                ),
                "data_requirement_ids": list(
                    expected_snapshot["data_requirement_ids"]
                ),
                "n6_state": MissionNodeState.NOT_STARTED.value,
            }

        if n5.get("state") != MissionNodeState.READY.value:
            raise N5DataInventoryError(
                "RC72_N5_DATA_FIRST_MATERIALIZATION_REQUIRES_READY:%s"
                % str(n5.get("state") or "UNKNOWN")
            )
        if n6.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N5DataInventoryError("RC72_N5_DATA_FIRST_MATERIALIZATION_N6_LOCK_REQUIRED")

        now = _now()
        for expected in expected_rows:
            payload = dict(expected)
            payload.update(
                {"created_at": now, "updated_at": now, "artifact_version": 1}
            )
            self.truth.append_atomic(_REQUIREMENT_EVENT, payload)
        snapshot_payload = dict(expected_snapshot)
        snapshot_payload.update(
            {"created_at": now, "updated_at": now, "artifact_version": 1}
        )
        self.truth.append_atomic(_SNAPSHOT_EVENT, snapshot_payload)

        persisted_requirements = self.truth.query(
            _REQUIREMENT_ARTIFACT, release_batch_id=release_batch_id
        )
        persisted_snapshots = self.truth.query(
            _SNAPSHOT_ARTIFACT, release_batch_id=release_batch_id
        )
        if (
            len(persisted_requirements) != len(expected_rows)
            or len(persisted_snapshots) != 1
        ):
            raise N5DataInventoryError("RC72_N5_DATA_PERSISTENCE_FAILED")
        RC72StateMachine(self.truth, release_id=release_id).transition_state(
            str(n5["mission_node_id"]),
            MissionNodeState.RUNNING,
            reason="canonical N5 Case data-requirement inventory materialized",
        )
        current_n6 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if current_n6.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N5DataInventoryError("RC72_N5_DATA_MATERIALIZATION_RELEASED_N6")
        return {
            "status": "MATERIALIZED",
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "mission_node_id": str(n5["mission_node_id"]),
            "node_state": MissionNodeState.RUNNING.value,
            "snapshot_id": str(expected_snapshot["snapshot_id"]),
            "case_count": int(expected_snapshot["case_count"]),
            "data_requirement_count": int(expected_snapshot["data_requirement_count"]),
            "data_requirement_ids": list(expected_snapshot["data_requirement_ids"]),
            "n6_state": MissionNodeState.NOT_STARTED.value,
        }


install_rc72_n5_data_inventory_overlay()

__all__ = [
    "N5DataInventoryError",
    "N5DataRequirementInventoryService",
    "install_rc72_n5_data_inventory_overlay",
    "validate_rc72_n5_data_inventory_snapshot",
    "validate_rc72_n5_data_requirement",
]
