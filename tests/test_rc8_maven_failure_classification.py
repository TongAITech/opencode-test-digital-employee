from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from rc8_node.execution import MavenJUnitExecutionAdapter
from rc8_runtime.governance import FailureOwnership


def _fake_maven(tmp_path: Path, junit_xml: str, *, exit_code: int = 1) -> str:
    project = tmp_path / "project"
    report = project / "target" / "surefire-reports" / "TEST-failure.xml"
    script = tmp_path / "fake_maven_failure.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "path = Path(%r)\n" % str(report)
        + "path.parent.mkdir(parents=True, exist_ok=True)\n"
        + "path.write_text(%r, encoding='utf-8')\n" % junit_xml
        + "print('fresh junit failure written')\n"
        + "raise SystemExit(%s)\n" % exit_code,
        encoding="utf-8",
    )
    if os.name == "nt":
        wrapper = tmp_path / "mvn.cmd"
        wrapper.write_text('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, script), encoding="utf-8")
    else:
        wrapper = tmp_path / "mvn"
        wrapper.write_text('#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n' % (sys.executable, script), encoding="utf-8")
        wrapper.chmod(0o755)
    return str(wrapper)


def test_fresh_assertion_failure_is_unknown_and_requires_semantic_review(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    command = _fake_maven(
        tmp_path,
        '''<testsuite tests="1" failures="1" errors="0" skipped="0">
          <testcase classname="com.acme.FooTest" name="businessRule">
            <failure type="org.opentest4j.AssertionFailedError" message="expected: &lt;A&gt; but was: &lt;B&gt;">stack</failure>
          </testcase>
        </testsuite>''',
    )
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)

    result = adapter.execute(str(project))

    assert result.returncode == 1
    assert result.actual.failures == 1
    assert result.execution_passed is False
    assert result.failure_classification is not None
    assert result.failure_classification.primary_ownership == FailureOwnership.UNKNOWN
    assert result.failure_classification.semantic_review_required is True
    payload = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert payload["failure_classification"]["primary_ownership"] == "UNKNOWN"
    assert payload["failure_classification"]["semantic_review_required"] is True
    assert Path(result.failure_classification.result_path).is_file()


def test_fresh_dependency_failure_is_classified_without_product_claim(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    command = _fake_maven(
        tmp_path,
        '''<testsuite tests="1" failures="0" errors="1" skipped="0">
          <testcase classname="com.acme.FooTest" name="loadsDependency">
            <error type="java.lang.NoClassDefFoundError" message="com/acme/Missing">java.lang.NoClassDefFoundError: com/acme/Missing</error>
          </testcase>
        </testsuite>''',
    )
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)

    result = adapter.execute(str(project))

    assert result.failure_classification is not None
    assert result.failure_classification.primary_ownership == FailureOwnership.DEPENDENCY
    assert result.failure_classification.semantic_review_required is False
    assert all(fact.ownership != FailureOwnership.PRODUCT for fact in result.failure_classification.facts)


def test_green_current_attempt_does_not_reuse_historical_failure_classification(tmp_path: Path) -> None:
    project = tmp_path / "project"
    stale = project / "target" / "surefire-reports" / "TEST-old.xml"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(
        '<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase classname="Old" name="old"><failure type="java.lang.AssertionError">old</failure></testcase></testsuite>',
        encoding="utf-8",
    )
    command = _fake_maven(
        tmp_path,
        '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="New" name="green"/></testsuite>',
        exit_code=0,
    )
    adapter = MavenJUnitExecutionAdapter(str(tmp_path / "evidence"), maven_command=command)

    result = adapter.execute(str(project))

    assert result.actual.passed is True
    assert result.stale_xml_ignored == 1
    assert result.failure_classification is None
    payload = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert payload["failure_classification"]["collected"] is False
    assert payload["failure_classification"]["primary_ownership"] is None
