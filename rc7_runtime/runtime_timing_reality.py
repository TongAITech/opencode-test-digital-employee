"""RC7.1 runtime-owned execution timing evidence.

The Case Evidence Contract requires ``started_at`` and ``finished_at``.  Those
values must not be trusted when they originate from a test script.  This module
wraps the RC6 RunnerAdapter only when the adapter is using RC7's
``_EvidenceBackedProcessHarness``.  It records wall-clock UTC time around the
real subprocess execution, persists a file-backed timing receipt, overwrites
script-authored Case timestamps with Runtime truth, and adds the receipt to the
runner evidence set so ClosedLoopRuntimeExecutionService will hash/persist it in
canonical R1.

Normal RC6 runners are intentionally untouched.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional

from rc6_runtime.automation import RunnerAdapter


_INSTALLED = False
_ORIGINAL_EXECUTE = None
RUNTIME_TIMING_FILENAME = "runtime-timing.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _is_rc7_evidence_harness(harness: object) -> bool:
    cls = harness.__class__
    return cls.__name__ == "_EvidenceBackedProcessHarness" and cls.__module__ == "rc7_runtime.runtime_execution"


def _timing_path(stdout_ref: str) -> Path:
    if not isinstance(stdout_ref, str) or not stdout_ref.startswith("file://"):
        raise RuntimeError("RC7_RUNTIME_TIMING_REQUIRES_FILE_BACKED_STDOUT")
    stdout_path = Path(stdout_ref[len("file://"):]).expanduser().resolve()
    return stdout_path.parent / RUNTIME_TIMING_FILENAME


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")


def install_rc7_1_runtime_timing() -> None:
    """Install the RC7-only timing overlay exactly once per process."""
    global _INSTALLED, _ORIGINAL_EXECUTE
    if _INSTALLED:
        return

    original = RunnerAdapter.execute
    _ORIGINAL_EXECUTE = original

    def execute_with_runtime_timing(
        self: RunnerAdapter,
        *,
        spec,
        script,
        validation,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ):
        if not _is_rc7_evidence_harness(self.harness):
            return original(
                self,
                spec=spec,
                script=script,
                validation=validation,
                cwd=cwd,
                env=env,
            )

        started_at = _utc_now()
        result = original(
            self,
            spec=spec,
            script=script,
            validation=validation,
            cwd=cwd,
            env=env,
        )
        finished_at = _utc_now()

        timing_path = _timing_path(result.stdout_ref)
        payload = {
            "schema_version": 1,
            "source": "RC7_RUNTIME",
            "tc_id": str(spec.tc_id),
            "case_version": int(spec.case_version),
            "layer": str(spec.layer),
            "script_id": str(script.script_id),
            "runner_type": str(result.runner_type),
            "test_symbol": str(result.test_symbol),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": int(result.duration_ms),
            "exit_code": int(result.exit_code),
        }
        encoded = _canonical_bytes(payload)
        timing_path.write_bytes(encoded)
        timing_ref = "file://" + str(timing_path)
        timing_sha256 = hashlib.sha256(encoded).hexdigest()

        actual = deepcopy(result.actual_result)
        if not isinstance(actual, dict):
            actual = {"runner_actual_result": deepcopy(result.actual_result)}
        runtime_timing = dict(payload)
        runtime_timing.update({
            "evidence_ref": timing_ref,
            "sha256": timing_sha256,
        })
        actual["runtime_timing"] = runtime_timing

        # The layer contract is a Runtime-owned conclusion at this point.  A
        # test script may describe its steps/results, but cannot authoritatively
        # choose the execution clock.  Runtime overwrites both values after the
        # real process has returned.
        layer_evidence = actual.get("layer_evidence")
        if isinstance(layer_evidence, dict):
            layer_evidence = deepcopy(layer_evidence)
            layer_evidence["started_at"] = started_at
            layer_evidence["finished_at"] = finished_at
            layer_evidence["runtime_timing_ref"] = timing_ref
            actual["layer_evidence"] = layer_evidence

        refs = tuple(dict.fromkeys(tuple(result.evidence_refs) + (timing_ref,)))
        return replace(
            result,
            actual_result=actual,
            evidence_refs=refs,
        )

    RunnerAdapter.execute = execute_with_runtime_timing
    _INSTALLED = True
