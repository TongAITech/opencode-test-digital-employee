from __future__ import annotations

import json
from types import SimpleNamespace

from rc7_runtime.rc72_context_worker_bridge import Rc72ContextAwareDshTaskWorkerBridge
from rc7_runtime.rc72_model_usage import DshTokenUsageParser
from rc7_runtime.rc72_model_usage_worker_bridge import Rc72TokenUsageLauncherProxy


class _RecordingAudit:
    def __init__(self):
        self.calls = []

    def observe(self, **kwargs):
        self.calls.append(kwargs)
        return DshTokenUsageParser.parse(kwargs["events"])


class _DelegateLauncher:
    def __init__(self, invocation, output):
        self.invocation = invocation
        self.output = output
        self.calls = []

    def execute(self, assignment, prompt):
        self.calls.append((assignment, prompt))
        return self.invocation, self.output


class _Control:
    def __init__(self):
        self.truth = SimpleNamespace(query=lambda *args, **kwargs: [])


def _write_jsonl(tmp_path, events):
    path = tmp_path / "assignment.jsonl"
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )
    return "file://" + path.as_posix()


def _invocation(raw_output_ref):
    return SimpleNamespace(
        mission_id="MISSION-REAL",
        attempt_id="ATT-REAL",
        assignment_id="ASN-REAL",
        dsh_session_id="session-real",
        evidence_refs=["dsh://session/session-real", raw_output_ref],
    )


def test_measured_dsh_usage_reaches_audit_with_canonical_invocation_ids(tmp_path):
    raw_ref = _write_jsonl(
        tmp_path,
        [
            {"type": "session", "session_id": "session-real"},
            {"type": "tool_call", "tool_name": "codegraph"},
            {
                "type": "final",
                "provider": "bank-provider",
                "model": "bank-model",
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 180,
                    "total_tokens": 1380,
                },
                "text": "{}",
            },
        ],
    )
    invocation = _invocation(raw_ref)
    output = {"task_id": "WI-1"}
    delegate = _DelegateLauncher(invocation, output)
    audit = _RecordingAudit()
    proxy = Rc72TokenUsageLauncherProxy(delegate, audit)

    assignment = object()
    returned = proxy.execute(assignment, "real prompt")

    assert returned == (invocation, output)
    assert delegate.calls == [(assignment, "real prompt")]
    assert len(audit.calls) == 1
    observed = audit.calls[0]
    assert observed["mission_id"] == "MISSION-REAL"
    assert observed["attempt_id"] == "ATT-REAL"
    assert observed["assignment_id"] == "ASN-REAL"
    assert observed["dsh_session_id"] == "session-real"
    assert observed["raw_output_ref"] == raw_ref
    parsed = DshTokenUsageParser.parse(observed["events"])
    assert parsed.observation_status == "OBSERVED"
    assert parsed.provider == "bank-provider"
    assert parsed.model == "bank-model"
    assert parsed.input_tokens == 1200
    assert parsed.output_tokens == 180
    assert parsed.total_tokens == 1380


def test_proven_model_response_without_counters_is_unknown_never_zero(tmp_path):
    raw_ref = _write_jsonl(
        tmp_path,
        [
            {"type": "session", "session_id": "session-real"},
            {"type": "tool_call", "tool_name": "database"},
            {"type": "final", "text": "{\"task_id\":\"WI-1\"}"},
        ],
    )
    audit = _RecordingAudit()
    proxy = Rc72TokenUsageLauncherProxy(
        _DelegateLauncher(_invocation(raw_ref), {"task_id": "WI-1"}),
        audit,
    )

    proxy.execute(object(), "prompt")

    assert len(audit.calls) == 1
    parsed = DshTokenUsageParser.parse(audit.calls[0]["events"])
    assert parsed.observation_status == "UNKNOWN"
    assert parsed.unknown_reason == "TOKEN_USAGE_NOT_EXPOSED_BY_DSH_JSONL"
    assert parsed.input_tokens is None
    assert parsed.output_tokens is None
    assert parsed.total_tokens is None


def test_unrelated_jsonl_events_do_not_create_fake_usage_observation(tmp_path):
    raw_ref = _write_jsonl(
        tmp_path,
        [
            {"type": "session", "session_id": "session-real"},
            {"type": "tool_call", "tool_name": "codegraph"},
            {
                "type": "tool_result",
                "tool_name": "codegraph",
                "status": "ok",
                "input_tokens": 999,
            },
            {"type": "stderr", "text": "diagnostic only"},
        ],
    )
    audit = _RecordingAudit()
    proxy = Rc72TokenUsageLauncherProxy(
        _DelegateLauncher(_invocation(raw_ref), {"task_id": "WI-1"}),
        audit,
    )

    proxy.execute(object(), "prompt")

    assert audit.calls == []


def test_rc72_context_bridge_wraps_launcher_without_changing_execute_tuple(tmp_path):
    raw_ref = _write_jsonl(
        tmp_path,
        [
            {"type": "final", "usage": {"input_tokens": 7, "output_tokens": 3}},
        ],
    )
    invocation = _invocation(raw_ref)
    output = {"task_id": "WI-1"}
    delegate = _DelegateLauncher(invocation, output)
    audit = _RecordingAudit()

    bridge = Rc72ContextAwareDshTaskWorkerBridge(
        _Control(),
        delegate,
        token_usage_audit=audit,
    )

    assert isinstance(bridge.launcher, Rc72TokenUsageLauncherProxy)
    returned = bridge.launcher.execute(object(), "prompt")
    assert returned == (invocation, output)
    assert len(audit.calls) == 1
