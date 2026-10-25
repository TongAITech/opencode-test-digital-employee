from __future__ import annotations

import hashlib

import pytest

from rc7_runtime.bank_field_reality import evaluate_bank_field_rows
from rc7_runtime.bank_field_services import (
    CAP_AUTH_4A,
    CAP_CAT,
    CAP_DB_READ,
    CAP_DB_WRITE,
    PROBE_KIND,
    REQUIRED_CAPABILITIES,
)


MISSION = "MISSION-RC71-REALITY"
TASK = "TASK-EXECUTION"
TARGET = "PFC-FIELD-TARGET"
SOURCE_COMMIT = "abcdef0123456789abcdef0123456789abcdef01"
EXECUTION_UPDATED_AT = 1000


def _attempt() -> str:
    return "BANK-FIELD-PROBE-" + hashlib.sha256(
        (MISSION + "\x1f" + TARGET).encode("utf-8")
    ).hexdigest()[:20]


def _row(capability: str, *, source_ref=None, created_at: int = 1001):
    refs = [
        TASK,
        _attempt(),
        TARGET,
        capability,
        "provider:bank-runtime-provider",
        "field-tool://" + capability.lower(),
        "field-evidence://" + capability.lower(),
    ]
    if capability == CAP_DB_WRITE:
        refs.append("EVD-HGAPP-current")
    return {
        "evidence_id": "EVD-BANK-SVC-" + capability.lower(),
        "mission_id": MISSION,
        "kind": PROBE_KIND,
        "source_ref": source_ref or (
            "provider://bank-runtime-provider/" + capability
        ),
        "content_ref": (
            "state://bank-field-services/%s/%s/%s.json"
            % (MISSION, TARGET, capability.lower())
        ),
        "subject_refs": refs,
        "content_hash": "a" * 64,
        "created_at": created_at,
    }


def _valid_rows():
    return [_row(capability) for capability in REQUIRED_CAPABILITIES]


def _evaluate(rows):
    return evaluate_bank_field_rows(
        rows,
        mission_id=MISSION,
        execution_task_id=TASK,
        execution_updated_at=EXECUTION_UPDATED_AT,
        target_id=TARGET,
        source_commit=SOURCE_COMMIT,
    )


def test_current_runtime_provider_receipts_can_satisfy_bank_field_gate() -> None:
    result = _evaluate(_valid_rows())
    assert result["status"] == "PASS"
    assert result["blocking_reasons"] == []
    assert set(result["trusted_capabilities"]) == set(REQUIRED_CAPABILITIES)
    assert result["expected_probe_attempt_id"] == _attempt()


@pytest.mark.parametrize(
    "source_ref",
    [
        "engineering-fixture://bank-auth",
        "fixture://bank-auth",
        "mock://bank-auth",
        "synthetic://bank-auth",
        "test://bank-auth",
        "migration://bank-auth",
    ],
)
def test_fixture_and_migration_sources_cannot_certify_bank_field(source_ref: str) -> None:
    rows = _valid_rows()
    rows[0] = _row(CAP_AUTH_4A, source_ref=source_ref)
    result = _evaluate(rows)
    assert result["status"] == "HOLD"
    assert any(
        reason.startswith("BANK_FIELD_FORBIDDEN_EVIDENCE_SOURCE:%s:" % CAP_AUTH_4A)
        for reason in result["blocking_reasons"]
    )


@pytest.mark.parametrize(
    "source_ref",
    [
        "",
        "https://example.invalid/probe",
        "file://local/probe.json",
        "unknown-runtime://provider/probe",
    ],
)
def test_empty_or_unknown_source_cannot_certify_bank_field(source_ref: str) -> None:
    rows = _valid_rows()
    row = _row(CAP_AUTH_4A)
    row["source_ref"] = source_ref
    rows[0] = row
    result = _evaluate(rows)
    assert result["status"] == "HOLD"
    assert (
        "BANK_FIELD_REALITY_PROVIDER_SOURCE_REQUIRED:%s" % CAP_AUTH_4A
        in result["blocking_reasons"]
    )


