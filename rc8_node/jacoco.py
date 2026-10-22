"""Snapshot-bound JaCoCo coverage collection for the RC8 L1 closed loop.

JaCoCo is execution evidence, not a sufficiency decision.  The collector accepts
an explicit changed-code scope from the code-analysis stage, ignores unchanged
historical reports, and materializes deterministic changed method/line/branch
Actual.  Coverage gaps are facts for later governance evaluation; they are not
silently promoted to Layer PASS.
"""
from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class JaCoCoCoverageError(RuntimeError):
    pass


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JaCoCoCoverageError("%s_REQUIRED" % name.upper())
    return value.strip()


def _normalize_package(value: str) -> str:
    return _required(value, "package_name").replace(".", "/").strip("/")


def _normalize_class(value: str) -> str:
    return _required(value, "class_name").replace(".", "/").strip("/")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass(frozen=True)
class ChangedLine:
    package_name: str
    source_file: str
    line_number: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "package_name", _normalize_package(self.package_name))
        object.__setattr__(self, "source_file", _required(self.source_file, "source_file").replace("\\", "/").split("/")[-1])
        if not isinstance(self.line_number, int) or self.line_number < 1:
            raise JaCoCoCoverageError("LINE_NUMBER_INVALID")

    @property
    def key(self) -> str:
        return "%s/%s:%s" % (self.package_name, self.source_file, self.line_number)


@dataclass(frozen=True)
class ChangedMethod:
    class_name: str
    method_name: str
    descriptor: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_name", _normalize_class(self.class_name))
        object.__setattr__(self, "method_name", _required(self.method_name, "method_name"))
        object.__setattr__(self, "descriptor", _required(self.descriptor, "descriptor"))

    @property
    def key(self) -> str:
        return "%s#%s%s" % (self.class_name, self.method_name, self.descriptor)


@dataclass(frozen=True)
class ChangedCoverageScope:
    source_snapshot_ref: str
    lines: Tuple[ChangedLine, ...] = tuple()
    methods: Tuple[ChangedMethod, ...] = tuple()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_snapshot_ref", _required(self.source_snapshot_ref, "source_snapshot_ref"))
        if not isinstance(self.lines, tuple) or not all(isinstance(item, ChangedLine) for item in self.lines):
            raise JaCoCoCoverageError("CHANGED_LINES_INVALID")
        if not isinstance(self.methods, tuple) or not all(isinstance(item, ChangedMethod) for item in self.methods):
            raise JaCoCoCoverageError("CHANGED_METHODS_INVALID")
        if not self.lines and not self.methods:
            raise JaCoCoCoverageError("CHANGED_COVERAGE_SCOPE_EMPTY")
        if len({item.key for item in self.lines}) != len(self.lines):
            raise JaCoCoCoverageError("CHANGED_LINE_DUPLICATE")
        if len({item.key for item in self.methods}) != len(self.methods):
            raise JaCoCoCoverageError("CHANGED_METHOD_DUPLICATE")


@dataclass(frozen=True)
class CoverageActual:
    covered: int
    total: int
    missing_subjects: Tuple[str, ...] = tuple()

    @property
    def ratio(self) -> float:
        return 1.0 if self.total == 0 else float(self.covered) / float(self.total)


@dataclass(frozen=True)
class JaCoCoCoverageResult:
    source_snapshot_ref: str
    reports: Tuple[str, ...]
    report_sha256: Tuple[str, ...]
    changed_method: CoverageActual
    changed_line: CoverageActual
    changed_branch: CoverageActual
    stale_reports_ignored: int
    result_path: str
    sha256: str
    classification: str = "JACOCO_CHANGED_SCOPE_COLLECTED"


ReportFingerprint = Tuple[int, int, str]


