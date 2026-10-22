from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from rc8_node.execution import ExecutionAdapterError, MavenJUnitExecutionAdapter


def _fake_maven(
    tmp_path: Path,
    *,
    failures: int = 0,
    exit_code: int = 0,
    write_report: bool = True,
    report_name: str = "TEST-rc8.xml",
    gb18030_output: bool = False,
) -> str:
    project = tmp_path / "project"
    report_dir = project / "target" / "surefire-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    xml = '<testsuite name="rc8" tests="2" failures="%s" errors="0" skipped="0"></testsuite>' % failures
    script = tmp_path / ("fake_maven_%s.py" % report_name.replace(".", "_"))
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "report = Path(%r)\n" % str(report_dir / report_name) +
        "if %r:\n" % write_report +
        "    report.parent.mkdir(parents=True, exist_ok=True)\n"
        "    report.write_text(%r, encoding='utf-8')\n" % xml +
        ("sys.stdout.buffer.write('中文 Maven 输出'.encode('gb18030'))\n" if gb18030_output else "print('RC8 Maven execution')\n") +
        "raise SystemExit(%s)\n" % exit_code,
        encoding="utf-8",
    )
    if os.name == "nt":
        path = tmp_path / "mvn.cmd"
        path.write_text('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, script), encoding="utf-8")
    else:
        path = tmp_path / "mvn"
        path.write_text('#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n' % (sys.executable, script), encoding="utf-8")
        path.chmod(0o755)
    return str(path)


def _write_stale_report(project: Path, *, tests: int = 2182, errors: int = 1810) -> Path:
    report = project / "target" / "surefire-reports" / "TEST-stale.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        '<testsuite name="old" tests="%s" failures="0" errors="%s" skipped="0"></testsuite>' % (tests, errors),
        encoding="utf-8",
    )
    return report


def test_real_subprocess_execution_parses_only_fresh_junit_actual(tmp_path: Path) -> None:
    command = _fake_maven(tmp_path)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    result = adapter.execute(str(tmp_path / "project"))
    assert result.returncode == 0
    assert result.actual.tests == 2
    assert result.actual.passed is True
    assert result.execution_passed is True
    payload = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert payload["execution_passed"] is True
    assert payload["junit_freshness"]["fresh_reports"] == 1
    assert "created/changed by this attempt" in payload["truth_note"]
    assert Path(result.stdout_path).is_file()
    assert Path(result.stderr_path).is_file()


def test_junit_failure_overrides_zero_process_exit_for_pass_truth(tmp_path: Path) -> None:
    command = _fake_maven(tmp_path, failures=1, exit_code=0)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    result = adapter.execute(str(tmp_path / "project"))
    assert result.returncode == 0
    assert result.actual.failures == 1
    assert result.actual.passed is False
    assert result.execution_passed is False


def test_success_without_fresh_junit_xml_fails_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    command = _fake_maven(tmp_path, write_report=False)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    with pytest.raises(ExecutionAdapterError, match="JUNIT_XML_EVIDENCE_MISSING"):
        adapter.execute(str(project))


def test_historical_surefire_xml_is_ignored_when_maven_fails_before_tests(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    stale = _write_stale_report(project)
    command = _fake_maven(tmp_path, exit_code=1, write_report=False)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    result = adapter.execute(str(project))

    assert stale.is_file()
    assert result.returncode == 1
    assert result.classification == "MAVEN_FAILED_BEFORE_FRESH_JUNIT"
    assert result.actual.tests == 0
    assert result.actual.errors == 0
    assert result.actual.xml_files == []
    assert result.stale_xml_ignored == 1
    assert result.execution_passed is False

    payload = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert payload["junit_freshness"]["stale_reports_ignored"] == 1
    assert payload["junit_freshness"]["fresh_reports"] == 0
    assert payload["actual"]["tests"] == 0


def test_stale_report_is_not_counted_when_new_report_is_created(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_stale_report(project)
    command = _fake_maven(tmp_path, report_name="TEST-current.xml")
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    result = adapter.execute(str(project))

    assert result.actual.tests == 2
    assert result.actual.errors == 0
    assert result.stale_xml_ignored == 1
    assert len(result.actual.xml_files) == 1
    assert result.actual.xml_files[0].endswith("TEST-current.xml")


def test_gb18030_maven_output_is_normalized_to_utf8_evidence(tmp_path: Path) -> None:
    command = _fake_maven(tmp_path, gb18030_output=True)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    result = adapter.execute(str(tmp_path / "project"))

    assert result.returncode == 0
    assert result.stdout_encoding == "gb18030"
    assert "中文 Maven 输出" in Path(result.stdout_path).read_text(encoding="utf-8")
    assert result.execution_passed is True


def test_maven_nonzero_never_becomes_execution_pass_even_if_fresh_junit_is_green(tmp_path: Path) -> None:
    command = _fake_maven(tmp_path, exit_code=1, write_report=True)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)
    result = adapter.execute(str(tmp_path / "project"))

    assert result.actual.passed is True
    assert result.returncode == 1
    assert result.execution_passed is False
    assert result.classification == "MAVEN_NONZERO_WITH_FRESH_JUNIT"
