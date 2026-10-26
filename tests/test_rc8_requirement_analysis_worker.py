from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rc8_node.dsh_json_runner import DshJsonResult, DshJsonRunnerError
from rc8_node.requirement_analysis_worker import RequirementAnalysisWorker
from rc8_runtime import NodeIdentity


FIELDS = (
    "source_assertions",
    "atomic_statements",
    "trace_links",
    "evidence_refs",
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
)


def _candidate():
    value = {field: [] for field in FIELDS}
    value["source_assertions"] = ["src"]
    value["atomic_statements"] = ["A1"]
    value["evidence_refs"] = ["source:REQ.md#L1-L5"]
    value["trace_links"] = [{"statement_ref": "A1", "evidence_ref": "source:REQ.md#L1-L5"}]
    value["normal_paths"] = ["normal"]
    return value


class FakeCenter:
    def __init__(self, *, source_refs=None):
        self.sequence = -1
        self.source_refs = list(source_refs or [])

    def get(self, path, **_kwargs):
        if path.startswith("/api/v1/requirement-revisions/"):
            return {
                "requirement_revision_id": "REQ-V2",
                "requirement_id": "REQ",
                "revision_label": "V2",
                "payload": {"source_refs": list(self.source_refs)},
            }
        if path.startswith("/api/v1/scope-revisions/"):
            return {
                "scope_revision_id": "SR2",
                "requirement_revision_id": "REQ-V2",
                "revision_label": "SR2",
                "payload": {},
            }
        if path.endswith("/runtime-sequence"):
            return {"latest_sequence": self.sequence, "next_sequence": self.sequence + 1}
        raise AssertionError(path)


