from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import AgentRuntimeError, DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n4_test_design_assignment import N4TestDesignAssignmentService
from rc7_runtime.rc72_n4_test_design_dispatch import N4TestDesignDispatchService
from rc7_runtime.rc72_n4_test_design_handoff import (
    N4TestDesignDshHandoffService,
    N4TestDesignHandoffError,
    validate_rc72_n4_test_design_attempt,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n4_test_design_dispatch import _n4_ready


TOOL_READ = "filesystem"
TOOL_GRAPH = "codegraph"


def _ready(tmp_path: Path, monkeypatch):
    truth, snapshot = _n4_ready(tmp_path, monkeypatch)
    dispatched = N4TestDesignDispatchService(
        truth, source_commit=COMMIT
    ).dispatch(release_batch_id=BATCH)
    assigned = N4TestDesignAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)
    assert assigned["status"] == "ASSIGNED"
    return truth, snapshot, dispatched, assigned


def _candidate(requirement_id, sst_id, *, gap=False, placeholder=False, wrong_scope=False):
    obligation_id = "OBL-%s-%s" % (requirement_id, sst_id)
    evidence_ref = "tool://design/%s/%s" % (requirement_id, sst_id)
    req = "WRONG-REQ" if wrong_scope else requirement_id
    step = "TBD" if placeholder else "submit valid request for the scoped business rule"
    obligations = [
        {
            "obligation_id": obligation_id,
            "requirement_id": req,
            "sst_id": sst_id,
            "kind": "BUSINESS_RULE",
            "business_scope": "scoped Requirement/SST business rule",
            "change_slice": "changed service behavior and regression slice",
            "risk": "LOW",
            "layer": "L3",
            "oracle_types": ["API_RESPONSE", "BUSINESS_RULE"],
            "evidence_refs": [evidence_ref],
            "required": True,
        }
    ]
    cases = [] if gap else [
        {
            "tc_id": "TC-%s-%s" % (requirement_id, sst_id),
            "release_batch_id": BATCH,
            "requirement_id": req,
            "sst_id": sst_id,
            "obligation_id": obligation_id,
            "layer": "L3",
            "risk": "LOW",
            "preconditions": ["target deployment and API route are proven available"],
            "data_requirements": ["valid scoped request data"],
            "steps": [step],
            "expected_results": ["API and business rule result match the requirement"],
            "oracle": {
                "checks": [
                    {"type": "API_RESPONSE", "evidence_ref": evidence_ref},
                    {"type": "BUSINESS_RULE", "evidence_ref": evidence_ref},
                ]
            },
            "evidence_requirements": ["request/response and correlated runtime evidence"],
            "code_trace": ["changed service symbol from parent CODE_ANALYSIS_CANDIDATE"],
            "action_semantics": {
                "state_changing": False,
                "negative": False,
                "authorization_sensitive": False,
            },
            "coverage_links": [
                {"subject_id": obligation_id, "evidence_ref": evidence_ref}
            ],
            "status": "CANDIDATE",
        }
    ]
    return {
        "status": "CANDIDATE",
        "release_batch_id": BATCH,
        "requirement_id": requirement_id,
        "sst_id": sst_id,
        "obligations": obligations,
        "cases": cases,
        "unknowns": [],
        "gaps": ([{"id": "GAP-DESIGN", "type": "CASE_NOT_YET_PROVEN"}] if gap else []),
    }


def _launcher(
    tmp_path: Path,
    truth,
    *,
    calls=None,
    fixed_session=None,
    tool_name=TOOL_READ,
    placeholder=False,
    gap=False,
    wrong_scope=False,
):
    dsh = tmp_path / "dsh-n4-design"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch-n4-design.json"
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        prompt = str(command[-1])
        assert "TEST_DESIGN_WORKER" in prompt
        assert "Requirement x SST" in prompt
        receipts = truth.query("rc72_n4_test_design_assignment", release_batch_id=BATCH)
        matches = [
            row for row in receipts
            if str(row["requirement_id"]) in prompt and str(row["sst_id"]) in prompt
        ]
        assert len(matches) == 1
        row = matches[0]
        session_id = fixed_session or "session-n4-design-%d" % counter["count"]
        candidate = _candidate(
            str(row["requirement_id"]),
            str(row["sst_id"]),
            placeholder=placeholder,
            gap=gap,
            wrong_scope=wrong_scope,
        )
        events = [
            {"type": "session", "session_id": session_id},
            {"type": "tool_call", "tool_name": tool_name},
            {"type": "final", "text": json.dumps(candidate, ensure_ascii=False)},
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
            stderr="",
        )

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n4-design-handoff-test-key"),
        coordinator_instance_id="coordinator-n4-design",
        release_id=RELEASE,
        state_root=str(tmp_path / "state-n4-design"),
        command_runner=runner,
    )


