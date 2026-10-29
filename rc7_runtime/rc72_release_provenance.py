"""Canonical ReleaseBatch field/fixture provenance for RC7.2.

This module establishes whether one canonical ReleaseBatch is backed by real
provider evidence, explicit fixture evidence, or neither. It never infers FIELD
from release names, prompts, caller booleans, or scope labels.

FIELD evidence must be an existing RC7 bank-field service probe with a
``provider://`` source and matching Mission/release truth. Exact ReleaseBatch
binding is accepted either when the evidence explicitly names the target
release_batch_id or when canonical R1 proves there is exactly one ReleaseBatch
for that Mission + release_id. Ambiguous or cross-bound evidence fails closed.

FIXTURE evidence must be explicit, use the dedicated fixture provenance kind,
and name the target release_batch_id in subject_refs.

The resulting provenance receipt is canonical R1 truth. It is an admission
input for later Q7 logic; it does not itself qualify Q7 or set field_verified.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_release_batch_provenance"
_EVENT = "RC72_RELEASE_BATCH_PROVENANCE_UPSERTED"
_BUCKET = "rc72_release_batch_provenances"

FIELD = "FIELD"
FIXTURE = "FIXTURE"
UNKNOWN = "UNKNOWN"
_ALLOWED_PROVENANCE = {FIELD, FIXTURE, UNKNOWN}

FIELD_EVIDENCE_KIND = "BANK_FIELD_SERVICE_PROBE"
FIXTURE_EVIDENCE_KIND = "RC72_RELEASE_FIXTURE_PROVENANCE"

REASON_FIELD = "PROVIDER_BACKED_FIELD_EVIDENCE"
REASON_FIXTURE = "EXPLICIT_FIXTURE_EVIDENCE"
REASON_CONFLICT = "CONFLICTING_PROVENANCE_EVIDENCE"
REASON_NONE = "NO_VALID_PROVENANCE_EVIDENCE"


def _now() -> int:
    return int(time.time())


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("RELEASE_PROVENANCE_%s_REQUIRED" % name.upper())
    return value.strip()


def _validate_string_list(value: Any, name: str) -> List[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_%s_INVALID" % name.upper()
        )
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_%s_DUPLICATE" % name.upper()
        )
    return list(value)


def validate_rc72_release_batch_provenance(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "provenance_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "provenance",
        "reason",
        "evidence_digest",
    ):
        out[name] = _contracts._require_str(out, name)

    out["provenance"] = out["provenance"].upper()
    if out["provenance"] not in _ALLOWED_PROVENANCE:
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_VALUE_INVALID"
        )
    if len(out["evidence_digest"]) != 64:
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_EVIDENCE_DIGEST_INVALID"
        )

    for name in (
        "evidence_refs",
        "field_evidence_refs",
        "fixture_evidence_refs",
        "rejected_evidence_refs",
    ):
        out[name] = _validate_string_list(out.get(name), name)

    if sorted(set(out["field_evidence_refs"] + out["fixture_evidence_refs"])) != sorted(
        out["evidence_refs"]
    ):
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_EVIDENCE_REF_MISMATCH"
        )
    if out["provenance"] == FIELD and not out["field_evidence_refs"]:
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_FIELD_EVIDENCE_REQUIRED"
        )
    if out["provenance"] == FIXTURE and not out["fixture_evidence_refs"]:
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_FIXTURE_EVIDENCE_REQUIRED"
        )
    if out["provenance"] == FIELD and out["fixture_evidence_refs"]:
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_FIELD_CANNOT_HAVE_FIXTURE_EVIDENCE"
        )
    if out["provenance"] == FIXTURE and out["field_evidence_refs"]:
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_FIXTURE_CANNOT_HAVE_FIELD_EVIDENCE"
        )

    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RELEASE_PROVENANCE_%s_INVALID" % name.upper()
            )

    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RELEASE_PROVENANCE_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_release_provenance_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_release_batch_provenance
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "provenance_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "provenance_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class ReleaseBatchProvenanceService:
    """Derive and persist fail-closed ReleaseBatch provenance from R1 evidence."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_release_provenance_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")

    @staticmethod
    def _provenance_id(mission_id: str, release_batch_id: str) -> str:
        raw = "%s\x1f%s" % (mission_id, release_batch_id)
        return "RBPROV-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _batch(self, release_batch_id: str) -> Dict[str, Any]:
        batch_id = _required(release_batch_id, "release_batch_id")
        rows = self.truth.query("rc72_release_batch", release_batch_id=batch_id)
        if len(rows) != 1:
            raise ContractError(
                "RELEASE_PROVENANCE_BATCH_NOT_UNIQUE:%s:%d"
                % (batch_id, len(rows))
            )
        batch = rows[0]
        if batch.get("release_id") != self.release_id:
            raise ContractError("RELEASE_PROVENANCE_BATCH_RELEASE_MISMATCH")
        return batch

    def _same_release_batches(self, mission_id: str) -> Tuple[str, ...]:
        rows = [
            row
            for row in self.truth.query("rc72_release_batch", mission_id=mission_id)
            if row.get("release_id") == self.release_id
        ]
        values = sorted(
            str(row.get("release_batch_id"))
            for row in rows
            if isinstance(row.get("release_batch_id"), str)
            and str(row.get("release_batch_id")).strip()
        )
        return tuple(values)

    @staticmethod
    def _explicit_batch_subjects(
        evidence: Mapping[str, Any],
        canonical_batch_ids: Iterable[str],
    ) -> Tuple[str, ...]:
        known = set(canonical_batch_ids)
        refs = evidence.get("subject_refs") or []
        return tuple(
            sorted(
                ref
                for ref in refs
                if isinstance(ref, str) and ref in known
            )
        )

    def _field_candidate(
        self,
        evidence: Mapping[str, Any],
        *,
        mission_id: str,
        release_batch_id: str,
        same_release_batches: Tuple[str, ...],
    ) -> bool:
        if evidence.get("kind") != FIELD_EVIDENCE_KIND:
            return False
        if evidence.get("mission_id") != mission_id:
            return False
        if evidence.get("release_id") != self.release_id:
            return False
        source_ref = str(evidence.get("source_ref") or "")
        if not source_ref.startswith("provider://"):
            return False

        explicit = self._explicit_batch_subjects(
            evidence,
            same_release_batches,
        )
        if explicit:
            return explicit == (release_batch_id,)

        # Existing RC7 bank-field probes predate release_batch_id subjects. They
        # may be bound only when canonical R1 proves the Mission+release has
        # exactly one ReleaseBatch. Ambiguity fails closed.
        return same_release_batches == (release_batch_id,)

    def _fixture_candidate(
        self,
        evidence: Mapping[str, Any],
        *,
        mission_id: str,
        release_batch_id: str,
    ) -> bool:
        if evidence.get("kind") != FIXTURE_EVIDENCE_KIND:
            return False
        if evidence.get("mission_id") != mission_id:
            return False
        if evidence.get("release_id") != self.release_id:
            return False
        source_ref = str(evidence.get("source_ref") or "")
        if not source_ref.startswith("fixture://"):
            return False
        return release_batch_id in list(evidence.get("subject_refs") or [])

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "provenance": payload.get("provenance"),
            "reason": payload.get("reason"),
            "evidence_refs": list(payload.get("evidence_refs") or []),
            "field_evidence_refs": list(payload.get("field_evidence_refs") or []),
            "fixture_evidence_refs": list(payload.get("fixture_evidence_refs") or []),
            "rejected_evidence_refs": list(payload.get("rejected_evidence_refs") or []),
            "evidence_digest": payload.get("evidence_digest"),
        }

    def evaluate(self, release_batch_id: str) -> Dict[str, Any]:
        batch = self._batch(release_batch_id)
        mission_id = str(batch.get("mission_id") or "")
        if not mission_id:
            raise ContractError("RELEASE_PROVENANCE_BATCH_MISSION_REQUIRED")

        same_release_batches = self._same_release_batches(mission_id)
        rows = self.truth.query("rc7_evidence")
        field_refs: List[str] = []
        fixture_refs: List[str] = []
        rejected_refs: List[str] = []

        for evidence in rows:
            evidence_id = str(evidence.get("evidence_id") or "")
            if not evidence_id:
                continue

            field_kind = evidence.get("kind") == FIELD_EVIDENCE_KIND
            fixture_kind = evidence.get("kind") == FIXTURE_EVIDENCE_KIND
            if not field_kind and not fixture_kind:
                continue

            if field_kind:
                if self._field_candidate(
                    evidence,
                    mission_id=mission_id,
                    release_batch_id=release_batch_id,
                    same_release_batches=same_release_batches,
                ):
                    field_refs.append(evidence_id)
                else:
                    rejected_refs.append(evidence_id)
                continue

            if self._fixture_candidate(
                evidence,
                mission_id=mission_id,
                release_batch_id=release_batch_id,
            ):
                fixture_refs.append(evidence_id)
            else:
                rejected_refs.append(evidence_id)

        field_refs = sorted(set(field_refs))
        fixture_refs = sorted(set(fixture_refs))
        rejected_refs = sorted(set(rejected_refs))

        if field_refs and fixture_refs:
            provenance = UNKNOWN
            reason = REASON_CONFLICT
        elif field_refs:
            provenance = FIELD
            reason = REASON_FIELD
        elif fixture_refs:
            provenance = FIXTURE
            reason = REASON_FIXTURE
        else:
            provenance = UNKNOWN
            reason = REASON_NONE

        evidence_refs = sorted(set(field_refs + fixture_refs))
        evidence_digest = _sha(
            {
                "mission_id": mission_id,
                "release_id": self.release_id,
                "release_batch_id": release_batch_id,
                "provenance": provenance,
                "reason": reason,
                "field_evidence_refs": field_refs,
                "fixture_evidence_refs": fixture_refs,
                "rejected_evidence_refs": rejected_refs,
            }
        )
        provenance_id = self._provenance_id(mission_id, release_batch_id)
        existing = self.truth.query(_ARTIFACT, provenance_id=provenance_id)
        if len(existing) > 1:
            raise ContractError("RELEASE_PROVENANCE_RECEIPT_NOT_UNIQUE")

        now = _now()
        created_at = now
        artifact_version = 1
        if existing:
            current = existing[0]
            created_at = int(current.get("created_at", now))
            artifact_version = int(current.get("artifact_version", 1))
        payload = {
            "provenance_id": provenance_id,
            "release_id": self.release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "provenance": provenance,
            "reason": reason,
            "evidence_refs": evidence_refs,
            "field_evidence_refs": field_refs,
            "fixture_evidence_refs": fixture_refs,
            "rejected_evidence_refs": rejected_refs,
            "evidence_digest": evidence_digest,
            "created_at": created_at,
            "updated_at": now,
            "artifact_version": artifact_version,
        }

        if existing and self._signature(existing[0]) == self._signature(payload):
            return existing[0]
        if existing:
            payload["artifact_version"] = artifact_version + 1

        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, provenance_id=provenance_id)
        if len(rows) != 1:
            raise ContractError("RELEASE_PROVENANCE_PERSISTENCE_FAILED")
        return rows[0]


install_rc72_release_provenance_overlay()
