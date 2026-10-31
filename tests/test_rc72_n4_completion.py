from pathlib import Path

import pytest

from rc7_runtime.dsh_test_design_evaluator import DshTestDesignEvaluator
from rc7_runtime.rc72_n4_completion import N4CompletionError, N4DeliveryGateService
from rc7_runtime.rc72_n4_test_design_anchor import N4TestDesignEvidenceAnchorService
from rc7_runtime.rc72_n4_test_design_handoff import N4TestDesignDshHandoffService
from rc7_runtime.rc72_n4_test_design_promotion import N4TestDesignCandidatePromotionService
from rc7_runtime.rc72_n4_test_design_review import N4TestDesignReviewService

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc7_dsh_test_design_evaluator import FakeDesignReviewerLauncher
from test_rc72_n4_test_design_handoff import TOOL_GRAPH, TOOL_READ, _launcher, _ready
from test_rc72_n4_test_design_review import FailIfReviewerInvoked


class ScopedReviewerLauncher(FakeDesignReviewerLauncher):
    def __init__(self, suffix: str) -> None:
        super().__init__(tool_mode="full", decision="PASS")
        self.suffix = suffix

    def assign(self, **kwargs):
        assignment = super().assign(**kwargs)
        assignment.worker_instance_id = "worker-test-design-reviewer-%s" % self.suffix
        assignment.assignment_id = "assign-design-reviewer-%s" % self.suffix
        return assignment

    def execute(self, assignment, prompt):
        reviewer, output = super().execute(assignment, prompt)
        reviewer.dsh_session_id = "session-test-design-reviewer-%s" % self.suffix
        reviewer.evidence_refs = (
            "dsh://session/session-test-design-reviewer-%s" % self.suffix,
        )
        return reviewer, output


def _reviewed_batch(tmp_path: Path, monkeypatch, *, gap_index=None, leave_unreviewed=None):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    scopes = list(dispatched["design_scopes"])
    for index, scope in enumerate(scopes):
        is_gap = gap_index == index
        handoff = N4TestDesignDshHandoffService(
            truth,
            source_commit=COMMIT,
            launcher=_launcher(
                tmp_path,
                truth,
                fixed_session="session-n4-design-scope-%d" % index,
                gap=is_gap,
            ),
            allowed_tools=[TOOL_READ, TOOL_GRAPH],
        ).handoff(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )
        N4TestDesignEvidenceAnchorService(
            truth,
            source_commit=COMMIT,
            state_root=str(tmp_path / "state-n4-design"),
        ).anchor(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )
        N4TestDesignCandidatePromotionService(
            truth,
            release_id=RELEASE,
            mission_id=MISSION,
            source_commit=COMMIT,
            state_root=str(tmp_path / "state-n4-design"),
        ).promote(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )
        if leave_unreviewed == index:
            continue
        launcher = FailIfReviewerInvoked() if is_gap else ScopedReviewerLauncher(str(index))
        reviewed = N4TestDesignReviewService(
            truth,
            release_id=RELEASE,
            mission_id=MISSION,
            source_commit=COMMIT,
            evaluator=DshTestDesignEvaluator(launcher),
        ).review(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )
        if is_gap:
            assert reviewed["task_state"] == "REPAIR_REQUIRED"
        else:
            assert reviewed["task_state"] == "PASS"
    return truth, scopes


