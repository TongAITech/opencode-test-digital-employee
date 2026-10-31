"""RC7.2 N5 explicit DataRequirement -> DataRef binding and resolver.

A release data resource is not automatically evidence that it satisfies a Test
Case.  Reusing one requires an exact, evidence-backed binding to the canonical
N5 DataRequirement.  This module makes that trust boundary explicit and keeps
resolution deterministic:

* exactly one current verified binding -> REUSE_VERIFIED;
* no binding -> DISCOVERY_REQUIRED;
* multiple current verified bindings -> fail closed (never choose one);
* unverified/stale/mismatched resources or evidence -> fail closed.

This slice does not construct data, reserve it, PASS N5, or release N6.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_data_resources import install_rc72_data_overlay
from .rc72_n5_data_inventory import install_rc72_n5_data_inventory_overlay
from .truth_overlay import install_rc7_truth_overlay


_BINDING_ARTIFACT = "rc72_n5_data_binding"
_BINDING_EVENT = "RC72_N5_DATA_BINDING_UPSERTED"
_BINDING_BUCKET = "rc72_n5_data_bindings"
_PLAN_ARTIFACT = "rc72_n5_data_resolution_plan"
_PLAN_EVENT = "RC72_N5_DATA_RESOLUTION_PLAN_UPSERTED"
_PLAN_BUCKET = "rc72_n5_data_resolution_plans"
_BINDING_STATUS = "VERIFIED"
_PLAN_STATUSES = {"DISCOVERY_REQUIRED", "REUSE_VERIFIED"}
_STRATEGIES = {"DISCOVER_EXISTING", "CONSTRUCT_NEW"}
_RESERVATION_MODES = {"SHARED_READ", "EXCLUSIVE_WRITE"}
_INSTALLED = False


class N5DataResolutionError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataResolutionError("RC72_N5_RESOLUTION_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _validate_string_list(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if not isinstance(value, list) or not value:
        raise _contracts.DomainValidationError(
            "RC72_N5_RESOLUTION_%s_REQUIRED" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N5_RESOLUTION_%s_INVALID" % name.upper()
        )
    if len(value) != len(set(value)):
        raise _contracts.DomainValidationError(
            "RC72_N5_RESOLUTION_%s_DUPLICATE" % name.upper()
        )


def validate_rc72_n5_data_binding(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "binding_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "source_commit",
        "data_requirement_id",
        "source_case_sha256",
        "data_ref",
        "strategy",
        "source_or_constructor",
        "verification",
        "validity_window",
        "cleanup_policy",
        "reservation_mode",
        "resource_metadata_ref",
        "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["status"] != _BINDING_STATUS:
        raise _contracts.DomainValidationError("RC72_N5_DATA_BINDING_STATUS_INVALID")
    if out["strategy"] not in _STRATEGIES:
        raise _contracts.DomainValidationError("RC72_N5_DATA_BINDING_STRATEGY_INVALID")
    if out["reservation_mode"] not in _RESERVATION_MODES:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_BINDING_RESERVATION_MODE_INVALID"
        )
    if not out["source_case_sha256"].startswith("sha256:"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_BINDING_CASE_HASH_INVALID"
        )
    _validate_string_list(out, "verification_evidence_refs")
    _validate_string_list(out, "precondition_refs")
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_BINDING_%s_INVALID" % name.upper()
            )
    for forbidden in (
        "data_lease_id",
        "reservation_owner",
        "reserved",
        "n5_pass",
        "n6_ready",
        "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_BINDING_PREMATURE_CLAIM_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_BINDING_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _BINDING_ARTIFACT
    return out


def validate_rc72_n5_data_resolution_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "plan_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "source_commit",
        "data_requirement_id",
        "source_case_sha256",
        "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["status"] not in _PLAN_STATUSES:
        raise _contracts.DomainValidationError("RC72_N5_DATA_PLAN_STATUS_INVALID")
    if not out["source_case_sha256"].startswith("sha256:"):
        raise _contracts.DomainValidationError("RC72_N5_DATA_PLAN_CASE_HASH_INVALID")
    binding_id = out.get("binding_id")
    data_ref = out.get("data_ref")
    if out["status"] == "REUSE_VERIFIED":
        if not isinstance(binding_id, str) or not binding_id.strip():
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_PLAN_BINDING_REQUIRED"
            )
        if not isinstance(data_ref, str) or not data_ref.strip():
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_PLAN_DATA_REF_REQUIRED"
            )
    else:
        if binding_id not in (None, "") or data_ref not in (None, ""):
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_PLAN_DISCOVERY_CANNOT_GUESS_DATA_REF"
            )
        out["binding_id"] = None
        out["data_ref"] = None
    for forbidden in (
        "reserved",
        "data_lease_id",
        "n5_pass",
        "n6_ready",
        "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_PLAN_PREMATURE_CLAIM_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N5_DATA_PLAN_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DATA_PLAN_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _PLAN_ARTIFACT
    return out


def install_rc72_n5_data_resolution_overlay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    install_rc7_truth_overlay()
    install_rc72_n5_data_inventory_overlay()
    install_rc72_data_overlay()
    _contracts.VALIDATORS[_BINDING_ARTIFACT] = validate_rc72_n5_data_binding
    _truth.BUCKETS[_BINDING_ARTIFACT] = _BINDING_BUCKET
    _truth.IDENTITY_FIELDS[_BINDING_ARTIFACT] = "binding_id"
    _truth.EVENT_TYPES[_BINDING_EVENT] = (_BINDING_ARTIFACT, "binding_id")
    _contracts.VALIDATORS[_PLAN_ARTIFACT] = validate_rc72_n5_data_resolution_plan
    _truth.BUCKETS[_PLAN_ARTIFACT] = _PLAN_BUCKET
    _truth.IDENTITY_FIELDS[_PLAN_ARTIFACT] = "plan_id"
    _truth.EVENT_TYPES[_PLAN_EVENT] = (_PLAN_ARTIFACT, "plan_id")
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


class N5DataResolutionService:
    """Register verified exact bindings and deterministically plan reuse/discovery."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        source_commit: str,
    ) -> None:
        install_rc72_n5_data_resolution_overlay()
        _ensure_bucket(truth, _BINDING_BUCKET, _BINDING_ARTIFACT)
        _ensure_bucket(truth, _PLAN_BUCKET, _PLAN_ARTIFACT)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.source_commit = _required(source_commit, "source_commit")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _requirement(self, data_requirement_id: str) -> Dict[str, Any]:
        row = self._one(
            "rc72_n5_data_requirement", data_requirement_id=data_requirement_id
        )
        if row.get("release_id") != self.release_id:
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_REQUIREMENT_RELEASE_MISMATCH"
            )
        if row.get("source_commit") != self.source_commit:
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_REQUIREMENT_SOURCE_MISMATCH"
            )
        if row.get("status") != "UNRESOLVED":
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_REQUIREMENT_STATE_INVALID"
            )
        return row

    def _canonical_evidence(
        self, mission_id: str, evidence_refs: Sequence[str]
    ) -> List[str]:
        refs: List[str] = []
        for evidence_ref in evidence_refs:
            ref = _required(evidence_ref, "verification_evidence_ref")
            if ref in refs:
                raise N5DataResolutionError(
                    "RC72_N5_RESOLUTION_VERIFICATION_EVIDENCE_DUPLICATE"
                )
            rows = self.truth.query("rc7_evidence", evidence_id=ref)
            if len(rows) != 1 or rows[0].get("mission_id") != mission_id:
                raise N5DataResolutionError(
                    "RC72_N5_RESOLUTION_VERIFICATION_EVIDENCE_NOT_CANONICAL:%s"
                    % ref
                )
            refs.append(ref)
        if not refs:
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_VERIFICATION_EVIDENCE_REQUIRED"
            )
        return refs

    def bind_verified(
        self,
        *,
        data_requirement_id: str,
        data_ref: str,
        strategy: str,
        source_or_constructor: str,
        verification: str,
        verification_evidence_refs: Sequence[str],
        precondition_refs: Sequence[str],
        validity_window: str,
        cleanup_policy: str,
    ) -> Dict[str, Any]:
        data_requirement_id = _required(data_requirement_id, "data_requirement_id")
        data_ref = _required(data_ref, "data_ref")
        strategy = _required(strategy, "strategy").upper()
        if strategy not in _STRATEGIES:
            raise N5DataResolutionError("RC72_N5_RESOLUTION_STRATEGY_INVALID")
        requirement = self._requirement(data_requirement_id)
        mission_id = str(requirement["mission_id"])
        resource = self._one("rc72_data_resource", data_ref=data_ref)
        if resource.get("release_id") != self.release_id:
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_RESOURCE_RELEASE_MISMATCH"
            )
        if resource.get("verified") is not True:
            raise N5DataResolutionError("RC72_N5_RESOLUTION_DATA_REF_NOT_VERIFIED")
        evidence_refs = self._canonical_evidence(
            mission_id, list(verification_evidence_refs)
        )
        preconditions = [
            _required(item, "precondition_ref") for item in list(precondition_refs)
        ]
        if not preconditions or len(preconditions) != len(set(preconditions)):
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_PRECONDITION_REFS_INVALID"
            )
        reservation_mode = (
            "EXCLUSIVE_WRITE" if resource.get("mutable") is True else "SHARED_READ"
        )
        binding_id = _stable_id(
            "N5DATABIND", mission_id, data_requirement_id, data_ref
        )
        expected = {
            "binding_id": binding_id,
            "release_id": self.release_id,
            "mission_id": mission_id,
            "release_batch_id": str(requirement["release_batch_id"]),
            "source_commit": self.source_commit,
            "data_requirement_id": data_requirement_id,
            "source_case_sha256": str(requirement["source_case_sha256"]),
            "data_ref": data_ref,
            "strategy": strategy,
            "source_or_constructor": _required(
                source_or_constructor, "source_or_constructor"
            ),
            "verification": _required(verification, "verification"),
            "verification_evidence_refs": evidence_refs,
            "precondition_refs": preconditions,
            "validity_window": _required(validity_window, "validity_window"),
            "cleanup_policy": _required(cleanup_policy, "cleanup_policy"),
            "reservation_mode": reservation_mode,
            "resource_metadata_ref": _required(
                resource.get("metadata_ref"), "resource_metadata_ref"
            ),
            "status": _BINDING_STATUS,
        }
        existing = self.truth.query(_BINDING_ARTIFACT, binding_id=binding_id)
        if existing:
            if len(existing) != 1:
                raise N5DataResolutionError(
                    "RC72_N5_RESOLUTION_BINDING_NOT_UNIQUE"
                )
            current = existing[0]
            for key, value in expected.items():
                if current.get(key) != value:
                    raise N5DataResolutionError(
                        "RC72_N5_RESOLUTION_EXISTING_BINDING_CONFLICT:%s" % key
                    )
            return {
                "status": "RESUMED",
                "binding_id": binding_id,
                "data_requirement_id": data_requirement_id,
                "data_ref": data_ref,
                "reservation_mode": reservation_mode,
            }
        now = _now()
        payload = dict(expected)
        payload.update(
            {"created_at": now, "updated_at": now, "artifact_version": 1}
        )
        self.truth.append_atomic(_BINDING_EVENT, payload)
        return {
            "status": "BOUND_VERIFIED",
            "binding_id": binding_id,
            "data_requirement_id": data_requirement_id,
            "data_ref": data_ref,
            "reservation_mode": reservation_mode,
        }

    def _validate_binding(
        self, requirement: Mapping[str, Any], binding: Mapping[str, Any]
    ) -> Dict[str, Any]:
        if binding.get("release_id") != self.release_id:
            raise N5DataResolutionError("RC72_N5_RESOLUTION_BINDING_RELEASE_MISMATCH")
        if binding.get("mission_id") != requirement.get("mission_id"):
            raise N5DataResolutionError("RC72_N5_RESOLUTION_BINDING_MISSION_MISMATCH")
        if binding.get("release_batch_id") != requirement.get("release_batch_id"):
            raise N5DataResolutionError("RC72_N5_RESOLUTION_BINDING_BATCH_MISMATCH")
        if binding.get("source_commit") != self.source_commit:
            raise N5DataResolutionError("RC72_N5_RESOLUTION_BINDING_SOURCE_MISMATCH")
        if binding.get("source_case_sha256") != requirement.get("source_case_sha256"):
            raise N5DataResolutionError("RC72_N5_RESOLUTION_BINDING_CASE_STALE")
        if binding.get("status") != _BINDING_STATUS:
            raise N5DataResolutionError("RC72_N5_RESOLUTION_BINDING_NOT_VERIFIED")
        resource = self._one("rc72_data_resource", data_ref=str(binding["data_ref"]))
        if resource.get("release_id") != self.release_id or resource.get("verified") is not True:
            raise N5DataResolutionError("RC72_N5_RESOLUTION_BOUND_RESOURCE_NOT_VERIFIED")
        expected_mode = (
            "EXCLUSIVE_WRITE" if resource.get("mutable") is True else "SHARED_READ"
        )
        if binding.get("reservation_mode") != expected_mode:
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_BINDING_RESERVATION_MODE_STALE"
            )
        self._canonical_evidence(
            str(requirement["mission_id"]),
            list(binding.get("verification_evidence_refs") or []),
        )
        return resource

    def _plan_payload(self, requirement: Mapping[str, Any]) -> Dict[str, Any]:
        data_requirement_id = str(requirement["data_requirement_id"])
        bindings = self.truth.query(
            _BINDING_ARTIFACT, data_requirement_id=data_requirement_id
        )
        verified = [row for row in bindings if row.get("status") == _BINDING_STATUS]
        if len(verified) > 1:
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_AMBIGUOUS_VERIFIED_BINDINGS:%s:%d"
                % (data_requirement_id, len(verified))
            )
        binding_id: Optional[str] = None
        data_ref: Optional[str] = None
        status = "DISCOVERY_REQUIRED"
        if verified:
            binding = verified[0]
            self._validate_binding(requirement, binding)
            binding_id = str(binding["binding_id"])
            data_ref = str(binding["data_ref"])
            status = "REUSE_VERIFIED"
        return {
            "plan_id": _stable_id(
                "N5DATAPLAN", str(requirement["mission_id"]), data_requirement_id
            ),
            "release_id": self.release_id,
            "mission_id": str(requirement["mission_id"]),
            "release_batch_id": str(requirement["release_batch_id"]),
            "source_commit": self.source_commit,
            "data_requirement_id": data_requirement_id,
            "source_case_sha256": str(requirement["source_case_sha256"]),
            "status": status,
            "binding_id": binding_id,
            "data_ref": data_ref,
        }

    @staticmethod
    def _plan_signature(row: Mapping[str, Any]) -> Tuple[Any, ...]:
        return tuple(
            row.get(name)
            for name in (
                "release_id",
                "mission_id",
                "release_batch_id",
                "source_commit",
                "data_requirement_id",
                "source_case_sha256",
                "status",
                "binding_id",
                "data_ref",
            )
        )

    def resolve_all(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        snapshots = self.truth.query(
            "rc72_n5_data_inventory_snapshot", release_batch_id=release_batch_id
        )
        if len(snapshots) != 1:
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_INVENTORY_SNAPSHOT_REQUIRED"
            )
        snapshot = snapshots[0]
        if snapshot.get("source_commit") != self.source_commit:
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_INVENTORY_SOURCE_MISMATCH"
            )
        mission_id = str(snapshot["mission_id"])
        n5 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type="N5_TEST_DATA"
        )
        n6 = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type="N6_EXECUTABLE_READINESS",
        )
        if n5.get("state") != "RUNNING":
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_N5_RUNNING_REQUIRED:%s"
                % str(n5.get("state") or "UNKNOWN")
            )
        if n6.get("state") != "NOT_STARTED":
            raise N5DataResolutionError("RC72_N5_RESOLUTION_N6_MUST_REMAIN_LOCKED")
        requirements = self.truth.query(
            "rc72_n5_data_requirement", release_batch_id=release_batch_id
        )
        expected_ids = list(snapshot.get("data_requirement_ids") or [])
        if not expected_ids or {
            str(row.get("data_requirement_id")) for row in requirements
        } != set(expected_ids):
            raise N5DataResolutionError(
                "RC72_N5_RESOLUTION_REQUIREMENT_DENOMINATOR_MISMATCH"
            )
        plans: List[Dict[str, Any]] = []
        for requirement in sorted(
            requirements, key=lambda row: str(row["data_requirement_id"])
        ):
            if requirement.get("source_commit") != self.source_commit:
                raise N5DataResolutionError(
                    "RC72_N5_RESOLUTION_REQUIREMENT_SOURCE_MISMATCH"
                )
            plan = self._plan_payload(requirement)
            current_rows = self.truth.query(_PLAN_ARTIFACT, plan_id=str(plan["plan_id"]))
            now = _now()
            if current_rows:
                if len(current_rows) != 1:
                    raise N5DataResolutionError(
                        "RC72_N5_RESOLUTION_PLAN_NOT_UNIQUE"
                    )
                current = current_rows[0]
                if self._plan_signature(current) == self._plan_signature(plan):
                    plans.append(current)
                    continue
                payload = dict(plan)
                payload.update(
                    {
                        "created_at": int(current.get("created_at") or now),
                        "updated_at": now,
                        "artifact_version": int(current.get("artifact_version") or 1)
                        + 1,
                    }
                )
                self.truth.append_atomic(_PLAN_EVENT, payload)
                plans.append(
                    self._one(_PLAN_ARTIFACT, plan_id=str(plan["plan_id"]))
                )
                continue
            payload = dict(plan)
            payload.update(
                {"created_at": now, "updated_at": now, "artifact_version": 1}
            )
            self.truth.append_atomic(_PLAN_EVENT, payload)
            plans.append(self._one(_PLAN_ARTIFACT, plan_id=str(plan["plan_id"])))
        return {
            "status": "RESOLVED_DETERMINISTICALLY",
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "plan_count": len(plans),
            "reuse_verified_count": sum(
                1 for row in plans if row.get("status") == "REUSE_VERIFIED"
            ),
            "discovery_required_count": sum(
                1 for row in plans if row.get("status") == "DISCOVERY_REQUIRED"
            ),
            "plans": [
                {
                    "plan_id": str(row["plan_id"]),
                    "data_requirement_id": str(row["data_requirement_id"]),
                    "status": str(row["status"]),
                    "binding_id": row.get("binding_id"),
                    "data_ref": row.get("data_ref"),
                }
                for row in plans
            ],
            "n5_state": "RUNNING",
            "n6_state": "NOT_STARTED",
        }


install_rc72_n5_data_resolution_overlay()

__all__ = [
    "N5DataResolutionError",
    "N5DataResolutionService",
    "install_rc72_n5_data_resolution_overlay",
    "validate_rc72_n5_data_binding",
    "validate_rc72_n5_data_resolution_plan",
]
