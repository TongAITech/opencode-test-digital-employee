from pathlib import Path
import hashlib
import json

import pytest

from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
)
from rc7_runtime.rc72_n2_completion import N2CompletionError, N2DeliveryGateService
from rc7_runtime.truth_overlay import append_entity

from rc72_n2_test_support import (
    BATCH,
    COMMIT,
    MISSION,
    RELEASE,
    REQUIREMENTS,
    build_truth,
    dispatch_n2,
)


def _sha256(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _semantic(requirement_id):
    source_id = "SRC-%s" % requirement_id
    atom_id = "ATOM-%s" % requirement_id
    evidence_id = "EVD-N2-SOURCE-%s" % requirement_id
    return {
        "requirement_id": requirement_id,
        "sst_ids": ["SST-%s" % requirement_id],
        "source_refs": ["starlink://requirement/%s" % requirement_id],
        "candidate_unknowns": [],
        "candidate_gaps": [],
        "sufficiency_v2_required": True,
        "source_assertions": [{"id": source_id, "text": "source"}],
        "atomic_statements": [
            {
                "id": atom_id,
                "text": "testable requirement",
                "source_ref": "starlink://requirement/%s" % requirement_id,
                "testable": True,
            }
        ],
        "trace_links": [
            {"source_id": source_id, "atomic_id": atom_id, "evidence_ref": evidence_id}
        ],
        "business_rules": [{"id": "BR-%s" % requirement_id}],
        "roles": [{"id": "ROLE-%s" % requirement_id}],
        "preconditions": [{"id": "PRE-%s" % requirement_id}],
        "normal_paths": [{"id": "NP-%s" % requirement_id}],
        "negative_paths": [{"id": "NEG-%s" % requirement_id}],
        "boundaries": [{"id": "BOUND-%s" % requirement_id}],
        "states": [{"id": "STATE-%s" % requirement_id}],
        "data_constraints": [{"id": "DATA-%s" % requirement_id}],
        "dependencies": [{"id": "DEP-%s" % requirement_id}],
        "side_effects": [{"id": "SIDE-%s" % requirement_id}],
        "dimension_exclusions": [],
    }


def _seed_reviewed_requirements(tmp_path: Path, *, repair_requirement=None, leave_unreviewed=None):
    truth = build_truth(tmp_path)
    dispatch_n2(truth)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    dispatches = truth.query("rc72_n2_requirement_dispatch", release_batch_id=BATCH)
    by_task = {row["workitem_id"]: row for row in dispatches}
    produced = {}

    # Produce every canonical candidate before any repair evaluation can create
    # higher-priority REPAIR work that would alter scheduler selection.
    for index in range(len(REQUIREMENTS)):
        worker = "ANALYZER-N2-%d" % index
        leased = control.lease_next(
            worker_ref=worker,
            capabilities=["requirement_reasoning"],
        )
        assert leased is not None
        dispatch = by_task[leased.task_id]
        requirement_id = dispatch["requirement_id"]
        control.start(leased.task_id, worker_ref=worker)

        semantic = _semantic(requirement_id)
        artifact_id = "ART-N2-%s" % requirement_id
        source_evidence_id = "EVD-N2-SOURCE-%s" % requirement_id
        envelope = {
            "task_id": leased.task_id,
            "artifact": {
                "artifact_id": artifact_id,
                "artifact_type": "REQUIREMENT_ANALYSIS_OUTPUT",
                "content_ref": "starlink://requirement/%s" % requirement_id,
                "parent_refs": list(leased.input_artifact_refs),
                "evidence_refs": [source_evidence_id],
            },
            "semantic_payload": semantic,
        }
        raw = (json.dumps(envelope, sort_keys=True) + "\n").encode("utf-8")
        path = tmp_path / ("candidate-%s.json" % requirement_id)
        path.write_bytes(raw)
        source_ref = "starlink://requirement/%s" % requirement_id
        evidence = Evidence(
            evidence_id=source_evidence_id,
            mission_id=MISSION,
            kind="N2_REQUIREMENT_SOURCE_PROOF",
            source_ref=source_ref,
            content_ref=source_ref,
            subject_refs=[leased.task_id, requirement_id],
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=MISSION,
            artifact_type="REQUIREMENT_ANALYSIS_OUTPUT",
            producer_task_id=leased.task_id,
            content_ref="file://" + str(path.resolve()),
            parent_refs=list(leased.input_artifact_refs),
            evidence_refs=[source_evidence_id],
            content_hash=_sha256(raw),
        )
        control.submit_worker_output(
            WorkerOutput(
                task_id=leased.task_id,
                worker_ref=worker,
                artifacts=(artifact,),
                evidence=(evidence,),
            )
        )
        produced[requirement_id] = (leased.task_id, artifact_id, worker, source_evidence_id)

    for requirement_id in REQUIREMENTS:
        if requirement_id == leave_unreviewed:
            continue
        task_id, artifact_id, analyzer, source_evidence_id = produced[requirement_id]
        reviewer = "REVIEWER-N2-%s" % requirement_id
        review_evidence_id = "EVD-N2-REVIEW-%s" % requirement_id
        append_entity(
            truth,
            Evidence(
                evidence_id=review_evidence_id,
                mission_id=MISSION,
                kind="INDEPENDENT_REQUIREMENT_REVIEW_PROOF",
                source_ref="dsh://worker/%s" % reviewer,
                content_ref="dsh://session/session-review-%s" % requirement_id,
                subject_refs=[task_id, artifact_id],
            ),
            release_id=RELEASE,
            artifact_version=1,
        )
        gaps = ()
        result = EvaluationResult.PASS
        gap_refs = []
        if requirement_id == repair_requirement:
            gap = Gap(
                gap_id="GAP-N2-%s" % requirement_id,
                mission_id=MISSION,
                source_node="REQUIREMENT_ANALYSIS",
                category="REQUIREMENT_AMBIGUITY",
                severity=GapSeverity.HIGH,
                target_node="REQUIREMENT_ANALYSIS",
                description="fixture unresolved requirement ambiguity",
                subject_refs=[artifact_id, requirement_id, task_id],
                evidence_refs=[source_evidence_id, review_evidence_id],
                acceptance_criteria=["resolve ambiguity with durable evidence"],
            )
            gaps = (gap,)
            gap_refs = [gap.gap_id]
            result = EvaluationResult.REPAIR_REQUIRED
        evaluation = Evaluation(
            evaluation_id="EVAL-N2-%s" % requirement_id,
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            artifact_refs=[artifact_id],
            result=result,
            evaluator_ref="dsh:%s+deterministic-requirement-gate" % reviewer,
            dimensions={"gate_status": "SUFFICIENT" if result == EvaluationResult.PASS else "NOT_SUFFICIENT_CONTENT"},
            gap_refs=gap_refs,
            evidence_refs=[source_evidence_id, review_evidence_id],
        )
        control.accept_evaluation(task_id, evaluation=evaluation, gaps=gaps)
    return truth, produced


def test_all_independently_accepted_requirements_gate_n2_pass_and_release_n3(tmp_path):
    truth, _ = _seed_reviewed_requirements(tmp_path)
    service = N2DeliveryGateService(truth, source_commit=COMMIT)

    result = service.complete(release_batch_id=BATCH)

    assert result["delivery"]["requirement_count"] == len(REQUIREMENTS)
    assert result["delivery"]["passed_requirement_count"] == len(REQUIREMENTS)
    assert result["delivery"]["known_gap_ids"] == []
    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["failed"] == []
    assert result["gate"]["n2_state"] == "PASS"
    assert result["gate"]["n3_state"] == "READY"
    n3 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS")[0]
    assert n3["state"] == "READY"
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []

    resumed = service.complete(release_batch_id=BATCH)
    assert resumed["delivery"]["status"] == "RESUMED"
    assert resumed["gate"]["status"] == "RESUMED"
    assert resumed["gate"]["n3_state"] == "READY"


def test_one_repair_required_requirement_forces_n2_revision_and_keeps_n3_locked(tmp_path):
    repair_requirement = REQUIREMENTS[0]
    truth, _ = _seed_reviewed_requirements(
        tmp_path, repair_requirement=repair_requirement
    )
    service = N2DeliveryGateService(truth, source_commit=COMMIT)

    result = service.complete(release_batch_id=BATCH)

    assert result["gate"]["decision"] == "NEEDS_REVISION"
    assert result["gate"]["n2_state"] == "NEEDS_REVISION"
    assert result["gate"]["n3_state"] == "NOT_STARTED"
    assert "N2_ALL_REQUIREMENT_TASKS_PASS" in result["gate"]["failed"]
    assert "N2_ALL_REQUIREMENT_EVALUATIONS_PASS" in result["gate"]["failed"]
    assert "N2_NO_UNRESOLVED_REQUIREMENT_GAPS" in result["gate"]["failed"]
    assert "GAP-N2-%s" % repair_requirement in result["delivery"]["known_gap_ids"]
    n3 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS")[0]
    assert n3["state"] == "NOT_STARTED"


def test_incomplete_requirement_review_cannot_fabricate_n2_delivery(tmp_path):
    truth, _ = _seed_reviewed_requirements(
        tmp_path, leave_unreviewed=REQUIREMENTS[-1]
    )

    with pytest.raises(N2CompletionError, match="REVIEW_INCOMPLETE"):
        N2DeliveryGateService(truth, source_commit=COMMIT).admit_delivery(
            release_batch_id=BATCH
        )

    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N2_REQUIREMENT"
    ) == []
    n3 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS")[0]
    assert n3["state"] == "NOT_STARTED"
