from pathlib import Path

import pytest

from rc8_node.agent import NodeAgentError
from rc8_node.execution import JUnitActual, MavenExecutionResult
from rc8_node.execution_publish import CoveragePublishContext, publish_maven_junit_execution
from rc8_node.jacoco import CoverageActual, JaCoCoCoverageResult
from rc8_runtime import NodeIdentity


class RecordingAgent:
    def __init__(self, available=True):
        self.identity = NodeIdentity(
            node_id="node-1", operator_ref="tester", os_family="linux",
            architecture="x86_64", shell="bash", registered_at=1,
        )
        self.available = available
        self.calls = []
        self.manifests = []
        self.events = []

    def upload_artifact_file(self, manifest, file_path):
        assert Path(file_path).is_file()
        self.calls.append(("artifact", manifest.kind))
        self.manifests.append(manifest)
        return {"artifact_id": manifest.artifact_id, "availability": "AVAILABLE" if self.available else "UPLOADING"}

    def append_runtime_event(self, event):
        self.calls.append(("r1", event.event_type))
        self.events.append(event)
        return {"status": "APPENDED", "event_id": event.event_id}


def _result(tmp_path: Path) -> MavenExecutionResult:
    actual_path = tmp_path / "actual.json"
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    junit_path = tmp_path / "TEST-l1.xml"
    jacoco_actual_path = tmp_path / "jacoco-changed-scope-actual.json"
    jacoco_xml_path = tmp_path / "jacoco.xml"
    actual_path.write_text('{"actual":true}', encoding="utf-8")
    stdout_path.write_text("maven output", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    junit_path.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"/>', encoding="utf-8")
    jacoco_actual_path.write_text('{"coverage":true}', encoding="utf-8")
    jacoco_xml_path.write_text('<report name="l1"/>', encoding="utf-8")
    coverage = JaCoCoCoverageResult(
        source_snapshot_ref="snapshot:l1-head",
        reports=(str(jacoco_xml_path),),
        report_sha256=("1" * 64,),
        changed_method=CoverageActual(1, 1),
        changed_line=CoverageActual(3, 4, ("com/acme/Foo.java:14",)),
        changed_branch=CoverageActual(2, 4),
        stale_reports_ignored=0,
        result_path=str(jacoco_actual_path),
        sha256="2" * 64,
    )
    actual = JUnitActual(tests=1, failures=0, errors=0, skipped=0, xml_files=[str(junit_path)])
    return MavenExecutionResult(
        ["mvn", "test"], 0, 1, 2, actual, str(actual_path), "0" * 64,
        str(stdout_path), str(stderr_path), "JUNIT_FRESH_REPORTS_COLLECTED", 0,
        "utf-8", "utf-8", coverage, True, "JACOCO_CHANGED_SCOPE_COLLECTED",
    )


def _context() -> CoveragePublishContext:
    return CoveragePublishContext(
        stage_instance_id="stage-l1-execution",
        attempt_id="attempt-1",
        subject_ref="sst:SST-001",
    )


def test_coverage_evidence_is_available_before_three_r1_coverage_events(tmp_path: Path) -> None:
    agent = RecordingAgent()
    published = publish_maven_junit_execution(
        agent,
        test_run_id="run-1",
        work_item_id="wi-1",
        result=_result(tmp_path),
        event_id="evt-exec-1",
        sequence=20,
        coverage_context=_context(),
    )

    assert len(agent.manifests) == 6
    assert [event.event_type for event in agent.events] == [
        "MAVEN_JUNIT_ACTUAL_RECORDED",
        "COVERAGE_COLLECTED",
        "COVERAGE_COLLECTED",
        "COVERAGE_COLLECTED",
    ]
    assert [event.sequence for event in agent.events] == [20, 21, 22, 23]
    dimensions = [event.data["metric"]["dimension"] for event in agent.events[1:]]
    assert dimensions == ["CHANGED_METHOD", "CHANGED_LINE", "CHANGED_BRANCH"]
    assert [event.data["metric"]["covered"] for event in agent.events[1:]] == [1, 3, 2]
    assert [event.data["metric"]["total"] for event in agent.events[1:]] == [1, 4, 4]
    assert all(event.attempt_id == "attempt-1" for event in agent.events)
    first_r1 = next(index for index, call in enumerate(agent.calls) if call[0] == "r1")
    assert all(call[0] == "artifact" for call in agent.calls[:first_r1])
    assert len(published["coverage_events"]) == 3
    assert published["actual_passed"] is True


def test_coverage_result_without_governance_context_is_rejected_before_upload(tmp_path: Path) -> None:
    agent = RecordingAgent()
    with pytest.raises(NodeAgentError, match="COVERAGE_PUBLISH_CONTEXT_REQUIRED"):
        publish_maven_junit_execution(
            agent,
            test_run_id="run-1",
            work_item_id="wi-1",
            result=_result(tmp_path),
            event_id="evt-exec-2",
            sequence=30,
        )
    assert agent.calls == []


def test_unavailable_jacoco_or_execution_artifact_blocks_all_runtime_events(tmp_path: Path) -> None:
    agent = RecordingAgent(available=False)
    with pytest.raises(NodeAgentError, match="EXECUTION_EVIDENCE_NOT_AVAILABLE"):
        publish_maven_junit_execution(
            agent,
            test_run_id="run-1",
            work_item_id="wi-1",
            result=_result(tmp_path),
            event_id="evt-exec-3",
            sequence=40,
            coverage_context=_context(),
        )
    assert agent.events == []
