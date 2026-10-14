from __future__ import annotations

import json
import sys
from pathlib import Path

from rc6_release.dsh import write_patch
from rc7_release.dsh_bridge_qualification import (
    _lifecycle_proof,
    _mission_event_count,
    _patch_path,
    run_real_qualification,
)
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.dsh_worker_bridge import DEFAULT_NODE_POLICIES


class _FakeStore:
    def __init__(self, events):
        self._events = list(events)

    def iter_raw(self):
        return iter(self._events)


class _FakeTruth:
    def __init__(self, events):
        self.store = _FakeStore(events)


def _worker_event(event_type: str, mission_id: str, worker_id: str, suffix: int):
    return {
        "event_id": "evt-%s-%s" % (suffix, event_type.lower()),
        "event_type": event_type,
        "payload": {
            "mission_id": mission_id,
            "worker_instance_id": worker_id,
        },
    }


def test_real_qualification_patch_is_a_file_below_state_root(tmp_path) -> None:
    state_root = tmp_path / "state"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    state_root.mkdir(parents=True)

    patch = _patch_path(state_root)
    assert patch != state_root
    assert patch.parent == state_root / "control"

    patch.parent.mkdir(parents=True, exist_ok=True)
    rendered = write_patch(patch, repo_root, sys.executable)
    assert rendered == patch
    assert rendered.is_file()
    text = rendered.read_text(encoding="utf-8")
    assert "pfc_aitest_rc6" in text
    assert str(repo_root.resolve()) in text


def test_real_qualification_is_not_proven_when_dsh_is_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PFC_DSH_BIN", raising=False)
    monkeypatch.setenv("PATH", "")
    state_root = tmp_path / "qualification-state"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)

    result = run_real_qualification(
        state_root=str(state_root),
        repo_root=str(repo_root),
        dsh_bin=None,
        timeout_seconds=1,
    )

    assert result.status == "NOT_PROVEN"
    assert result.reason == "DSH_NOT_AVAILABLE"
    assert result.r1_event_count == 0
    result_path = state_root / "qualification" / "rc7-dsh-bridge-result.json"
    assert result_path.is_file()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "NOT_PROVEN"
    assert payload["reason"] == "DSH_NOT_AVAILABLE"


def test_lifecycle_proof_is_scoped_to_current_mission() -> None:
    mission = "MISSION-CLEAN"
    worker = "worker-clean"
    lifecycle = (
        "WORKER_ASSIGN_REQUESTED",
        "WORKER_ADMITTED",
        "WORKER_STARTED",
        "WORKER_TOOL_CALLED",
        "WORKER_OUTPUT_PRODUCED",
        "WORKER_COMPLETED",
        "HANDOFF_RETURNED",
    )
    events = [
        {
            "event_id": "evt-old-fail",
            "event_type": "ROUTING_INTEGRITY_FAIL",
            "payload": {"mission_id": "MISSION-OLD", "reason": "old failure"},
        }
    ]
    events.extend(
        _worker_event(event_type, mission, worker, index)
        for index, event_type in enumerate(lifecycle, 1)
    )
    truth = _FakeTruth(events)

    proof = _lifecycle_proof(truth, mission, worker)
    assert len(proof) == len(lifecycle)
    assert _mission_event_count(truth, mission) == len(lifecycle)


def test_all_default_dsh_policies_fit_rc7_authority_roles() -> None:
    authority = RC7AuthorityRuntime(b"rc7-authority-test-key-32-bytes!!")
    for node, policy in DEFAULT_NODE_POLICIES.items():
        identity = authority.issue_identity(
            policy.role,
            policy.phase,
            None,
            0,
            "session-%s" % node.lower(),
        )
        lease = authority.issue_lease(
            identity.worker_id,
            "task:%s" % node,
            policy.allowed_artifact_types,
            policy.allowed_tools,
            ttl_seconds=300,
        )
        assert set(lease.allowed_artifact_types) == set(policy.allowed_artifact_types)
        assert set(lease.allowed_tools) == set(policy.allowed_tools)
