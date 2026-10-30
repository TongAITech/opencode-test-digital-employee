from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.candidate_payload import CandidatePayloadReader
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n2_candidate_guard import N2GovernedRequirementHandoffService
from rc7_runtime.rc72_n2_requirement_assignment import (
    N2RequirementAssignmentService,
    install_rc72_n2_requirement_assignment_overlay,
)
from rc7_runtime.rc72_n2_requirement_handoff import N2RequirementDshHandoffService
from rc7_runtime.rc72_n2_requirement_promotion import (
    N2RequirementCandidatePromotionService,
    N2RequirementPromotionError,
)

from rc72_n2_test_support import (
    BATCH,
    COMMIT,
    MISSION,
    RELEASE,
    REQUIREMENTS,
    build_truth,
    dispatch_n2,
)


TOOL = "requirement-source-probe"


def _candidate(requirement_id, *, unknowns=None, gaps=None):
    source_ref = "starlink://requirement/%s" % requirement_id
    atom_id = "ATOM-%s" % requirement_id
    source_id = "SRC-%s" % requirement_id
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
            {"id": source_id, "text": "fixture source assertion", "source_ref": source_ref}
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
            "sst_ids": ["SST-%s" % requirement_id],
            "source_refs": [source_ref],
            "analysis": analysis,
        },
        "unknowns": list(unknowns or []),
        "gaps": list(gaps or []),
    }


def _ready(tmp_path, *, unknowns=None, gaps=None):
    truth = build_truth(tmp_path)
    install_rc72_n2_requirement_assignment_overlay()
    dispatch_n2(truth)
    N2RequirementAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)

    dsh = tmp_path / "dsh-n2-promotion"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch-n2-promotion.json"
    patch.write_text("{}", encoding="utf-8")
    counter = {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        prompt = str(command[-1])
        matches = [req for req in REQUIREMENTS if req in prompt]
        assert len(matches) == 1
        requirement_id = matches[0]
        candidate = _candidate(requirement_id, unknowns=unknowns, gaps=gaps)
        events = [
            {"type": "session", "session_id": "session-n2-promotion-%d" % counter["count"]},
            {"type": "tool_call", "tool_name": TOOL},
            {"type": "final", "text": json.dumps(candidate, ensure_ascii=False)},
        ]
        stdout = "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    state_root = tmp_path / "state-n2-promotion"
    launcher = DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n2-promotion-test-signing-key"),
        coordinator_instance_id="coordinator-n2-promotion",
        release_id=RELEASE,
        state_root=str(state_root),
        command_runner=runner,
    )
    return truth, launcher, state_root


def _governed_handoff(truth, launcher, requirement_id):
    return N2GovernedRequirementHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[TOOL],
    ).handoff(release_batch_id=BATCH, requirement_id=requirement_id)


def _promotion(truth, state_root):
    return N2RequirementCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(state_root),
    )


