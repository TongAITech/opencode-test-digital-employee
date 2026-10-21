from pathlib import Path

import pytest

from rc8_node.execution import JUnitActual, MavenExecutionResult
from rc8_node.work_item_execution import execute_maven_junit_work_item
from rc8_runtime import NodeIdentity


class RecordingAgent:
    def __init__(self, available=True):
        self.identity = NodeIdentity(node_id="node-1", operator_ref="tester", os_family="linux", architecture="x86_64", shell="bash", registered_at=1)
        self.available = available
        self.calls = []

    def lease(self, work_item_id, ttl_seconds=60):
        self.calls.append(("lease", work_item_id, ttl_seconds))
        return {"state": "LEASED"}

    def start(self, work_item_id):
        self.calls.append(("start", work_item_id))
        return {"state": "RUNNING"}

    def upload_artifact_file(self, manifest, file_path):
        self.calls.append(("artifact", manifest.kind))
        return {"availability": "AVAILABLE" if self.available else "UPLOADING"}

    def append_runtime_event(self, event):
        self.calls.append(("r1", event.event_type, event.data["passed"]))
        return {"status": "APPENDED"}

    def complete(self, work_item_id):
        self.calls.append(("complete", work_item_id))
        return {"state": "COMPLETED"}


class RecordingAdapter:
    def __init__(self, tmp_path, failures=0):
        self.tmp_path = tmp_path
        self.failures = failures
        self.calls = []

    def execute(self, project_dir, goals=None):
        self.calls.append((project_dir, goals))
        actual_path = self.tmp_path / "actual.json"
        stdout_path = self.tmp_path / "stdout.log"
        stderr_path = self.tmp_path / "stderr.log"
        xml_path = self.tmp_path / "TEST-one.xml"
        actual_path.write_text('{"actual":true}', encoding="utf-8")
        stdout_path.write_text("maven output", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        xml_path.write_text('<testsuite tests="1" failures="%s" errors="0" skipped="0"/>' % self.failures, encoding="utf-8")
        actual = JUnitActual(tests=1, failures=self.failures, errors=0, skipped=0, xml_files=[str(xml_path)])
        return MavenExecutionResult(["mvn", "test"], 0, 1, 2, actual, str(actual_path), "0" * 64, str(stdout_path), str(stderr_path))


def test_work_item_orders_lease_start_execution_evidence_r1_complete(tmp_path):
    agent = RecordingAgent()
    adapter = RecordingAdapter(tmp_path)
    result = execute_maven_junit_work_item(
        agent, adapter, test_run_id="run-1", work_item_id="wi-1", project_dir=str(tmp_path),
        event_id="evt-1", sequence=10, goals=["test"], lease_ttl_seconds=321,
    )
    names = [call[0] for call in agent.calls]
    assert names[:2] == ["lease", "start"]
    assert names[-2:] == ["r1", "complete"]
    assert names.count("artifact") == 4
    assert adapter.calls == [(str(tmp_path), ["test"])]
    assert result["actual_passed"] is True


def test_failed_actual_is_recorded_before_completion_not_converted_to_pass(tmp_path):
    agent = RecordingAgent()
    adapter = RecordingAdapter(tmp_path, failures=1)
    result = execute_maven_junit_work_item(
        agent, adapter, test_run_id="run-1", work_item_id="wi-1", project_dir=str(tmp_path),
        event_id="evt-2", sequence=11,
    )
    r1 = [call for call in agent.calls if call[0] == "r1"]
    assert r1 == [("r1", "MAVEN_JUNIT_ACTUAL_RECORDED", False)]
    assert agent.calls[-1] == ("complete", "wi-1")
    assert result["actual_passed"] is False


def test_missing_available_evidence_fail_closes_without_completion(tmp_path):
    agent = RecordingAgent(available=False)
    adapter = RecordingAdapter(tmp_path)
    with pytest.raises(Exception, match="EXECUTION_EVIDENCE_NOT_AVAILABLE"):
        execute_maven_junit_work_item(
            agent, adapter, test_run_id="run-1", work_item_id="wi-1", project_dir=str(tmp_path),
            event_id="evt-3", sequence=12,
        )
    names = [call[0] for call in agent.calls]
    assert "r1" not in names
    assert "complete" not in names
