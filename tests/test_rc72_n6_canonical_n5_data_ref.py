from copy import deepcopy

import pytest

from rc7_runtime.rc72_n6_executable_readiness import (
    CanonicalN5DataRefError,
    ExecutableReadinessError,
    N6ExecutableReadinessCompiler,
    canonical_n5_data_ref,
)

from test_rc72_n6_executable_readiness import NOW, _binding, _case, _data_ref


CASE_HASH = "sha256:" + ("a" * 64)


def _requirement(case):
    return {
        "data_requirement_id": "N5REQ-CANONICAL-001",
        "release_batch_id": case["release_batch_id"],
        "mission_id": case["mission_id"],
        "requirement_id": case["requirement_id"],
        "sst_id": case["sst_id"],
        "obligation_id": case["obligation_id"],
        "case_id": case["case_id"],
        "source_case_sha256": CASE_HASH,
    }


def _canonical_binding(case):
    requirement = _requirement(case)
    return {
        "binding_id": "N5BIND-CANONICAL-001",
        "release_batch_id": case["release_batch_id"],
        "mission_id": case["mission_id"],
        "data_requirement_id": requirement["data_requirement_id"],
        "source_case_sha256": CASE_HASH,
        "data_ref": "data://fat1/pcc/config/canonical-001",
        "strategy": "DISCOVER_EXISTING",
        "source_or_constructor": "tdsql://fat1/pcc/select-by-business-key",
        "verification": "row exists and satisfies exact Case precondition",
        "verification_evidence_refs": ["EVD-N5-CANONICAL-001"],
        "precondition_refs": ["precondition://%s" % case["case_id"]],
        "validity_window": "mission-attempt-window",
        "cleanup_policy": "release reservation; no mutation cleanup required",
        "reservation_mode": "SHARED_READ",
        "resource_metadata_ref": "db://fat1/pcc/canonical-001",
        "status": "VERIFIED",
    }


def test_n6_compiles_canonical_n5_validity_window_without_fabricated_expiry():
    case = deepcopy(_case())
    binding = _canonical_binding(case)
    data_ref = canonical_n5_data_ref(binding, _requirement(case))

    assert data_ref["resolved_ref_status"] == "VERIFIED"
    assert data_ref["validity_window"] == "mission-attempt-window"
    assert "expires_at" not in data_ref
    assert "EVD-N5-CANONICAL-001" in data_ref["authoritative_sources"]

    contract = N6ExecutableReadinessCompiler().compile(
        case,
        [data_ref],
        _binding(),
        now=NOW,
    )

    assert contract.case_id == case["case_id"]
    assert contract.data_refs[0]["data_ref"] == binding["data_ref"]
    assert contract.data_refs[0]["validity_window"] == "mission-attempt-window"
    assert "expires_at" not in contract.data_refs[0]


def test_n6_keeps_explicit_expiry_fail_closed_for_legacy_or_ttl_data_ref():
    ref = deepcopy(_data_ref())
    ref["expires_at"] = "2025-01-01T00:00:00Z"

    with pytest.raises(ExecutableReadinessError) as exc_info:
        N6ExecutableReadinessCompiler().compile(
            _case(),
            [ref],
            _binding(),
            now=NOW,
        )

    codes = {item.code for item in exc_info.value.violations}
    assert "N6_DATA_REF_EXPIRED" in codes


def test_n6_rejects_data_ref_with_neither_expiry_nor_canonical_validity_window():
    ref = deepcopy(_data_ref())
    ref.pop("expires_at", None)
    ref.pop("validity_window", None)

    with pytest.raises(ExecutableReadinessError) as exc_info:
        N6ExecutableReadinessCompiler().compile(
            _case(),
            [ref],
            _binding(),
            now=NOW,
        )

    violations = [
        item for item in exc_info.value.violations
        if item.code == "N6_DATA_REF_VALIDITY_UNRESOLVED"
    ]
    assert len(violations) == 1
    assert violations[0].target_node == "N5"


def test_canonical_n5_adapter_rejects_unverified_binding():
    case = deepcopy(_case())
    binding = _canonical_binding(case)
    binding["status"] = "UNVERIFIED"

    with pytest.raises(CanonicalN5DataRefError, match="STATUS_NOT_VERIFIED"):
        canonical_n5_data_ref(binding, _requirement(case))


def test_canonical_n5_adapter_rejects_case_hash_mismatch():
    case = deepcopy(_case())
    binding = _canonical_binding(case)
    requirement = _requirement(case)
    requirement["source_case_sha256"] = "sha256:" + ("b" * 64)

    with pytest.raises(CanonicalN5DataRefError, match="CASE_HASH_MISMATCH"):
        canonical_n5_data_ref(binding, requirement)
