"""C10 real prompt retry hydration: no R1 parent/Gap/Oracle proof, no reduction."""
from __future__ import annotations

import json

import pytest

from rc7_runtime.rc72_native_delta_prompt import hydrate_native_retry_delta


def _metadata():
    return {
        "role": "design",
        "mission_id": "M-REAL",
        "workitem_id": "WI-REQUIRED",
        "attempt_id": "ATT-CHILD",
        "parent_attempt_id": "ATT-PARENT",
        "context_mode": "RETRY_DELTA",
        "context_projection_status": "REFERENCE_ONLY",
        "retry_context_observation_status": "OBSERVED",
        "retry_delta_native_authorized": True,
        "context_canonical_input_refs": (
            "ART-REQUIREMENTS-DOCUMENT-00000000001",
            "ART-CODE-CHANGES-SNAPSHOT-00000000002",
            "ART-REVIEW-TRACE-SUMMARY-00000000003",
            "ART-API-SCHEMA-SOURCE-00000000004",
        ),
        "context_effective_refs": (
            "PREVIOUS-ATTEMPT-SUMMARY",
            "GAP-REMAINING",
            "EVD-NEW",
        ),
        "retry_previous_summary_ref": "PREVIOUS-ATTEMPT-SUMMARY",
    }


def _prompt(m=None):
    meta = m or _metadata()
    context = {
        "mission_id": meta["mission_id"],
        "workitem_id": meta["workitem_id"],
        "input_refs": list(meta["context_canonical_input_refs"]),
        "must_test": {
            "positive": True, "negative": True, "boundary": True,
            "oracles": ["SQL_DB", "API_BODY", "SIDE_EFFECT", "CAT_TRACE"],
            "levels": ["L1", "L2", "L3", "L4", "L5", "L6", "L7"],
        },
        "authorized_tools": ["db", "cat", "codegraph"],
    }
    shape = {
        "status": "CANDIDATE",
        "cases": ["required valid test design"],
        "gaps": [], "evidence_refs": ["real proof"],
    }
    return (
        "NATIVE_AUTH_AND_SOURCE_GATE\n"
        "Keep every inherited test obligation. Context="
        + json.dumps(context, sort_keys=True, ensure_ascii=False)
        + " RequiredShape="
        + json.dumps(shape, sort_keys=True, ensure_ascii=False)
    ), context, shape


def test_observed_native_delta_replaces_only_input_refs_without_changing_oracle_or_schema():
    raw, original_context, shape = _prompt()
    result = hydrate_native_retry_delta(raw, _metadata())
    assert result.applied is True
    assert result.status == "NATIVE_RETRY_DELTA_APPLIED"
    assert result.bytes_saved > 0
    assert result.prompt.startswith("NATIVE_AUTH_AND_SOURCE_GATE\nKeep every inherited test obligation. ")
    context_part = result.prompt.split(" Context=", 1)[1]
    compact_context, compact_shape = context_part.split(" RequiredShape=", 1)
    revised = json.loads(compact_context)
    assert json.loads(compact_shape) == shape
    assert revised["input_refs"] == list(_metadata()["context_effective_refs"])
    assert revised["must_test"] == original_context["must_test"]
    assert revised["authorized_tools"] == original_context["authorized_tools"]
    assert result.removed_refs == tuple(original_context["input_refs"])
    assert result.bytes_saved == len(raw.encode()) - len(result.prompt.encode())


@pytest.mark.parametrize("change", [
    {"retry_delta_native_authorized": False},
    {"retry_context_observation_status": "UNKNOWN"},
    {"context_mode": "RETRY_DELTA_UNKNOWN"},
    {"context_mode": "FULL_CONTEXT_RETRY"},
    {"parent_attempt_id": None},
    {"context_projection_status": "NOT_BOUND"},
    {"role": "design_review"},
    {"role": "requirement_review"},
    {"context_effective_refs": ()},
    {"retry_previous_summary_ref": "FORGED-NOT-IN-DELTA"},
])
def test_unproven_or_independent_reviewer_delta_never_removes_business_refs(change):
    base = _metadata()
    base.update(change)
    raw, *_ = _prompt()
    result = hydrate_native_retry_delta(raw, base)
    assert not result.applied
    assert result.prompt == raw
    assert result.bytes_saved == 0


def test_forged_task_scope_or_noncanonical_worker_input_refs_keeps_native_prompt():
    raw, *_ = _prompt()
    for changed in [
        raw.replace('"mission_id": "M-REAL"', '"mission_id": "M-FORGED"'),
        raw.replace('"workitem_id": "WI-REQUIRED"', '"workitem_id": "WI-FORGED"'),
        raw.replace('"input_refs": [', '"unrelated_refs": ['),
        raw.replace(" RequiredShape=", " trailing text RequiredShape="),
        raw.replace('"input_refs": [', '"input_refs": ["SOURCE-UNAPPROVED", '),
    ]:
        result = hydrate_native_retry_delta(changed, _metadata())
        assert result.prompt == changed
        assert not result.applied


def test_semantic_retry_does_not_claim_savings_for_longer_delta_or_json_unparsable():
    meta = _metadata()
    meta["context_effective_refs"] = (
        "PREVIOUS-ATTEMPT-SUMMARY",
        "GAP-" + "x" * 250,
        "EVD-NEW",
    )
    raw, *_ = _prompt()
    result = hydrate_native_retry_delta(raw, meta)
    assert not result.applied
    assert result.prompt == raw
    assert not hydrate_native_retry_delta("NATIVE Context={broken", _metadata()).applied
