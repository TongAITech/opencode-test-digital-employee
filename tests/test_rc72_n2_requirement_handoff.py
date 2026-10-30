from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import AgentRuntimeError, DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n2_requirement_assignment import (
    N2RequirementAssignmentService,
    install_rc72_n2_requirement_assignment_overlay,
)
from rc7_runtime.rc72_n2_requirement_handoff import (
    N2RequirementDshHandoffService,
    N2RequirementHandoffError,
    install_rc72_n2_requirement_handoff_overlay,
    validate_rc72_n2_requirement_attempt,
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


def _candidate(requirement_id, *, sst_ids=None, gaps=None):
    dims = (
        "atomic_statements",
        "source_assertions",
        "business_rules",
        "roles",
        "preconditions",
        "normal_paths",
        "negative_paths",
        "boundaries",
        "states",
        "data_constraints",
        "dependencies",
        "side_effects",
        "dimension_exclusions",
    )
    analysis = {name: [] for name in dims}
    analysis["atomic_statements"] = [
        {"id": "ATOM-%s" % requirement_id, "text": "fixture statement", "source_ref": "starlink://%s" % requirement_id}
    ]
    analysis["source_assertions"] = [
        {"id": "SRC-%s" % requirement_id, "text": "fixture source", "source_ref": "starlink://%s" % requirement_id}
    ]
    return {
        "status": "CANDIDATE",
        "facts": {
            "requirement_id": requirement_id,
            "sst_ids": list(sst_ids if sst_ids is not None else ["SST-%s" % requirement_id]),
            "source_refs": ["starlink://%s" % requirement_id],
            "analysis": analysis,
        },
        "unknowns": [],
        "gaps": list(gaps or []),
    }


def _ready(tmp_path):
    truth = build_truth(tmp_path)
    install_rc72_n2_requirement_assignment_overlay()
    install_rc72_n2_requirement_handoff_overlay()
    dispatch_n2(truth)
    assigned = N2RequirementAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)
    assert assigned["status"] == "ASSIGNED"
    return truth, assigned


def _launcher(
    tmp_path: Path,
    truth,
    *,
    calls=None,
    fixed_requirement=None,
    fixed_sst_ids=None,
    fixed_gaps=None,
    fixed_session=None,
    tool_name=TOOL,
):
    dsh = tmp_path / "dsh-n2"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch-n2.json"
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        prompt = str(command[-1])
        if fixed_requirement is not None:
            requirement_id = fixed_requirement
        else:
            matches = [req for req in REQUIREMENTS if req in prompt]
            assert len(matches) == 1
            requirement_id = matches[0]
        session_id = fixed_session or "session-n2-%d" % counter["count"]
        candidate = _candidate(
            requirement_id,
            sst_ids=fixed_sst_ids,
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
        authority=RC72AuthorityRuntime(b"rc72-n2-handoff-test-signing-key"),
        coordinator_instance_id="coordinator-n2",
        release_id=RELEASE,
        state_root=str(tmp_path / "state-n2"),
        command_runner=runner,
    )


def test_each_n2_requirement_runs_in_distinct_fresh_task_scoped_dsh_session(tmp_path):
    truth, assigned = _ready(tmp_path)
    calls = {"count": 0}
    launcher = _launcher(tmp_path, truth, calls=calls)
    service = N2RequirementDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    )

    results = [
        service.handoff(release_batch_id=BATCH, requirement_id=requirement_id)
        for requirement_id in REQUIREMENTS
    ]

    assert calls["count"] == len(REQUIREMENTS)
    assert all(item["status"] == "SESSION_OBSERVED" for item in results)
    assert len({item["dsh_session_id"] for item in results}) == len(REQUIREMENTS)
    assert len({item["worker_instance_id"] for item in results}) == len(REQUIREMENTS)
    assert {item["requirement_id"] for item in results} == set(REQUIREMENTS)

    attempts = truth.query("rc72_n2_requirement_attempt", mission_id=MISSION)
    assert len(attempts) == len(REQUIREMENTS)
    assigned_workers = {
        item["requirement_id"]: item["worker_instance_id"]
        for item in assigned["assignments"]
    }
    for attempt in attempts:
        assert attempt["worker_instance_id"] == assigned_workers[attempt["requirement_id"]]
        assert attempt["candidate_schema"] == "RC72_N2_REQUIREMENT_CANDIDATE_V1"
        assert attempt["observed_tool_calls"][0]["tool_name"] == TOOL
        assert any(ref.startswith("file://") for ref in attempt["runtime_evidence_refs"])
        task = truth.query("rc7_task", task_id=attempt["workitem_id"])[0]
        assert task["state"] == "LEASED"
        assert task["lease_owner"] == attempt["worker_instance_id"]
        events = [
            row for row in truth.query("agent_runtime_event", mission_id=MISSION)
            if row.get("event_name") == "HANDOFF_RETURNED"
            and row.get("assignment_id") == attempt["runtime_assignment_id"]
        ]
        assert len(events) == 1
        assert events[0]["scope"] == "task:%s" % attempt["workitem_id"]

    assert truth.query("rc72_node_delivery", mission_id=MISSION, node_type="N2_REQUIREMENT") == []
    assert truth.query("rc72_node_gate", mission_id=MISSION, node_type="N2_REQUIREMENT") == []


