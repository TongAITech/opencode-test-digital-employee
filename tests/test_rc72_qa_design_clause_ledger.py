"""Independent structure/admission guard for the 95-unit frozen-design QA ledger.

This is a ledger completeness/integrity test, NOT a claim that any design
clause passed integration, Field acceptance or business testing.
"""
import csv
import re
from pathlib import Path


LEDGER = Path(__file__).resolve().parents[1] / "docs" / "rc7.2" / "qa-release" / "DESIGN-CLAUSE-AUDIT-BASELINE.csv"
FIELDS = (
    "clause_id", "design_clause", "production_code", "formal_product_entry",
    "contract_test_candidates", "negative_test_candidates", "recovery_test_candidates",
    "ci_exact_source_snapshot", "source_sha", "r1_evidence_status",
    "adjudicated_status", "weight", "field_boundary", "remaining_gap",
)


def _expected_ids():
    domain = {
        "AGENT_TEAMS", "WORKER", "SESSION", "LEASE",
        "L1", "L2", "L3", "L4", "L5", "L6", "L7",
        "JOURNEY", "LIBRA", "CODEGRAPH", "MODEL_ECONOMY", "R1",
        "WINDOWS", "LINUX", "OFFLINE_DELIVERY",
    }
    return (
        {"Phase-%02d" % x for x in range(11)}
        | {"GAP-%02d" % x for x in range(1, 9)}
        | {"CT-%02d" % x for x in range(1, 27)}
        | {"C%02d" % x for x in range(1, 13)}
        | {"N%d" % x for x in range(1, 11)}
        | {"Q%d" % x for x in range(1, 10)}
        | domain
    )


def _load():
    with LEDGER.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        assert tuple(reader.fieldnames or ()) == FIELDS
        rows = list(reader)
    return rows


def test_frozen_design_denominator_is_exact_and_unique():
    rows = _load()
    ids = [row["clause_id"] for row in rows]
    assert len(rows) == 95
    assert len(ids) == len(set(ids))
    assert set(ids) == _expected_ids()
    assert all(None not in row and all(row[f].strip() for f in FIELDS) for row in rows)


def test_each_clause_remains_tied_to_one_explicit_source_and_unweighted_truth():
    rows = _load()
    shas = {row["source_sha"] for row in rows}
    assert len(shas) == 1
    assert re.fullmatch(r"[0-9a-f]{40}", next(iter(shas)))
    assert all(row["ci_exact_source_snapshot"] != "NOT_MAPPED" for row in rows)
    assert all(row["weight"] == "TBD_NO_PERCENTAGE" for row in rows)
    # Presence of a source/test path is not evidence of an executed test.
    allowed = {
        "BLOCKED", "COMPONENT_TESTED", "ENGINEERING_VERIFIED",
        "PRODUCT_INTEGRATED", "FIELD_VERIFIED", "BANK_FINAL",
    }
    assert all(row["adjudicated_status"] in allowed for row in rows)


def test_field_or_final_status_must_have_nonplaceholder_exact_sha_r1_evidence():
    for row in _load():
        if row["adjudicated_status"] in {"FIELD_VERIFIED", "BANK_FINAL"}:
            assert "MISSING" not in row["field_boundary"]
            assert "NOT_VERIFIED" not in row["field_boundary"]
            assert not row["r1_evidence_status"].startswith("NO_")
            assert row["r1_evidence_status"] not in {"UNKNOWN", "NOT_MAPPED"}
        if row["clause_id"] == "Q9":
            assert row["adjudicated_status"] != "BANK_FINAL" or (
                row["r1_evidence_status"] not in {"UNKNOWN", "NOT_MAPPED"}
                and "MISSING" not in row["field_boundary"]
            )
