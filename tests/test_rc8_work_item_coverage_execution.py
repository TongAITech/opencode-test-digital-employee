from pathlib import Path

import pytest

from rc8_node.execution import JUnitActual, MavenExecutionResult
from rc8_node.execution_publish import CoveragePublishContext
from rc8_node.jacoco import ChangedCoverageScope, ChangedLine, CoverageActual, JaCoCoCoverageResult
from rc8_node.work_item_execution import execute_maven_junit_work_item
from rc8_runtime import NodeIdentity


class RecordingAgent:
    def __init__(self):
        self.identity = NodeIdentity(
            node_id="node-1", operator_ref="tester", os_family="linux",
            architecture="x86_64", shell="bash", registered_at=1,
        )
        self.calls = []
        self.events = []

    def lease(self, work_item_id, ttl_seconds=60):
        self.calls.append(("lease", work_item_id))
        return {"state": "LEASED"}

    def start(self, work_item_id):
        self.calls.append(("start", work_item_id))
        return {"state": "RUNNING"}

    def upload_artifact_file(self, manifest, file_path):
        self.calls.append(("artifact", manifest.kind))
        return {"artifact_id": manifest.artifact_id, "availability": "AVAILABLE"}

    def append_runtime_event(self, event):
        self.calls.append(("r1", event.event_type))
        self.events.append(event)
        return {"status": "APPENDED", "event_id": event.event_id}

    def complete(self, work_item_id):
        self.calls.append(("complete", work_item_id))
        return {"state": "COMPLETED"}


class CoverageAdapter:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.calls = []

    def execute(self, project_dir, goals=None, coverage_scope=None):
        self.calls.append((project_dir, goals, coverage_scope))
        actual_path = self.tmp_path / "actual.json"
        stdout_path = self.tmp_path / "stdout.log"
        stderr_path = self.tmp_path / "stderr.log"
        junit_path = self.tmp_path / "TEST-l1.xml"
        jacoco_actual = self.tmp_path / "jacoco-actual.json"
        jacoco_xml = self.tmp_path / "jacoco.xml"
        actual_path.write_text("{}", encoding="utf-8")
        stdout_path.write_text("ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        junit_path.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"/>', encoding="utf-8")
        jacoco_actual.write_text("{}", encoding="utf-8")
        jacoco_xml.write_text("<report/>", encoding="utf-8")
        coverage = JaCoCoCoverageResult(
            source_snapshot_ref=coverage_scope.source_snapshot_ref,
            reports=(str(jacoco_xml),),
            report_sha256=("1" * 64,),
            changed_method=CoverageActual(0, 0),
            changed_line=CoverageActual(1, 1),
            changed_branch=CoverageActual(0, 0),
            stale_reports_ignored=0,
            result_path=str(jacoco_actual),
            sha256="2" * 64,
        )
        actual = JUnitActual(1, 0, 0, 0, [str(junit_path)])
        return MavenExecutionResult(
            ["mvn", "test"], 0, 1, 2, actual, str(actual_path), "0" * 64,
            str(stdout_path), str(stderr_path), "JUNIT_FRESH_REPORTS_COLLECTED", 0,
            "utf-8", "utf-8", coverage, True, "JACOCO_CHANGED_SCOPE_COLLECTED",
        )


def _scope():
    return ChangedCoverageScope(
        source_snapshot_ref="snapshot:l1-head",
        lines=(ChangedLine("com/acme", "Foo.java", 10),),
    )


def _context():
    return CoveragePublishContext(
        stage_instance_id="stage-l1",
        attempt_id="attempt-l1-1",
        subject_ref="sst:SST-001",
    )


def test_coverage_scope_and_context_flow_through_one_governed_attempt_transaction(tmp_path: Path) -> None:
    agent = RecordingAgent()
    adapter = CoverageAdapter(tmp_path)
    scope = _scope()
    result = execute_maven_junit_work_item(
        agent,
        adapter,
        test_run_id="run-1",
        work_item_id="wi-1",
        project_dir=str(tmp_path),
        event_id="evt-1",
        sequence=50,
        goals=["test", "jacoco:report"],
        coverage_scope=scope,
        coverage_context=_context(),
    )

    assert adapter.calls == [(str(tmp_path), ["test", "jacoco:report"], scope)]
    assert [event.event_type for event in agent.events] == [
        "ATTEMPT_STARTED",
        "MAVEN_JUNIT_ACTUAL_RECORDED",
        "COVERAGE_COLLECTED",
        "COVERAGE_COLLECTED",
        "COVERAGE_COLLECTED",
        "ATTEMPT_COMPLETED",
    ]
    assert [event.sequence for event in agent.events] == [50, 51, 52, 53, 54, 55]
    assert agent.events[0].attempt_id == "attempt-l1-1"
    terminal = agent.events[-1]
    assert terminal.attempt_id == "attempt-l1-1"
    assert terminal.data["stage_instance_id"] == "stage-l1"
    assert terminal.data["input_snapshot_ref"] == "snapshot:l1-head"
    assert len(terminal.data["coverage_refs"]) == 3
    assert terminal.data["gap_refs"] == []
    assert terminal.data.get("failure_ownership") is None
    assert terminal.data["evidence_refs"]
    assert agent.calls[0][0] == "lease"
    assert agent.calls[1][0] == "start"
    assert agent.calls[-1] == ("complete", "wi-1")
    assert result["attempt_started"] is not None
    assert result["attempt_terminal"] is not None
    assert result["actual_passed"] is True
    assert result["coverage_collected"] is True


@pytest.mark.parametrize("scope,context", [(_scope(), None), (None, _context())])
def test_partial_coverage_governance_context_is_rejected_before_lease(tmp_path: Path, scope, context) -> None:
    agent = RecordingAgent()
    adapter = CoverageAdapter(tmp_path)
    with pytest.raises(ValueError, match="COVERAGE_SCOPE_AND_CONTEXT_MUST_BE_SUPPLIED_TOGETHER"):
        execute_maven_junit_work_item(
            agent,
            adapter,
            test_run_id="run-1",
            work_item_id="wi-1",
            project_dir=str(tmp_path),
            event_id="evt-2",
            sequence=60,
            coverage_scope=scope,
            coverage_context=context,
        )
    assert agent.calls == []
    assert adapter.calls == []
