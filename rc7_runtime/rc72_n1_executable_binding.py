"""Canonical RC7.2 N1 executable-runtime binding truth.

This module does not discover or guess routes.  It only promotes an explicitly
verified executable binding that already exists inside the hash-anchored N1 DSH
candidate after the canonical N1 NodeGate has PASSed.

The resulting artifact is intended to be consumed by N6 using an exact
``binding_key``.  Missing, ambiguous, unverified, or lineage-mismatched bindings
fail closed and remain an N1 gap.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_domain import AutonomousMissionNode, MissionNodeState, NodeGateDecision
from .rc72_n1_completion import N1DeliveryGateService, install_rc72_n1_completion_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_NODE = AutonomousMissionNode.N1_REALITY
_ARTIFACT = "rc72_n1_executable_binding"
_EVENT = "RC72_N1_EXECUTABLE_BINDING_UPSERTED"
_BUCKET = "rc72_n1_executable_bindings"
_SCHEMA_VERSION = "rc7.2-n1-executable-binding-v1"


class N1ExecutableBindingError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N1ExecutableBindingError("RC72_N1_EXEC_BIND_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise N1ExecutableBindingError(
            "RC72_N1_EXEC_BIND_%s_OBJECT_REQUIRED" % name.upper()
        )
    return dict(value)


def _verified_route(
    value: Any,
    *,
    name: str,
    value_keys: Sequence[str],
) -> Dict[str, Any]:
    item = _mapping(value, name)
    if item.get("verified") is not True:
        raise N1ExecutableBindingError(
            "RC72_N1_EXEC_BIND_%s_NOT_VERIFIED" % name.upper()
        )
    _required(item.get("source_ref"), "%s_source_ref" % name)
    if not any(
        isinstance(item.get(key), str) and item.get(key).strip()
        for key in value_keys
    ):
        raise N1ExecutableBindingError(
            "RC72_N1_EXEC_BIND_%s_VALUE_REQUIRED" % name.upper()
        )
    return item


def _ready_items(value: Any, name: str) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise N1ExecutableBindingError(
            "RC72_N1_EXEC_BIND_%s_REQUIRED" % name.upper()
        )
    out: List[Dict[str, Any]] = []
    for index, raw in enumerate(value):
        item = _mapping(raw, "%s_%d" % (name, index))
        _required(item.get("name"), "%s_%d_name" % (name, index))
        if str(item.get("status") or "").upper() != "READY":
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_%s_%d_NOT_READY" % (name.upper(), index)
            )
        _required(item.get("source_ref"), "%s_%d_source_ref" % (name, index))
        out.append(item)
    return out


def _uniq(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def validate_rc72_n1_executable_binding(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "binding_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "source_commit",
        "binding_key",
        "schema_version",
        "source_n1_artifact_id",
        "source_n1_delivery_id",
        "source_n1_gate_id",
        "source_raw_sha256",
        "binding_sha256",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["schema_version"] != _SCHEMA_VERSION:
        raise _contracts.DomainValidationError("RC72_N1_EXEC_BIND_SCHEMA_INVALID")
    if out.get("verified") is not True:
        raise _contracts.DomainValidationError("RC72_N1_EXEC_BIND_VERIFIED_REQUIRED")
    if not out["source_raw_sha256"].startswith("sha256:") or len(out["source_raw_sha256"]) != 71:
        raise _contracts.DomainValidationError("RC72_N1_EXEC_BIND_SOURCE_SHA_INVALID")
    digest = out["binding_sha256"].lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise _contracts.DomainValidationError("RC72_N1_EXEC_BIND_SHA256_INVALID")
    for name in ("environment", "endpoint", "tool_route", "request"):
        if not isinstance(out.get(name), dict) or not out[name]:
            raise _contracts.DomainValidationError(
                "RC72_N1_EXEC_BIND_%s_OBJECT_REQUIRED" % name.upper()
            )
    for name in ("capabilities", "resources", "authoritative_sources"):
        if not isinstance(out.get(name), list) or not out[name]:
            raise _contracts.DomainValidationError(
                "RC72_N1_EXEC_BIND_%s_REQUIRED" % name.upper()
            )
    for forbidden in (
        "cleanup",
        "data_ref",
        "data_refs",
        "data_lease_id",
        "execution_result",
        "n6_pass",
        "n7_pass",
        "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N1_EXEC_BIND_PREMATURE_CLAIM_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N1_EXEC_BIND_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n1_executable_binding_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n1_completion_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n1_executable_binding
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "binding_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "binding_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is not None and not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N1ExecutableBindingService:
    """Promote one exact verified N1 runtime binding into canonical R1 truth."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n1_executable_binding_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.n1 = N1DeliveryGateService(truth, source_commit=self.source_commit)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_TRUTH_NOT_UNIQUE:%s:%d" % (
                    artifact_type,
                    len(rows),
                )
            )
        return rows[0]

    def _passed_n1(self, release_batch_id: str):
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        node = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type=_NODE.value,
        )
        if node.get("state") != MissionNodeState.PASS.value:
            raise N1ExecutableBindingError("RC72_N1_EXEC_BIND_N1_NOT_PASS")
        version = node.get("active_delivery_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_ACTIVE_DELIVERY_REQUIRED"
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
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_ACTIVE_DELIVERY_NOT_UNIQUE"
            )
        delivery = deliveries[0]
        gates = [
            row
            for row in self.truth.query(
                "rc72_node_gate", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("delivery_id") == delivery.get("delivery_id")
            and row.get("gate_id") in list(node.get("gate_refs") or [])
            and row.get("decision") == NodeGateDecision.PASS.value
            and not list(row.get("failed") or [])
        ]
        if len(gates) != 1:
            raise N1ExecutableBindingError("RC72_N1_EXEC_BIND_PASS_GATE_NOT_UNIQUE")
        artifact_refs = list(delivery.get("artifact_refs") or [])
        if len(artifact_refs) != 1:
            raise N1ExecutableBindingError("RC72_N1_EXEC_BIND_N1_ARTIFACT_REQUIRED")
        artifact = self._one("rc7_artifact", artifact_id=str(artifact_refs[0]))
        if artifact.get("artifact_type_name") != "N1_REALITY_CANDIDATE":
            raise N1ExecutableBindingError("RC72_N1_EXEC_BIND_N1_ARTIFACT_TYPE_INVALID")
        return batch, node, delivery, gates[0], artifact

    def _anchored_candidate(
        self,
        release_batch_id: str,
        artifact: Mapping[str, Any],
    ) -> Dict[str, Any]:
        attempt = self.n1._attempt(release_batch_id)
        anchor = self.n1._anchor(attempt)
        candidate, content_ref, raw_hash, _calls = self.n1._raw_candidate(attempt, anchor)
        if (
            artifact.get("content_ref") != content_ref
            or artifact.get("content_hash") != raw_hash
            or anchor.get("raw_output_sha256") != raw_hash
        ):
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_ANCHORED_SOURCE_MISMATCH"
            )
        return candidate

    def _normalize(
        self,
        raw: Mapping[str, Any],
        *,
        release_id: str,
        mission_id: str,
        release_batch_id: str,
        binding_key: str,
    ) -> Dict[str, Any]:
        if raw.get("verified") is not True:
            raise N1ExecutableBindingError("RC72_N1_EXEC_BIND_NOT_VERIFIED")
        for field, expected in (
            ("release_id", release_id),
            ("mission_id", mission_id),
            ("release_batch_id", release_batch_id),
            ("source_commit", self.source_commit),
            ("binding_key", binding_key),
        ):
            if _required(raw.get(field), field) != expected:
                raise N1ExecutableBindingError(
                    "RC72_N1_EXEC_BIND_%s_MISMATCH" % field.upper()
                )

        environment = _mapping(raw.get("environment"), "environment")
        _required(environment.get("name"), "environment_name")
        if str(environment.get("status") or "").upper() != "READY":
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_ENVIRONMENT_NOT_READY"
            )
        _required(environment.get("source_ref"), "environment_source_ref")

        endpoint = _verified_route(
            raw.get("endpoint"),
            name="endpoint",
            value_keys=("url", "endpoint", "path"),
        )
        tool_route = _verified_route(
            raw.get("tool_route"),
            name="tool_route",
            value_keys=("tool", "name", "route"),
        )

        request = _mapping(raw.get("request"), "request")
        _required(request.get("source_ref"), "request_source_ref")
        if not any(
            isinstance(request.get(key), str) and request.get(key).strip()
            for key in ("schema_ref", "schema", "contract_ref")
        ):
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_REQUEST_SCHEMA_REQUIRED"
            )
        if "method" in request:
            _required(request.get("method"), "request_method")

        capabilities = _ready_items(raw.get("capabilities"), "capabilities")
        resources = _ready_items(raw.get("resources"), "resources")

        declared_sources = raw.get("authoritative_sources")
        if not isinstance(declared_sources, list) or not declared_sources:
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_AUTHORITATIVE_SOURCES_REQUIRED"
            )
        sources = []
        for value in declared_sources:
            sources.append(_required(value, "authoritative_source"))
        sources.extend(
            [
                _required(environment.get("source_ref"), "environment_source_ref"),
                _required(endpoint.get("source_ref"), "endpoint_source_ref"),
                _required(tool_route.get("source_ref"), "tool_route_source_ref"),
                _required(request.get("source_ref"), "request_source_ref"),
            ]
        )
        sources.extend(_required(item.get("source_ref"), "capability_source_ref") for item in capabilities)
        sources.extend(_required(item.get("source_ref"), "resource_source_ref") for item in resources)

        return {
            "schema_version": _SCHEMA_VERSION,
            "verified": True,
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "binding_key": binding_key,
            "environment": environment,
            "endpoint": endpoint,
            "tool_route": tool_route,
            "request": request,
            "capabilities": capabilities,
            "resources": resources,
            "authoritative_sources": _uniq(sources),
        }

    def canonicalize(
        self,
        *,
        release_batch_id: str,
        binding_key: str,
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        binding_key = _required(binding_key, "binding_key")
        batch, _node, delivery, gate, artifact = self._passed_n1(release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        candidate = self._anchored_candidate(release_batch_id, artifact)
        facts = candidate.get("facts")
        if not isinstance(facts, Mapping):
            raise N1ExecutableBindingError("RC72_N1_EXEC_BIND_FACTS_REQUIRED")
        bindings = facts.get("executable_bindings")
        if not isinstance(bindings, list) or not bindings:
            raise N1ExecutableBindingError("RC72_N1_EXEC_BIND_BINDINGS_REQUIRED")
        exact = [
            item
            for item in bindings
            if isinstance(item, Mapping) and item.get("binding_key") == binding_key
        ]
        if len(exact) != 1:
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_EXACT_BINDING_REQUIRED:%d" % len(exact)
            )
        semantic = self._normalize(
            exact[0],
            release_id=release_id,
            mission_id=mission_id,
            release_batch_id=release_batch_id,
            binding_key=binding_key,
        )
        digest = _canonical_hash(semantic)
        binding_id = _stable_id(
            "N1XBIND",
            release_batch_id,
            binding_key,
            str(artifact["content_hash"]),
            digest,
        )
        expected = dict(semantic)
        expected.update(
            {
                "binding_id": binding_id,
                "source_n1_artifact_id": str(artifact["artifact_id"]),
                "source_n1_delivery_id": str(delivery["delivery_id"]),
                "source_n1_gate_id": str(gate["gate_id"]),
                "source_raw_sha256": str(artifact["content_hash"]),
                "binding_sha256": digest,
                "artifact_version": 1,
            }
        )
        current = self.truth.query(_ARTIFACT, binding_id=binding_id)
        if current:
            if len(current) != 1:
                raise N1ExecutableBindingError(
                    "RC72_N1_EXEC_BIND_EXISTING_NOT_UNIQUE"
                )
            for key, value in expected.items():
                if current[0].get(key) != value:
                    raise N1ExecutableBindingError(
                        "RC72_N1_EXEC_BIND_EXISTING_CONFLICT:%s" % key
                    )
            return dict(current[0])
        self.truth.append_atomic(_EVENT, expected)
        rows = self.truth.query(_ARTIFACT, binding_id=binding_id)
        if len(rows) != 1:
            raise N1ExecutableBindingError(
                "RC72_N1_EXEC_BIND_PERSISTENCE_FAILED"
            )
        return rows[0]


install_rc72_n1_executable_binding_overlay()

__all__ = [
    "N1ExecutableBindingError",
    "N1ExecutableBindingService",
    "install_rc72_n1_executable_binding_overlay",
    "validate_rc72_n1_executable_binding",
]