def test_n2_handoff_is_idempotent_without_second_dsh_launch(tmp_path):
    truth, _ = _ready(tmp_path)
    calls = {"count": 0}
    launcher = _launcher(tmp_path, truth, calls=calls)
    service = N2RequirementDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    )

    first = service.handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])
    second = service.handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])

    assert first["status"] == "SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["attempt_id"] == second["attempt_id"]
    assert first["dsh_session_id"] == second["dsh_session_id"]
    assert calls["count"] == 1


def test_candidate_requirement_mismatch_is_not_admitted_as_n2_attempt(tmp_path):
    truth, _ = _ready(tmp_path)
    launcher = _launcher(
        tmp_path, truth, fixed_requirement="STBB19-WRONG"
    )
    service = N2RequirementDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    )

    with pytest.raises(
        N2RequirementHandoffError,
        match="CANDIDATE_REQUIREMENT_MISMATCH",
    ):
        service.handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])

    assert truth.query("rc72_n2_requirement_attempt", mission_id=MISSION) == []


def test_missing_sst_requires_explicit_gap_instead_of_guessing(tmp_path):
    truth, _ = _ready(tmp_path)
    launcher = _launcher(
        tmp_path, truth, fixed_sst_ids=[], fixed_gaps=[]
    )
    service = N2RequirementDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    )

    with pytest.raises(
        N2RequirementHandoffError,
        match="SST_DISCOVERY_GAP_REQUIRED",
    ):
        service.handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])

    assert truth.query("rc72_n2_requirement_attempt", mission_id=MISSION) == []


def test_missing_sst_with_explicit_gap_is_valid_candidate_attempt_not_pass(tmp_path):
    truth, _ = _ready(tmp_path)
    launcher = _launcher(
        tmp_path,
        truth,
        fixed_sst_ids=[],
        fixed_gaps=[{"id": "GAP-SST", "type": "SST_NOT_PROVEN"}],
    )
    result = N2RequirementDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    ).handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])

    assert result["status"] == "SESSION_OBSERVED"
    attempt = truth.query(
        "rc72_n2_requirement_attempt", attempt_id=result["attempt_id"]
    )[0]
    assert attempt["state"] == "WORKER_COMPLETED_PENDING_DELIVERY"
    assert "node_pass" not in attempt
    assert "evaluation" not in attempt
    assert truth.query("rc72_node_gate", mission_id=MISSION, node_type="N2_REQUIREMENT") == []


def test_reused_dsh_session_across_requirements_is_rejected(tmp_path):
    truth, _ = _ready(tmp_path)
    launcher = _launcher(
        tmp_path, truth, fixed_session="session-n2-reused"
    )
    service = N2RequirementDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    )

    service.handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])
    with pytest.raises(AgentRuntimeError, match="WORKER_SESSION_NOT_INDEPENDENT"):
        service.handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[1])

    assert len(truth.query("rc72_n2_requirement_attempt", mission_id=MISSION)) == 1


def test_unapproved_tool_cannot_be_admitted_as_n2_attempt(tmp_path):
    truth, _ = _ready(tmp_path)
    launcher = _launcher(
        tmp_path, truth, tool_name="unapproved-shell"
    )
    service = N2RequirementDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    )

    with pytest.raises(N2RequirementHandoffError, match="UNAUTHORIZED_TOOL"):
        service.handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])

    assert truth.query("rc72_n2_requirement_attempt", mission_id=MISSION) == []


def test_attempt_contract_rejects_business_truth_smuggling(tmp_path):
    truth, _ = _ready(tmp_path)
    launcher = _launcher(tmp_path, truth)
    result = N2RequirementDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=[TOOL]
    ).handoff(release_batch_id=BATCH, requirement_id=REQUIREMENTS[0])
    attempt = dict(
        truth.query("rc72_n2_requirement_attempt", attempt_id=result["attempt_id"])[0]
    )
    attempt["node_gate"] = "PASS"

    with pytest.raises(Exception, match="BUSINESS_CLAIM_FORBIDDEN:node_gate"):
        validate_rc72_n2_requirement_attempt(attempt)
