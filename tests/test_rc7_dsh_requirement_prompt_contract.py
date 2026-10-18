from __future__ import annotations

from rc7_runtime.authorized_dsh_launcher import Rc7AuthorizedDshHeadlessWorkerLauncher
from rc7_runtime.dsh_worker_bridge import (
    _COMPACT_OUTPUT_CONTRACT,
    _REQUIREMENT_TRACE_CONTRACT,
    _compact_artifact_input_projection,
)


class _Truth:
    def __init__(self):
        self.rows = {
            "rc7_artifact": [
                {
                    "artifact_id": "ART-REALITY-1",
                    "artifact_type_name": "BANK_REALITY_SNAPSHOT",
                    "producer_task_id": "TASK-REALITY-1",
                    "content_ref": "file:///state/reality.json",
                    "evidence_refs": ["EVD-REAL-1"],
                }
            ],
            "rc7_evidence": [
                {
                    "evidence_id": "EVD-REAL-1",
                    "source_ref": "file:///workspace/README_zh-CN.md",
                    "content_ref": "file:///workspace/README_zh-CN.md",
                }
            ],
        }

    def query(self, kind, **filters):
        return [
            dict(row)
            for row in self.rows.get(kind, [])
            if all(row.get(key) == value for key, value in filters.items())
        ]


def test_artifact_input_projection_uses_canonical_r1_entity_and_evidence_aliases():
    projected = _compact_artifact_input_projection(
        _Truth(),
        ("ART-REALITY-1", "file:///workspace/README_zh-CN.md"),
    )

    assert projected == [
        {
            "artifact_id": "ART-REALITY-1",
            "canonical_truth_query": {
                "artifact_type": "rc7_artifact",
                "filters": {"artifact_id": "ART-REALITY-1"},
            },
            "projection_status": "RESOLVED",
            "artifact_type_name": "BANK_REALITY_SNAPSHOT",
            "producer_task_id": "TASK-REALITY-1",
            "content_ref": "file:///state/reality.json",
            "evidence_refs": ["EVD-REAL-1"],
            "evidence_aliases": [
                {
                    "evidence_id": "EVD-REAL-1",
                    "content_ref": "file:///workspace/README_zh-CN.md",
                    "source_ref": "file:///workspace/README_zh-CN.md",
                }
            ],
        }
    ]


def test_missing_artifact_is_unresolved_without_fabricated_metadata():
    projected = _compact_artifact_input_projection(_Truth(), ("ART-MISSING",))

    assert projected == [
        {
            "artifact_id": "ART-MISSING",
            "canonical_truth_query": {
                "artifact_type": "rc7_artifact",
                "filters": {"artifact_id": "ART-MISSING"},
            },
            "projection_status": "UNRESOLVED",
        }
    ]
    assert "content_ref" not in projected[0]
    assert "evidence_refs" not in projected[0]


def test_requirement_trace_contract_reuses_durable_evidence_alias_instead_of_inventing_id():
    assert _REQUIREMENT_TRACE_CONTRACT["trace_link_required_field"] == "evidence_ref"
    rule = _REQUIREMENT_TRACE_CONTRACT["evidence_ref_rule"]
    assert "content_ref" in rule
    assert "source_ref" in rule
    assert any("invented EVID-*" in item for item in _REQUIREMENT_TRACE_CONTRACT["forbidden"])
    assert "Do not copy source documents" in _COMPACT_OUTPUT_CONTRACT
    assert "configured output budget" in _COMPACT_OUTPUT_CONTRACT


def test_explicit_provider_429_rate_limit_is_classified_without_json_guessing():
    raw = (
        '{"type":"status","phase":"turn_end","reason":{"kind":"error",'
        '"error":{"message":"429: daily quota reached","code":"RATE_LIMIT"}}}\n'
        '{"type":"stderr","text":"dsh: RATE_LIMIT: 429: '
        '{\\"code\\":\\"free_daily_limit\\"}"}\n'
    )
    assert (
        Rc7AuthorizedDshHeadlessWorkerLauncher._provider_failure_reason_from_text(raw)
        == "MODEL_PROVIDER_RATE_LIMIT"
    )


def test_global_free_rate_limit_is_classified():
    raw = 'HTTP 429 {"code":"free_global_rate_limited","type":"rate_limit_error"}'
    assert (
        Rc7AuthorizedDshHeadlessWorkerLauncher._provider_failure_reason_from_text(raw)
        == "MODEL_PROVIDER_RATE_LIMIT"
    )


def test_plain_strict_json_failure_is_not_reclassified_as_provider_rate_limit():
    raw = '{"type":"final","text":"not-json"}'
    assert Rc7AuthorizedDshHeadlessWorkerLauncher._provider_failure_reason_from_text(raw) == ""


def test_429_without_rate_limit_marker_is_not_overclassified():
    raw = 'HTTP 429 but no provider classification payload was preserved'
    assert Rc7AuthorizedDshHeadlessWorkerLauncher._provider_failure_reason_from_text(raw) == ""
