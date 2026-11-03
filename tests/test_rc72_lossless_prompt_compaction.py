"""C10 production native prompt compaction: lossless JSON and real byte evidence."""
from __future__ import annotations

import json
import hashlib

import pytest

from rc7_runtime.rc72_lossless_prompt_compaction import compact_native_prompt_json


def _native_prompt(*, shape=True):
    body = {
        "mission_id": "MISSION-BLOAN-1.2.1",
        "workitem_id": "WI-N4-CASE",
        "input_refs": ["ART-CODE-IMPACT", "ART-SST-SOURCE", "ART-REVIEW-EVIDENCE"],
        "required_levels": ["L1", "L2", "L3", "L4", "L5", "L6", "L7"],
        "required_oracles": {
            "negative": True,
            "boundary": True,
            "business_result": "EXPECTED_VALUE_FROM_SOURCE",
        },
    }
    expected = {
        "status": "CANDIDATE",
        "cases": [{
            "tc_id": "test case",
            "steps": ["concrete execution step"],
            "preconditions": ["approved runtime binding"],
            "expected_results": ["concrete business assertions"],
            "evidence_refs": ["raw native proof"],
        }],
        "gaps": [], "unknowns": [],
    }
    prefix = (
        "NATIVE_READ_GATE\\n"
        "Use only approved real source reads; no invented oracle or PASS. "
        "Context="
    )
    prompt = prefix + json.dumps(body, ensure_ascii=False, sort_keys=True)
    if shape:
        prompt += " RequiredShape=" + json.dumps(expected, ensure_ascii=False, sort_keys=True)
    return prompt, body, expected


def test_real_n4_native_context_and_required_shape_compact_without_losing_fields():
    original, body, expected = _native_prompt()
    compacted = compact_native_prompt_json(original)
    assert compacted.status == "LOSSLESS_JSON"
    assert compacted.saved_bytes > 0
    assert compacted.original_bytes == len(original.encode("utf-8"))
    assert compacted.compacted_bytes == len(compacted.prompt.encode("utf-8"))
    assert compacted.prompt.startswith("NATIVE_READ_GATE\\nUse only approved real source reads; no invented oracle or PASS. Context=")
    projection = compacted.prompt.split("Context=", 1)[1]
    actual_body, actual_shape = projection.split(" RequiredShape=", 1)
    assert json.loads(actual_body) == body
    assert json.loads(actual_shape) == expected
    assert "L7" in compacted.prompt
    assert "negative" in compacted.prompt
    assert "raw native proof" in compacted.prompt


def test_native_n1_context_only_compacts_without_change_to_read_gate():
    original, body, _ = _native_prompt(shape=False)
    result = compact_native_prompt_json(original)
    assert result.status == "LOSSLESS_JSON"
    assert json.loads(result.prompt.split("Context=", 1)[1]) == body
    assert result.prompt.startswith("NATIVE_READ_GATE")


@pytest.mark.parametrize("text", [
    "native no JSON at all",
    "tool speaks about Context= in prose",
    "NATIVE Context={broken]",
    "NATIVE Context={\"key\":1,\"key\":2}",
    "NATIVE Context={\"abc\": NaN}",
    "NATIVE Context={\"abc\": 1} trailing unapproved prose",
    "NATIVE Context={\"abc\": 1} RequiredShape={\"a\":1,\"a\":2}",
    "NATIVE Context={\"abc\": 1} RequiredShape=[]",
    "NATIVE Context={\"abc\": 1} RequiredShape={\"x\": 2} unexpected",
])
def test_ambiguous_or_invalid_json_prompt_stays_byte_identical(text):
    comp = compact_native_prompt_json(text)
    assert comp.status == "UNCHANGED"
    assert comp.prompt == text
    assert comp.saved_bytes == 0


def test_no_false_compaction_when_only_reference_marker_inside_json_data():
    prompt = 'NATIVE Context=' + json.dumps(
        {"details": "An unrelated business Context= value must remain literal."}
    )
    result = compact_native_prompt_json(prompt)
    assert result.prompt == prompt
    assert result.status == "UNCHANGED"


def test_unicode_model_payload_preserves_identical_strings_after_compaction():
    payload = {"业务规则": "还款试算不允许绕过审核", "业务预期": ["正例", "反例", "边界"]}
    prompt = "Native N4 Context=" + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    result = compact_native_prompt_json(prompt)
    assert result.status == "LOSSLESS_JSON"
    assert json.loads(result.prompt.split("Context=", 1)[1]) == payload
    assert hashlib.sha256(result.prompt.encode("utf-8")).hexdigest() != hashlib.sha256(prompt.encode("utf-8")).hexdigest()
