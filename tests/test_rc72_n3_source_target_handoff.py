from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n3_source_target_assignment import N3SourceTargetAssignmentService
from rc7_runtime.rc72_n3_source_target_dispatch import N3SourceTargetDispatchService
from rc7_runtime.rc72_n3_source_target_handoff import (
    N3SourceTargetDshHandoffService,
    N3SourceTargetHandoffError,
    validate_rc72_n3_source_target_attempt,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_source_target_dispatch import _n2_pass


TOOL = "source-target-probe"
APPLICATION = "BLOAN"


def _candidate(application_id, *, targets=None, gaps=None):
    if targets is None:
        targets = [
            {
                "target_id": "SRC-TARGET-%s" % application_id,
                "repository_ref": "git://repo/%s" % application_id,
                "source_revision": "a" * 40,
                "evidence_refs": ["tool://source-target-probe/%s" % application_id],
            }
        ]
    return {
        "status": "CANDIDATE",
        "application_id": application_id,
        "targets": list(targets),
        "unknowns": [],
        "gaps": list(gaps or []),
    }


def _ready(tmp_path: Path):
    truth = _n2_pass(tmp_path)
    N3SourceTargetDispatchService(
        truth, source_commit=COMMIT
    ).dispatch(release_batch_id=BATCH)
    assigned = N3SourceTargetAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)
    assert assigned["status"] == "ASSIGNED"
    return truth, assigned


def _launcher(
    tmp_path: Path,
    truth,
    *,
    calls=None,
    fixed_application=None,
    fixed_targets=None,
    fixed_gaps=None,
    fixed_session=None,
    tool_name=TOOL,
):
    dsh = tmp_path / "dsh-n3-source"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch-n3-source.json"
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        prompt = str(command[-1])
        application_id = fixed_application or APPLICATION
        if fixed_application is None:
            assert APPLICATION in prompt
        session_id = fixed_session or "session-n3-source-%d" % counter["count"]
        candidate = _candidate(
            application_id,
            targets=fixed_targets,
            gaps=fixed_gaps,
        )
        events = [
            {"type": "session", "session_id": session_id},
            {"type": "tool_call", "tool_name": tool_name},
            {"type": "final", "text": json.dumps(candidate, ensure_ascii=False)},
        ]
        stdout = "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n3-source-handoff-test-key"),
        coordinator_instance_id="coordinator-n3-source",
        release_id=RELEASE,
        state_root=str(tmp_path / "state-n3-source"),
        command_runner=runner,
    )


def test_n3_source_assignment_runs_in_fresh_task_scoped_dsh_session(tmp_path: Path):
    truth, assigned = _ready(tmp_path)
    calls = {"count": 0}
    result = N3SourceTargetDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, calls=calls),
        allowed_tools=[TOOL],
    ).handoff(release_batch_id=BATCH, application_id=APPLICATION)

    assert calls["count"] == 1
    assert result["status"] == "SESSION_OBSERVED"
    assert result["dsh_session_id"].startswith("session-n3-source-")
    assert result["worker_instance_id"] == assigned["assignments"][0]["worker_instance_id"]
    attempt = truth.query(
        "rc72_n3_source_target_attempt", attempt_id=result["attempt_id"]
    )[0]
    assert attempt["candidate_schema"] == "RC72_N3_SOURCE_TARGET_CANDIDATE_V1"
    assert attempt["observed_tool_calls"][0]["tool_name"] == TOOL
    assert any(ref.startswith("file://") for ref in attempt["runtime_evidence_refs"])
    assert attempt["state"] == "WORKER_COMPLETED_PENDING_DELIVERY"
    assert "repository_ref" not in attempt
    assert "source_revision" not in attempt
    assert "targets" not in attempt

    task = truth.query("rc7_task", task_id=attempt["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["lease_owner"] == attempt["worker_instance_id"]
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n4["state"] == "NOT_STARTED"


def test_n3_source_handoff_is_idempotent_without_second_dsh_launch(tmp_path: Path):
    truth, _ = _ready(tmp_path)
    calls = {"count": 0}
    service = N3SourceTargetDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, calls=calls),
        allowed_tools=[TOOL],
    )

    first = service.handoff(release_batch_id=BATCH, application_id=APPLICATION)
    second = service.handoff(release_batch_id=BATCH, application_id=APPLICATION)

    assert first["status"] == "SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["attempt_id"] == second["attempt_id"]
    assert first["dsh_session_id"] == second["dsh_session_id"]
    assert calls["count"] == 1


def test_n3_source_candidate_application_mismatch_is_rejected(tmp_path: Path):
    truth, _ = _ready(tmp_path)
    service = N3SourceTargetDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, fixed_application="WRONG-APP"),
        allowed_tools=[TOOL],
    )

    with pytest.raises(
        N3SourceTargetHandoffError,
        match="CANDIDATE_APPLICATION_MISMATCH",
    ):
        service.handoff(release_batch_id=BATCH, application_id=APPLICATION)

    assert truth.query("rc72_n3_source_target_attempt", mission_id=MISSION) == []


def test_n3_source_missing_mapping_requires_explicit_gap(tmp_path: Path):
    truth, _ = _ready(tmp_path)
    service = N3SourceTargetDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, fixed_targets=[], fixed_gaps=[]),
        allowed_tools=[TOOL],
    )

    with pytest.raises(
        N3SourceTargetHandoffError,
        match="DISCOVERY_GAP_REQUIRED",
    ):
        service.handoff(release_batch_id=BATCH, application_id=APPLICATION)

    assert truth.query("rc72_n3_source_target_attempt", mission_id=MISSION) == []


def test_n3_source_missing_mapping_with_gap_is_candidate_attempt_not_acceptance(tmp_path: Path):
    truth, _ = _ready(tmp_path)
    result = N3SourceTargetDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path,
            truth,
            fixed_targets=[],
            fixed_gaps=[{"id": "GAP-SOURCE", "type": "SOURCE_TARGET_NOT_PROVEN"}],
        ),
        allowed_tools=[TOOL],
    ).handoff(release_batch_id=BATCH, application_id=APPLICATION)

    attempt = truth.query(
        "rc72_n3_source_target_attempt", attempt_id=result["attempt_id"]
    )[0]
    assert attempt["state"] == "WORKER_COMPLETED_PENDING_DELIVERY"
    assert "source_mapping_accepted" not in attempt
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []


def test_unapproved_tool_cannot_be_admitted_as_n3_source_attempt(tmp_path: Path):
    truth, _ = _ready(tmp_path)
    service = N3SourceTargetDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, tool_name="unapproved-shell"),
        allowed_tools=[TOOL],
    )

    with pytest.raises(N3SourceTargetHandoffError, match="UNAUTHORIZED_TOOL"):
        service.handoff(release_batch_id=BATCH, application_id=APPLICATION)

    assert truth.query("rc72_n3_source_target_attempt", mission_id=MISSION) == []


def test_n3_source_attempt_contract_rejects_source_truth_smuggling(tmp_path: Path):
    truth, _ = _ready(tmp_path)
    result = N3SourceTargetDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth),
        allowed_tools=[TOOL],
    ).handoff(release_batch_id=BATCH, application_id=APPLICATION)
    attempt = dict(
        truth.query("rc72_n3_source_target_attempt", attempt_id=result["attempt_id"])[0]
    )
    attempt["repository_ref"] = "git://repo/BLOAN"

    with pytest.raises(Exception, match="SOURCE_TRUTH_CLAIM_FORBIDDEN:repository_ref"):
        validate_rc72_n3_source_target_attempt(attempt)
