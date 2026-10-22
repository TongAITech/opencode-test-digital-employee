"""Real RC8 Maven/JUnit WorkItem execution adapter.

This adapter runs Maven as a real local subprocess and derives Actual test
results only from JUnit XML created or changed by THIS execution attempt.
Historical Surefire/Failsafe reports are never allowed to become current Actual.
When an L1 changed-code coverage scope is supplied, JaCoCo is snapshotted before
the same Maven process and only fresh reports may become coverage Actual.
Failing fresh JUnit reports are classified conservatively for failure ownership;
ambiguous application/assertion failures remain UNKNOWN for semantic review.
Windows Maven output is captured as bytes and decoded defensively so a local
GBK/GB18030 console cannot crash the truth pipeline.
"""
from __future__ import annotations

import hashlib
import json
import locale
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .failure_classification import FailureClassificationResult, JUnitFailureClassifier
from .jacoco import (
    ChangedCoverageScope,
    JaCoCoChangedScopeCollector,
    JaCoCoCoverageError,
    JaCoCoCoverageResult,
)


class ExecutionAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class JUnitActual:
    tests: int
    failures: int
    errors: int
    skipped: int
    xml_files: List[str]

    @property
    def passed(self) -> bool:
        return self.tests > 0 and self.failures == 0 and self.errors == 0


@dataclass(frozen=True)
class MavenExecutionResult:
    command: List[str]
    returncode: Optional[int]
    started_at: int
    finished_at: int
    actual: JUnitActual
    result_path: str
    sha256: str
    stdout_path: str
    stderr_path: str
    classification: str = "UNKNOWN"
    stale_xml_ignored: int = 0
    stdout_encoding: str = "unknown"
    stderr_encoding: str = "unknown"
    coverage: Optional[JaCoCoCoverageResult] = None
    coverage_required: bool = False
    coverage_classification: str = "NOT_REQUESTED"
    failure_classification: Optional[FailureClassificationResult] = None

    @property
    def execution_passed(self) -> bool:
        """Maven, JUnit Actual and requested L1 coverage evidence must pass their truth gates."""
        process_and_tests = self.returncode == 0 and self.actual.passed
        coverage_ready = not self.coverage_required or self.coverage is not None
        return process_and_tests and coverage_ready


ReportFingerprint = Tuple[int, int, str]