def test_n4_complete_requires_all_scopes_and_releases_n5_only_after_aggregate_pass(
    tmp_path: Path, monkeypatch
):
    truth, scopes = _reviewed_batch(tmp_path, monkeypatch)
    result = N4DeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)

    assert result["delivery"]["status"] == "DELIVERY_ADMITTED"
    assert result["delivery"]["scope_count"] == len(scopes)
    assert result["delivery"]["passed_scope_count"] == len(scopes)
    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["failed"] == []
    assert result["gate"]["n4_state"] == "PASS"
    assert result["gate"]["n5_state"] == "READY"

    delivery = truth.query(
        "rc72_node_delivery", delivery_id=result["delivery"]["delivery_id"]
    )[0]
    assert len(delivery["artifact_refs"]) == len(scopes)
    assert len(delivery["created_by_workitems"]) == len(scopes)
    assert delivery["known_gaps"] == []
    assert delivery["sufficiency_score"] == 1.0
    assert sum(ref.startswith("n4-anchor://") for ref in delivery["input_refs"]) == len(scopes)
    assert sum(ref.startswith("evaluation://") for ref in delivery["input_refs"]) == len(scopes)

    gate = truth.query("rc72_node_gate", gate_id=result["gate"]["gate_id"])[0]
    assert gate["decision"] == "PASS"
    assert "N4_CANONICAL_SCOPE_SET_COMPLETE" in gate["passed"]
    assert "N4_REQUIRED_OBLIGATIONS_COVERED" in gate["passed"]
    assert "N4_CASE_CONTRACT_COMPLETE" in gate["passed"]
    assert "N4_ORACLE_EVIDENCE_DURABLE" in gate["passed"]
    assert "N4_FRESH_REVIEW_SESSION" in gate["passed"]
    assert "N4_SEMANTIC_SUFFICIENCY_PASS" in gate["passed"]

    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n4["state"] == "PASS"
    assert n5["state"] == "READY"
    transitions = [
        row
        for row in truth.query("rc72_node_transition", mission_id=MISSION)
        if row.get("from_node_type") == "N4_TEST_DESIGN"
        and row.get("to_node_type") == "N5_TEST_DATA"
    ]
    assert len(transitions) == 1
    assert transitions[0]["source_gate_id"] == gate["gate_id"]

    replay = N4DeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)
    assert replay["delivery"]["status"] == "RESUMED"
    assert replay["gate"]["status"] == "RESUMED"
    assert replay["gate"]["decision"] == "PASS"
    assert replay["gate"]["n5_state"] == "READY"
    assert len(
        [
            row
            for row in truth.query("rc72_node_transition", mission_id=MISSION)
            if row.get("from_node_type") == "N4_TEST_DESIGN"
            and row.get("to_node_type") == "N5_TEST_DATA"
        ]
    ) == 1


def test_n4_reviewed_gap_scope_forces_needs_revision_and_keeps_n5_locked(
    tmp_path: Path, monkeypatch
):
    truth, scopes = _reviewed_batch(tmp_path, monkeypatch, gap_index=0)
    assert len(scopes) >= 1

    result = N4DeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)

    assert result["delivery"]["status"] == "DELIVERY_ADMITTED"
    assert result["delivery"]["passed_scope_count"] == len(scopes) - 1
    assert result["gate"]["decision"] == "NEEDS_REVISION"
    assert result["gate"]["n4_state"] == "NEEDS_REVISION"
    assert result["gate"]["n5_state"] == "NOT_STARTED"
    assert "N4_ALL_DESIGN_TASKS_PASS" in result["gate"]["failed"]
    assert "N4_ALL_DESIGN_EVALUATIONS_PASS" in result["gate"]["failed"]
    assert "N4_REQUIRED_OBLIGATIONS_COVERED" in result["gate"]["failed"]
    assert "N4_CASE_CONTRACT_COMPLETE" in result["gate"]["failed"]
    assert "N4_SEMANTIC_SUFFICIENCY_PASS" in result["gate"]["failed"]
    assert "N4_NO_CANDIDATE_GAPS" in result["gate"]["failed"]
    assert "N4_NO_UNRESOLVED_DESIGN_GAPS" in result["gate"]["failed"]
    assert truth.query(
        "rc72_node_transition",
        mission_id=MISSION,
        from_node_type="N4_TEST_DESIGN",
        to_node_type="N5_TEST_DATA",
    ) == []


def test_n4_delivery_forbidden_until_every_scope_has_completed_review(
    tmp_path: Path, monkeypatch
):
    truth, scopes = _reviewed_batch(tmp_path, monkeypatch, leave_unreviewed=0)
    assert scopes

    with pytest.raises(
        N4CompletionError,
        match="REVIEW_INCOMPLETE",
    ):
        N4DeliveryGateService(
            truth, source_commit=COMMIT
        ).admit_delivery(release_batch_id=BATCH)

    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n4["state"] == "RUNNING"
    assert n5["state"] == "NOT_STARTED"
