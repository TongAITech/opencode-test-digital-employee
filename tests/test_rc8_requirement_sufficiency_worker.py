from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rc8_node.requirement_sufficiency_worker import RequirementSufficiencyWorker
from rc8_runtime import NodeIdentity


def _candidate(*, complete: bool = True):
    return {
        "source_assertions": ["SRC-1"] if complete else [],
        "atomic_statements": ["A1"],
        "trace_links": [{"statement_ref": "A1", "evidence_ref": "source:REQ#1"}],
        "evidence_refs": ["source:REQ#1"],
        "business_rules": [],
        "roles": [],
        "preconditions": [],
        "normal_paths": ["normal"] if complete else [],
        "negative_paths": [],
        "boundaries": [],
        "states": [],
        "data_constraints": [],
        "dependencies": [],
        "side_effects": [],
    }


def _analysis(candidate):
    return {
        "schema_version": "rc8.requirement-analysis.v1",
        "requirement_revision_id": "REQ-V2",
        "scope_revision_id": "SR2",
        "candidate": candidate,
    }


class FakeCenter:
    def __init__(self, analysis):
        self.analysis = analysis
        self.sequence = -1
        self.reads = []

    def get(self, path, **kwargs):
        if "/artifacts/ANALYSIS/json" in path:
            self.reads.append((path, kwargs.get("headers") or {}))
            return {
                "artifact_id": "ANALYSIS",
                "manifest": {"availability": "AVAILABLE"},
                "content": self.analysis,
            }
        if path.endswith("/runtime-sequence"):
            return {"latest_sequence": self.sequence, "next_sequence": self.sequence + 1}
        raise AssertionError(path)


class FakeAgent:
    def __init__(self, center):
        self.center = center
        self.identity = NodeIdentity(
            node_id="NODE-SUFF",
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
        return {"work_item": {"state": "RUNNING"}}

    def append_runtime_event(self, event, *, lease_id):
        self.events.append((event, lease_id))
        self.center.sequence = max(self.center.sequence, event.sequence)
        return {"receipt": {"status": "PERSISTENCE_VERIFIED"}}

    def upload_artifact_file(self, manifest, file_path, *, lease_id, **_kwargs):
        path = Path(file_path)
        assert path.is_file()
        self.uploads.append((manifest, json.loads(path.read_text(encoding="utf-8")), lease_id))
        return {"manifest": {"availability": "AVAILABLE"}}

    def complete(self, work_item_id, *, lease_id):
        self.completed.append((work_item_id, lease_id))
        return {"work_item": {"state": "COMPLETED"}}


def _claim(*, gap_id=None):
    refs = [
        "delivery-scope:SCOPE-1",
        "stage-instance:STAGE-SUFF",
        "test-round:ROUND-1",
        "requirement-revision:REQ-V2",
        "scope-revision:SR2",
        "artifact:ANALYSIS",
    ]
    if gap_id:
        refs.append("gap:%s" % gap_id)
    return SimpleNamespace(
        lease_id="LEASE-SUFF",
        stage_instance_id="STAGE-SUFF",
        work_item={
            "identity": {
                "work_item_id": "WORK-SUFF",
                "test_run_id": "TR-1",
                "stage": "REQUIREMENT_SUFFICIENCY",
                "scope_refs": refs,
            },
            "lease_id": "LEASE-SUFF",
        },
    )


def test_complete_analysis_produces_policy_sufficient_not_model_pass(tmp_path: Path) -> None:
    center = FakeCenter(_analysis(_candidate(complete=True)))
    agent = FakeAgent(center)
    worker = RequirementSufficiencyWorker(agent=agent, work_dir=str(tmp_path), now_fn=lambda: 100)

    result = worker.execute(_claim())
    assert result["result"] == "SUFFICIENT"
    assert [event.event_type for event, _ in agent.events] == [
        "ATTEMPT_STARTED",
        "SUFFICIENCY_EVALUATED",
        "ATTEMPT_COMPLETED",
    ]
    evaluation = agent.events[1][0]
    assert evaluation.data["evaluator_id"] == "RC8_REQUIREMENT_SUFFICIENCY_POLICY"
    assert evaluation.data["policy_version"] == "rc8.requirement-sufficiency.v1"
    assert evaluation.data["result"] == "SUFFICIENT"
    assert evaluation.data["unresolved_gap_ids"] == []
    assert agent.uploads[0][1]["analysis_artifact_ref"] == "artifact:ANALYSIS"
    assert agent.completed == [("WORK-SUFF", "LEASE-SUFF")]
    assert center.reads[0][1]["X-RC8-Lease-Id"] == "LEASE-SUFF"


def test_incomplete_analysis_opens_gap_and_is_insufficient(tmp_path: Path) -> None:
    center = FakeCenter(_analysis(_candidate(complete=False)))
    agent = FakeAgent(center)
    worker = RequirementSufficiencyWorker(agent=agent, work_dir=str(tmp_path), now_fn=lambda: 100)

    result = worker.execute(_claim())
    assert result["result"] == "INSUFFICIENT"
    assert result["gap_id"].startswith("gap-requirement-")
    assert [event.event_type for event, _ in agent.events] == [
        "ATTEMPT_STARTED",
        "GAP_OPENED",
        "SUFFICIENCY_EVALUATED",
        "ATTEMPT_COMPLETED",
    ]
    gap = agent.events[1][0]
    evaluation = agent.events[2][0]
    assert gap.data["owner_stage"] == "REQUIREMENT_ANALYSIS"
    assert gap.data["gap_type"] == "REQUIREMENT_UNCLEAR"
    assert evaluation.data["result"] == "INSUFFICIENT"
    assert evaluation.data["unresolved_gap_ids"] == [result["gap_id"]]
    assert "dimension:requirement-source-assertions" in evaluation.data["unsatisfied_requirement_refs"]
    assert "dimension:requirement-normal-path" in evaluation.data["unsatisfied_requirement_refs"]


def test_repaired_analysis_closes_prior_gap_before_sufficient_evaluation(tmp_path: Path) -> None:
    center = FakeCenter(_analysis(_candidate(complete=True)))
    agent = FakeAgent(center)
    worker = RequirementSufficiencyWorker(agent=agent, work_dir=str(tmp_path), now_fn=lambda: 100)

    result = worker.execute(_claim(gap_id="GAP-OLD"))
    assert result["result"] == "SUFFICIENT"
    assert result["closed_gap_ids"] == ["GAP-OLD"]
    assert [event.event_type for event, _ in agent.events] == [
        "ATTEMPT_STARTED",
        "GAP_CLOSED",
        "SUFFICIENCY_EVALUATED",
        "ATTEMPT_COMPLETED",
    ]
    assert agent.events[1][0].data["gap_id"] == "GAP-OLD"
    assert agent.events[2][0].data["result"] == "SUFFICIENT"


def test_model_supplied_is_sufficient_field_is_ignored(tmp_path: Path) -> None:
    candidate = _candidate(complete=False)
    candidate["is_sufficient"] = True
    center = FakeCenter(_analysis(candidate))
    worker = RequirementSufficiencyWorker(
        agent=FakeAgent(center),
        work_dir=str(tmp_path),
        now_fn=lambda: 100,
    )
    result = worker.execute(_claim())
    assert result["result"] == "INSUFFICIENT"
