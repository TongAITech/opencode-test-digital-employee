from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Evidence
from rc7_runtime.dsh_requirement_evaluator import (
    DshRequirementEvaluator,
    DshRequirementEvaluatorError,
)
from rc7_runtime.truth_overlay import append_entity


def _truth_with_source(tmp_path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    evidence = Evidence(
        evidence_id="EVD-DURABLE-SOURCE",
        mission_id="MISSION-EVIDENCE-BINDING",
        kind="SOURCE_DOCUMENT",
        source_ref="file:///requirements/STB915-7489.md",
        content_ref="evidence://sst/STB915-7489",
        subject_refs=["TASK-REQ"],
    )
    append_entity(truth, evidence, release_id="RC7")
    control = type(
        "Control",
        (),
        {"truth": truth, "mission_id": "MISSION-EVIDENCE-BINDING"},
    )()
    return truth, control, evidence


def test_requirement_trace_alias_is_normalized_to_canonical_r1_evidence_id(tmp_path) -> None:
    _truth, control, evidence = _truth_with_source(tmp_path)
    artifact_row = {
        # A worker-controlled unresolved string may still exist in legacy/raw
        # data, but it must not become acceptance authority.
        "evidence_refs": ["source://worker-invented", evidence.evidence_id],
    }
    analysis = {
        "trace_links": [
            {
                "source_id": "SRC-1",
                "atomic_id": "A-1",
                "evidence_ref": evidence.content_ref,
            }
        ],
        "evidence_refs": ["source://worker-invented"],
    }

    DshRequirementEvaluator._bind_analysis_evidence(control, artifact_row, analysis)

    assert analysis["evidence_refs"] == [evidence.evidence_id]
    assert analysis["trace_links"][0]["evidence_ref"] == evidence.evidence_id


def test_requirement_trace_to_non_durable_worker_string_is_rejected(tmp_path) -> None:
    _truth, control, evidence = _truth_with_source(tmp_path)
    artifact_row = {"evidence_refs": [evidence.evidence_id]}
    analysis = {
        "trace_links": [
            {
                "source_id": "SRC-1",
                "atomic_id": "A-1",
                "evidence_ref": "evidence://worker-invented-does-not-exist",
            }
        ]
    }

    with pytest.raises(
        DshRequirementEvaluatorError,
        match="REQUIREMENT_TRACE_EVIDENCE_NOT_DURABLE",
    ):
        DshRequirementEvaluator._bind_analysis_evidence(control, artifact_row, analysis)


def test_requirement_candidate_without_any_durable_evidence_is_rejected(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = type(
        "Control",
        (),
        {"truth": truth, "mission_id": "MISSION-EVIDENCE-BINDING"},
    )()
    artifact_row = {"evidence_refs": ["source://worker-only"]}
    analysis = {
        "trace_links": [
            {
                "source_id": "SRC-1",
                "atomic_id": "A-1",
                "evidence_ref": "source://worker-only",
            }
        ]
    }

    with pytest.raises(
        DshRequirementEvaluatorError,
        match="REQUIREMENT_ARTIFACT_HAS_NO_DURABLE_EVIDENCE",
    ):
        DshRequirementEvaluator._bind_analysis_evidence(control, artifact_row, analysis)
