from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Sequence

from . import rc72_n6_executable_readiness_core as _core

ARTIFACT_TYPE_N6_EXECUTABLE_CONTRACT = _core.ARTIFACT_TYPE_N6_EXECUTABLE_CONTRACT
EVENT_N6_EXECUTABLE_CONTRACT_COMPILED = _core.EVENT_N6_EXECUTABLE_CONTRACT_COMPILED
N6_SCHEMA_VERSION = _core.N6_SCHEMA_VERSION

ReadinessViolation = _core.ReadinessViolation
ExecutableReadinessError = _core.ExecutableReadinessError
ExecutableContract = _core.ExecutableContract

_RUNTIME_BINDING_VIOLATION_CODES = {
    "N6_REQUEST_SCHEMA_UNRESOLVED",
    "N6_REQUEST_UNRESOLVED",
}


class CanonicalN5DataRefError(ValueError):
    pass


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalN5DataRefError("N6_CANONICAL_N5_%s_REQUIRED" % name.upper())
    return value.strip()


def canonical_n5_data_ref(
    binding_payload: Mapping[str, Any],
    requirement_payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """Adapt canonical N5 truth to the N6 DataRef contract without inventing TTL.

    N5 currently proves validity through a named validity window plus canonical
    verification evidence.  N6 therefore carries that policy through unchanged;
    it never manufactures an ``expires_at`` timestamp.  Lineage is enriched only
    from the matching canonical DataRequirement.
    """
    if not isinstance(binding_payload, Mapping) or not isinstance(requirement_payload, Mapping):
        raise CanonicalN5DataRefError("N6_CANONICAL_N5_MAPPING_REQUIRED")

    binding = dict(binding_payload)
    requirement = dict(requirement_payload)
    if _required_text(binding.get("status"), "status") != "VERIFIED":
        raise CanonicalN5DataRefError("N6_CANONICAL_N5_STATUS_NOT_VERIFIED")

    binding_requirement_id = _required_text(
        binding.get("data_requirement_id"), "data_requirement_id"
    )
    if binding_requirement_id != _required_text(
        requirement.get("data_requirement_id"), "requirement_data_requirement_id"
    ):
        raise CanonicalN5DataRefError("N6_CANONICAL_N5_REQUIREMENT_MISMATCH")

    binding_case_hash = _required_text(
        binding.get("source_case_sha256"), "source_case_sha256"
    )
    if not binding_case_hash.startswith("sha256:"):
        raise CanonicalN5DataRefError("N6_CANONICAL_N5_CASE_HASH_INVALID")
    if binding_case_hash != _required_text(
        requirement.get("source_case_sha256"), "requirement_source_case_sha256"
    ):
        raise CanonicalN5DataRefError("N6_CANONICAL_N5_CASE_HASH_MISMATCH")

    for key in ("release_batch_id", "mission_id"):
        if _required_text(binding.get(key), key) != _required_text(
            requirement.get(key), "requirement_%s" % key
        ):
            raise CanonicalN5DataRefError(
                "N6_CANONICAL_N5_%s_MISMATCH" % key.upper()
            )

    evidence_refs = binding.get("verification_evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs or not all(
        isinstance(item, str) and item.strip() for item in evidence_refs
    ):
        raise CanonicalN5DataRefError(
            "N6_CANONICAL_N5_VERIFICATION_EVIDENCE_REQUIRED"
        )

    precondition_refs = binding.get("precondition_refs")
    if not isinstance(precondition_refs, list) or not precondition_refs or not all(
        isinstance(item, str) and item.strip() for item in precondition_refs
    ):
        raise CanonicalN5DataRefError("N6_CANONICAL_N5_PRECONDITION_REFS_REQUIRED")

    authoritative_sources = []
    for value in (
        "n5-binding://%s" % _required_text(binding.get("binding_id"), "binding_id"),
        "n5-data-requirement://%s" % binding_requirement_id,
        _required_text(binding.get("source_or_constructor"), "source_or_constructor"),
        _required_text(binding.get("resource_metadata_ref"), "resource_metadata_ref"),
    ) + tuple(evidence_refs):
        if value not in authoritative_sources:
            authoritative_sources.append(value)

    result = {
        "resolved_ref_status": "VERIFIED",
        "status": "VERIFIED",
        "release_batch_id": _required_text(binding.get("release_batch_id"), "release_batch_id"),
        "mission_id": _required_text(binding.get("mission_id"), "mission_id"),
        "requirement_id": _required_text(requirement.get("requirement_id"), "requirement_id"),
        "case_id": _required_text(requirement.get("case_id"), "case_id"),
        "data_requirement_id": binding_requirement_id,
        "source_case_sha256": binding_case_hash,
        "data_ref": _required_text(binding.get("data_ref"), "data_ref"),
        "strategy": _required_text(binding.get("strategy"), "strategy"),
        "verification": _required_text(binding.get("verification"), "verification"),
        "verification_evidence_refs": list(evidence_refs),
        "precondition_refs": list(precondition_refs),
        "validity_window": _required_text(binding.get("validity_window"), "validity_window"),
        "cleanup_policy": _required_text(binding.get("cleanup_policy"), "cleanup_policy"),
        "reservation_policy": _required_text(binding.get("reservation_mode"), "reservation_mode"),
        "resource_metadata_ref": _required_text(binding.get("resource_metadata_ref"), "resource_metadata_ref"),
        "authoritative_sources": authoritative_sources,
    }
    for key in ("sst_id", "obligation_id"):
        value = requirement.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    return result


class N6ExecutableReadinessCompiler(_core.N6ExecutableReadinessCompiler):
    """Public N6 compiler with canonical semantic back-edge routing.

    The core compiler owns deterministic contract construction. This facade keeps
    gap ownership aligned with the frozen N1-N10 contract: request/schema facts
    supplied by the verified runtime binding belong to N1, never N4. No violation
    is suppressed or downgraded; only the semantic target is normalized.
    """

    def compile(
        self,
        case_payload: Mapping[str, Any],
        data_ref_payloads: Sequence[Mapping[str, Any]],
        runtime_binding: Mapping[str, Any],
        *,
        now: Optional[datetime] = None,
    ) -> ExecutableContract:
        try:
            return super().compile(
                case_payload,
                data_ref_payloads,
                runtime_binding,
                now=now,
            )
        except ExecutableReadinessError as error:
            rewritten = []
            changed = False
            for violation in error.violations:
                target_node = violation.target_node
                if violation.code in _RUNTIME_BINDING_VIOLATION_CODES:
                    target_node = "N1"
                if target_node != violation.target_node:
                    changed = True
                rewritten.append(
                    ReadinessViolation(
                        violation.code,
                        target_node,
                        violation.field,
                        violation.reason,
                    )
                )
            if changed:
                raise ExecutableReadinessError(tuple(rewritten)) from error
            raise


__all__ = [
    "ARTIFACT_TYPE_N6_EXECUTABLE_CONTRACT",
    "EVENT_N6_EXECUTABLE_CONTRACT_COMPILED",
    "N6_SCHEMA_VERSION",
    "ReadinessViolation",
    "ExecutableReadinessError",
    "ExecutableContract",
    "CanonicalN5DataRefError",
    "canonical_n5_data_ref",
    "N6ExecutableReadinessCompiler",
]
