from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.authority import AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n2_candidate_guard import N2GovernedRequirementHandoffService
from rc7_runtime.rc72_n2_requirement_assignment import N2RequirementAssignmentService
from rc7_runtime.rc72_n2_requirement_promotion import N2RequirementCandidatePromotionService
from rc7_runtime.rc72_n2_requirement_review import N2RequirementReviewService

from rc72_n2_test_support import (
    BATCH,
    COMMIT,
    MISSION,
    RELEASE,
    REQUIREMENTS,
    build_truth,
    dispatch_n2,
)


ANALYZER_TOOL = "requirement-source-probe"
REVIEW_TOOL = "review-source-probe"


def _candidate(requirement_id, *, sst_ids=None, unknowns=None, gaps=None):
    source_ref = "starlink://requirement/%s" % requirement_id
    source_id = "SRC-%s" % requirement_id
    atom_id = "ATOM-%s" % requirement_id
    analysis = {
        "atomic_statements": [
            {
                "id": atom_id,
                "text": "fixture requirement assertion",
                "source_ref": source_ref,
                "testable": True,
            }
        ],
        "source_assertions": [
            {"id": source_id, "text": "fixture source", "source_ref": source_ref}
        ],
        "trace_links": [
            {"source_id": source_id, "atomic_id": atom_id, "evidence_ref": source_ref}
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
    return {
        "status": "CANDIDATE",
        "facts": {
            "requirement_id": requirement_id,
            "sst_ids": list(["SST-%s" % requirement_id] if sst_ids is None else sst_ids),
            "source_refs": [source_ref],
            "analysis": analysis,
        },
        "unknowns": list(unknowns or []),
        "gaps": list(gaps or []),
    }


def _prepare_promoted(
    tmp_path,
    *,
    requirement_id=None,
    sst_ids=None,
    unknowns=None,
    gaps=None,
):
    requirement_id = requirement_id or REQUIREMENTS[0]
    truth = build_truth(tmp_path)
    dispatch_n2(truth)
    N2RequirementAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)

    analyzer_bin = tmp_path / "dsh-analyzer-review-test"
    analyzer_bin.write_text("fixture", encoding="utf-8")
    analyzer_patch = tmp_path / "patch-analyzer-review-test.json"
    analyzer_patch.write_text("{}", encoding="utf-8")

    def analyzer_runner(command, **kwargs):
        prompt = str(command[-1])
        matches = [req for req in REQUIREMENTS if req in prompt]
        assert len(matches) == 1
        req = matches[0]
        candidate = _candidate(
            req,
            sst_ids=sst_ids if req == requirement_id else None,
            unknowns=unknowns if req == requirement_id else None,
            gaps=gaps if req == requirement_id else None,
        )
        events = [
            {"type": "session", "session_id": "session-analyzer-%s" % req},
            {"type": "tool_call", "tool_name": ANALYZER_TOOL},
            {"type": "final", "text": json.dumps(candidate, ensure_ascii=False)},
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
            stderr="",
        )

    analyzer_state_root = tmp_path / "state-analyzer-review-test"
    analyzer_launcher = DshHeadlessWorkerLauncher(
        dsh_bin=str(analyzer_bin),
        patch_path=str(analyzer_patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n2-review-analyzer-key"),
        coordinator_instance_id="coordinator-analyzer-review-test",
        release_id=RELEASE,
        state_root=str(analyzer_state_root),
        command_runner=analyzer_runner,
    )
    N2GovernedRequirementHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=analyzer_launcher,
        allowed_tools=[ANALYZER_TOOL],
    ).handoff(release_batch_id=BATCH, requirement_id=requirement_id)
    promoted = N2RequirementCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(analyzer_state_root),
    ).promote(release_batch_id=BATCH, requirement_id=requirement_id)
    return truth, promoted