class FakeAgent:
    def __init__(self, center):
        self.center = center
        self.identity = NodeIdentity(
            node_id="NODE-1",
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
        self.failed = []

    def start(self, work_item_id, *, lease_id):
        self.started.append((work_item_id, lease_id))
        return {"work_item": {"state": "RUNNING"}}

    def append_runtime_event(self, event, *, lease_id):
        self.events.append((event, lease_id))
        self.center.sequence = max(self.center.sequence, event.sequence)
        return {"receipt": {"status": "PERSISTENCE_VERIFIED"}}

    def upload_artifact_file(self, manifest, file_path, *, lease_id, **_kwargs):
        path = Path(file_path)
        assert path.is_file()
        body = json.loads(path.read_text(encoding="utf-8"))
        self.uploads.append((manifest, body, lease_id))
        return {"manifest": {"availability": "AVAILABLE"}}

    def complete(self, work_item_id, *, lease_id):
        self.completed.append((work_item_id, lease_id))
        return {"work_item": {"state": "COMPLETED"}}

    def fail(self, work_item_id, *, lease_id):
        self.failed.append((work_item_id, lease_id))
        terminal = "BLOCKED" if self.events[-1][0].event_type == "ATTEMPT_BLOCKED" else "FAILED"
        return {"work_item": {"state": terminal}}


class SuccessRunner:
    def __init__(self):
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return DshJsonResult(
            session_id="session-worker-1",
            tool_calls=({"call_ref": "dsh-event://tool-call/1", "tool_name": "read"},),
            output=_candidate(),
            stdout="{}",
            stderr="",
            exit_code=0,
        )


class FailingRunner:
    def run(self, _prompt):
        raise DshJsonRunnerError("DSH_TIMEOUT", stdout="partial", stderr="timeout")


class NeverRunner:
    def run(self, _prompt):
        raise AssertionError("runner must not be invoked without revision source refs")


def _claim():
    return SimpleNamespace(
        lease_id="LEASE-1",
        stage_instance_id="STAGE-REQ",
        work_item={
            "identity": {
                "work_item_id": "WORK-REQ",
                "test_run_id": "TR-1",
                "stage": "REQUIREMENT_ANALYSIS",
                "scope_refs": [
                    "delivery-scope:SCOPE-1",
                    "stage-instance:STAGE-REQ",
                    "test-round:ROUND-1",
                    "requirement-revision:REQ-V2",
                    "scope-revision:SR2",
                ],
            },
            "lease_id": "LEASE-1",
        },
    )


def test_success_uses_center_lease_attempt_and_only_revision_declared_sources(tmp_path: Path) -> None:
    center = FakeCenter(source_refs=["file:///bank/REQ-V2.md"])
    agent = FakeAgent(center)
    runner = SuccessRunner()
    worker = RequirementAnalysisWorker(agent=agent, dsh_runner=runner, work_dir=str(tmp_path), now_fn=lambda: 100)

    result = worker.execute(_claim())
    assert result["status"] == "COMPLETED"
    assert result["attempt_id"] == "LEASE-1"
    assert len(runner.prompts) == 1
    assert "file:///bank/REQ-V2.md" in runner.prompts[0]
    assert "RequirementRevision REQ-V2" in runner.prompts[0]
    assert agent.started == [("WORK-REQ", "LEASE-1")]
    assert [event.event_type for event, _lease in agent.events] == ["ATTEMPT_COMPLETED"]
    assert all(event.attempt_id == "LEASE-1" for event, _lease in agent.events)
    assert all(event.event_type != "ATTEMPT_STARTED" for event, _lease in agent.events)
    assert len(agent.uploads) == 1
    manifest, body, lease = agent.uploads[0]
    assert manifest.kind == "REQUIREMENT_ANALYSIS"
    assert manifest.attempt_id == "LEASE-1"
    assert lease == "LEASE-1"
    assert body["requirement_revision_id"] == "REQ-V2"
    assert body["scope_revision_id"] == "SR2"
    assert body["source_refs"] == ["file:///bank/REQ-V2.md"]
    assert body["dsh_session_id"] == "session-worker-1"
    assert agent.completed == [("WORK-REQ", "LEASE-1")]
    assert agent.failed == []


def test_missing_revision_sources_blocks_under_center_owned_attempt_without_calling_model(tmp_path: Path) -> None:
    center = FakeCenter(source_refs=[])
    agent = FakeAgent(center)
    worker = RequirementAnalysisWorker(agent=agent, dsh_runner=NeverRunner(), work_dir=str(tmp_path), now_fn=lambda: 100)

    result = worker.execute(_claim())
    assert result["status"] == "BLOCKED"
    assert result["attempt_id"] == "LEASE-1"
    assert result["reason"] == "REQUIREMENT_REVISION_SOURCE_REFS_REQUIRED"
    assert [event.event_type for event, _lease in agent.events] == ["ATTEMPT_BLOCKED"]
    assert agent.events[-1][0].attempt_id == "LEASE-1"
    assert agent.events[-1][0].data["failure_ownership"] == "DEPENDENCY"
    assert agent.completed == []
    assert agent.failed == [("WORK-REQ", "LEASE-1")]
    assert agent.uploads[0][0].kind == "REQUIREMENT_ANALYSIS_FAILURE"
    assert agent.uploads[0][0].attempt_id == "LEASE-1"


def test_dsh_failure_is_evidenced_under_center_owned_attempt(tmp_path: Path) -> None:
    center = FakeCenter(source_refs=["file:///bank/REQ-V2.md"])
    agent = FakeAgent(center)
    worker = RequirementAnalysisWorker(agent=agent, dsh_runner=FailingRunner(), work_dir=str(tmp_path), now_fn=lambda: 100)

    result = worker.execute(_claim())
    assert result["status"] == "FAILED_RUNTIME"
    assert result["attempt_id"] == "LEASE-1"
    assert result["reason"] == "DSH_TIMEOUT"
    assert [event.event_type for event, _lease in agent.events] == ["ATTEMPT_FAILED_RUNTIME"]
    assert agent.events[-1][0].attempt_id == "LEASE-1"
    assert agent.events[-1][0].data["failure_ownership"] == "SESSION_RUNTIME"
    assert agent.uploads[0][1]["detail"]["stderr_tail"] == "timeout"
    assert agent.uploads[0][0].attempt_id == "LEASE-1"
    assert agent.completed == []
    assert agent.failed == [("WORK-REQ", "LEASE-1")]


def test_worker_rejects_claim_without_frozen_revision_refs(tmp_path: Path) -> None:
    claim = _claim()
    claim.work_item["identity"]["scope_refs"] = ["delivery-scope:SCOPE-1"]
    worker = RequirementAnalysisWorker(
        agent=FakeAgent(FakeCenter(source_refs=["x"])),
        dsh_runner=SuccessRunner(),
        work_dir=str(tmp_path),
    )
    try:
        worker.execute(claim)
        raise AssertionError("missing revision refs must fail")
    except Exception as exc:
        assert "REQUIREMENT_REVISION_REF_REQUIRED_EXACTLY_ONCE" in str(exc)
