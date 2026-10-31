from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n3_code_analysis_assignment import N3CodeAnalysisAssignmentService
from rc7_runtime.rc72_n3_code_analysis_handoff import (
    N3CodeAnalysisDshHandoffService,
    N3CodeAnalysisHandoffError,
    validate_rc72_n3_code_analysis_attempt,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n3_code_analysis_assignment import _dispatched


def _ready(tmp_path: Path, *, two_targets=False):
    truth, dispatched = _dispatched(tmp_path, two_targets=two_targets)
    assigned = N3CodeAnalysisAssignmentService(
        truth, source_commit=COMMIT
    ).assign_all(release_batch_id=BATCH)
    assert assigned["status"] == "ASSIGNED"
    return truth, dispatched, assigned


def _candidate(row, *, repository_ref=None):
    return {
        "status": "CANDIDATE",
        "application_id": row["application_id"],
        "target_id": row["target_id"],
        "repository_ref": repository_ref or row["repository_ref"],
        "source_revision": row["source_revision"],
        "requirement_ids": ["REQ-%s" % row["application_id"]],
        "source_revisions": [row["source_revision"]],
        "changed_files": ["src/main/java/example/ChangedService.java"],
        "changed_symbols": ["example.ChangedService#execute"],
        "symbol_explanations": [
            {
                "symbol": "example.ChangedService#execute",
                "explanation": "evidence-backed impact candidate",
                "evidence_refs": ["tool://codegraph/%s" % row["target_id"]],
            }
        ],
        "reverse_requirement_mappings": [
            {
                "requirement_id": "REQ-%s" % row["application_id"],
                "symbol": "example.ChangedService#execute",
                "evidence_ref": "tool://codegraph/%s" % row["target_id"],
            }
        ],
        "evidence_refs": [
            "tool://git/%s" % row["target_id"],
            "tool://codegraph/%s" % row["target_id"],
        ],
        "codegraph_required": True,
        "unknowns": [],
        "gaps": [],
    }


def _launcher(
    tmp_path: Path,
    truth,
    rows,
    *,
    calls=None,
    tool_names=("git", "codegraph"),
    wrong_repository=False,
):
    dsh = tmp_path / "dsh-n3-code"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch-n3-code.json"
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0, "prompts": []}

    def runner(command, **kwargs):
        counter["count"] += 1
        prompt = str(command[-1])
        counter.setdefault("prompts", []).append(prompt)
        matches = [
            row for row in rows
            if ('"target_id": "%s"' % row["target_id"]) in prompt
        ]
        assert len(matches) == 1
        row = matches[0]
        assert row["repository_ref"] in prompt
        assert row["source_revision"] in prompt
        assert "never infer or switch repository" in prompt
        assert "real git tool" in prompt
        assert "real codegraph tool" in prompt
        candidate = _candidate(
            row,
            repository_ref=(
                "git://repo/WRONG"
                if wrong_repository else row["repository_ref"]
            ),
        )
        events = [
            {
                "type": "session",
                "session_id": "session-n3-code-%d" % counter["count"],
            }
        ]
        for tool_name in tool_names:
            events.append({"type": "tool_call", "tool_name": tool_name})
        events.append(
            {
                "type": "final",
                "text": json.dumps(candidate, ensure_ascii=False),
            }
        )
        stdout = (
            "\n".join(
                json.dumps(event, ensure_ascii=False) for event in events
            )
            + "\n"
        )
        return subprocess.CompletedProcess(
            command, 0, stdout=stdout, stderr=""
        )

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n3-code-handoff-test-key"),
        coordinator_instance_id="coordinator-n3-code",
        release_id=RELEASE,
        state_root=str(tmp_path / "state-n3-code"),
        command_runner=runner,
    )


def test_code_assignments_launch_distinct_fresh_task_scoped_dsh_attempts(
    tmp_path: Path,
):
    truth, _dispatched_rows, assigned = _ready(
        tmp_path, two_targets=True
    )
    rows = assigned["assignments"]
    calls = {"count": 0, "prompts": []}
    launcher = _launcher(tmp_path, truth, rows, calls=calls)
    service = N3CodeAnalysisDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher
    )

    results = [
        service.handoff(
            release_batch_id=BATCH, target_id=row["target_id"]
        )
        for row in rows
    ]

    assert calls["count"] == 2
    assert len({row["dsh_session_id"] for row in results}) == 2
    assert {
        row["worker_instance_id"] for row in results
    } == {
        row["worker_instance_id"] for row in rows
    }
    assert all(row["status"] == "SESSION_OBSERVED" for row in results)

    attempts = truth.query(
        "rc72_n3_code_analysis_attempt", release_batch_id=BATCH
    )
    assert len(attempts) == 2
    for attempt in attempts:
        source = next(
            row for row in rows
            if row["target_id"] == attempt["target_id"]
        )
        assert attempt["worker_instance_id"] == source["worker_instance_id"]
        assert attempt["repository_ref"] == source["repository_ref"]
        assert attempt["source_revision"] == source["source_revision"]
        assert attempt["authorized_tools"] == ["git", "codegraph"]
        assert {
            item["tool_name"] for item in attempt["observed_tool_calls"]
        } == {"git", "codegraph"}
        assert attempt["authority_lease_id"]
        assert attempt["state"] == "WORKER_COMPLETED_PENDING_PROMOTION"
        assert any(
            ref.startswith("file://")
            for ref in attempt["runtime_evidence_refs"]
        )
        task = truth.query(
            "rc7_task", task_id=attempt["workitem_id"]
        )[0]
        assert task["state"] == "LEASED"
        assert task["lease_owner"] == attempt["worker_instance_id"]
        assert task["output_artifact_refs"] == []
        assert task["evaluation_id"] is None

        returned = [
            event for event in truth.query(
                "agent_runtime_event", mission_id=MISSION
            )
            if event.get("event_name") == "HANDOFF_RETURNED"
            and event.get("assignment_id") == attempt["runtime_assignment_id"]
        ]
        assert len(returned) == 1
        assert source["repository_ref"] in returned[0]["input_refs"]
        assert (
            "git-revision://%s" % source["source_revision"]
            in returned[0]["input_refs"]
        )

    assert truth.query(
        "rc72_node_delivery",
        mission_id=MISSION,
        node_type="N3_CODE_ANALYSIS",
    ) == []
    assert truth.query(
        "rc72_node_gate",
        mission_id=MISSION,
        node_type="N3_CODE_ANALYSIS",
    ) == []
    n4 = truth.query(
        "rc72_mission_node",
        mission_id=MISSION,
        node_type="N4_TEST_DESIGN",
    )[0]
    assert n4["state"] == "NOT_STARTED"


