"""Real RC8 Maven/JUnit WorkItem execution adapter.

This adapter runs Maven as a real local subprocess and derives Actual test
results from Surefire/Failsafe XML. It does not infer PASS from process text or
from a model claim. Center/R1 publication is handled by the Node Agent layer.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


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

    def _collect_actual(self, project_dir: Path) -> JUnitActual:
        candidates = sorted(set(
            list(project_dir.glob("**/target/surefire-reports/*.xml")) +
            list(project_dir.glob("**/target/failsafe-reports/*.xml"))
        ))
        if not candidates:
            raise ExecutionAdapterError("JUNIT_XML_EVIDENCE_MISSING")
        totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for path in candidates:
            values = self._read_suite(path)
            for key in totals:
                totals[key] += values[key]
        return JUnitActual(
            tests=totals["tests"], failures=totals["failures"], errors=totals["errors"], skipped=totals["skipped"],
            xml_files=[str(path) for path in candidates],
        )

    def execute(self, project_dir: str, *, goals: Optional[List[str]] = None) -> MavenExecutionResult:
        root = Path(project_dir)
        if not root.is_dir():
            raise ExecutionAdapterError("MAVEN_PROJECT_DIR_NOT_FOUND")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        command = [self.maven_command] + list(goals or ["test"])
        started = int(time.time())
        returncode: Optional[int] = None
        stdout = ""
        stderr = ""
        try:
            completed = subprocess.run(command, cwd=str(root), capture_output=True, text=True, timeout=self.timeout_seconds, check=False)
            returncode = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except FileNotFoundError as exc:
            stderr = str(exc)
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = "MAVEN_EXECUTION_TIMEOUT"

        stdout_path = self.evidence_dir / "maven-stdout.log"
        stderr_path = self.evidence_dir / "maven-stderr.log"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        if returncode is None:
            raise ExecutionAdapterError("MAVEN_EXECUTION_UNAVAILABLE")

        actual = self._collect_actual(root)
        finished = int(time.time())
        payload: Dict[str, object] = {
            "schema_version": 1,
            "capability_id": self.capability_id,
            "command": command,
            "returncode": returncode,
            "started_at": started,
            "finished_at": finished,
            "actual": {
                "tests": actual.tests,
                "failures": actual.failures,
                "errors": actual.errors,
                "skipped": actual.skipped,
                "passed": actual.passed,
                "xml_files": actual.xml_files,
            },
            "truth_note": "Actual is parsed from JUnit XML; subprocess exit code alone never proves PASS",
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        result_path = self.evidence_dir / "maven-junit-actual.json"
        temp = result_path.with_suffix(".json.tmp")
        temp.write_bytes(encoded)
        os.replace(str(temp), str(result_path))
        digest = hashlib.sha256(encoded).hexdigest()
        return MavenExecutionResult(command, returncode, started, finished, actual, str(result_path), digest, str(stdout_path), str(stderr_path))
