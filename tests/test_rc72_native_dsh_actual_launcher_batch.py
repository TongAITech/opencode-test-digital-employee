"""C10 real RC6 DshHeadlessWorkerLauncher integration (controlled subprocess output).

Unlike tests with overridden launchers, execute/assign here are the actual
native RC6 implementations: HMAC identities, task leases, process environment,
worker lifecycle R1 events, native raw JSONL, and one model-call R1 receipt per
shared batch. Only command_runner returns controlled local CI JSONL; this is
NOT a bank/provider Field test and never proves business execution PASS.
"""
from __future__ import annotations

import json
import subprocess

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.authority import AuthorityRuntime
from rc7_runtime.rc72_model_usage import TokenUsageAuditService
from rc7_runtime.rc72_native_shared_batch_composition import compose_native_batch_services

from test_rc72_native_shared_batch import (
    MISSION, RELEASE, _execution_output, _review_output, _fixture,
)


def _native_launcher(truth, tmp_path, *, label, authority, output, tools):
    binary = tmp_path / "dsh-test-binary"
    binary.write_text("controlled test command path\n", encoding="utf-8")
    patch = tmp_path / "approved-native-patch.json"
    patch.write_text("{}", encoding="utf-8")
    process_calls = []

    def runner(command, **kwargs):
        process_calls.append((tuple(command), dict(kwargs)))
        assert command[0] == str(binary)
        assert command[-2] == "--json"
        assert kwargs["check"] is False
        events = [{"type": "session", "session_id": "session-" + label}]
        for name in tools:
            events.append({"type": "tool_call", "tool_name": name})
        events.append({
            "type": "final", "provider": "controlled-contract-test",
            "usage": {
                "input_tokens": 60, "output_tokens": 30, "total_tokens": 90,
            },
            "text": json.dumps(output),
        })
        return subprocess.CompletedProcess(
            command, 0,
            stdout="\n".join(json.dumps(event) for event in events) + "\n",
            stderr="",
        )

    launcher = DshHeadlessWorkerLauncher(
        dsh_bin=str(binary), patch_path=str(patch),
        cwd=str(tmp_path), truth=truth, authority=authority,
        coordinator_instance_id="coordinator-contract",
        release_id=RELEASE,
        state_root=str(tmp_path / ("native-" + label)),
        command_runner=runner,
    )
    return launcher, process_calls


def _assignment(launcher, *, agent, role, scope, attempt, refs, tools):
    return launcher.assign(
        agent_id=agent, role=role, phase="N7_EXECUTION",
        mission_id=MISSION, attempt_id=attempt, scope=scope,
        input_refs=refs,
        allowed_artifact_types=(),
        allowed_tools=tools,
    )


def test_native_rc6_assign_execute_replay_batch_and_independent_reviewer(tmp_path):
    truth, economy, batch, _, _, _ = _fixture(tmp_path)
    authority = AuthorityRuntime(b"rc72-c10-real-native-launcher-contract-key")
    executor, execution_commands = _native_launcher(
        truth, tmp_path, label="executor", authority=authority,
        output=_execution_output(),
        tools=("approved-real-tool", "approved-real-tool"),
    )
    reviewer, reviewer_commands = _native_launcher(
        truth, tmp_path, label="reviewer", authority=authority,
        output=_review_output(),
        tools=("read-evidence",),
    )
    services = compose_native_batch_services(
        truth, release_id=RELEASE, mission_id=MISSION,
        execution_launcher=executor, evaluator_launcher=reviewer,
        economy=economy,
        usage_audit=TokenUsageAuditService(truth, release_id=RELEASE),
    )
    refs = set(batch.context_envelope.shared_refs)
    for item_refs in batch.context_envelope.workitem_refs.values():
        refs.update(item_refs)
    signed_executor = _assignment(
        executor, agent="shared-n7-runner", role="L3_EXECUTE",
        scope="execution-batch:" + batch.batch_id,
        attempt="ATT-NATIVE-BATCH", refs=tuple(sorted(refs)),
        tools=("approved-real-tool",),
    )
    candidate = services.execution.dispatch(
        batch,
        attempt_ids_by_workitem={"WI-1": "ATT-1", "WI-2": "ATT-2"},
        assignment=signed_executor,
    )
    assert candidate["status"] == "UNVERIFIED"
    assert len(candidate["members"]) == 2
    assert len(execution_commands) == 1
    assert "CASE-WI-1" in execution_commands[0][0][-1]
    assert "CASE-WI-2" in execution_commands[0][0][-1]

    signed_reviewer = _assignment(
        reviewer, agent="independent-n7-evaluator", role="REQUIREMENT_REVIEWER",
        scope="evaluation-batch:" + batch.batch_id,
        attempt="ATT-NATIVE-REVIEW",
        refs=(candidate["raw_output_ref"],), tools=("read-evidence",),
    )
    reviewed = services.evaluator.review(
        candidate_id=candidate["candidate_id"],
        assignment=signed_reviewer,
    )
    assert reviewed["status"] == "UNVERIFIED_INDEPENDENT_REVIEW"
    assert len(reviewer_commands) == 1
    assert reviewed["dsh_session_id"] != candidate["dsh_session_id"]
    assert reviewed["worker_instance_id"] != candidate["worker_instance_id"]

    raw_calls = truth.query("rc72_token_call", mission_id=MISSION)
    assert len(raw_calls) == 2
    assert {row["process_outcome"] for row in raw_calls} == {"RETURNED"}
    assert economy.summary(MISSION)["dsh_process_invocations"] == 2
    # Native RC6 Worker events are produced by the real launcher, not
    # invented by test fixture or C10 batch service.
    runtime_events = truth.query("agent_runtime_event", mission_id=MISSION)
    assert len([e for e in runtime_events
                if e.get("event_name") == "WORKER_STARTED"]) == 2
    assert len([e for e in runtime_events
                if e.get("event_name") == "HANDOFF_RETURNED"]) == 2
    assert len([e for e in runtime_events
                if e.get("event_name") == "WORKER_TOOL_CALLED"]) == 3

    assert truth.query("execution_attempt", mission_id=MISSION) == []
    assert truth.query("assertion", release_id=RELEASE) == []
    assert truth.query("rc72_node_gate", mission_id=MISSION) == []
