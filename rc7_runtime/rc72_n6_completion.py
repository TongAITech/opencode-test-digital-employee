"""Canonical RC7.2 N6 delivery/gate around compiled ExecutableContracts.

N6 persists compiler output to R1, admits one NodeDelivery, independently
re-checks the persisted contracts, and only then releases N7.  It never creates
execution results or DataLeases; those belong to N7 consumers.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_domain import (
    AutonomousMissionNode, MissionNodeState, NodeDelivery, NodeGate, NodeGateDecision,
)
from .rc72_n6_executable_readiness import (
    EVENT_N6_EXECUTABLE_CONTRACT_COMPILED, N6_SCHEMA_VERSION, ExecutableContract,
)
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay

_NODE = AutonomousMissionNode.N6_EXECUTABLE_READINESS
_PARENT = AutonomousMissionNode.N5_TEST_DATA
_NEXT = AutonomousMissionNode.N7_EXECUTION
_ARTIFACT = "rc72_n6_executable_contract"
_BUCKET = "rc72_n6_executable_contracts"
_PRODUCER = "rc72-runtime-n6-contract-delivery"
_GATE_WORKER = "rc72-runtime-n6-gate"
_GATE_SESSION = "runtime://rc72/n6-gate/v1"
_CRITERIA = (
    "N6_PARENT_N5_PASS_LINEAGE",
    "N6_EXECUTABLE_CONTRACT_SET_NONEMPTY",
    "N6_EXECUTABLE_CONTRACT_SOURCE_CURRENT",
    "N6_EXECUTABLE_CONTRACT_DIGEST_VALID",
    "N6_EXECUTABLE_CONTRACT_LINEAGE_MATCH",
    "N6_RUNTIME_BINDINGS_RESOLVED",
    "N6_DATA_REFS_VERIFIED",
    "N6_DATA_REFS_CURRENT",
    "N6_PRECONDITIONS_STEPS_DEFINED",
    "N6_ASSERTIONS_ORACLES_DEFINED",
    "N6_EVIDENCE_REQUIREMENTS_DEFINED",
    "N6_AUTHORITATIVE_SOURCES_BOUND",
    "N6_NO_PREMATURE_DATA_LEASE",
)


class N6CompletionError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N6CompletionError("RC72_N6_COMPLETION_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _uniq(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _maps(value: Any) -> List[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _iso(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("timestamp is empty")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _semantic(row: Mapping[str, Any]) -> Dict[str, Any]:
    keys = (
        "schema_version", "release_batch_id", "mission_id", "requirement_id",
        "sst_id", "obligation_id", "case_id", "case_ref", "environment",
        "endpoint", "tool_route", "request", "input", "data_refs",
        "preconditions", "steps", "assertions", "oracles", "evidence_required",
        "cleanup", "capabilities", "resources", "authoritative_sources",
    )
    return {key: row.get(key) for key in keys}


def _digest(row: Mapping[str, Any]) -> str:
    raw = json.dumps(
        _semantic(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_rc72_n6_executable_contract(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "contract_id", "release_id", "source_commit", "schema_version",
        "release_batch_id", "mission_id", "requirement_id", "sst_id",
        "obligation_id", "case_id", "case_ref", "compiled_at", "contract_sha256",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["schema_version"] != N6_SCHEMA_VERSION:
        raise _contracts.DomainValidationError("RC72_N6_CONTRACT_SCHEMA_INVALID")
    digest = out["contract_sha256"].lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise _contracts.DomainValidationError("RC72_N6_CONTRACT_SHA256_INVALID")
    for name in ("environment", "endpoint", "tool_route", "request", "input", "cleanup"):
        if not isinstance(out.get(name), dict):
            raise _contracts.DomainValidationError("RC72_N6_CONTRACT_%s_OBJECT_REQUIRED" % name.upper())
    for name in (
        "data_refs", "preconditions", "steps", "assertions", "oracles",
        "evidence_required", "capabilities", "resources", "authoritative_sources",
    ):
        if not isinstance(out.get(name), list) or not out[name]:
            raise _contracts.DomainValidationError("RC72_N6_CONTRACT_%s_REQUIRED" % name.upper())
    for alias, legacy in (
        ("required_capabilities", "capabilities"),
        ("required_resources", "resources"),
    ):
        if alias in out and out.get(alias) != out.get(legacy):
            raise _contracts.DomainValidationError(
                "RC72_N6_CONTRACT_%s_MISMATCH" % alias.upper()
            )
    for name in ("data_lease_id", "data_leases", "execution_result", "actual_result", "n7_pass", "field_verified", "bank_final"):
        if name in out:
            raise _contracts.DomainValidationError("RC72_N6_CONTRACT_PREMATURE_CLAIM_FORBIDDEN:%s" % name)
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N6_CONTRACT_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n6_completion_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n6_executable_contract
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "contract_id"
    _truth.EVENT_TYPES[EVENT_N6_EXECUTABLE_CONTRACT_COMPILED] = (_ARTIFACT, "contract_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is not None and not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N6DeliveryGateService:
    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        source_commit: str,
        now: Optional[datetime] = None,
    ) -> None:
        install_rc72_n6_completion_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.source_commit = _required(source_commit, "source_commit")
        self._now_override = now

    def _now(self) -> datetime:
        current = self._now_override or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N6CompletionError(
                "RC72_N6_COMPLETION_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows))
            )
        return rows[0]

    def _context(self, release_batch_id: str):
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        if batch.get("release_id") != self.release_id:
            raise N6CompletionError("RC72_N6_COMPLETION_RELEASE_MISMATCH")
        mission_id = _required(batch.get("mission_id"), "mission_id")
        node = self._one("rc72_mission_node", mission_id=mission_id, node_type=_NODE.value)
        parent = self._one("rc72_mission_node", mission_id=mission_id, node_type=_PARENT.value)
        next_node = self._one("rc72_mission_node", mission_id=mission_id, node_type=_NEXT.value)
        if node.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N6CompletionError("RC72_N6_COMPLETION_NODE_SCOPE_MISMATCH")
        if parent.get("state") != MissionNodeState.PASS.value:
            raise N6CompletionError("RC72_N6_COMPLETION_PARENT_N5_NOT_PASS")
        version = parent.get("active_delivery_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise N6CompletionError("RC72_N6_COMPLETION_PARENT_N5_DELIVERY_REQUIRED")
        deliveries = [
            row for row in self.truth.query("rc72_node_delivery", mission_node_id=str(parent["mission_node_id"]))
            if row.get("version") == version and row.get("delivery_id") in list(parent.get("delivery_refs") or [])
        ]
        if len(deliveries) != 1:
            raise N6CompletionError("RC72_N6_COMPLETION_PARENT_N5_DELIVERY_NOT_UNIQUE")
        parent_delivery = deliveries[0]
        gates = [
            row for row in self.truth.query("rc72_node_gate", mission_node_id=str(parent["mission_node_id"]))
            if row.get("delivery_id") == parent_delivery.get("delivery_id")
            and row.get("gate_id") in list(parent.get("gate_refs") or [])
            and row.get("decision") == NodeGateDecision.PASS.value
            and not list(row.get("failed") or [])
        ]
        if len(gates) != 1:
            raise N6CompletionError("RC72_N6_COMPLETION_PARENT_N5_GATE_NOT_UNIQUE")
        if node.get("state") not in {"READY", "RUNNING", "REVIEW_PENDING", "PASS", "NEEDS_REVISION"}:
            raise N6CompletionError("RC72_N6_COMPLETION_NODE_STATE_INVALID:%s" % node.get("state"))
        if node.get("state") != "PASS" and next_node.get("state") != "NOT_STARTED":
            raise N6CompletionError("RC72_N6_COMPLETION_N7_PREMATURELY_RELEASED")
        return batch, node, next_node, parent_delivery, gates[0]

    def _persist(self, contract: ExecutableContract, *, batch_id: str, mission_id: str) -> str:
        if contract.release_batch_id != batch_id:
            raise N6CompletionError("RC72_N6_COMPLETION_CONTRACT_BATCH_MISMATCH")
        if contract.mission_id != mission_id:
            raise N6CompletionError("RC72_N6_COMPLETION_CONTRACT_MISSION_MISMATCH")
        contract_id = _stable_id("N6CONTRACT", mission_id, contract.case_id, contract.contract_sha256)
        expected = contract.to_payload()
        expected.pop("artifact_type", None)
        expected.update({
            "contract_id": contract_id,
            "release_id": self.release_id,
            "source_commit": self.source_commit,
            "artifact_version": 1,
        })
        current = self.truth.query(_ARTIFACT, contract_id=contract_id)
        if current:
            if len(current) != 1:
                raise N6CompletionError("RC72_N6_COMPLETION_CONTRACT_NOT_UNIQUE")
            for key, value in expected.items():
                current_value = current[0].get(key)
                if current_value is None and key == "required_capabilities":
                    current_value = current[0].get("capabilities")
                elif current_value is None and key == "required_resources":
                    current_value = current[0].get("resources")
                if current_value != value:
                    raise N6CompletionError("RC72_N6_COMPLETION_EXISTING_CONTRACT_CONFLICT:%s" % key)
            return contract_id
        self.truth.append_atomic(EVENT_N6_EXECUTABLE_CONTRACT_COMPILED, expected)
        return contract_id

    def admit_delivery(self, *, release_batch_id: str, contracts: Sequence[ExecutableContract]) -> Dict[str, Any]:
        batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, _next, parent_delivery, parent_gate = self._context(batch_id)
        mission_id = str(batch["mission_id"])
        values = list(contracts or ())
        if not values:
            raise N6CompletionError("RC72_N6_COMPLETION_CONTRACTS_REQUIRED")
        if not all(isinstance(item, ExecutableContract) for item in values):
            raise N6CompletionError("RC72_N6_COMPLETION_CONTRACT_TYPE_INVALID")
        if len({item.case_id for item in values}) != len(values):
            raise N6CompletionError("RC72_N6_COMPLETION_CASE_DUPLICATE")
        ids = [self._persist(item, batch_id=batch_id, mission_id=mission_id) for item in sorted(values, key=lambda item: item.case_id)]
        delivery_id = _stable_id("N6DEL", mission_id, batch_id, self.source_commit, ",".join(ids))
        existing = self.truth.query("rc72_node_delivery", delivery_id=delivery_id)
        if existing:
            if len(existing) != 1 or list(existing[0].get("artifact_refs") or []) != ids:
                raise N6CompletionError("RC72_N6_COMPLETION_DELIVERY_CONFLICT")
            return {"status": "RESUMED", "delivery_id": delivery_id, "contract_count": len(ids), "contract_ids": ids, "node_state": self._one("rc72_mission_node", mission_id=mission_id, node_type=_NODE.value)["state"]}
        runtime = RC72StateMachine(self.truth, release_id=self.release_id)
        if node.get("state") in {"READY", "NEEDS_REVISION"}:
            runtime.transition_state(str(node["mission_node_id"]), MissionNodeState.RUNNING, reason="compile canonical executable contracts")
            node = runtime.node(str(node["mission_node_id"]))
        if node.get("state") != "RUNNING":
            raise N6CompletionError("RC72_N6_COMPLETION_DELIVERY_REQUIRES_RUNNING_NODE:%s" % node.get("state"))
        previous = self.truth.query("rc72_node_delivery", mission_node_id=str(node["mission_node_id"]))
        version = max([int(row.get("version") or 0) for row in previous] + [0]) + 1
        rows = [self._one(_ARTIFACT, contract_id=value) for value in ids]
        inputs = _uniq(
            ["n5-delivery://%s" % parent_delivery["delivery_id"], "n5-gate://%s" % parent_gate["gate_id"]]
            + [str(row["case_ref"]) for row in rows]
            + [str(ref.get("data_ref")) for row in rows for ref in _maps(row.get("data_refs")) if ref.get("data_ref")]
            + [str(source) for row in rows for source in list(row.get("authoritative_sources") or []) if isinstance(source, str) and source]
        )
        runtime.submit_delivery(NodeDelivery(
            delivery_id=delivery_id, mission_id=mission_id,
            mission_node_id=str(node["mission_node_id"]), node_type=_NODE,
            version=version, producer_ref=_PRODUCER, input_refs=inputs,
            artifact_refs=ids, evidence_refs=[], known_gaps=[], created_by_workitems=[],
            sufficiency_score=1.0,
        ))
        return {"status": "DELIVERY_ADMITTED", "delivery_id": delivery_id, "delivery_version": version, "contract_count": len(ids), "contract_ids": ids, "node_state": "REVIEW_PENDING"}

    @staticmethod
    def _runtime_ok(row: Mapping[str, Any]) -> bool:
        environment = _map(row.get("environment"))
        endpoint, tool, request = _map(row.get("endpoint")), _map(row.get("tool_route")), _map(row.get("request"))
        return bool(
            environment.get("name")
            and environment.get("status") == "READY"
            and environment.get("source_ref")
            and endpoint.get("verified") is True and endpoint.get("source_ref")
            and (endpoint.get("url") or endpoint.get("endpoint") or endpoint.get("path"))
            and tool.get("verified") is True and tool.get("source_ref")
            and (tool.get("tool") or tool.get("name") or tool.get("route"))
            and request.get("source_ref") and (request.get("schema_ref") or request.get("schema") or request.get("contract_ref"))
            and _maps(row.get("capabilities")) and all(item.get("status") == "READY" and item.get("source_ref") for item in _maps(row.get("capabilities")))
            and _maps(row.get("resources")) and all(item.get("status") == "READY" and item.get("source_ref") for item in _maps(row.get("resources")))
        )

    def _data_ref_current(self, row: Mapping[str, Any], ref: Mapping[str, Any]) -> bool:
        if ref.get("resolved_ref_status") != "VERIFIED" or not ref.get("data_ref"):
            return False
        for key in ("release_batch_id", "mission_id", "requirement_id", "case_id"):
            if str(ref.get(key) or "") != str(row.get(key) or ""):
                return False
        expires_at = str(ref.get("expires_at") or "").strip()
        if expires_at:
            try:
                return _iso(expires_at) > self._now()
            except (TypeError, ValueError):
                return False
        validity_window = str(ref.get("validity_window") or "").strip()
        return bool(validity_window)

    def _criteria(self, *, mission_id: str, batch_id: str, delivery: Mapping[str, Any], parent_gate: Mapping[str, Any]) -> Dict[str, bool]:
        refs = list(delivery.get("artifact_refs") or [])
        rows = [row for ref in refs for row in self.truth.query(_ARTIFACT, contract_id=str(ref))]
        unique = bool(refs) and len(rows) == len(refs) and len({row.get("contract_id") for row in rows}) == len(refs)
        return {
            "N6_PARENT_N5_PASS_LINEAGE": parent_gate.get("decision") == "PASS" and not list(parent_gate.get("failed") or []),
            "N6_EXECUTABLE_CONTRACT_SET_NONEMPTY": unique,
            "N6_EXECUTABLE_CONTRACT_SOURCE_CURRENT": bool(rows) and all(row.get("source_commit") == self.source_commit for row in rows),
            "N6_EXECUTABLE_CONTRACT_DIGEST_VALID": bool(rows) and all(row.get("contract_sha256") == _digest(row) for row in rows),
            "N6_EXECUTABLE_CONTRACT_LINEAGE_MATCH": bool(rows) and all(row.get("release_id") == self.release_id and row.get("release_batch_id") == batch_id and row.get("mission_id") == mission_id and row.get("schema_version") == N6_SCHEMA_VERSION for row in rows),
            "N6_RUNTIME_BINDINGS_RESOLVED": bool(rows) and all(self._runtime_ok(row) for row in rows),
            "N6_DATA_REFS_VERIFIED": bool(rows) and all(_maps(row.get("data_refs")) and all(ref.get("resolved_ref_status") == "VERIFIED" and ref.get("data_ref") for ref in _maps(row.get("data_refs"))) for row in rows),
            "N6_DATA_REFS_CURRENT": bool(rows) and all(_maps(row.get("data_refs")) and all(self._data_ref_current(row, ref) for ref in _maps(row.get("data_refs"))) for row in rows),
            "N6_PRECONDITIONS_STEPS_DEFINED": bool(rows) and all(list(row.get("preconditions") or []) and list(row.get("steps") or []) for row in rows),
            "N6_ASSERTIONS_ORACLES_DEFINED": bool(rows) and all(list(row.get("assertions") or []) and list(row.get("oracles") or []) for row in rows),
            "N6_EVIDENCE_REQUIREMENTS_DEFINED": bool(rows) and all(list(row.get("evidence_required") or []) for row in rows),
            "N6_AUTHORITATIVE_SOURCES_BOUND": bool(rows) and all(list(row.get("authoritative_sources") or []) for row in rows),
            "N6_NO_PREMATURE_DATA_LEASE": bool(rows) and not self.truth.query("rc72_data_lease") and all(not any(key in row for key in ("data_lease_id", "data_leases", "execution_result", "actual_result")) for row in rows),
        }

    def apply_gate(self, *, release_batch_id: str) -> Dict[str, Any]:
        batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, next_node, _parent_delivery, parent_gate = self._context(batch_id)
        mission_id = str(batch["mission_id"])
        active = node.get("active_delivery_version")
        if isinstance(active, bool) or not isinstance(active, int) or active < 1:
            raise N6CompletionError("RC72_N6_COMPLETION_ACTIVE_DELIVERY_REQUIRED")
        deliveries = [row for row in self.truth.query("rc72_node_delivery", mission_node_id=str(node["mission_node_id"])) if row.get("version") == active and row.get("delivery_id") in list(node.get("delivery_refs") or [])]
        if len(deliveries) != 1:
            raise N6CompletionError("RC72_N6_COMPLETION_ACTIVE_DELIVERY_NOT_UNIQUE")
        delivery = deliveries[0]
        result = self._criteria(mission_id=mission_id, batch_id=batch_id, delivery=delivery, parent_gate=parent_gate)
        passed, failed = [name for name in _CRITERIA if result[name]], [name for name in _CRITERIA if not result[name]]
        decision = NodeGateDecision.PASS if not failed else NodeGateDecision.NEEDS_REVISION
        gate_id = _stable_id("N6GATE", str(delivery["delivery_id"]), self.source_commit, decision.value, ",".join(failed))
        runtime = RC72StateMachine(self.truth, release_id=self.release_id)
        existing = self.truth.query("rc72_node_gate", gate_id=gate_id)
        if existing:
            if len(existing) != 1:
                raise N6CompletionError("RC72_N6_COMPLETION_GATE_NOT_UNIQUE")
            current, current_next = runtime.node(str(node["mission_node_id"])), runtime.node_by_type(mission_id, _NEXT)
            if decision == NodeGateDecision.PASS and current_next.get("state") == "NOT_STARTED":
                runtime.forward(_NODE, _NEXT, source_gate_id=gate_id)
                current_next = runtime.node_by_type(mission_id, _NEXT)
            return {"status": "RESUMED", "gate_id": gate_id, "decision": decision.value, "passed": passed, "failed": failed, "n6_state": current["state"], "n7_state": current_next["state"]}
        if node.get("state") != "REVIEW_PENDING":
            raise N6CompletionError("RC72_N6_COMPLETION_GATE_REQUIRES_REVIEW_PENDING:%s" % node.get("state"))
        runtime.apply_gate(NodeGate(
            gate_id=gate_id, mission_id=mission_id,
            mission_node_id=str(node["mission_node_id"]), node_type=_NODE,
            delivery_id=str(delivery["delivery_id"]), decision=decision,
            reviewer_worker_id=_GATE_WORKER, reviewer_session_id=_GATE_SESSION,
            criteria=list(_CRITERIA), passed=passed, failed=failed,
            evidence_refs=list(delivery.get("evidence_refs") or []),
            return_node=_NODE if failed else None,
            reason="deterministic N6 executable-readiness %s" % ("satisfied" if not failed else "failed: " + ",".join(failed)),
        ))
        n7_state = runtime.node_by_type(mission_id, _NEXT)["state"]
        if decision == NodeGateDecision.PASS:
            if next_node.get("state") != "NOT_STARTED":
                raise N6CompletionError("RC72_N6_COMPLETION_N7_STATE_INVALID_BEFORE_FORWARD")
            runtime.forward(_NODE, _NEXT, source_gate_id=gate_id)
            n7_state = runtime.node_by_type(mission_id, _NEXT)["state"]
        return {"status": "GATE_APPLIED", "gate_id": gate_id, "decision": decision.value, "passed": passed, "failed": failed, "n6_state": runtime.node(str(node["mission_node_id"]))["state"], "n7_state": n7_state, "field_verified": False, "bank_final": False}

    def complete(self, *, release_batch_id: str, contracts: Sequence[ExecutableContract]) -> Dict[str, Any]:
        return {
            "delivery": self.admit_delivery(release_batch_id=release_batch_id, contracts=contracts),
            "gate": self.apply_gate(release_batch_id=release_batch_id),
        }


install_rc72_n6_completion_overlay()

__all__ = ["N6CompletionError", "N6DeliveryGateService", "install_rc72_n6_completion_overlay", "validate_rc72_n6_executable_contract"]
