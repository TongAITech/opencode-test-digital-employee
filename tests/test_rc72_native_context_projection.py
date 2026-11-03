"""Native C10 ContextEnvelope admission: canonical refs, truthful retry provenance."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task
from rc7_runtime.rc72_native_context_projection import (
    NativeContextProjectionError, native_context_projection,
)
from rc7_runtime.rc72_model_economy import (
    ModelCallClass, TokenEconomyError, TokenEconomyService,
)
from rc7_runtime.rc72_retry_context import (
    install_rc72_retry_context_overlay, _ensure_projection_bucket,
)


MISSION = "M-C10-CONTEXT"
RELEASE = "REL-C10-CONTEXT"
WORKITEM = "WI-CTX-1"


def _canonical(tmp_path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="preserve test scope"),
    )
    control.register_task(Task(
        task_id=WORKITEM, mission_id=MISSION,
        node="TEST_DESIGN", task_type="DESIGN",
        objective="independent oracle and negative cases",
        input_artifact_refs=["ART-UPSTREAM-1", "ART-UPSTREAM-2"],
        gap_refs=["GAP-1"],
    ))
    task = truth.query("rc7_task", task_id=WORKITEM)[0]
    return truth, task


def _assignment(*, attempt_id="ATT-1", inputs=("ART-UPSTREAM-2", "ART-REVIEW-CANDIDATE")):
    return SimpleNamespace(mission_id=MISSION, attempt_id=attempt_id, input_refs=inputs)


def _project(truth, task, assignment=None):
    return native_context_projection(
        truth, assignment=assignment or _assignment(), task=task,
        mission_id=MISSION, release_id=RELEASE,
    )


def _retry_receipt(truth, *, status="OBSERVED", mode="RETRY_DELTA"):
    install_rc72_retry_context_overlay()
    _ensure_projection_bucket(truth)
    has_delta = status == "OBSERVED"
    truth.append_atomic("RC72_RETRY_CONTEXT_COMPILED", {
        "retry_context_id": "RETRY-CTX-1",
        "release_id": RELEASE,
        "mission_id": MISSION,
        "workitem_id": WORKITEM,
        "attempt_id": "ATT-CHILD",
        "parent_attempt_id": "ATT-PARENT",
        "assignment_id": "ASSIGN-CHILD",
        "observation_status": status,
        "context_mode": mode,
        "canonical_gap_refs": ["GAP-1"],
        "explicit_gap_refs": ["GAP-1"] if has_delta else [],
        "delta_evidence_refs": ["EVD-NEW"] if has_delta else [],
        "changed_dependency_refs": ["DEP-NEW"] if has_delta else [],
        "canonical_lineage_refs_not_in_delta": ["ART-UPSTREAM-1"] if has_delta else [],
        "previous_attempt_summary_ref": "SUMMARY-PARENT" if has_delta else None,
        "full_context_reason": None,
        "retry_delta_sha256": "a" * 64 if has_delta else None,
        "recorded_at": 1,
        "artifact_version": 1,
    })


def test_real_native_context_refs_are_deduped_and_review_candidate_preserved(tmp_path):
    truth, task = _canonical(tmp_path)
    metadata = _project(truth, task)
    assert metadata["context_projection_status"] == "REFERENCE_ONLY"
    assert metadata["context_projection_applied_to_prompt"] is False
    assert metadata["context_mode"] == "NORMAL"
    assert metadata["context_canonical_ref_count"] == 4
    assert metadata["context_effective_ref_count"] == 4
    assert metadata["context_unhydrated_lineage_ref_count"] == 0
    assert metadata["context_envelope_id"].startswith("CTX-")
    assert len(metadata["context_envelope_sha256"]) == 64
    # Same exact R1 refs + Attempt are repeatable and content-addressed.
    assert _project(truth, task) == metadata


def test_observed_r1_retry_delta_only_projects_changed_refs_not_full_context(tmp_path):
    truth, task = _canonical(tmp_path)
    _retry_receipt(truth)
    metadata = _project(truth, task, _assignment(attempt_id="ATT-CHILD", inputs=()))
    assert metadata["context_mode"] == "RETRY_DELTA"
    assert metadata["parent_attempt_id"] == "ATT-PARENT"
    assert metadata["context_canonical_ref_count"] == 3
    assert metadata["context_effective_ref_count"] == 4
    assert metadata["context_unhydrated_lineage_ref_count"] == 2
    assert metadata["context_projection_applied_to_prompt"] is False
    # The business Task, including both required upstream inputs, stays immutable.
    assert truth.query("rc7_task", task_id=WORKITEM)[0]["input_artifact_refs"] == [
        "ART-UPSTREAM-1", "ART-UPSTREAM-2",
    ]


def test_missing_retry_delta_never_claims_unchanged_context_was_excluded(tmp_path):
    truth, task = _canonical(tmp_path)
    _retry_receipt(truth, status="UNKNOWN", mode="RETRY_DELTA_UNKNOWN")
    metadata = _project(truth, task, _assignment(attempt_id="ATT-CHILD", inputs=()))
    assert metadata["context_mode"] == "RETRY_DELTA_UNKNOWN"
    assert metadata["context_unhydrated_lineage_ref_count"] == 0
    assert metadata["parent_attempt_id"] == "ATT-PARENT"


def test_cross_mission_or_forged_task_ref_is_rejected(tmp_path):
    truth, task = _canonical(tmp_path)
    with pytest.raises(NativeContextProjectionError, match="TASK_SCOPE_MISMATCH"):
        native_context_projection(
            truth, assignment=_assignment(), task=task,
            mission_id="M-OTHER", release_id=RELEASE,
        )
    with pytest.raises(NativeContextProjectionError, match="WORKER_INPUT_REFS_INVALID"):
        _project(truth, task, _assignment(inputs=("ART-UPSTREAM-1", None)))


def test_native_context_projection_r1_is_reference_only_never_claimed_savings(tmp_path):
    truth, task = _canonical(tmp_path)
    metadata = _project(truth, task)
    economy = TokenEconomyService(truth, release_id=RELEASE)
    economy.configure_budget(
        mission_id=MISSION, max_total_tokens=1000, max_model_calls=10,
        max_single_call_tokens=100, max_retry_tokens=100,
        max_retry_calls=10,
    )
    admitted = economy.admit_call(
        mission_id=MISSION, node="N4_TEST_DESIGN", stage="TEST_DESIGN",
        workitem_id=WORKITEM, attempt_id="ATT-1", agent_id="designer",
        call_class=ModelCallClass.LLM_REQUIRED, retry=False,
        prompt="full native mandatory design prompt is unmodified",
        context_projection=metadata,
    )
    assert admitted.admitted
    row = truth.query("rc72_token_call", call_id=admitted.call_id)[0]
    assert row["context_envelope_sha256"] == metadata["context_envelope_sha256"]
    assert row["context_projection_status"] == "REFERENCE_ONLY"
    assert row["context_projection_applied_to_prompt"] is False
    assert row["context_bytes"] == len(
        "full native mandatory design prompt is unmodified".encode()
    )
    tampered = dict(metadata, context_projection_applied_to_prompt=True)
    with pytest.raises(TokenEconomyError, match="SAVINGS_UNPROVEN"):
        economy.admit_call(
            mission_id=MISSION, node="N4_TEST_DESIGN", stage="TEST_DESIGN",
            workitem_id=WORKITEM, attempt_id="ATT-2", agent_id="designer",
            call_class=ModelCallClass.LLM_REQUIRED, retry=True,
            prompt="do not claim savings without native prompt proof",
            context_projection=tampered,
        )
    assert len(truth.query("rc72_token_call", mission_id=MISSION)) == 1