def test_each_requirement_sst_design_scope_runs_in_distinct_fresh_dsh_session(
    tmp_path: Path, monkeypatch
):
    truth, _snapshot, dispatched, assigned = _ready(tmp_path, monkeypatch)
    calls = {"count": 0}
    launcher = _launcher(tmp_path, truth, calls=calls)
    service = N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    )
    results = [
        service.handoff(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )
        for scope in dispatched["design_scopes"]
    ]

    assert calls["count"] == len(dispatched["design_scopes"])
    assert all(row["status"] == "SESSION_OBSERVED" for row in results)
    assert len({row["dsh_session_id"] for row in results}) == len(results)
    assert len({row["worker_instance_id"] for row in results}) == len(results)
    assert {
        (row["requirement_id"], row["sst_id"]) for row in results
    } == {
        (row["requirement_id"], row["sst_id"]) for row in dispatched["design_scopes"]
    }

    attempts = truth.query("rc72_n4_test_design_attempt", mission_id=MISSION)
    assert len(attempts) == len(results)
    assigned_workers = {
        (row["requirement_id"], row["sst_id"]): row["worker_instance_id"]
        for row in assigned["assignments"]
    }
    for attempt in attempts:
        scope = (attempt["requirement_id"], attempt["sst_id"])
        assert attempt["worker_instance_id"] == assigned_workers[scope]
        assert attempt["candidate_schema"] == "RC72_N4_TEST_DESIGN_CANDIDATE_V1"
        assert attempt["state"] == "WORKER_COMPLETED_PENDING_PROMOTION"
        assert attempt["observed_tool_calls"][0]["tool_name"] == TOOL_READ
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

    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n5["state"] == "NOT_STARTED"


def test_n4_design_handoff_is_idempotent_without_second_dsh_launch(tmp_path: Path, monkeypatch):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    scope = dispatched["design_scopes"][0]
    calls = {"count": 0}
    service = N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, calls=calls),
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    )
    first = service.handoff(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    second = service.handoff(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    assert first["status"] == "SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["attempt_id"] == second["attempt_id"]
    assert first["dsh_session_id"] == second["dsh_session_id"]
    assert calls["count"] == 1


def test_n4_design_candidate_scope_mismatch_is_rejected(tmp_path: Path, monkeypatch):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    scope = dispatched["design_scopes"][0]
    service = N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, wrong_scope=True),
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    )
    with pytest.raises(N4TestDesignHandoffError, match="OBLIGATION_SCOPE_MISMATCH"):
        service.handoff(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )
    assert truth.query("rc72_n4_test_design_attempt", mission_id=MISSION) == []


def test_n4_design_placeholder_is_rejected_instead_of_deferred_to_execution(
    tmp_path: Path, monkeypatch
):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    scope = dispatched["design_scopes"][0]
    service = N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, placeholder=True),
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    )
    with pytest.raises(N4TestDesignHandoffError, match="PLACEHOLDER_FORBIDDEN"):
        service.handoff(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )
    assert truth.query("rc72_n4_test_design_attempt", mission_id=MISSION) == []


def test_uncovered_required_obligation_is_allowed_only_with_explicit_gap(
    tmp_path: Path, monkeypatch
):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    scope = dispatched["design_scopes"][0]
    result = N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, gap=True),
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    ).handoff(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    assert result["status"] == "SESSION_OBSERVED"
    attempt = truth.query("rc72_n4_test_design_attempt", attempt_id=result["attempt_id"])[0]
    assert attempt["state"] == "WORKER_COMPLETED_PENDING_PROMOTION"
    assert "node_pass" not in attempt
    assert "evaluation" not in attempt


def test_reused_n4_design_dsh_session_is_rejected(tmp_path: Path, monkeypatch):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    assert len(dispatched["design_scopes"]) >= 2
    launcher = _launcher(tmp_path, truth, fixed_session="session-n4-design-reused")
    service = N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    )
    first, second = dispatched["design_scopes"][:2]
    service.handoff(
        release_batch_id=BATCH,
        requirement_id=first["requirement_id"],
        sst_id=first["sst_id"],
    )
    with pytest.raises(AgentRuntimeError, match="WORKER_SESSION_NOT_INDEPENDENT"):
        service.handoff(
            release_batch_id=BATCH,
            requirement_id=second["requirement_id"],
            sst_id=second["sst_id"],
        )
    assert len(truth.query("rc72_n4_test_design_attempt", mission_id=MISSION)) == 1


def test_unapproved_tool_cannot_be_admitted_as_n4_design_attempt(tmp_path: Path, monkeypatch):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    scope = dispatched["design_scopes"][0]
    service = N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, tool_name="unapproved-shell"),
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    )
    with pytest.raises(N4TestDesignHandoffError, match="UNAUTHORIZED_TOOL"):
        service.handoff(
            release_batch_id=BATCH,
            requirement_id=scope["requirement_id"],
            sst_id=scope["sst_id"],
        )
    assert truth.query("rc72_n4_test_design_attempt", mission_id=MISSION) == []


def test_n4_attempt_contract_rejects_business_truth_smuggling(tmp_path: Path, monkeypatch):
    truth, _snapshot, dispatched, _assigned = _ready(tmp_path, monkeypatch)
    scope = dispatched["design_scopes"][0]
    result = N4TestDesignDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth),
        allowed_tools=[TOOL_READ, TOOL_GRAPH],
    ).handoff(
        release_batch_id=BATCH,
        requirement_id=scope["requirement_id"],
        sst_id=scope["sst_id"],
    )
    attempt = dict(
        truth.query("rc72_n4_test_design_attempt", attempt_id=result["attempt_id"])[0]
    )
    attempt["node_gate"] = "PASS"
    with pytest.raises(Exception, match="BUSINESS_CLAIM_FORBIDDEN:node_gate"):
        validate_rc72_n4_test_design_attempt(attempt)