def test_self_reported_real_flag_has_no_certification_authority() -> None:
    rows = _valid_rows()
    forged = _row(CAP_AUTH_4A, source_ref="synthetic://self-report")
    forged["real"] = True
    forged["target_verified"] = True
    rows[0] = forged
    result = _evaluate(rows)
    assert result["status"] == "HOLD"
    assert CAP_AUTH_4A not in result["trusted_capabilities"]


def test_stale_probe_before_current_execution_is_rejected() -> None:
    rows = _valid_rows()
    rows[0] = _row(CAP_AUTH_4A, created_at=EXECUTION_UPDATED_AT - 1)
    result = _evaluate(rows)
    assert result["status"] == "HOLD"
    assert (
        "BANK_FIELD_REALITY_STALE_EVIDENCE:%s" % CAP_AUTH_4A
        in result["blocking_reasons"]
    )


@pytest.mark.parametrize(
    "field,bad_value,expected",
    [
        ("mission_id", "MISSION-OLD", "BANK_FIELD_REALITY_MISSION_MISMATCH"),
        ("task", "TASK-OLD", "BANK_FIELD_REALITY_TASK_MISMATCH"),
        ("attempt", "BANK-FIELD-PROBE-old", "BANK_FIELD_REALITY_ATTEMPT_MISMATCH"),
        ("target", "TARGET-OLD", "BANK_FIELD_REALITY_TARGET_MISMATCH"),
    ],
)
def test_old_or_wrong_identity_receipts_are_rejected(
    field: str, bad_value: str, expected: str
) -> None:
    rows = _valid_rows()
    row = _row(CAP_AUTH_4A)
    if field == "mission_id":
        row["mission_id"] = bad_value
    else:
        refs = list(row["subject_refs"])
        index = {"task": 0, "attempt": 1, "target": 2}[field]
        refs[index] = bad_value
        row["subject_refs"] = refs
    rows[0] = row
    result = _evaluate(rows)
    assert result["status"] == "HOLD"
    assert any(reason.startswith(expected + ":" + CAP_AUTH_4A) for reason in result["blocking_reasons"])


def test_untrusted_tool_or_evidence_reference_is_rejected() -> None:
    rows = _valid_rows()
    row = _row(CAP_CAT)
    row["subject_refs"] = [
        TASK,
        _attempt(),
        TARGET,
        CAP_CAT,
        "provider:bank-runtime-provider",
        "unknown-tool://cat",
        "unknown-evidence://cat",
    ]
    rows[1] = row
    result = _evaluate(rows)
    assert result["status"] == "HOLD"
    assert (
        "BANK_FIELD_REALITY_TRUSTED_TOOL_REF_MISSING:%s" % CAP_CAT
        in result["blocking_reasons"]
    )


def test_db_write_requires_human_gate_approval_receipt() -> None:
    rows = _valid_rows()
    row = _row(CAP_DB_WRITE)
    row["subject_refs"] = [
        ref for ref in row["subject_refs"] if not ref.startswith("EVD-HGAPP-")
    ]
    rows[3] = row
    result = _evaluate(rows)
    assert result["status"] == "HOLD"
    assert "BANK_FIELD_REALITY_DB_WRITE_APPROVAL_REQUIRED" in result["blocking_reasons"]


def test_engineering_fixture_can_coexist_but_cannot_occupy_field_probe_slot() -> None:
    rows = _valid_rows()
    rows.append(
        {
            "evidence_id": "EVD-ENGINEERING-FIXTURE",
            "mission_id": MISSION,
            "kind": "ENGINEERING_RECON",
            "source_ref": "engineering-fixture://controlled-ci",
            "content_ref": "fixture://controlled-ci/result",
            "subject_refs": ["ENGINEERING_ONLY"],
            "created_at": 1001,
        }
    )
    result = _evaluate(rows)
    assert result["status"] == "PASS"
    assert len(result["trusted_capabilities"]) == 4


def test_duplicate_authoritative_probe_fails_closed() -> None:
    rows = _valid_rows()
    duplicate = dict(_row(CAP_DB_READ))
    duplicate["evidence_id"] = "EVD-BANK-SVC-duplicate"
    rows.append(duplicate)
    result = _evaluate(rows)
    assert result["status"] == "HOLD"
    assert (
        "BANK_FIELD_REALITY_PROBE_NOT_UNIQUE:%s:2" % CAP_DB_READ
        in result["blocking_reasons"]
    )
