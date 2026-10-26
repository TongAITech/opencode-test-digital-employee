from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rc8_node.scope_intake_worker import ScopeIntakeWorker
from rc8_runtime import NodeIdentity


class FakeCenter:
    def __init__(self):
        self.sequence = -1

    def get(self, path, **_kwargs):
        if path.endswith("/runtime-sequence"):
            return {"latest_sequence": self.sequence, "next_sequence": self.sequence + 1}
        raise AssertionError(path)


class FakeAgent:
    def __init__(self):
        self.center = FakeCenter()
        self.identity = NodeIdentity(
            node_id="NODE-SCOPE",
            operator_ref="test",
            os_family="linux",
            architecture="x86_64",
            shell="bash",
            registered_at=1,
        )
        self.started = []
        self.events = []
        self.uploads = []
        self.completed = []

    def start(self, work_item_id, *, lease_id):
        self.started.append((work_item_id, lease_id))
        # Simulate the real Center-owned ATTEMPT_STARTED consuming sequence 0.
        self.center.sequence = max(self.center.sequence, 0)
        return {"work_item": {"state": "RUNNING"}}

    def append_runtime_event(self, event, *, lease_id):
        self.events.append((event, lease_id))
        self.center.sequence = event.sequence
        return {"receipt": {"status": "PERSISTENCE_VERIFIED"}}

    def upload_artifact_file(self, manifest, file_path, *, lease_id, **_kwargs):
        path = Path(file_path)
        self.uploads.append((manifest, json.loads(path.read_text(encoding="utf-8")), lease_id))
        return {"manifest": {"availability": "AVAILABLE"}}

    def complete(self, work_item_id, *, lease_id):
        self.completed.append((work_item_id, lease_id))
        return {"work_item": {"state": "COMPLETED"}}


def _claim():
    return SimpleNamespace(
        lease_id="LEASE-SCOPE",
        stage_instance_id="STAGE-SCOPE",
        work_item={
            "identity": {
                "work_item_id": "WORK-SCOPE",
                "test_run_id": "TR-SCOPE",
                "stage": "SCOPE_INTAKE",
                "scope_refs": ["delivery-scope:SCOPE-1", "test-round:ROUND-1"],
            },
            "lease_id": "LEASE-SCOPE",
        },
    )


def test_scope_intake_worker_uses_center_attempt_and_publishes_available_evidence_before_completion(tmp_path: Path) -> None:
    agent = FakeAgent()
    worker = ScopeIntakeWorker(agent=agent, work_dir=str(tmp_path), now_fn=lambda: 100)
    result = worker.execute(_claim())

    assert result["status"] == "COMPLETED"
    assert result["attempt_id"] == "LEASE-SCOPE"
    assert agent.started == [("WORK-SCOPE", "LEASE-SCOPE")]

    # Worker must never create ATTEMPT_STARTED; Center already did that in start().
    assert [event.event_type for event, _ in agent.events] == ["ATTEMPT_COMPLETED"]
    assert [event.sequence for event, _ in agent.events] == [1]
    terminal_event = agent.events[0][0]
    assert terminal_event.attempt_id == "LEASE-SCOPE"
    assert terminal_event.data["evidence_refs"] == [result["artifact_ref"]]
    assert "input_snapshot_ref" not in terminal_event.data

    manifest, content, lease = agent.uploads[0]
    assert lease == "LEASE-SCOPE"
    assert manifest.kind == "SCOPE_INTAKE"
    assert manifest.attempt_id == "LEASE-SCOPE"
    assert content["scope_refs"] == ["delivery-scope:SCOPE-1", "test-round:ROUND-1"]
    assert content["input_snapshot_ref"].startswith("scope-intake:")
    assert agent.completed == [("WORK-SCOPE", "LEASE-SCOPE")]
