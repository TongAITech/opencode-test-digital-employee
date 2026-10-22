"""Real RC8 Maven/JUnit WorkItem execution adapter.

This adapter runs Maven as a real local subprocess and derives Actual test
results only from JUnit XML created or changed by THIS execution attempt.
Historical Surefire/Failsafe reports are never allowed to become current Actual.
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

    @property
    def execution_passed(self) -> bool:
        """Maven itself and JUnit Actual must both pass."""
        return self.returncode == 0 and self.actual.passed


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
        """Decode subprocess output without trusting the Python UTF-8 mode.

        Bank Windows consoles commonly emit GBK/GB18030 even when Python runs in
        UTF-8 mode. Capture bytes first, try strict known encodings, then replace
        undecodable bytes as the final evidence-preserving fallback.
        """
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

    def execute(self, project_dir: str, *, goals: Optional[List[str]] = None) -> MavenExecutionResult:
        root = Path(project_dir)
        if not root.is_dir():
            raise ExecutionAdapterError("MAVEN_PROJECT_DIR_NOT_FOUND")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        command = [self.maven_command] + list(goals or ["test"])

        # Snapshot BEFORE the process starts. Unchanged historical reports are
        # stale evidence and must never be counted as this attempt's Actual.
        before_reports = self._snapshot_reports(root)
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
                # A successful Maven test command with no current JUnit evidence
                # cannot be promoted to PASS.
                raise ExecutionAdapterError("JUNIT_XML_EVIDENCE_MISSING")
            actual = JUnitActual(tests=0, failures=0, errors=0, skipped=0, xml_files=[])
            classification = "MAVEN_FAILED_BEFORE_FRESH_JUNIT"
        else:
            actual = self._collect_actual(fresh_reports)
            classification = "JUNIT_FRESH_REPORTS_COLLECTED" if returncode == 0 else "MAVEN_NONZERO_WITH_FRESH_JUNIT"

        finished = int(time.time())
        execution_passed = returncode == 0 and actual.passed
        payload: Dict[str, object] = {
            "schema_version": 2,
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
            "truth_note": "Only JUnit XML created/changed by this attempt is Actual; Maven return code must also be zero for execution PASS",
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
        )
