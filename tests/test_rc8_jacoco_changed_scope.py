from __future__ import annotations

from pathlib import Path

import pytest

from rc8_node.jacoco import (
    ChangedCoverageScope,
    ChangedLine,
    ChangedMethod,
    JaCoCoChangedScopeCollector,
    JaCoCoCoverageError,
)


def _report(project: Path, xml: str, module: str = "") -> Path:
    base = project / module if module else project
    path = base / "target" / "site" / "jacoco" / "jacoco.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    return path


def _xml(*, line10_ci: int = 3, method_covered: int = 6) -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<report name="rc8">
  <package name="com/acme">
    <class name="com/acme/Foo" sourcefilename="Foo.java">
      <method name="classify" desc="(I)I" line="10">
        <counter type="INSTRUCTION" missed="0" covered="%s"/>
      </method>
    </class>
    <sourcefile name="Foo.java">
      <line nr="10" mi="0" ci="%s" mb="0" cb="2"/>
      <line nr="11" mi="2" ci="0" mb="1" cb="1"/>
    </sourcefile>
  </package>
</report>
""" % (method_covered, line10_ci)


def _scope() -> ChangedCoverageScope:
    return ChangedCoverageScope(
        source_snapshot_ref="snapshot:abc123",
        lines=(
            ChangedLine("com.acme", "Foo.java", 10),
            ChangedLine("com/acme", "Foo.java", 11),
            ChangedLine("com/acme", "Foo.java", 12),
        ),
        methods=(
            ChangedMethod("com.acme.Foo", "classify", "(I)I"),
            ChangedMethod("com/acme/Foo", "uncovered", "()V"),
        ),
    )


def test_collects_changed_method_line_branch_actual_from_fresh_jacoco(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    collector = JaCoCoChangedScopeCollector(str(tmp_path / "evidence"))
    before = collector.snapshot(str(project))
    report = _report(project, _xml())

    result = collector.collect_fresh(str(project), before=before, scope=_scope())

    assert result.reports == (str(report),)
    assert result.changed_method.covered == 1
    assert result.changed_method.total == 2
    assert result.changed_method.missing_subjects == ("com/acme/Foo#uncovered()V",)
    assert result.changed_line.covered == 1
    assert result.changed_line.total == 3
    assert result.changed_line.missing_subjects == ("com/acme/Foo.java:12",)
    assert result.changed_branch.covered == 3
    assert result.changed_branch.total == 4
    assert result.changed_branch.ratio == 0.75
    assert Path(result.result_path).is_file()
    assert result.classification == "JACOCO_CHANGED_SCOPE_COLLECTED"


def test_historical_jacoco_xml_cannot_be_reused_as_current_attempt_truth(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _report(project, _xml())
    collector = JaCoCoChangedScopeCollector(str(tmp_path / "evidence"))
    before = collector.snapshot(str(project))

    with pytest.raises(JaCoCoCoverageError, match="JACOCO_XML_EVIDENCE_MISSING"):
        collector.collect_fresh(str(project), before=before, scope=_scope())


def test_changed_report_after_snapshot_is_fresh_even_when_path_is_unchanged(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    report = _report(project, _xml(line10_ci=0, method_covered=0))
    collector = JaCoCoChangedScopeCollector(str(tmp_path / "evidence"))
    before = collector.snapshot(str(project))
    report.write_text(_xml(line10_ci=3, method_covered=6), encoding="utf-8")

    result = collector.collect_fresh(str(project), before=before, scope=_scope())

    assert result.stale_reports_ignored == 0
    assert result.changed_method.covered == 1
    assert result.changed_line.covered == 1


def test_conflicting_duplicate_subjects_across_fresh_module_reports_fail_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    collector = JaCoCoChangedScopeCollector(str(tmp_path / "evidence"))
    before = collector.snapshot(str(project))
    _report(project, _xml(line10_ci=3), module="module-a")
    _report(project, _xml(line10_ci=1), module="module-b")

    with pytest.raises(JaCoCoCoverageError, match="JACOCO_LINE_CONFLICT"):
        collector.collect_fresh(str(project), before=before, scope=_scope())


def test_changed_scope_must_have_at_least_one_line_or_method() -> None:
    with pytest.raises(JaCoCoCoverageError, match="CHANGED_COVERAGE_SCOPE_EMPTY"):
        ChangedCoverageScope(source_snapshot_ref="snapshot:abc123")


def test_duplicate_changed_subjects_are_rejected() -> None:
    line = ChangedLine("com/acme", "Foo.java", 10)
    with pytest.raises(JaCoCoCoverageError, match="CHANGED_LINE_DUPLICATE"):
        ChangedCoverageScope(source_snapshot_ref="snapshot:abc123", lines=(line, line))