def test_code_handoff_replay_does_not_launch_second_dsh_session(
    tmp_path: Path,
):
    truth, _dispatched_rows, assigned = _ready(tmp_path)
    row = assigned["assignments"][0]
    calls = {"count": 0, "prompts": []}
    service = N3CodeAnalysisDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, [row], calls=calls),
    )

    first = service.handoff(
        release_batch_id=BATCH, target_id=row["target_id"]
    )
    second = service.handoff(
        release_batch_id=BATCH, target_id=row["target_id"]
    )

    assert first["status"] == "SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["attempt_id"] == second["attempt_id"]
    assert first["dsh_session_id"] == second["dsh_session_id"]
    assert calls["count"] == 1


def test_code_handoff_recovers_observed_runtime_event_without_relaunch(
    tmp_path: Path,
):
    truth, _dispatched_rows, assigned = _ready(tmp_path)
    row = assigned["assignments"][0]
    calls = {"count": 0, "prompts": []}
    launcher = _launcher(tmp_path, truth, [row], calls=calls)
    first_service = N3CodeAnalysisDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher
    )

    def crash_after_handoff(**kwargs):
        raise RuntimeError("fixture crash after HANDOFF_RETURNED")

    first_service._persist_from_invocation = crash_after_handoff
    with pytest.raises(RuntimeError, match="fixture crash"):
        first_service.handoff(
            release_batch_id=BATCH, target_id=row["target_id"]
        )

    assert calls["count"] == 1
    assert truth.query(
        "rc72_n3_code_analysis_attempt", release_batch_id=BATCH
    ) == []

    recovered = N3CodeAnalysisDshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher
    ).handoff(
        release_batch_id=BATCH, target_id=row["target_id"]
    )

    assert recovered["status"] == "RECOVERED"
    assert calls["count"] == 1
    assert len(
        truth.query(
            "rc72_n3_code_analysis_attempt", release_batch_id=BATCH
        )
    ) == 1


def test_java_candidate_without_real_codegraph_call_is_not_admitted(
    tmp_path: Path,
):
    truth, _dispatched_rows, assigned = _ready(tmp_path)
    row = assigned["assignments"][0]
    service = N3CodeAnalysisDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path, truth, [row], tool_names=("git",)
        ),
    )

    with pytest.raises(
        N3CodeAnalysisHandoffError,
        match="JAVA_CODEGRAPH_CALL_REQUIRED",
    ):
        service.handoff(
            release_batch_id=BATCH, target_id=row["target_id"]
        )

    assert truth.query(
        "rc72_n3_code_analysis_attempt", release_batch_id=BATCH
    ) == []


def test_candidate_cannot_switch_accepted_repository(
    tmp_path: Path,
):
    truth, _dispatched_rows, assigned = _ready(tmp_path)
    row = assigned["assignments"][0]
    service = N3CodeAnalysisDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path, truth, [row], wrong_repository=True
        ),
    )

    with pytest.raises(
        N3CodeAnalysisHandoffError,
        match="CANDIDATE_REPOSITORY_REF_MISMATCH",
    ):
        service.handoff(
            release_batch_id=BATCH, target_id=row["target_id"]
        )

    assert truth.query(
        "rc72_n3_code_analysis_attempt", release_batch_id=BATCH
    ) == []


def test_code_attempt_contract_forbids_acceptance_and_n4_claims(
    tmp_path: Path,
):
    truth, _dispatched_rows, assigned = _ready(tmp_path)
    row = assigned["assignments"][0]
    result = N3CodeAnalysisDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, [row]),
    ).handoff(
        release_batch_id=BATCH, target_id=row["target_id"]
    )
    attempt = dict(
        truth.query(
            "rc72_n3_code_analysis_attempt",
            attempt_id=result["attempt_id"],
        )[0]
    )

    for field, value in (
        ("graph_evidence", {"forbidden": True}),
        ("evaluation", {"decision": "PASS"}),
        ("node_pass", True),
        ("n4_started", True),
        ("field_verified", True),
    ):
        tampered = dict(attempt)
        tampered[field] = value
        with pytest.raises(
            Exception,
            match="ACCEPTANCE_CLAIM_FORBIDDEN:%s" % field,
        ):
            validate_rc72_n3_code_analysis_attempt(tampered)
