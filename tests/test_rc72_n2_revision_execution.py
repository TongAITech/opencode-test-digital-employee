from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.candidate_payload import CandidatePayloadReader
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n2_completion import N2DeliveryGateService
from rc7_runtime.rc72_n2_revision import N2RevisionDispatchService
from rc7_runtime.rc72_n2_revision_execution import (
    N2RevisionCandidatePromotionService,
    N2RevisionDshHandoffService,
    N2RevisionExecutionError,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE, REQUIREMENTS
from test_rc72_n2_completion import _seed_reviewed_requirements
from test_rc72_n2_revision import _drive_repair_to_evidence_pending


TOOL = "requirement-source-probe"


def _candidate(requirement_id):
    source_ref = "starlink://requirement/%s?revision=2" % requirement_id
    source_id = "SRC-REV-%s" % requirement_id
    atom_id = "ATOM-REV-%s" % requirement_id
    return {
        "status": "CANDIDATE",
        "facts": {
            "requirement_id": requirement_id,
            "sst_ids": ["SST-%s" % requirement_id],
            "source_refs": [source_ref],
            "analysis": {
                "atomic_statements": [{
                    "id": atom_id,
                    "text": "revised testable assertion",
                    "source_ref": source_ref,
                    "testable": True,
                }],
                "source_assertions": [{"id": source_id, "text": "revised source"}],
                "trace_links": [{
                    "source_id": source_id,
                    "atomic_id": atom_id,
                    "evidence_ref": source_ref,
                }],
                "business_rules": [{"id": "BR-REV-%s" % requirement_id}],
                "roles": [{"id": "ROLE-REV-%s" % requirement_id}],
                "preconditions": [{"id": "PRE-REV-%s" % requirement_id}],
                "normal_paths": [{"id": "NP-REV-%s" % requirement_id}],
                "negative_paths": [{"id": "NEG-REV-%s" % requirement_id}],
                "boundaries": [{"id": "BOUND-REV-%s" % requirement_id}],
                "states": [{"id": "STATE-REV-%s" % requirement_id}],
                "data_constraints": [{"id": "DATA-REV-%s" % requirement_id}],
                "dependencies": [{"id": "DEP-REV-%s" % requirement_id}],
                "side_effects": [{"id": "SIDE-REV-%s" % requirement_id}],
                "dimension_exclusions": [],
            },
        },
        "unknowns": [],
        "gaps": [],
    }


def _prepared_revision(tmp_path):
    affected = REQUIREMENTS[0]
    truth, _ = _seed_reviewed_requirements(tmp_path, repair_requirement=affected)
    N2DeliveryGateService(truth, source_commit=COMMIT).complete(release_batch_id=BATCH)
    _drive_repair_to_evidence_pending(truth, affected)
    plan = N2RevisionDispatchService(truth, source_commit=COMMIT).plan_and_assign(
        release_batch_id=BATCH
    )
    assert len(plan["revisions"]) == 1
    return truth, affected, plan["revisions"][0]


def _launcher(tmp_path, truth, requirement_id, calls=None, session_id="session-n2-revision-fresh"):
    dsh = tmp_path / "dsh-n2-revision"
    dsh.write_text("fixture", encoding="utf-8")
    patch = tmp_path / "patch-n2-revision.json"
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        events = [
            {"type": "session", "session_id": session_id},
            {"type": "tool_call", "tool_name": TOOL},
            {"type": "final", "text": json.dumps(_candidate(requirement_id))},
        ]
        stdout = "\n".join(json.dumps(event) for event in events) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n2-revision-execution-key"),
        coordinator_instance_id="coordinator-n2-revision",
        release_id=RELEASE,
        state_root=str(tmp_path / "state"),
        command_runner=runner,
    )


def test_revision_receipt_runs_fresh_dsh_and_promotes_only_to_output_produced(tmp_path):
    truth, affected, revision = _prepared_revision(tmp_path)
    launcher = _launcher(tmp_path, truth, affected)
    handoff = N2RevisionDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    ).handoff(release_batch_id=BATCH, requirement_id=affected)

    assert handoff["status"] == "SESSION_OBSERVED"
    assert handoff["revision_generation"] == 2
    assert handoff["worker_instance_id"] == revision["revision_worker_instance_id"]
    assert handoff["dsh_session_id"] == "session-n2-revision-fresh"
    assert handoff["attempt_state"] == "WORKER_COMPLETED_PENDING_DELIVERY"
    task = truth.query("rc7_task", task_id=revision["revision_workitem_id"])[0]
    assert task["state"] == "LEASED"

    attempt = truth.query("rc72_n2_revision_attempt", revision_id=revision["revision_id"])[0]
    assert attempt["raw_output_ref"].startswith("file://")
    assert attempt["raw_output_sha256"].startswith("sha256:")
    assert attempt["revision_generation"] == 2

    promoted = N2RevisionCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state"),
    ).promote(release_batch_id=BATCH, requirement_id=affected)

    assert promoted["status"] == "PROMOTED"
    assert promoted["task_state"] == "OUTPUT_PRODUCED"
    payload = CandidatePayloadReader().load(
        truth,
        promoted["artifact_id"],
        expected_mission_id=MISSION,
        expected_task_id=revision["revision_workitem_id"],
    )
    assert payload.semantic_payload["requirement_id"] == affected
    assert payload.semantic_payload["candidate_unknowns"] == []
    assert payload.semantic_payload["candidate_gaps"] == []
    assert revision["previous_artifact_id"] in payload.envelope["artifact"]["parent_refs"]

    assert truth.query("rc7_evaluation", artifact_refs=[promoted["artifact_id"]]) == []
    n2 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N2_REQUIREMENT")[0]
    n3 = truth.query("rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS")[0]
    assert n2["state"] == "RUNNING"
    assert n3["state"] == "NOT_STARTED"


def test_revision_handoff_replay_reuses_same_attempt_without_second_dsh_launch(tmp_path):
    truth, affected, _revision = _prepared_revision(tmp_path)
    calls = {"count": 0}
    launcher = _launcher(tmp_path, truth, affected, calls=calls)
    service = N2RevisionDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    )

    first = service.handoff(release_batch_id=BATCH, requirement_id=affected)
    second = service.handoff(release_batch_id=BATCH, requirement_id=affected)

    assert first["status"] == "SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["attempt_id"] == second["attempt_id"]
    assert first["dsh_session_id"] == second["dsh_session_id"]
    assert calls["count"] == 1


def test_revision_raw_tamper_is_rejected_before_canonical_candidate(tmp_path):
    truth, affected, revision = _prepared_revision(tmp_path)
    launcher = _launcher(tmp_path, truth, affected)
    N2RevisionDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    ).handoff(release_batch_id=BATCH, requirement_id=affected)
    attempt = truth.query("rc72_n2_revision_attempt", revision_id=revision["revision_id"])[0]
    raw_path = Path(str(attempt["raw_output_ref"])[len("file://"):])
    raw_path.write_text(raw_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(N2RevisionExecutionError, match="RAW_HASH_MISMATCH"):
        N2RevisionCandidatePromotionService(
            truth,
            release_id=RELEASE,
            mission_id=MISSION,
            source_commit=COMMIT,
            state_root=str(tmp_path / "state"),
        ).promote(release_batch_id=BATCH, requirement_id=affected)

    task = truth.query("rc7_task", task_id=revision["revision_workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["output_artifact_refs"] == []
