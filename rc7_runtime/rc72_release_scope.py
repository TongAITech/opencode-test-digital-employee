"""RC7.2 ReleaseBatch scope denominator truth.

Observed Requirements/SSTs/Cases can never define their own denominator.  A
ReleaseScopeManifest freezes the expected Requirement -> SST -> required L1-L7
scope for one ReleaseBatch.  ScopeDenominatorSnapshot compares canonical
TestObligation truth with that manifest and fails closed on missing or extra
scope.  It intentionally does not judge execution PASS, defects or coverage.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .truth_overlay import install_rc7_truth_overlay


_SCOPE_MANIFEST = "rc72_release_scope_manifest"
_SCOPE_SNAPSHOT = "rc72_scope_denominator_snapshot"
_EVENT_TYPES = {
    "RC72_RELEASE_SCOPE_MANIFEST_UPSERTED": (_SCOPE_MANIFEST, "manifest_id"),
    "RC72_SCOPE_DENOMINATOR_SNAPSHOT_UPSERTED": (_SCOPE_SNAPSHOT, "snapshot_id"),
}
_BUCKETS = {
    _SCOPE_MANIFEST: "rc72_release_scope_manifests",
    _SCOPE_SNAPSHOT: "rc72_scope_denominator_snapshots",
}
_VALID_LEVELS = {"L1", "L2", "L3", "L4", "L5", "L6", "L7"}


def _now() -> int:
    return int(time.time())


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


@dataclass(frozen=True)
class ReleaseScopeManifest:
    manifest_id: str
    mission_id: str
    release_batch_id: str
    requirement_ssts: Dict[str, List[str]]
    required_levels_by_sst: Dict[str, List[str]]
    source_refs: List[str] = field(default_factory=list)
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in ("manifest_id", "mission_id", "release_batch_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError("%s_REQUIRED" % name.upper())
        if not isinstance(self.requirement_ssts, dict) or not self.requirement_ssts:
            raise ContractError("RELEASE_SCOPE_REQUIREMENT_SSTS_REQUIRED")
        if not isinstance(self.required_levels_by_sst, dict):
            raise ContractError("RELEASE_SCOPE_REQUIRED_LEVELS_INVALID")
        if not isinstance(self.source_refs, list) or not self.source_refs or not all(
            isinstance(ref, str) and ref.strip() for ref in self.source_refs
        ):
            raise ContractError("RELEASE_SCOPE_SOURCE_REFS_REQUIRED")


@dataclass(frozen=True)
class ScopeDenominatorSnapshot:
    snapshot_id: str
    manifest_id: str
    mission_id: str
    release_batch_id: str
    expected_requirement_count: int
    expected_sst_count: int
    expected_required_level_count: int
    missing_ssts: List[str]
    missing_required_levels: Dict[str, List[str]]
    out_of_scope_obligation_ids: List[str]
    denominator_complete: bool
    created_at: int = field(default_factory=_now)


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (identity, "mission_id", "release_batch_id", "release_id"):
        out[name] = _required(out, name)
    out["artifact_type"] = artifact_type
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def _validate_string_map_of_lists(value: Any, name: str) -> Dict[str, List[str]]:
    if not isinstance(value, dict) or not value:
        raise _contracts.DomainValidationError("%s_INVALID" % name)
    result: Dict[str, List[str]] = {}
    for key, items in value.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(items, list):
            raise _contracts.DomainValidationError("%s_INVALID" % name)
        if not all(isinstance(item, str) and item.strip() for item in items):
            raise _contracts.DomainValidationError("%s_INVALID" % name)
        result[key] = list(items)
    return result


def _validate_manifest(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _SCOPE_MANIFEST, "manifest_id")
    out["requirement_ssts"] = _validate_string_map_of_lists(out.get("requirement_ssts"), "RELEASE_SCOPE_REQUIREMENT_SSTS")
    out["required_levels_by_sst"] = _validate_string_map_of_lists(out.get("required_levels_by_sst"), "RELEASE_SCOPE_REQUIRED_LEVELS")
    _contracts._require_string_list(out, "source_refs")
    if not out["source_refs"]:
        raise _contracts.DomainValidationError("RELEASE_SCOPE_SOURCE_REFS_REQUIRED")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("RELEASE_SCOPE_CREATED_AT_INVALID")
    return out


def _validate_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _SCOPE_SNAPSHOT, "snapshot_id")
    out["manifest_id"] = _required(out, "manifest_id")
    for name in ("expected_requirement_count", "expected_sst_count", "expected_required_level_count"):
        if not isinstance(out.get(name), int) or out[name] < 0:
            raise _contracts.DomainValidationError("SCOPE_DENOMINATOR_%s_INVALID" % name.upper())
    _contracts._require_string_list(out, "missing_ssts")
    _contracts._require_string_list(out, "out_of_scope_obligation_ids")
    missing = out.get("missing_required_levels")
    if not isinstance(missing, dict):
        raise _contracts.DomainValidationError("SCOPE_DENOMINATOR_MISSING_LEVELS_INVALID")
    for sst, levels in missing.items():
        if not isinstance(sst, str) or not sst.strip() or not isinstance(levels, list) or not all(
            isinstance(level, str) and level in _VALID_LEVELS for level in levels
        ):
            raise _contracts.DomainValidationError("SCOPE_DENOMINATOR_MISSING_LEVELS_INVALID")
    if not isinstance(out.get("denominator_complete"), bool):
        raise _contracts.DomainValidationError("SCOPE_DENOMINATOR_COMPLETE_INVALID")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("SCOPE_DENOMINATOR_CREATED_AT_INVALID")
    return out


def install_rc72_release_scope_overlay() -> None:
    install_rc7_truth_overlay()
    validators = {
        _SCOPE_MANIFEST: _validate_manifest,
        _SCOPE_SNAPSHOT: _validate_snapshot,
    }
    for artifact_type, validator in validators.items():
        _contracts.VALIDATORS[artifact_type] = validator
        _truth.BUCKETS[artifact_type] = _BUCKETS[artifact_type]
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


def _ensure_projection_buckets(truth: TruthRuntime) -> None:
    for artifact_type, bucket in _BUCKETS.items():
        if not hasattr(truth.projection, bucket):
            setattr(truth.projection, bucket, {})
        truth.projection._versions.setdefault(artifact_type, {})


class ReleaseScopeService:
    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_release_scope_overlay()
        _ensure_projection_buckets(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("RELEASE_SCOPE_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()

    def install_overlay(self) -> None:
        install_rc72_release_scope_overlay()

    def _append(self, event_type: str, payload: Dict[str, Any]):
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, out)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("RELEASE_SCOPE_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    @staticmethod
    def _all_ssts(requirement_ssts: Mapping[str, List[str]]) -> List[str]:
        return [sst for requirement_id in sorted(requirement_ssts) for sst in requirement_ssts[requirement_id]]

    def persist_manifest(self, manifest: ReleaseScopeManifest) -> None:
        if self.truth.query(_SCOPE_MANIFEST, manifest_id=manifest.manifest_id):
            raise ContractError("RELEASE_SCOPE_MANIFEST_ALREADY_EXISTS")
        batch = self._one("rc72_release_batch", release_batch_id=manifest.release_batch_id)
        if batch.get("mission_id") != manifest.mission_id:
            raise ContractError("RELEASE_SCOPE_MISSION_MISMATCH")
        expected_requirements = set(batch.get("requirement_ids") or [])
        manifest_requirements = set(manifest.requirement_ssts)
        if manifest_requirements != expected_requirements:
            raise ContractError("RELEASE_SCOPE_REQUIREMENT_DENOMINATOR_MISMATCH")

        all_ssts = self._all_ssts(manifest.requirement_ssts)
        if not all_ssts or any(not isinstance(sst, str) or not sst.strip() for sst in all_ssts):
            raise ContractError("RELEASE_SCOPE_SST_DENOMINATOR_INVALID")
        if len(all_ssts) != len(set(all_ssts)):
            raise ContractError("RELEASE_SCOPE_SST_DUPLICATE_OWNERSHIP")
        if set(manifest.required_levels_by_sst) != set(all_ssts):
            raise ContractError("RELEASE_SCOPE_REQUIRED_LEVELS_INVALID")
        for levels in manifest.required_levels_by_sst.values():
            if not isinstance(levels, list) or not levels or any(
                not isinstance(level, str) or level.upper() not in _VALID_LEVELS for level in levels
            ):
                raise ContractError("RELEASE_SCOPE_REQUIRED_LEVELS_INVALID")
            if len({level.upper() for level in levels}) != len(levels):
                raise ContractError("RELEASE_SCOPE_REQUIRED_LEVELS_INVALID")

        payload = asdict(manifest)
        payload["requirement_ssts"] = {
            req: list(ssts) for req, ssts in sorted(manifest.requirement_ssts.items())
        }
        payload["required_levels_by_sst"] = {
            sst: [level.upper() for level in levels]
            for sst, levels in sorted(manifest.required_levels_by_sst.items())
        }
        self._append("RC72_RELEASE_SCOPE_MANIFEST_UPSERTED", payload)

    def evaluate_denominator(self, *, manifest_id: str) -> ScopeDenominatorSnapshot:
        manifest = self._one(_SCOPE_MANIFEST, manifest_id=manifest_id)
        obligations = self.truth.query("rc72_test_obligation", mission_id=str(manifest["mission_id"]))
        obligations = [
            row for row in obligations
            if row.get("release_batch_id") == manifest.get("release_batch_id")
        ]

        requirement_ssts = dict(manifest["requirement_ssts"])
        required_levels = dict(manifest["required_levels_by_sst"])
        sst_owner = {
            sst: req for req, ssts in requirement_ssts.items() for sst in ssts
        }
        by_sst: Dict[str, List[Dict[str, Any]]] = {sst: [] for sst in sst_owner}
        out_of_scope: List[str] = []
        for row in obligations:
            sst = row.get("sst_id")
            req = row.get("requirement_id")
            if sst not in sst_owner or sst_owner.get(str(sst)) != req:
                out_of_scope.append(str(row.get("obligation_id")))
                continue
            by_sst[str(sst)].append(row)

        missing_ssts = sorted(sst for sst, rows in by_sst.items() if not rows)
        missing_levels: Dict[str, List[str]] = {}
        for sst, expected_levels in required_levels.items():
            actual = {str(row.get("test_level") or "").upper() for row in by_sst.get(sst, [])}
            missing = sorted(level.upper() for level in expected_levels if level.upper() not in actual)
            if missing:
                missing_levels[sst] = missing

        snapshot = ScopeDenominatorSnapshot(
            snapshot_id=_new("SCOPE-SNAPSHOT"),
            manifest_id=manifest_id,
            mission_id=str(manifest["mission_id"]),
            release_batch_id=str(manifest["release_batch_id"]),
            expected_requirement_count=len(requirement_ssts),
            expected_sst_count=len(sst_owner),
            expected_required_level_count=sum(len(levels) for levels in required_levels.values()),
            missing_ssts=missing_ssts,
            missing_required_levels=missing_levels,
            out_of_scope_obligation_ids=sorted(out_of_scope),
            denominator_complete=not missing_ssts and not missing_levels and not out_of_scope,
        )
        self._append(
            "RC72_SCOPE_DENOMINATOR_SNAPSHOT_UPSERTED",
            asdict(snapshot),
        )
        return snapshot
