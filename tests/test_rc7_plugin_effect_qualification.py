from __future__ import annotations

import json
from pathlib import Path

import rc6_runtime.agent_runtime  # noqa: F401
from rc6_runtime.truth import TruthRuntime
from rc7_release.dsh_plugins import REQUIRED
from rc7_release.plugin_effect_qualification import evaluate_plugin_effects
from rc7_runtime.models import Evidence, Mission, Task, TaskStatus
from rc7_runtime.node_tool_conformance import NODE_TOOL_CALL_KIND
from rc7_runtime.session_continuity import SESSION_EVENT, install_session_overlay
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


MISSION = "MISSION-PLUGIN-EFFECT"
RELEASE = "REL-PLUGIN-EFFECT"


def _profile(path: Path, *, missing_package: str | None = None) -> Path:
    installs = []
    for package in REQUIRED:
        accepted = package != missing_package
        installs.append({"package": package, "accepted": accepted, "exit_code": 0 if accepted else 1})
    payload = {
        "status": "PASS",
        "protected_bank_profile_integrity": "PASS",
        "runtime_profile": "rc7-bank",
        "install": {"status": "PASS", "installs": installs},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _worker_call(truth, *, event_id: str, worker: str, task_id: str, tool_name: str, call_ref: str) -> None:
    call = {"tool_name": tool_name, "call_ref": call_ref, "arguments": {"task_id": task_id}}
    truth.append_atomic(
        "WORKER_TOOL_CALLED",
        {
            "id": event_id,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "event_name": "WORKER_TOOL_CALLED",
            "coordinator_instance_id": "DIRECTOR",
            "worker_instance_id": worker,
            "agent_id": "field-worker",
            "attempt_id": "ATT-%s" % event_id,
            "assignment_id": "ASSIGN-%s" % event_id,
            "lease_id": "LEASE-%s" % event_id,
            "parent_worker_id": "DIRECTOR",
            "scope": "task:%s" % task_id,
            "input_refs": [],
            "tool_calls": [call],
            "tool_call": call,
            "output_refs": [],
            "evidence_refs": [],
            "started_at": 1,
            "finished_at": 2,
            "result": "PASS",
            "occurred_at": 2,
            "artifact_version": 1,
        },
    )


def _build_r1(tmp_path: Path, *, browser_call: bool = True) -> Path:
    install_rc7_truth_overlay()
    install_session_overlay()
    path = tmp_path / "event-stream.jsonl"
    truth = TruthRuntime(path)
    append_entity(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="qualify plugin effects"),
        release_id=RELEASE,
    )
    tasks = (
        Task(
            task_id="TASK-REQ",
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            task_type="PRODUCE",
            objective="requirement",
            state=TaskStatus.PASS,
            lease_owner="WORKER-REQ",
        ),
        Task(
            task_id="TASK-EXEC",
            mission_id=MISSION,
            node="EXECUTION",
            task_type="PRODUCE",
            objective="execution",
            state=TaskStatus.PASS,
            lease_owner="WORKER-EXEC",
        ),
    )
    for task in tasks:
        append_entity(truth, task, release_id=RELEASE)

    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-NODE-CALL",
            mission_id=MISSION,
            kind=NODE_TOOL_CALL_KIND,
            source_ref="mcp://pfc-aitest-rc7/truth_query",
            content_ref="node-tool-call://truth-query",
            subject_refs=["TASK-REQ", "WORKER-REQ", "TRUTH_QUERY"],
            content_hash="a" * 64,
        ),
        release_id=RELEASE,
    )
    _worker_call(
        truth,
        event_id="EVT-BRIDGE",
        worker="WORKER-REQ",
        task_id="TASK-REQ",
        tool_name="mcp__pfc_aitest_rc7__truth_query",
        call_ref="dsh://call/bridge",
    )
    if browser_call:
        _worker_call(
            truth,
            event_id="EVT-BROWSER",
            worker="WORKER-EXEC",
            task_id="TASK-EXEC",
            tool_name="browserskill_navigate",
            call_ref="dsh://call/browser",
        )
    else:
        _worker_call(
            truth,
            event_id="EVT-EXEC",
            worker="WORKER-EXEC",
            task_id="TASK-EXEC",
            tool_name="runner_execute",
            call_ref="dsh://call/runner",
        )

    for index, predecessor, successor in (
        (1, "SESSION-A", "SESSION-B"),
        (2, "SESSION-B", "SESSION-C"),
    ):
        truth.append_atomic(
            SESSION_EVENT,
            {
                "handoff_id": "HANDOFF-%d" % index,
                "mission_id": MISSION,
                "release_id": RELEASE,
                "task_id": "TASK-REQ",
                "generation": index,
                "predecessor_session_ref": predecessor,
                "successor_session_ref": successor,
                "status": "ACTIVATED",
                "task_state": "RUNNING",
                "artifact_refs": [],
                "gap_refs": [],
                "activated_at": 100 + index,
                "artifact_version": 1,
            },
        )
    return path


def test_plugin_effect_qualification_requires_activation_plus_runtime_effect(tmp_path):
    r1 = _build_r1(tmp_path)
    profile = _profile(tmp_path / "runtime-profile.json")
    result = evaluate_plugin_effects(
        r1_path=str(r1),
        mission_id=MISSION,
        runtime_profile_evidence=str(profile),
    )
    assert result["status"] == "PASS"
    assert not result["blocking_reasons"]
    assert all(row["status"] == "PASS" for row in result["activation"].values())
    assert all(row["status"] == "PASS" for row in result["effects"].values())
    assert result["effects"]["dsh-context"]["session_refs"] == ["SESSION-A", "SESSION-B", "SESSION-C"]


def test_browser_plugin_is_not_effective_without_real_browser_call(tmp_path):
    r1 = _build_r1(tmp_path, browser_call=False)
    profile = _profile(tmp_path / "runtime-profile.json")
    result = evaluate_plugin_effects(
        r1_path=str(r1),
        mission_id=MISSION,
        runtime_profile_evidence=str(profile),
    )
    assert result["status"] == "HOLD"
    assert result["activation"]["@wxg-prc-cpg/browser-skill-dsh-plugin"]["status"] == "PASS"
    assert result["effects"]["@wxg-prc-cpg/browser-skill-dsh-plugin"]["status"] == "HOLD"
    assert "PLUGIN_CAPABILITY_EFFECT_NOT_PROVEN:@wxg-prc-cpg/browser-skill-dsh-plugin" in result["blocking_reasons"]


def test_bundled_or_profile_presence_cannot_replace_activation_proof(tmp_path):
    r1 = _build_r1(tmp_path)
    missing = REQUIRED[0]
    profile = _profile(tmp_path / "runtime-profile.json", missing_package=missing)
    result = evaluate_plugin_effects(
        r1_path=str(r1),
        mission_id=MISSION,
        runtime_profile_evidence=str(profile),
    )
    assert result["status"] == "HOLD"
    assert result["activation"][missing]["status"] == "HOLD"
    assert "PLUGIN_ACTIVATION_NOT_PROVEN:%s" % missing in result["blocking_reasons"]