class JaCoCoChangedScopeCollector:
    """Collect JaCoCo Actual only from reports created/changed by this attempt."""

    capability_id = "jacoco-changed-scope"

    def __init__(self, evidence_dir: str) -> None:
        self.evidence_dir = Path(evidence_dir)

    @staticmethod
    def _report_paths(project_dir: Path) -> List[Path]:
        # Covers the normal per-module report and jacoco-aggregate without
        # assuming a fixed Maven module layout.
        return sorted(set(project_dir.glob("**/target/site/jacoco*/jacoco.xml")))

    @staticmethod
    def _fingerprint(path: Path) -> ReportFingerprint:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size, _sha256(path))

    def snapshot(self, project_dir: str) -> Dict[str, ReportFingerprint]:
        root = Path(project_dir)
        if not root.is_dir():
            raise JaCoCoCoverageError("JACOCO_PROJECT_DIR_NOT_FOUND")
        result: Dict[str, ReportFingerprint] = {}
        for path in self._report_paths(root):
            try:
                result[str(path.resolve())] = self._fingerprint(path)
            except OSError as exc:
                raise JaCoCoCoverageError("JACOCO_XML_SNAPSHOT_FAILED:%s" % path.name) from exc
        return result

    def _fresh_reports(self, root: Path, before: Mapping[str, ReportFingerprint]) -> Tuple[List[Path], int]:
        fresh: List[Path] = []
        stale = 0
        for path in self._report_paths(root):
            resolved = str(path.resolve())
            try:
                current = self._fingerprint(path)
            except OSError as exc:
                raise JaCoCoCoverageError("JACOCO_XML_SNAPSHOT_FAILED:%s" % path.name) from exc
            if before.get(resolved) != current:
                fresh.append(path)
            else:
                stale += 1
        return fresh, stale

    @staticmethod
    def _counter(element: ET.Element, counter_type: str) -> Tuple[int, int]:
        for child in element:
            if _local_name(child.tag) != "counter" or child.attrib.get("type") != counter_type:
                continue
            try:
                return int(child.attrib.get("missed", "0")), int(child.attrib.get("covered", "0"))
            except ValueError as exc:
                raise JaCoCoCoverageError("JACOCO_COUNTER_INVALID:%s" % counter_type) from exc
        return 0, 0

    @staticmethod
    def _parse_report(path: Path) -> Tuple[Dict[str, Tuple[int, int, int, int]], Dict[str, Tuple[int, int]]]:
        try:
            root = ET.parse(str(path)).getroot()
        except (OSError, ET.ParseError) as exc:
            raise JaCoCoCoverageError("JACOCO_XML_INVALID:%s" % path) from exc

        lines: Dict[str, Tuple[int, int, int, int]] = {}
        methods: Dict[str, Tuple[int, int]] = {}
        for package in root.iter():
            if _local_name(package.tag) != "package":
                continue
            package_name = str(package.attrib.get("name") or "").strip("/")
            for child in package:
                tag = _local_name(child.tag)
                if tag == "sourcefile":
                    source_file = str(child.attrib.get("name") or "")
                    for line in child:
                        if _local_name(line.tag) != "line":
                            continue
                        try:
                            number = int(line.attrib.get("nr", "0"))
                            values = (
                                int(line.attrib.get("mi", "0")),
                                int(line.attrib.get("ci", "0")),
                                int(line.attrib.get("mb", "0")),
                                int(line.attrib.get("cb", "0")),
                            )
                        except ValueError as exc:
                            raise JaCoCoCoverageError("JACOCO_LINE_COUNTER_INVALID:%s" % path) from exc
                        key = "%s/%s:%s" % (package_name, source_file, number)
                        previous = lines.get(key)
                        if previous is not None and previous != values:
                            raise JaCoCoCoverageError("JACOCO_LINE_CONFLICT:%s" % key)
                        lines[key] = values
                elif tag == "class":
                    class_name = str(child.attrib.get("name") or "").replace(".", "/").strip("/")
                    for method in child:
                        if _local_name(method.tag) != "method":
                            continue
                        name = str(method.attrib.get("name") or "")
                        descriptor = str(method.attrib.get("desc") or "")
                        missed, covered = JaCoCoChangedScopeCollector._counter(method, "INSTRUCTION")
                        key = "%s#%s%s" % (class_name, name, descriptor)
                        values = (missed, covered)
                        previous = methods.get(key)
                        if previous is not None and previous != values:
                            raise JaCoCoCoverageError("JACOCO_METHOD_CONFLICT:%s" % key)
                        methods[key] = values
        return lines, methods

    @staticmethod
    def _merge_reports(paths: Iterable[Path]) -> Tuple[Dict[str, Tuple[int, int, int, int]], Dict[str, Tuple[int, int]]]:
        all_lines: Dict[str, Tuple[int, int, int, int]] = {}
        all_methods: Dict[str, Tuple[int, int]] = {}
        for path in paths:
            lines, methods = JaCoCoChangedScopeCollector._parse_report(path)
            for key, values in lines.items():
                previous = all_lines.get(key)
                if previous is not None and previous != values:
                    raise JaCoCoCoverageError("JACOCO_LINE_CONFLICT:%s" % key)
                all_lines[key] = values
            for key, values in methods.items():
                previous = all_methods.get(key)
                if previous is not None and previous != values:
                    raise JaCoCoCoverageError("JACOCO_METHOD_CONFLICT:%s" % key)
                all_methods[key] = values
        return all_lines, all_methods

    def collect_fresh(
        self,
        project_dir: str,
        *,
        before: Mapping[str, ReportFingerprint],
        scope: ChangedCoverageScope,
    ) -> JaCoCoCoverageResult:
        root = Path(project_dir)
        if not root.is_dir():
            raise JaCoCoCoverageError("JACOCO_PROJECT_DIR_NOT_FOUND")
        fresh, stale = self._fresh_reports(root, before)
        if not fresh:
            raise JaCoCoCoverageError("JACOCO_XML_EVIDENCE_MISSING")
        lines, methods = self._merge_reports(fresh)

        missing_lines: List[str] = []
        covered_lines = 0
        branch_covered = 0
        branch_total = 0
        for subject in scope.lines:
            values = lines.get(subject.key)
            if values is None:
                missing_lines.append(subject.key)
                continue
            _mi, ci, mb, cb = values
            if ci > 0:
                covered_lines += 1
            branch_covered += cb
            branch_total += mb + cb

        missing_methods: List[str] = []
        covered_methods = 0
        for subject in scope.methods:
            values = methods.get(subject.key)
            if values is None:
                missing_methods.append(subject.key)
                continue
            _missed, covered = values
            if covered > 0:
                covered_methods += 1

        method_actual = CoverageActual(covered_methods, len(scope.methods), tuple(missing_methods))
        line_actual = CoverageActual(covered_lines, len(scope.lines), tuple(missing_lines))
        branch_actual = CoverageActual(branch_covered, branch_total, tuple(missing_lines))
        report_hashes = tuple(_sha256(path) for path in fresh)

        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "capability_id": self.capability_id,
            "classification": "JACOCO_CHANGED_SCOPE_COLLECTED",
            "source_snapshot_ref": scope.source_snapshot_ref,
            "changed_scope": {
                "lines": [asdict(item) for item in scope.lines],
                "methods": [asdict(item) for item in scope.methods],
            },
            "report_freshness": {
                "fresh_reports": len(fresh),
                "stale_reports_ignored": stale,
            },
            "reports": [str(path) for path in fresh],
            "report_sha256": list(report_hashes),
            "actual": {
                "changed_method": asdict(method_actual),
                "changed_line": asdict(line_actual),
                "changed_branch": asdict(branch_actual),
            },
            "truth_note": "Only JaCoCo XML created/changed by this execution is coverage Actual; coverage counts are not a sufficiency decision",
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        result_path = self.evidence_dir / "jacoco-changed-scope-actual.json"
        temp = result_path.with_suffix(".json.tmp")
        temp.write_bytes(encoded)
        os.replace(str(temp), str(result_path))
        return JaCoCoCoverageResult(
            source_snapshot_ref=scope.source_snapshot_ref,
            reports=tuple(str(path) for path in fresh),
            report_sha256=report_hashes,
            changed_method=method_actual,
            changed_line=line_actual,
            changed_branch=branch_actual,
            stale_reports_ignored=stale,
            result_path=str(result_path),
            sha256=hashlib.sha256(encoded).hexdigest(),
        )
