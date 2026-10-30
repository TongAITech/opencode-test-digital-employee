from pathlib import Path
import json
import subprocess

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.authority import AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence
from rc7_runtime.rc72_n2_requirement_review import N2RequirementReviewService
from rc7_runtime.rc72_n2_revision import N2RevisionDispatchService
from rc7_runtime.rc72_n2_revision_completion import N2RevisionAwareDeliveryGateService
from rc7_runtime.rc72_n2_revision_execution import (
    N2RevisionCandidatePromotionService,
    N2RevisionDshHandoffService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE, REQUIREMENTS
from test_rc72_n2_revision_closed_loop import REVIEW_TOOL
from test_rc72_n2_revision_execution import TOOL, _launcher, _prepared_revision


def _gap_reviewer(tmp_path, truth):
    dsh = tmp_path / "dsh-n2-revision-gap-reviewer"
    dsh.write_text("fixture", encoding="utf-8")
    patch = tmp_path / "patch-n2-revision-gap-reviewer.json"
    patch.write_text("{}", encoding="utf-8")

    def runner(command, **kwargs):
        events = [
            {"type": "session", "session_id": "session-n2-revision-gap-review-fresh"},
            {"type": "tool_call", "tool_name": REVIEW_TOOL},
            {
                "type": "final",
                "text": json.dumps({
                    "decision": "GAPS",
                    "gap_ids": ["review-source-ambiguity"],
                    "summary": "one source-backed ambiguity remains",
                }),
            },
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(event) for event in events) + "\n",
            stderr="",
        )

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=AuthorityRuntime(b"rc72-n2-revision-gap-reviewer-key"),
        coordinator_instance_id="coordinator-n2-revision-gap-reviewer",
        release_id=RELEASE,
        state_root=str(tmp_path / "gap-review-state"),
        command_runner=runner,
    )


def _repair_revision_gap(truth, revision_task_id, requirement_id):
    source = truth.query("rc7_task", task_id=revision_task_id)[0]
    source_gaps = set(source.get("gap_refs") or [])
    repair_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR"
        and source_gaps.intersection(set(row.get("gap_refs") or []))
        and row.get("state") == "READY"
    ]
    assert len(repair_tasks) == 1
    repair = repair_tasks[0]
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    worker = "REPAIR-REVISION-GAP-%s" % requirement_id
    leased = control.lease_next(worker_ref=worker, capabilities=["requirement_reasoning"])
    assert leased is not None and leased.task_id == repair["task_id"]
    control.start(leased.task_id, worker_ref=worker)
    evidence = Evidence(
        evidence_id="EVD-REPAIR-REV2-%s" % requirement_id,
        mission_id=MISSION,
        kind="REQUIREMENT_REPAIR_PROOF",
        source_ref="starlink://requirement/%s?revision=2-repair" % requirement_id,
        content_ref="starlink://requirement/%s?revision=2-repair" % requirement_id,
        subject_refs=[leased.task_id, requirement_id],
    )
    artifact = Artifact(
        artifact_id="ART-REPAIR-REV2-%s" % requirement_id,
        mission_id=MISSION,
        artifact_type="REQUIREMENT_REPAIR_OUTPUT",
        producer_task_id=leased.task_id,
        content_ref=evidence.content_ref,
        evidence_refs=[evidence.evidence_id],
    )
    control.submit_worker_output(WorkerOutput(
        task_id=leased.task_id,
        worker_ref=worker,
        artifacts=(artifact,),
        evidence=(evidence,),
    ))
    control.accept_evaluation(
        leased.task_id,
        evaluation=Evaluation(
            evaluation_id="EVAL-REPAIR-REV2-%s" % requirement_id,
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            artifact_refs=[artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="independent-repair-reviewer-rev2-%s" % requirement_id,
            dimensions={"repair_evidence": "PASS"},
            evidence_refs=[evidence.evidence_id],
        ),
    )


def test_later_failed_n2_gate_creates_generation3_fresh_requirement_work(tmp_path: Path):
    truth, affected, generation2 = _prepared_revision(tmp_path)
    analyzer = _launcher(tmp_path, truth, affected)
    N2RevisionDshHandoffService(
        truth, source_commit=COMMIT, launcher=analyzer, allowed_tools=[TOOL]
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
            _gap_reviewer(tmp_path, truth), allowed_tools=[REVIEW_TOOL]
        ),
    ).review_and_apply(
        task_id=generation2["revision_workitem_id"],
        artifact_id=promoted["artifact_id"],
    )
    assert reviewed.evaluation_result == "REPAIR_REQUIRED"
    assert reviewed.task_state == "REPAIR_REQUIRED"
    assert reviewed.gap_ids

    failed = N2RevisionAwareDeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)
    assert failed["delivery"]["delivery_version"] == 2
    assert failed["gate"]["decision"] == "NEEDS_REVISION"
    assert failed["gate"]["n3_state"] == "NOT_STARTED"

    _repair_revision_gap(
        truth, generation2["revision_workitem_id"], affected
    )
    reactivated = truth.query(
        "rc7_task", task_id=generation2["revision_workitem_id"]
    )[0]
    assert reactivated["state"] == "READY"

    generation3_plan = N2RevisionDispatchService(
        truth, source_commit=COMMIT
    ).plan_and_assign(release_batch_id=BATCH)
    assert generation3_plan["status"] == "ASSIGNED"
    assert len(generation3_plan["revisions"]) == 1
    generation3 = generation3_plan["revisions"][0]
    assert generation3["requirement_id"] == affected
    assert generation3["revision_generation"] == 3
    assert generation3["revision_id"] != generation2["revision_id"]
    assert generation3["revision_workitem_id"] != generation2["revision_workitem_id"]
    assert generation3["revision_worker_instance_id"] != generation2["revision_worker_instance_id"]
    assert generation3["previous_workitem_id"] == generation2["revision_workitem_id"]
    assert generation3["previous_artifact_id"] == promoted["artifact_id"]

    gen2_task = truth.query(
        "rc7_task", task_id=generation2["revision_workitem_id"]
    )[0]
    gen3_task = truth.query(
        "rc7_task", task_id=generation3["revision_workitem_id"]
    )[0]
    assert gen2_task["state"] == "STALE"
    assert gen3_task["state"] == "LEASED"
    assert gen3_task["lease_owner"] == generation3["revision_worker_instance_id"]
    n3 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS")[0]
    assert n3["state"] == "NOT_STARTED"
