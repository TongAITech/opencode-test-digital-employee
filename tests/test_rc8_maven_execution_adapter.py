from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rc8_node.execution import ExecutionAdapterError, MavenJUnitExecutionAdapter


def _fake_maven(tmp_path: Path, *, failures: int = 0, exit_code: int = 0) -> str:
    project = tmp_path / "project"
    report_dir = project / "target" / "surefire-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    xml = '<testsuite name="rc8" tests="2" failures="%s" errors="0" skipped="0"></testsuite>' % failures
    if os.name == "nt":
        path = tmp_path / "mvn.cmd"
        path.write_text("@echo off\r\necho RC8 Maven execution\r\nexit /b %s\r\n" % exit_code, encoding="utf-8")
    else:
        path = tmp_path / "mvn"
        path.write_text("#!/usr/bin/env bash\necho 'RC8 Maven execution'\nexit %s\n" % exit_code, encoding="utf-8")
        path.chmod(0o755)
    (report_dir / "TEST-rc8.xml").write_text(xml, encoding="utf-8")
    return str(path)


def test_real_subprocess_execution_parses_junit_actual(tmp_path: Path) -> None:
    command = _fake_maven(tmp_path)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    result = adapter.execute(str(tmp_path / "project"))
    assert result.returncode == 0
    assert result.actual.tests == 2
    assert result.actual.passed is True
    payload = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert payload["actual"]["passed"] is True
    assert "exit code alone never proves PASS" in payload["truth_note"]
    assert Path(result.stdout_path).is_file()
    assert Path(result.stderr_path).is_file()


def test_junit_failure_overrides_zero_process_exit_for_pass_truth(tmp_path: Path) -> None:
    command = _fake_maven(tmp_path, failures=1, exit_code=0)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    result = adapter.execute(str(tmp_path / "project"))
    assert result.returncode == 0
    assert result.actual.failures == 1
    assert result.actual.passed is False


def test_missing_junit_xml_fails_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    command = _fake_maven(tmp_path)
    for path in (project / "target" / "surefire-reports").glob("*.xml"):
        path.unlink()
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    with pytest.raises(ExecutionAdapterError, match="JUNIT_XML_EVIDENCE_MISSING"):
        adapter.execute(str(project))