class MavenJUnitExecutionAdapter:
    """Execute one Maven/JUnit WorkItem and materialize machine-readable Actual."""

    capability_id = "maven-junit"

    def __init__(self, evidence_dir: str, *, maven_command: Optional[str] = None, timeout_seconds: int = 900) -> None:
        self.evidence_dir = Path(evidence_dir)
        self.maven_command = (maven_command or os.environ.get("RC8_MVN") or "mvn").strip()
        self.timeout_seconds = timeout_seconds
        if not self.maven_command:
            raise ExecutionAdapterError("MAVEN_COMMAND_REQUIRED")

    @staticmethod
    def _read_suite(path: Path) -> Dict[str, int]:
        try:
            root = ET.parse(str(path)).getroot()
        except (OSError, ET.ParseError) as exc:
            raise ExecutionAdapterError("JUNIT_XML_INVALID:%s" % path.name) from exc
        suites = [root] if root.tag == "testsuite" else list(root.findall(".//testsuite"))
        if not suites:
            raise ExecutionAdapterError("JUNIT_XML_HAS_NO_TESTSUITE:%s" % path.name)
        totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for suite in suites:
            for key in totals:
                raw = suite.attrib.get(key, "0")
                try:
                    totals[key] += int(raw)
                except ValueError as exc:
                    raise ExecutionAdapterError("JUNIT_XML_COUNT_INVALID:%s:%s" % (path.name, key)) from exc
        return totals

    @staticmethod
    def _report_paths(project_dir: Path) -> List[Path]:
        return sorted(set(
            list(project_dir.glob("**/target/surefire-reports/*.xml")) +
            list(project_dir.glob("**/target/failsafe-reports/*.xml"))
        ))

    @staticmethod
    def _fingerprint(path: Path) -> ReportFingerprint:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            while True:
                block = fh.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size, digest.hexdigest())

    def _snapshot_reports(self, project_dir: Path) -> Dict[str, ReportFingerprint]:
        snapshot: Dict[str, ReportFingerprint] = {}
        for path in self._report_paths(project_dir):
            try:
                snapshot[str(path.resolve())] = self._fingerprint(path)
            except OSError as exc:
                raise ExecutionAdapterError("JUNIT_XML_SNAPSHOT_FAILED:%s" % path.name) from exc
        return snapshot

    def _fresh_reports(self, project_dir: Path, before: Dict[str, ReportFingerprint]) -> Tuple[List[Path], int]:
        fresh: List[Path] = []
        stale = 0
        for path in self._report_paths(project_dir):
            resolved = str(path.resolve())
            try:
                current = self._fingerprint(path)
            except OSError as exc:
                raise ExecutionAdapterError("JUNIT_XML_SNAPSHOT_FAILED:%s" % path.name) from exc
            previous = before.get(resolved)
            if previous is None or previous != current:
                fresh.append(path)
            else:
                stale += 1
        return fresh, stale

    def _collect_actual(self, candidates: List[Path]) -> JUnitActual:
        totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for path in candidates:
            values = self._read_suite(path)
            for key in totals:
                totals[key] += values[key]
        return JUnitActual(
            tests=totals["tests"],
            failures=totals["failures"],
            errors=totals["errors"],
            skipped=totals["skipped"],
            xml_files=[str(path) for path in candidates],
        )

    @staticmethod
    def _decode_output(value: Union[bytes, str, None]) -> Tuple[str, str]:
        """Decode subprocess output without trusting the Python UTF-8 mode."""
        if value is None:
            return "", "empty"
        if isinstance(value, str):
            return value, "text"
        candidates: List[str] = ["utf-8", "gb18030"]
        preferred = locale.getpreferredencoding(False) or ""
        if preferred and preferred.lower() not in {item.lower() for item in candidates}:
            candidates.append(preferred)
        for encoding in candidates:
            try:
                return value.decode(encoding, errors="strict"), encoding
            except (UnicodeDecodeError, LookupError):
                continue
        return value.decode("utf-8", errors="replace"), "utf-8-replace"

    def execute(
        self,
        project_dir: str,
        *,
        goals: Optional[List[str]] = None,
        coverage_scope: Optional[ChangedCoverageScope] = None,
    ) -> MavenExecutionResult:
        root = Path(project_dir)
        if not root.is_dir():
            raise ExecutionAdapterError("MAVEN_PROJECT_DIR_NOT_FOUND")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        command = [self.maven_command] + list(goals or ["test"])

        # Snapshot BEFORE the process starts. Unchanged historical reports are
        # stale evidence and must never be counted as this attempt's Actual.
        before_reports = self._snapshot_reports(root)
        coverage_collector: Optional[JaCoCoChangedScopeCollector] = None
        coverage_before: Dict[str, Tuple[int, int, str]] = {}
        if coverage_scope is not None:
            coverage_collector = JaCoCoChangedScopeCollector(str(self.evidence_dir))
            coverage_before = coverage_collector.snapshot(str(root))

        started = int(time.time())
        returncode: Optional[int] = None
        stdout_raw: Union[bytes, str, None] = b""
        stderr_raw: Union[bytes, str, None] = b""
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                capture_output=True,
                text=False,
                timeout=self.timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
            stdout_raw = completed.stdout
            stderr_raw = completed.stderr
        except FileNotFoundError as exc:
            stderr_raw = str(exc)
        except subprocess.TimeoutExpired as exc:
            stdout_raw = exc.stdout
            stderr_raw = (exc.stderr or b"") + (b"\nMAVEN_EXECUTION_TIMEOUT" if isinstance(exc.stderr, (bytes, type(None))) else "\nMAVEN_EXECUTION_TIMEOUT")

        stdout, stdout_encoding = self._decode_output(stdout_raw)
        stderr, stderr_encoding = self._decode_output(stderr_raw)
        stdout_path = self.evidence_dir / "maven-stdout.log"
        stderr_path = self.evidence_dir / "maven-stderr.log"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        if returncode is None:
            raise ExecutionAdapterError("MAVEN_EXECUTION_UNAVAILABLE")

        fresh_reports, stale_ignored = self._fresh_reports(root, before_reports)
        if not fresh_reports:
            if returncode == 0:
                raise ExecutionAdapterError("JUNIT_XML_EVIDENCE_MISSING")
            actual = JUnitActual(tests=0, failures=0, errors=0, skipped=0, xml_files=[])
            classification = "MAVEN_FAILED_BEFORE_FRESH_JUNIT"
        else:
            actual = self._collect_actual(fresh_reports)
            classification = "JUNIT_FRESH_REPORTS_COLLECTED" if returncode == 0 else "MAVEN_NONZERO_WITH_FRESH_JUNIT"

        failure_classification: Optional[FailureClassificationResult] = None
        if actual.failures > 0 or actual.errors > 0:
            failure_classification = JUnitFailureClassifier(str(self.evidence_dir)).classify(actual.xml_files)

        process_and_tests_passed = returncode == 0 and actual.passed
        coverage: Optional[JaCoCoCoverageResult] = None
        coverage_classification = "NOT_REQUESTED"
        if coverage_scope is not None and coverage_collector is not None:
            try:
                coverage = coverage_collector.collect_fresh(
                    str(root), before=coverage_before, scope=coverage_scope,
                )
                coverage_classification = coverage.classification
            except JaCoCoCoverageError as exc:
                coverage_classification = str(exc)
                # Preserve the more primitive Maven/JUnit failure ownership. A
                # missing JaCoCo report only becomes the top classification when
                # the test process itself was otherwise green.
                if process_and_tests_passed:
                    classification = coverage_classification

        finished = int(time.time())
        execution_passed = process_and_tests_passed and (coverage_scope is None or coverage is not None)
        coverage_payload: Dict[str, object] = {
            "required": coverage_scope is not None,
            "classification": coverage_classification,
            "collected": coverage is not None,
        }
        if coverage is not None:
            coverage_payload.update({
                "source_snapshot_ref": coverage.source_snapshot_ref,
                "reports": list(coverage.reports),
                "report_sha256": list(coverage.report_sha256),
                "result_path": coverage.result_path,
                "result_sha256": coverage.sha256,
                "stale_reports_ignored": coverage.stale_reports_ignored,
                "actual": {
                    "changed_method": {
                        "covered": coverage.changed_method.covered,
                        "total": coverage.changed_method.total,
                        "missing_subjects": list(coverage.changed_method.missing_subjects),
                    },
                    "changed_line": {
                        "covered": coverage.changed_line.covered,
                        "total": coverage.changed_line.total,
                        "missing_subjects": list(coverage.changed_line.missing_subjects),
                    },
                    "changed_branch": {
                        "covered": coverage.changed_branch.covered,
                        "total": coverage.changed_branch.total,
                        "missing_subjects": list(coverage.changed_branch.missing_subjects),
                    },
                },
            })

        failure_payload: Dict[str, object] = {
            "collected": failure_classification is not None,
            "primary_ownership": None,
            "semantic_review_required": False,
        }
        if failure_classification is not None:
            failure_payload.update({
                "classification": failure_classification.classification,
                "primary_ownership": failure_classification.primary_ownership.value,
                "ownership_counts": dict(failure_classification.ownership_counts),
                "semantic_review_required": failure_classification.semantic_review_required,
                "result_path": failure_classification.result_path,
                "result_sha256": failure_classification.sha256,
                "facts": len(failure_classification.facts),
            })

        payload: Dict[str, object] = {
            "schema_version": 4,
            "capability_id": self.capability_id,
            "command": command,
            "returncode": returncode,
            "started_at": started,
            "finished_at": finished,
            "classification": classification,
            "execution_passed": execution_passed,
            "output_decoding": {
                "stdout": stdout_encoding,
                "stderr": stderr_encoding,
            },
            "junit_freshness": {
                "reports_before": len(before_reports),
                "fresh_reports": len(fresh_reports),
                "stale_reports_ignored": stale_ignored,
            },
            "actual": {
                "tests": actual.tests,
                "failures": actual.failures,
                "errors": actual.errors,
                "skipped": actual.skipped,
                "passed": actual.passed,
                "xml_files": actual.xml_files,
            },
            "failure_classification": failure_payload,
            "jacoco": coverage_payload,
            "truth_note": "Only JUnit/JaCoCo XML created/changed by this attempt is Actual; requested changed-scope coverage cannot be omitted from execution PASS",
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        result_path = self.evidence_dir / "maven-junit-actual.json"
        temp = result_path.with_suffix(".json.tmp")
        temp.write_bytes(encoded)
        os.replace(str(temp), str(result_path))
        digest = hashlib.sha256(encoded).hexdigest()
        return MavenExecutionResult(
            command,
            returncode,
            started,
            finished,
            actual,
            str(result_path),
            digest,
            str(stdout_path),
            str(stderr_path),
            classification,
            stale_ignored,
            stdout_encoding,
            stderr_encoding,
            coverage,
            coverage_scope is not None,
            coverage_classification,
            failure_classification,
        )