def _reviewer(tmp_path, truth, *, decision="PASS", gap_ids=None, calls=None):
    reviewer_bin = tmp_path / "dsh-independent-reviewer"
    reviewer_bin.write_text("fixture", encoding="utf-8")
    reviewer_patch = tmp_path / "patch-independent-reviewer.json"
    reviewer_patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def reviewer_runner(command, **kwargs):
        counter["count"] += 1
        output = {
            "decision": decision,
            "gap_ids": list(gap_ids or []),
            "summary": "independent fixture review",
        }
        events = [
            {"type": "session", "session_id": "session-reviewer-%d" % counter["count"]},
            {"type": "tool_call", "tool_name": REVIEW_TOOL},
            {"type": "final", "text": json.dumps(output)},
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(item) for item in events) + "\n",
            stderr="",
        )

    launcher = DshHeadlessWorkerLauncher(
        dsh_bin=str(reviewer_bin),
        patch_path=str(reviewer_patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=AuthorityRuntime(b"rc72-n2-independent-review-key"),
        coordinator_instance_id="coordinator-independent-review",
        release_id=RELEASE,
        state_root=str(tmp_path / "state-independent-review"),
        command_runner=reviewer_runner,
    )
    return DshRequirementEvaluator(launcher, allowed_tools=[REVIEW_TOOL])


def test_sufficient_candidate_requires_and_passes_fresh_independent_dsh_review(tmp_path):
    truth, promoted = _prepare_promoted(tmp_path)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    evaluator = _reviewer(tmp_path, truth)

    result = N2RequirementReviewService(control, evaluator).review_and_apply(
        task_id=promoted["task_id"], artifact_id=promoted["artifact_id"]
    )

    assert result.evaluation_result == "PASS"
    assert result.task_state == "PASS"
    assert result.worker_uncertainty_guard_triggered is False
    assert result.gap_ids == ()
    task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert result.reviewer_worker_id != task["lease_owner"]
    assert result.reviewer_session_id.startswith("session-reviewer-")
    evaluations = truth.query("rc7_evaluation", evaluation_id=result.evaluation_id)
    assert len(evaluations) == 1
    assert evaluations[0]["result"] == "PASS"
    assert truth.query("rc72_node_delivery", mission_id=MISSION, node_type="N2_REQUIREMENT") == []
    assert truth.query("rc72_node_gate", mission_id=MISSION, node_type="N2_REQUIREMENT") == []


def test_worker_unknown_forces_repair_even_when_independent_reviewer_says_pass(tmp_path):
    truth, promoted = _prepare_promoted(
        tmp_path,
        unknowns=[{"id": "UNK-PERM", "description": "permission owner unknown"}],
    )
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)

    result = N2RequirementReviewService(
        control, _reviewer(tmp_path, truth)
    ).review_and_apply(
        task_id=promoted["task_id"], artifact_id=promoted["artifact_id"]
    )

    assert result.evaluation_result == "REPAIR_REQUIRED"
    assert result.task_state == "REPAIR_REQUIRED"
    assert result.worker_uncertainty_guard_triggered is True
    assert result.gap_ids
    gaps = [truth.query("rc7_gap", gap_id=gap_id)[0] for gap_id in result.gap_ids]
    assert any(row["category"] == "REQUIREMENT_AMBIGUITY" for row in gaps)
    assert any("Worker-declared unresolved unknown" in row["description"] for row in gaps)
    repair_tasks = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR"
    ]
    assert repair_tasks


def test_unproven_sst_and_declared_gap_force_repair_despite_reviewer_pass(tmp_path):
    truth, promoted = _prepare_promoted(
        tmp_path,
        sst_ids=[],
        gaps=[{"id": "GAP-SST", "type": "SST_NOT_PROVEN"}],
    )
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)

    result = N2RequirementReviewService(
        control, _reviewer(tmp_path, truth)
    ).review_and_apply(
        task_id=promoted["task_id"], artifact_id=promoted["artifact_id"]
    )

    assert result.evaluation_result == "REPAIR_REQUIRED"
    assert result.task_state == "REPAIR_REQUIRED"
    gaps = [truth.query("rc7_gap", gap_id=gap_id)[0] for gap_id in result.gap_ids]
    descriptions = [row["description"] for row in gaps]
    assert any("no evidence-proven SST identity" in value for value in descriptions)
    assert any("Worker-declared unresolved gap" in value for value in descriptions)


def test_reviewer_gaps_remain_repair_required_without_worker_uncertainty(tmp_path):
    truth, promoted = _prepare_promoted(tmp_path)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)

    result = N2RequirementReviewService(
        control,
        _reviewer(tmp_path, truth, decision="GAPS", gap_ids=["REVIEW-GAP-1"]),
    ).review_and_apply(
        task_id=promoted["task_id"], artifact_id=promoted["artifact_id"]
    )

    assert result.evaluation_result == "REPAIR_REQUIRED"
    assert result.task_state == "REPAIR_REQUIRED"
    assert result.worker_uncertainty_guard_triggered is False
    gaps = [truth.query("rc7_gap", gap_id=gap_id)[0] for gap_id in result.gap_ids]
    assert any(row["category"] == "REQUIREMENT_REVIEW_GAP" for row in gaps)


def test_tampered_candidate_envelope_cannot_reach_reviewer(tmp_path):
    truth, promoted = _prepare_promoted(tmp_path)
    artifact = truth.query("rc7_artifact", artifact_id=promoted["artifact_id"])[0]
    path = Path(artifact["content_ref"][len("file://"):])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["semantic_payload"]["business_rules"].append({"id": "TAMPERED"})
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)

    with pytest.raises(Exception, match="HASH"):
        N2RequirementReviewService(
            control, _reviewer(tmp_path, truth)
        ).review_and_apply(
            task_id=promoted["task_id"], artifact_id=promoted["artifact_id"]
        )

    task = truth.query("rc7_task", task_id=promoted["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
    n2_evaluations = [
        row for row in truth.query("rc7_evaluation", mission_id=MISSION)
        if row.get("node") == "REQUIREMENT_ANALYSIS"
    ]
    assert n2_evaluations == []
