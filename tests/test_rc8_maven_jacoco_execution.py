from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from rc8_node.execution import MavenJUnitExecutionAdapter
from rc8_node.jacoco import ChangedCoverageScope, ChangedLine, ChangedMethod


def _scope() -> ChangedCoverageScope:
    return ChangedCoverageScope(
        source_snapshot_ref="snapshot:l1-head",
        lines=(
            ChangedLine("com/acme", "Foo.java", 10),
            ChangedLine("com/acme", "Foo.java", 11),
        ),
        methods=(ChangedMethod("com/acme/Foo", "classify", "(I)I"),),
    )


def _fake_maven(tmp_path: Path, *, write_jacoco: bool, failures: int = 0) -> str:
    project = tmp_path / "project"
    junit = project / "target" / "surefire-reports" / "TEST-l1.xml"
    jacoco = project / "target" / "site" / "jacoco" / "jacoco.xml"
    script = tmp_path / "fake_maven_jacoco.py"
    junit_xml = '<testsuite name="l1" tests="2" failures="%s" errors="0" skipped="0"></testsuite>' % failures
    jacoco_xml = """<report name="l1">
  <package name="com/acme">
    <class name="com/acme/Foo" sourcefilename="Foo.java">
      <method name="classify" desc="(I)I" line="10"><counter type="INSTRUCTION" missed="0" covered="5"/></method>
    </class>
    <sourcefile name="Foo.java">
      <line nr="10" mi="0" ci="3" mb="0" cb="2"/>
      <line nr="11" mi="2" ci="0" mb="1" cb="1"/>
    </sourcefile>
  </package>
</report>"""
    script.write_text(
        "from pathlib import Path\n"
        "junit = Path(%r)\n" % str(junit) +
        "junit.parent.mkdir(parents=True, exist_ok=True)\n"
        "junit.write_text(%r, encoding='utf-8')\n" % junit_xml +
        ("jacoco = Path(%r)\n" % str(jacoco) +
         "jacoco.parent.mkdir(parents=True, exist_ok=True)\n"
         "jacoco.write_text(%r, encoding='utf-8')\n" % jacoco_xml if write_jacoco else "") +
        "print('RC8 L1 Maven execution')\n",
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


def test_wb_execution_requires_fresh_jacoco_for_requested_changed_scope(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    command = _fake_maven(tmp_path, write_jacoco=True)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)

    result = adapter.execute(str(project), coverage_scope=_scope())

    assert result.actual.passed is True
    assert result.coverage_required is True
    assert result.coverage is not None
    assert result.coverage.changed_method.covered == 1
    assert result.coverage.changed_method.total == 1
    assert result.coverage.changed_line.covered == 1
    assert result.coverage.changed_line.total == 2
    assert result.coverage.changed_branch.covered == 3
    assert result.coverage.changed_branch.total == 4
    assert result.execution_passed is True
    payload = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert payload["jacoco"]["required"] is True
    assert payload["jacoco"]["collected"] is True
    assert payload["execution_passed"] is True


def test_green_junit_without_current_jacoco_cannot_pass_wb_execution(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    command = _fake_maven(tmp_path, write_jacoco=False)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)

    result = adapter.execute(str(project), coverage_scope=_scope())

    assert result.actual.passed is True
    assert result.returncode == 0
    assert result.coverage is None
    assert result.coverage_classification == "JACOCO_XML_EVIDENCE_MISSING"
    assert result.classification == "JACOCO_XML_EVIDENCE_MISSING"
    assert result.execution_passed is False


def test_historical_jacoco_cannot_satisfy_new_maven_attempt(tmp_path: Path) -> None:
    project = tmp_path / "project"
    stale = project / "target" / "site" / "jacoco" / "jacoco.xml"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("<report name='historical'></report>", encoding="utf-8")
    command = _fake_maven(tmp_path, write_jacoco=False)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)

    result = adapter.execute(str(project), coverage_scope=_scope())

    assert stale.is_file()
    assert result.coverage is None
    assert result.coverage_classification == "JACOCO_XML_EVIDENCE_MISSING"
    assert result.execution_passed is False


def test_missing_jacoco_does_not_hide_a_more_primitive_junit_failure(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    command = _fake_maven(tmp_path, write_jacoco=False, failures=1)
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)

    result = adapter.execute(str(project), coverage_scope=_scope())

    assert result.actual.passed is False
    assert result.coverage is None
    assert result.coverage_classification == "JACOCO_XML_EVIDENCE_MISSING"
    assert result.classification == "JUNIT_FRESH_REPORTS_COLLECTED"
    assert result.execution_passed is False
