"""R1 cold recovery must never repeat a bank tool effect under the same DSH Assignment."""
import json
import subprocess

import pytest
from rc6_runtime.agent_runtime import AgentRuntimeError, DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc6_runtime.authority import AuthorityRuntime


def _worker(tmp_path, responses):
    dsh = tmp_path / "dsh"
    patch = tmp_path / "patch.yml"
    dsh.write_text("stub")
    patch.write_text("stub")
    seen = []
    queue = list(responses)

    def call(command, **kwargs):
        seen.append((tuple(command), kwargs["cwd"]))
        return queue.pop(0)

    truth = TruthRuntime(tmp_path / "r1.jsonl")
    launcher = DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh), patch_path=str(patch), cwd=str(tmp_path),
        truth=truth, authority=AuthorityRuntime(b"0123456789abcdef-p1-recovery"),
        coordinator_instance_id="CAPTAIN-1", release_id="REL-P1",
        state_root=str(tmp_path / "run"), command_runner=call)
    return truth, launcher, seen


def _assign(launcher, attempt):
    return launcher.assign(
        agent_id="P1-WORKER", role="REQUIREMENT_ANALYZER",
        phase="REQUIREMENT_ANALYSIS", mission_id="M-P1",
        attempt_id=attempt, scope="SST-1", input_refs=("r1://input",),
        allowed_artifact_types=("requirement_analysis",),
        allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",))


def _complete(session):
    events = [
        dict(type="session", session_id=session),
        dict(type="tool_call", tool_name="mcp__pfc_aitest_rc6__runtime_status"),
        dict(type="final", text=json.dumps(dict(qualification_payload={"ok": True}))),
    ]
    return subprocess.CompletedProcess([], 0, stdout="\n".join(map(json.dumps, events)), stderr="")


@pytest.mark.parametrize("stderr,code", [
    ("provider HTTP 429 QUOTA_EXCEEDED", "DSH_PROVIDER_429_QUOTA_HOLD_NO_REPLAY"),
    ("HTTP 502 Bad Gateway", "DSH_STREAM_502_UNKNOWN_EFFECT_RECONCILIATION_REQUIRED"),
    ("STREAM_CLOSED remote provider", "DSH_STREAM_502_UNKNOWN_EFFECT_RECONCILIATION_REQUIRED"),
])
def test_transport_failure_records_r1_unknown_and_refuses_cold_assignment_replay(tmp_path, stderr, code):
    truth, launcher, seen = _worker(tmp_path, [
        subprocess.CompletedProcess([], 1, stdout="", stderr=stderr),
        _complete("session-fresh")])
    assignment = _assign(launcher, "attempt-original")
    with pytest.raises(AgentRuntimeError, match=code):
        launcher.execute(assignment, "original bank work")
    assert len(seen) == 1
    first = [row for row in truth.query("agent_runtime_event")
             if row.get("event_name") == "WORKER_COMPLETED"]
    assert len(first) == 1 and first[0]["result"] == "UNKNOWN"
    assert first[0]["business_effect"] == "UNKNOWN"
    assert first[0]["same_assignment_replay"] == "FORBIDDEN"
    assert any(ref.startswith("file://") for ref in first[0]["evidence_refs"])
    before = truth.store.path.read_bytes()
    launcher.truth = TruthRuntime(truth.store.path)
    with pytest.raises(AgentRuntimeError, match="WORKER_ASSIGNMENT_REPLAY_FORBIDDEN"):
        launcher.execute(assignment, "same attempt after restart")
    assert len(seen) == 1 and truth.store.path.read_bytes() == before
    fresh = _assign(launcher, "attempt-new-reviewed")
    invocation, output = launcher.execute(fresh, "new independently permitted attempt")
    assert len(seen) == 2 and invocation.result == "PASS"
    assert output == {"ok": True}
    assert len([row for row in launcher.truth.query("agent_runtime_event")
                if row.get("event_name") == "HANDOFF_RETURNED"]) == 1


def test_cold_dsh_session_identity_reuse_is_rejected(tmp_path):
    truth, launcher, seen = _worker(tmp_path, [
        _complete("session-unchanged"), _complete("session-unchanged")])
    launcher.execute(_assign(launcher, "attempt-one"), "first")
    launcher.truth = TruthRuntime(truth.store.path)
    with pytest.raises(AgentRuntimeError, match="WORKER_SESSION_NOT_INDEPENDENT"):
        launcher.execute(_assign(launcher, "attempt-two"), "second")
    assert len(seen) == 2
    assert len([row for row in launcher.truth.query("agent_runtime_event")
                if row.get("event_name") == "HANDOFF_RETURNED"]) == 1


def test_model_final_text_cannot_invent_http_failure(tmp_path):
    stdout = "\n".join(map(json.dumps, [
        dict(type="session", session_id="session-fresh-1"),
        dict(type="tool_call", tool_name="mcp__pfc_aitest_rc6__runtime_status"),
        dict(type="final", text=json.dumps(dict(qualification_payload={"statement": "HTTP 502"}))),
    ]))
    truth, launcher, _ = _worker(tmp_path, [subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")])
    invocation, _ = launcher.execute(_assign(launcher, "attempt-ok"), "normal")
    assert invocation.result == "PASS"
    assert not [row for row in truth.query("agent_runtime_event")
                if row.get("event_name") == "WORKER_COMPLETED" and row.get("result") == "UNKNOWN"]


def test_worker_start_r1_claim_serializes_concurrent_controllers(tmp_path):
    from rc6_runtime.agent_runtime import _worker_assignment_start_claim
    truth, launcher, seen = _worker(tmp_path, [_complete("session-claim")])
    assignment = _assign(launcher, "single")
    raw = truth.store.path.read_bytes()
    with _worker_assignment_start_claim(truth):
        with pytest.raises(AgentRuntimeError, match="WORKER_ASSIGNMENT_START_LEDGER_BUSY"):
            with _worker_assignment_start_claim(TruthRuntime(truth.store.path)):
                raise AssertionError("lock unexpectedly reentrant")
    assert truth.store.path.read_bytes() == raw
    launcher.execute(assignment, "one invocation")
    assert len(seen) == 1


def test_timeout_is_unknown_side_effect_and_cannot_be_replayed_after_restart(tmp_path):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 2, output=b'partial output', stderr=b'stream closed')
    truth, launcher, _ = _worker(tmp_path, [])
    launcher.command_runner = timeout
    assignment = _assign(launcher, "timeout")
    with pytest.raises(AgentRuntimeError):
        launcher.execute(assignment, "operation possibly in progress")
    entries = [row for row in truth.query("agent_runtime_event")
               if row.get("event_name") == "WORKER_COMPLETED"]
    assert len(entries) == 1 and entries[0]["result"] == "UNKNOWN"
    assert entries[0]["business_effect"] == "UNKNOWN"
    assert entries[0]["same_assignment_replay"] == "FORBIDDEN"
    launcher.truth = TruthRuntime(truth.store.path)
    with pytest.raises(AgentRuntimeError, match="WORKER_ASSIGNMENT_REPLAY_FORBIDDEN"):
        launcher.execute(assignment, "same attempt")
