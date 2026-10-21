from pathlib import Path

import pytest

from rc8_node.agent import NodeAgentError
from rc8_node.execution import JUnitActual, MavenExecutionResult
from rc8_node.execution_publish import publish_maven_junit_execution
from rc8_runtime import NodeIdentity


class RecordingAgent:
    def __init__(self, node_id="node-1", available=True):
        self.identity = NodeIdentity(node_id=node_id, operator_ref="tester", os_family="linux", architecture="x86_64", shell="bash", registered_at=1)
        self.available = available
        self.manifests = []
        self.events = []

    def upload_artifact_file(self, manifest, file_path):
        assert Path(file_path).is_file()
        self.manifests.append(manifest)
        return {"availability": "AVAILABLE" if self.available else "UPLOADING"}

    def append_runtime_event(self, event):
        self.events.append(event)
        return {"status": "APPENDED", "event_id": event.event_id}


def _result(tmp_path, failures=0):
    actual_path = tmp_path / "actual.json"
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    xml_path = tmp_path / "TEST-one.xml"
    actual_path.write_text('{"actual":true}', encoding="utf-8")
    stdout_path.write_text("maven output", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    xml_path.write_text('<testsuite tests="1" failures="%s" errors="0" skipped="0"/>' % failures, encoding="utf-8")
    actual = JUnitActual(tests=1, failures=failures, errors=0, skipped=0, xml_files=[str(xml_path)])
    return MavenExecutionResult(["mvn", "test"], 0, 1, 2, actual, str(actual_path), "0" * 64, str(stdout_path), str(stderr_path))


def test_execution_truth_uploads_evidence_before_r1_event(tmp_path):
    agent = RecordingAgent()
    result = publish_maven_junit_execution(agent, test_run_id="run-1", work_item_id="wi-1", result=_result(tmp_path), event_id="evt-1", sequence=7)
    assert len(agent.manifests) == 4
    assert len(agent.events) == 1
    event = agent.events[0]
    assert event.event_type == "MAVEN_JUNIT_ACTUAL_RECORDED"
    assert event.sequence == 7
    assert event.data["passed"] is True
    assert event.data["truth_source"] == "JUnit XML"
    assert event.refs == [m.artifact_id for m in agent.manifests]
    assert result["actual_passed"] is True


def test_junit_failure_is_published_as_failed_actual_even_when_maven_zero(tmp_path):
    agent = RecordingAgent()
    publish_maven_junit_execution(agent, test_run_id="run-1", work_item_id="wi-1", result=_result(tmp_path, failures=1), event_id="evt-2", sequence=8)
    assert agent.events[0].data["maven_returncode"] == 0
    assert agent.events[0].data["passed"] is False


def test_runtime_event_is_not_appended_until_all_evidence_is_available(tmp_path):
    agent = RecordingAgent(available=False)
    with pytest.raises(NodeAgentError, match="EXECUTION_EVIDENCE_NOT_AVAILABLE"):
        publish_maven_junit_execution(agent, test_run_id="run-1", work_item_id="wi-1", result=_result(tmp_path), event_id="evt-3", sequence=9)
    assert agent.events == []