def test_only_hash_anchored_traceable_attempt_can_promote_to_canonical_output(tmp_path):
    truth, launcher, state_root = _ready(tmp_path)
    requirement_id = REQUIREMENTS[0]

    # Base handoff proves execution but deliberately does not make the Attempt
    # promotion-eligible because no strict evidence anchor exists.
    base = N2RequirementDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[TOOL],
    ).handoff(release_batch_id=BATCH, requirement_id=requirement_id)
    assert base["status"] == "SESSION_OBSERVED"

    with pytest.raises(
        N2RequirementPromotionError,
        match="EXACT_EVIDENCE_ANCHOR_REQUIRED:0",
    ):
        _promotion(truth, state_root).promote(
            release_batch_id=BATCH, requirement_id=requirement_id
        )

    task = truth.query("rc7_task", task_id=truth.query(
        "rc72_n2_requirement_assignment", requirement_id=requirement_id
    )[0]["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task.get("output_artifact_refs") == []


def test_governed_candidate_promotes_to_hashed_reader_compatible_artifact_and_evidence(tmp_path):
    truth, launcher, state_root = _ready(tmp_path)
    requirement_id = REQUIREMENTS[0]
    handoff = _governed_handoff(truth, launcher, requirement_id)

    result = _promotion(truth, state_root).promote(
        release_batch_id=BATCH, requirement_id=requirement_id
    )

    assert result["status"] == "PROMOTED"
    assert result["task_state"] == "OUTPUT_PRODUCED"
    assert result["evidence_anchor_id"] == handoff["evidence_anchor_id"]
    assert result["content_hash"].startswith("sha256:")
    assert result["sst_ids"] == ["SST-%s" % requirement_id]
    assert len(result["evidence_ids"]) == 2

    artifact = truth.query("rc7_artifact", artifact_id=result["artifact_id"])[0]
    assert artifact["artifact_type_name"] == "REQUIREMENT_ANALYSIS_OUTPUT"
    assert artifact["producer_task_id"] == result["task_id"]
    assert artifact["state"] == "VALID"
    assert artifact["content_hash"] == result["content_hash"]
    evidence_rows = [
        truth.query("rc7_evidence", evidence_id=evidence_id)[0]
        for evidence_id in result["evidence_ids"]
    ]
    source_ref = "starlink://requirement/%s" % requirement_id
    assert any(row["source_ref"] == source_ref and row["content_ref"] == source_ref for row in evidence_rows)
    assert any(row["content_ref"] == handoff["candidate_output_ref"] or row["content_ref"].startswith("file://") for row in evidence_rows)

    candidate = CandidatePayloadReader().load(
        truth,
        result["artifact_id"],
        expected_mission_id=MISSION,
        expected_task_id=result["task_id"],
    )
    assert candidate.semantic_payload["requirement_id"] == requirement_id
    assert candidate.semantic_payload["sufficiency_v2_required"] is True
    assert candidate.semantic_payload["trace_links"][0]["evidence_ref"] == source_ref
    assert candidate.semantic_payload["candidate_unknowns"] == []
    assert candidate.semantic_payload["candidate_gaps"] == []


def test_raw_bytes_changed_after_anchor_are_rejected_before_task_start(tmp_path):
    truth, launcher, state_root = _ready(tmp_path)
    requirement_id = REQUIREMENTS[0]
    handoff = _governed_handoff(truth, launcher, requirement_id)
    anchor = truth.query(
        "rc72_n2_dsh_evidence_anchor", anchor_id=handoff["evidence_anchor_id"]
    )[0]
    raw_path = Path(anchor["raw_output_ref"][len("file://"):])
    raw_path.write_text(
        raw_path.read_text(encoding="utf-8") + json.dumps({"type": "tampered"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        N2RequirementPromotionError,
        match="RAW_OUTPUT_HASH_MISMATCH",
    ):
        _promotion(truth, state_root).promote(
            release_batch_id=BATCH, requirement_id=requirement_id
        )

    assignment = truth.query(
        "rc72_n2_requirement_assignment", requirement_id=requirement_id
    )[0]
    task = truth.query("rc7_task", task_id=assignment["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task.get("output_artifact_refs") == []


def test_promotion_is_idempotent_and_does_not_duplicate_canonical_artifact(tmp_path):
    truth, launcher, state_root = _ready(tmp_path)
    requirement_id = REQUIREMENTS[0]
    _governed_handoff(truth, launcher, requirement_id)
    service = _promotion(truth, state_root)

    first = service.promote(release_batch_id=BATCH, requirement_id=requirement_id)
    second = service.promote(release_batch_id=BATCH, requirement_id=requirement_id)

    assert first["status"] == "PROMOTED"
    assert second["status"] == "RESUMED"
    assert first["artifact_id"] == second["artifact_id"]
    assert first["content_hash"] == second["content_hash"]
    rows = truth.query("rc7_artifact", artifact_id=first["artifact_id"])
    assert len(rows) == 1


def test_worker_declared_unknowns_and_gaps_survive_promotion_for_downstream_repair(tmp_path):
    truth, launcher, state_root = _ready(
        tmp_path,
        unknowns=[{"id": "UNK-1", "description": "permission owner unknown"}],
        gaps=[{"id": "GAP-1", "type": "REQUIREMENT_AMBIGUITY"}],
    )
    requirement_id = REQUIREMENTS[0]
    _governed_handoff(truth, launcher, requirement_id)

    result = _promotion(truth, state_root).promote(
        release_batch_id=BATCH, requirement_id=requirement_id
    )
    candidate = CandidatePayloadReader().load(
        truth,
        result["artifact_id"],
        expected_mission_id=MISSION,
        expected_task_id=result["task_id"],
    )
    assert candidate.semantic_payload["candidate_unknowns"] == [
        {"id": "UNK-1", "description": "permission owner unknown"}
    ]
    assert candidate.semantic_payload["candidate_gaps"] == [
        {"id": "GAP-1", "type": "REQUIREMENT_AMBIGUITY"}
    ]
    task = truth.query("rc7_task", task_id=result["task_id"])[0]
    assert task["state"] == "OUTPUT_PRODUCED"
