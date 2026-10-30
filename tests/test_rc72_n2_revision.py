from pathlib import Path

import pytest

from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence
from rc7_runtime.rc72_n2_completion import N2DeliveryGateService
from rc7_runtime.rc72_n2_revision import N2RevisionDispatchService, N2RevisionError

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE, REQUIREMENTS
from test_rc72_n2_completion import _seed_reviewed_requirements


def _drive_repair_to_evidence_pending(truth, requirement_id):
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    repair_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR"
        and any(requirement_id in str(ref) for ref in list(row.get("gap_refs") or []))
    ]
    if not repair_tasks:
        # Gap ids are stable but do not necessarily embed Requirement text. Bind
        # the repair task through the source Requirement task's gap set instead.
        source_dispatch = truth.query(
            "rc72_n2_requirement_dispatch",
            release_batch_id=BATCH,
            requirement_id=requirement_id,
        )[0]
        source = truth.query("rc7_task", task_id=source_dispatch["workitem_id"])[0]
        source_gaps = set(source.get("gap_refs") or [])
        repair_tasks = [
            row for row in truth.query("rc7_task", mission_id=MISSION)
            if row.get("task_type") == "REPAIR"
            and source_gaps.intersection(set(row.get("gap_refs") or []))
        ]
    assert len(repair_tasks) == 1
    repair = repair_tasks[0]
    worker = "REPAIR-WORKER-%s" % requirement_id
    leased = control.lease_next(worker_ref=worker, capabilities=["requirement_reasoning"])
    assert leased is not None and leased.task_id == repair["task_id"]
    control.start(leased.task_id, worker_ref=worker)
    evidence = Evidence(
        evidence_id="EVD-REPAIR-%s" % requirement_id,
        mission_id=MISSION,
        kind="REQUIREMENT_REPAIR_PROOF",
        source_ref="starlink://requirement/%s" % requirement_id,
        content_ref="starlink://requirement/%s?revision=repair" % requirement_id,
        subject_refs=[leased.task_id, requirement_id],
    )
    artifact = Artifact(
        artifact_id="ART-REPAIR-%s" % requirement_id,
        mission_id=MISSION,
        artifact_type="REQUIREMENT_REPAIR_OUTPUT",
        producer_task_id=leased.task_id,
        content_ref="starlink://requirement/%s?revision=repair" % requirement_id,
        evidence_refs=[evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=leased.task_id,
            worker_ref=worker,
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )
    control.accept_evaluation(
        leased.task_id,
        evaluation=Evaluation(
            evaluation_id="EVAL-REPAIR-%s" % requirement_id,
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            artifact_refs=[artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="independent-repair-reviewer-%s" % requirement_id,
            dimensions={"repair_evidence": "PASS"},
            evidence_refs=[evidence.evidence_id],
        ),
    )


def test_n2_revision_waits_for_gap_repair_evidence(tmp_path: Path):
    affected = REQUIREMENTS[0]
    truth, _ = _seed_reviewed_requirements(tmp_path, repair_requirement=affected)
    result = N2DeliveryGateService(truth, source_commit=COMMIT).complete(
        release_batch_id=BATCH
    )
    assert result["gate"]["decision"] == "NEEDS_REVISION"

    with pytest.raises(N2RevisionError, match="REPAIR_EVIDENCE_NOT_READY"):
        N2RevisionDispatchService(truth, source_commit=COMMIT).plan_and_assign(
            release_batch_id=BATCH
        )

    n2 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N2_REQUIREMENT")[0]
    n3 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS")[0]
    assert n2["state"] == "NEEDS_REVISION"
    assert n3["state"] == "NOT_STARTED"
    assert truth.query("rc72_n2_revision_receipt", release_batch_id=BATCH) == []


def test_n2_revision_creates_fresh_work_only_for_affected_requirement(tmp_path: Path):
    affected = REQUIREMENTS[0]
    unaffected = REQUIREMENTS[1]
    truth, _ = _seed_reviewed_requirements(tmp_path, repair_requirement=affected)
    N2DeliveryGateService(truth, source_commit=COMMIT).complete(release_batch_id=BATCH)

    affected_dispatch = truth.query(
        "rc72_n2_requirement_dispatch", release_batch_id=BATCH, requirement_id=affected
    )[0]
    unaffected_dispatch = truth.query(
        "rc72_n2_requirement_dispatch", release_batch_id=BATCH, requirement_id=unaffected
    )[0]
    old_affected = truth.query("rc7_task", task_id=affected_dispatch["workitem_id"])[0]
    old_worker = old_affected["lease_owner"]

    _drive_repair_to_evidence_pending(truth, affected)
    reactivated = truth.query("rc7_task", task_id=affected_dispatch["workitem_id"])[0]
    assert reactivated["state"] == "READY"

    result = N2RevisionDispatchService(truth, source_commit=COMMIT).plan_and_assign(
        release_batch_id=BATCH
    )

    assert result["status"] == "ASSIGNED"
    assert result["node_state"] == "RUNNING"
    assert result["n3_state"] == "NOT_STARTED"
    assert len(result["revisions"]) == 1
    revision = result["revisions"][0]
    assert revision["requirement_id"] == affected
    assert revision["revision_generation"] == 2
    assert revision["revision_workitem_id"] != affected_dispatch["workitem_id"]
    assert revision["revision_worker_instance_id"] != old_worker

    retired = truth.query("rc7_task", task_id=affected_dispatch["workitem_id"])[0]
    unchanged = truth.query("rc7_task", task_id=unaffected_dispatch["workitem_id"])[0]
    revision_task = truth.query("rc7_task", task_id=revision["revision_workitem_id"])[0]
    assert retired["state"] == "STALE"
    assert unchanged["state"] == "PASS"
    assert revision_task["state"] == "LEASED"
    assert revision_task["lease_owner"] == revision["revision_worker_instance_id"]
    assert revision_task["gap_refs"] == revision["gap_refs"]
    assert revision["previous_artifact_id"] in revision_task["input_artifact_refs"]

    assert truth.query(
        "rc72_n2_requirement_attempt", workitem_id=revision["revision_workitem_id"]
    ) == []
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    ) == []
