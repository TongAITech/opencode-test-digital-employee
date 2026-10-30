from pathlib import Path
import json
import subprocess

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.authority import AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
from rc7_runtime.rc72_n2_requirement_review import N2RequirementReviewService
from rc7_runtime.rc72_n2_revision_completion import N2RevisionAwareDeliveryGateService
from rc7_runtime.rc72_n2_revision_execution import (
    N2RevisionCandidatePromotionService,
    N2RevisionDshHandoffService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE, REQUIREMENTS
from test_rc72_n2_revision_execution import TOOL, _launcher, _prepared_revision


REVIEW_TOOL = "review-source-probe"


def _reviewer(tmp_path, truth):
    dsh = tmp_path / "dsh-n2-revision-reviewer"
    dsh.write_text("fixture", encoding="utf-8")
    patch = tmp_path / "patch-n2-revision-reviewer.json"
    patch.write_text("{}", encoding="utf-8")

    def runner(command, **kwargs):
        events = [
            {"type": "session", "session_id": "session-n2-revision-review-fresh"},
            {"type": "tool_call", "tool_name": REVIEW_TOOL},
            {
                "type": "final",
                "text": json.dumps({
                    "decision": "PASS",
                    "gap_ids": [],
                    "summary": "independent source-backed revision review passed",
                }),
            },
        ]
        stdout = "\n".join(json.dumps(event) for event in events) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=AuthorityRuntime(b"rc72-n2-revision-reviewer-key"),
        coordinator_instance_id="coordinator-n2-revision-reviewer",
        release_id=RELEASE,
        state_root=str(tmp_path / "review-state"),
        command_runner=runner,
    )


def test_revision_candidate_independent_pass_closes_old_gap_and_admits_n2_delivery_v2(tmp_path: Path):
    truth, affected, revision = _prepared_revision(tmp_path)
    analyzer_launcher = _launcher(tmp_path, truth, affected)
    N2RevisionDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=analyzer_launcher,
        allowed_tools=[TOOL],
    ).handoff(release_batch_id=BATCH, requirement_id=affected)
    promoted = N2RevisionCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state"),
    ).promote(release_batch_id=BATCH, requirement_id=affected)

    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    reviewed = N2RequirementReviewService(
        control,
        DshRequirementEvaluator(
            _reviewer(tmp_path, truth),
            allowed_tools=[REVIEW_TOOL],
        ),
    ).review_and_apply(
        task_id=revision["revision_workitem_id"],
        artifact_id=promoted["artifact_id"],
    )

    assert reviewed.evaluation_result == "PASS"
    assert reviewed.task_state == "PASS"
    assert reviewed.worker_uncertainty_guard_triggered is False
    revised_task = truth.query("rc7_task", task_id=revision["revision_workitem_id"])[0]
    assert revised_task["state"] == "PASS"
    for gap_id in revision["gap_refs"]:
        gap = truth.query("rc7_gap", gap_id=gap_id)[0]
        assert gap["state"] == "RESOLVED"
        assert gap["resolution_evaluation_id"] == reviewed.evaluation_id

    completed = N2RevisionAwareDeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)

    assert completed["delivery"]["delivery_version"] == 2
    assert completed["delivery"]["revision_generations"][affected] == 2
    unaffected = next(item for item in REQUIREMENTS if item != affected)
    assert completed["delivery"]["revision_generations"][unaffected] == 1
    assert completed["delivery"]["known_gap_ids"] == []
    assert completed["gate"]["decision"] == "PASS"
    assert completed["gate"]["n2_state"] == "PASS"
    assert completed["gate"]["n3_state"] == "READY"

    deliveries = truth.query("rc72_node_delivery", mission_id=MISSION, node_type="N2_REQUIREMENT")
    assert sorted(row["version"] for row in deliveries) == [1, 2]
    v2 = next(row for row in deliveries if row["version"] == 2)
    assert "n2-revision://%s" % revision["revision_id"] in v2["input_refs"]
    assert revision["revision_workitem_id"] in v2["created_by_workitems"]
    assert revision["previous_workitem_id"] not in v2["created_by_workitems"]

    n3 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS")[0]
    assert n3["state"] == "READY"
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
