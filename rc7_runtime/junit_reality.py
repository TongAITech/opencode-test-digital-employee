"""RC7.1 current-run JUnit reality gate.

Maven process exit status is not sufficient proof that the selected JUnit test
actually ran in the current attempt. This adapter snapshots Surefire/Failsafe
XML before and after the Maven invocation, accepts only newly-created or changed
reports, persists those reports as durable evidence, and parses the current-run
test totals into the actual result.

The implementation is deliberately Python 3.8 compatible for the bank runtime.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime import automation as _automation
from rc6_runtime.automation import (
    AutomationContractError,
    JUnitRunnerAdapter as _BaseJUnitRunnerAdapter,
    RunnerExecutionResult,
    ScriptArtifact,
    ScriptValidation,
)
from rc6_runtime.executable_spec import ExecutableTestSpec


_DEPENDENCY_FAILURE_SIGNATURES = (
    "could not resolve dependencies",
    "could not find artifact",
    "non-resolvable",
    "nonresolvable",
    "failed to read artifact descriptor",
    "plugin or one of its dependencies could not be resolved",
    "transfer failed",
    "failed to transfer",
    "unknown host",
    "name or service not known",
    "connection timed out",
    "connect timed out",
    "connection refused",
    "no plugin found for prefix",
)


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _int_attr(element: ET.Element, name: str) -> int:
    raw = element.attrib.get(name, "0")
    try:
        return int(float(str(raw)))
    except (TypeError, ValueError):
        return 0


def _float_attr(element: ET.Element, name: str) -> float:
    raw = element.attrib.get(name, "0")
    try:
        return float(str(raw))
    except (TypeError, ValueError):
        return 0.0


class RealityCheckedJUnitRunnerAdapter(_BaseJUnitRunnerAdapter):
    """JUnit runner that refuses stale or report-less success."""

    runner_type = "JUNIT"

    def __init__(self, *, evidence_root: Optional[str] = None, timeout_seconds: int = 180) -> None:
        super().__init__(timeout_seconds=timeout_seconds)
        self._configured_evidence_root = (
            Path(evidence_root).expanduser().resolve() if evidence_root else None
        )
        if self._configured_evidence_root is not None:
            self._configured_evidence_root.mkdir(parents=True, exist_ok=True)

    def _evidence_root(self, cwd: str) -> Path:
        if self._configured_evidence_root is not None:
            return self._configured_evidence_root
        root = Path(cwd).expanduser().resolve() / "runtime-state" / "rc7.1-evidence"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _report_paths(cwd: str) -> Tuple[Path, ...]:
        root = Path(cwd).expanduser().resolve()
        candidates = []
        for folder in (root / "target" / "surefire-reports", root / "target" / "failsafe-reports"):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.xml")):
                if path.is_file():
                    candidates.append(path.resolve())
        return tuple(candidates)

    @staticmethod
    def _fingerprint(path: Path) -> Dict[str, Any]:
        data = path.read_bytes()
        stat = path.stat()
        return {
            "size": int(stat.st_size),
            "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    @classmethod
    def _snapshot(cls, cwd: str) -> Dict[str, Dict[str, Any]]:
        snapshot = {}
        for path in cls._report_paths(cwd):
            try:
                snapshot[str(path)] = cls._fingerprint(path)
            except OSError:
                continue
        return snapshot

    @staticmethod
    def _changed_reports(
        before: Mapping[str, Mapping[str, Any]],
        after: Mapping[str, Mapping[str, Any]],
    ) -> Tuple[Path, ...]:
        changed = []
        for raw_path, current in after.items():
            previous = before.get(raw_path)
            if previous is None or dict(previous) != dict(current):
                changed.append(Path(raw_path))
        return tuple(sorted(changed, key=lambda item: str(item)))

    @staticmethod
    def _read_ref_text(ref: str) -> str:
        if not isinstance(ref, str) or not ref.startswith("file://"):
            return ""
        path = Path(ref[len("file://"):])
        try:
            return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        except OSError:
            return ""

    @classmethod
    def _dependency_failure(cls, result: RunnerExecutionResult) -> bool:
        text = (cls._read_ref_text(result.stdout_ref) + "\n" + cls._read_ref_text(result.stderr_ref)).lower()
        return any(signature in text for signature in _DEPENDENCY_FAILURE_SIGNATURES)

    @staticmethod
    def _suite_summary(root: ET.Element) -> Dict[str, Any]:
        tag = _local_tag(root.tag)
        if tag == "testsuite":
            suites = (root,)
        elif tag == "testsuites":
            direct = tuple(child for child in list(root) if _local_tag(child.tag) == "testsuite")
            suites = direct if direct else tuple(
                element for element in root.iter() if _local_tag(element.tag) == "testsuite"
            )
        else:
            raise AutomationContractError("JUNIT_CURRENT_RUN_XML_ROOT_INVALID")

        tests = sum(_int_attr(suite, "tests") for suite in suites)
        failures = sum(_int_attr(suite, "failures") for suite in suites)
        errors = sum(_int_attr(suite, "errors") for suite in suites)
        skipped = sum(_int_attr(suite, "skipped") for suite in suites)
        duration = sum(_float_attr(suite, "time") for suite in suites)
        return {
            "tests": tests,
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
            "time_seconds": duration,
        }

    @classmethod
    def _parse_reports(cls, reports: Sequence[Path]) -> Dict[str, Any]:
        totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time_seconds": 0.0}
        for report in reports:
            try:
                root = ET.parse(str(report)).getroot()
            except (ET.ParseError, OSError) as exc:
                raise AutomationContractError("JUNIT_CURRENT_RUN_XML_INVALID:%s" % report.name) from exc
            row = cls._suite_summary(root)
            totals["tests"] += int(row["tests"])
            totals["failures"] += int(row["failures"])
            totals["errors"] += int(row["errors"])
            totals["skipped"] += int(row["skipped"])
            totals["time_seconds"] += float(row["time_seconds"])
        totals["time_seconds"] = round(float(totals["time_seconds"]), 6)
        return totals

    def _persist_reports(
        self,
        *,
        cwd: str,
        reports: Sequence[Path],
        before: Mapping[str, Mapping[str, Any]],
        after: Mapping[str, Mapping[str, Any]],
        result: RunnerExecutionResult,
    ) -> Tuple[Tuple[str, ...], str]:
        run_id = "JUNITRUN-" + uuid.uuid4().hex
        folder = self._evidence_root(cwd) / "junit-reality" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        refs = []
        copied = []
        for index, source in enumerate(reports, 1):
            target = folder / ("%03d-%s" % (index, source.name))
            shutil.copy2(str(source), str(target))
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            refs.append("file://" + str(target))
            copied.append({"source": str(source), "evidence": str(target), "sha256": digest})
        trace = folder / "current-run.json"
        trace.write_text(
            json.dumps(
                {
                    "schema": "rc7.1-junit-current-run-v1",
                    "runner_type": result.runner_type,
                    "test_symbol": result.test_symbol,
                    "process_exit_code": result.exit_code,
                    "before": dict(before),
                    "after": dict(after),
                    "accepted_reports": copied,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        trace_ref = "file://" + str(trace)
        refs.append(trace_ref)
        return tuple(refs), trace_ref

    def execute(
        self,
        *,
        spec: ExecutableTestSpec,
        script: ScriptArtifact,
        validation: ScriptValidation,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> RunnerExecutionResult:
        before = self._snapshot(cwd)
        started_ns = time.time_ns()
        result = super().execute(spec=spec, script=script, validation=validation, cwd=cwd, env=env)
        after = self._snapshot(cwd)
        changed = self._changed_reports(before, after)

        dependency_block = self._dependency_failure(result)
        if dependency_block and int(result.exit_code) != 0:
            actual = deepcopy(result.actual_result)
            actual.update(
                {
                    "junit_current_run": False,
                    "classification": "BLOCKED_ENVIRONMENT",
                    "blocked_reason": "MAVEN_DEPENDENCY_UNAVAILABLE",
                    "current_run_started_ns": started_ns,
                    "current_run_report_count": 0,
                }
            )
            return RunnerExecutionResult(
                runner_type=result.runner_type,
                test_symbol=result.test_symbol,
                exit_code=result.exit_code,
                status=result.status,
                actual_result=actual,
                stdout_ref=result.stdout_ref,
                stderr_ref=result.stderr_ref,
                tool_calls=result.tool_calls,
                tool_call_refs=result.tool_call_refs,
                evidence_refs=result.evidence_refs,
                duration_ms=result.duration_ms,
            )

        if int(result.exit_code) == 0 and not changed:
            raise AutomationContractError("JUNIT_CURRENT_RUN_XML_REQUIRED")

        if not changed:
            actual = deepcopy(result.actual_result)
            actual.update(
                {
                    "junit_current_run": False,
                    "classification": "TEST_FAIL",
                    "failure_reason": "JUNIT_CURRENT_RUN_XML_MISSING",
                    "current_run_started_ns": started_ns,
                    "current_run_report_count": 0,
                }
            )
            return RunnerExecutionResult(
                runner_type=result.runner_type,
                test_symbol=result.test_symbol,
                exit_code=result.exit_code,
                status=result.status,
                actual_result=actual,
                stdout_ref=result.stdout_ref,
                stderr_ref=result.stderr_ref,
                tool_calls=result.tool_calls,
                tool_call_refs=result.tool_call_refs,
                evidence_refs=result.evidence_refs,
                duration_ms=result.duration_ms,
            )

        totals = self._parse_reports(changed)
        if int(totals["tests"]) <= 0:
            raise AutomationContractError("JUNIT_CURRENT_RUN_HAS_NO_TESTS")

        report_refs, trace_ref = self._persist_reports(
            cwd=cwd,
            reports=changed,
            before=before,
            after=after,
            result=result,
        )
        failed = int(totals["failures"]) + int(totals["errors"]) > 0 or int(result.exit_code) != 0
        actual = deepcopy(result.actual_result)
        actual.update(totals)
        actual.update(
            {
                "junit_current_run": True,
                "classification": "TEST_FAIL" if failed else "TEST_PASS",
                "current_run_started_ns": started_ns,
                "current_run_report_count": len(changed),
                "junit_report_refs": list(report_refs[:-1]),
                "junit_trace_ref": trace_ref,
            }
        )
        evidence = tuple(dict.fromkeys(tuple(result.evidence_refs) + tuple(report_refs)))
        return RunnerExecutionResult(
            runner_type=result.runner_type,
            test_symbol=result.test_symbol,
            exit_code=result.exit_code,
            status=result.status,
            actual_result=actual,
            stdout_ref=result.stdout_ref,
            stderr_ref=result.stderr_ref,
            tool_calls=result.tool_calls,
            tool_call_refs=result.tool_call_refs,
            evidence_refs=evidence,
            duration_ms=result.duration_ms,
        )


def install_rc7_1_junit_reality_gate() -> None:
    """Install the RC7.1 adapter before RC7 execution modules import JUnitRunnerAdapter.

    RC7.1 is an additive field-fix line and intentionally leaves the RC6 source
    baseline untouched.  Installing the adapter at RC7 package bootstrap makes
    both runtime_execution and runtime_execution_control receive the strict
    adapter through their existing compatibility import.
    """
    if _automation.JUnitRunnerAdapter is not RealityCheckedJUnitRunnerAdapter:
        _automation.JUnitRunnerAdapter = RealityCheckedJUnitRunnerAdapter
