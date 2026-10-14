from __future__ import annotations

from rc7_runtime.dsh_proof import DshR1ProofReader, code_tool_category


class _Store:
    def __init__(self, events):
        self._events = list(events)

    def iter_raw(self):
        return iter(self._events)


class _Truth:
    def __init__(self, events):
        self.store = _Store(events)


def _event(event_id, mission, worker, tool_name, call_ref):
    return {
        "event_id": event_id,
        "event_type": "WORKER_TOOL_CALLED",
        "payload": {
            "mission_id": mission,
            "worker_instance_id": worker,
            "tool_call": {"tool_name": tool_name, "call_ref": call_ref},
        },
    }


def test_code_tool_category_does_not_confuse_gitnexus_with_git() -> None:
    assert code_tool_category("git") == "git"
    assert code_tool_category("mcp__pfc__git_diff") == "git"
    assert code_tool_category("codegraph") == "codegraph"
    assert code_tool_category("mcp__pfc__codegraph_callers") == "codegraph"
    assert code_tool_category("gitnexus") == "gitnexus"
    assert code_tool_category("mcp__pfc__gitnexus_query") == "gitnexus"


def test_r1_proof_reader_scopes_real_calls_by_mission_and_worker() -> None:
    mission = "MISSION-CODE-PROOF"
    worker = "worker-code"
    truth = _Truth(
        [
            _event("evt-git", mission, worker, "mcp__pfc__git_diff", "call://git/1"),
            _event("evt-cg", mission, worker, "mcp__pfc__codegraph_callers", "call://cg/1"),
            _event("evt-gn", mission, worker, "gitnexus", "call://gn/1"),
            _event("evt-other-mission", "MISSION-OTHER", worker, "git", "call://git/other"),
            _event("evt-other-worker", mission, "worker-other", "git", "call://git/other-worker"),
        ]
    )

    grouped = DshR1ProofReader().code_tool_calls(
        truth,
        mission_id=mission,
        worker_instance_id=worker,
    )

    assert [item.call_ref for item in grouped["git"]] == ["call://git/1"]
    assert [item.call_ref for item in grouped["codegraph"]] == ["call://cg/1"]
    assert [item.call_ref for item in grouped["gitnexus"]] == ["call://gn/1"]
    assert grouped["other"] == ()
