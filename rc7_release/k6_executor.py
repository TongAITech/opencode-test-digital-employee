from __future__ import annotations

import hashlib
import json
import locale
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


class K6ExecutorError(RuntimeError):
    pass


_DEFAULT_TIMEOUT_SECONDS = 900
_DEFAULT_MAX_CHARS = 200000


def _decode(value: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gb18030"):
        try:
            return value.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return value.decode("utf-8", errors="replace")


def _bounded(value: str, max_chars: int) -> Dict[str, Any]:
    return {
        "text": value[:max_chars],
        "truncated": len(value) > max_chars,
        "original_chars": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest(),
    }


def _workspace() -> Path:
    configured = os.environ.get("PFC_WORKSPACE") or os.environ.get("PFC_AITEST_HOME") or os.getcwd()
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise K6ExecutorError("K6_WORKSPACE_NOT_FOUND")
    return root


def _state_root() -> Path:
    configured = os.environ.get("PFC_AITEST_STATE_DIR")
    root = Path(configured).expanduser().resolve() if configured else (_workspace() / "runtime-state").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_client() -> str:
    configured = str(os.environ.get("PFC_K6_BIN") or "").strip()
    if not configured:
        raise K6ExecutorError("K6_CLIENT_NOT_CONFIGURED")
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    found = shutil.which(configured)
    if found:
        return found
    raise K6ExecutorError("K6_CLIENT_NOT_FOUND")


def _client_args() -> List[str]:
    raw = str(os.environ.get("PFC_K6_ARGS_JSON") or "[]").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise K6ExecutorError("K6_CLIENT_ARGS_JSON_INVALID") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise K6ExecutorError("K6_CLIENT_ARGS_MUST_BE_STRING_LIST")
    if any("\x00" in item or "\r" in item or "\n" in item for item in parsed):
        raise K6ExecutorError("K6_CLIENT_ARG_INVALID")
    return list(parsed)


def _target(target_id: object) -> str:
    target = str(target_id or "").strip()
    if not target:
        raise K6ExecutorError("K6_TARGET_ID_REQUIRED")
    configured = str(os.environ.get("PFC_K6_TARGET_ID") or "").strip()
    if not configured:
        raise K6ExecutorError("K6_TARGET_NOT_CONFIGURED")
    if configured != target:
        raise K6ExecutorError("K6_TARGET_MISMATCH")
    return target


def _script(script_path: object) -> Path:
    raw = str(script_path or "").strip()
    if not raw:
        raise K6ExecutorError("K6_SCRIPT_PATH_REQUIRED")
    root = _workspace()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise K6ExecutorError("K6_SCRIPT_PATH_ESCAPE") from exc
    if not resolved.is_file():
        raise K6ExecutorError("K6_SCRIPT_NOT_FOUND")
    return resolved


def _metric_values(metric: object, name: str) -> Mapping[str, Any]:
    if not isinstance(metric, Mapping):
        raise K6ExecutorError("K6_METRIC_INVALID:%s" % name)
    values = metric.get("values")
    if not isinstance(values, Mapping):
        raise K6ExecutorError("K6_METRIC_VALUES_REQUIRED:%s" % name)
    return values


def _validate_summary(raw: object, *, scenario_id: str) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise K6ExecutorError("K6_SUMMARY_MUST_BE_OBJECT")
    metrics = raw.get("metrics")
    if not isinstance(metrics, Mapping) or not metrics:
        raise K6ExecutorError("K6_SUMMARY_METRICS_REQUIRED")
    if "iterations" not in metrics:
        raise K6ExecutorError("K6_ITERATIONS_METRIC_REQUIRED")
    iteration_values = _metric_values(metrics["iterations"], "iterations")
    try:
        iteration_count = float(iteration_values.get("count", 0))
    except (TypeError, ValueError) as exc:
        raise K6ExecutorError("K6_ITERATION_COUNT_INVALID") from exc
    if iteration_count <= 0:
        raise K6ExecutorError("K6_NO_ITERATIONS_EXECUTED")

    threshold_results = []
    for metric_name, metric in metrics.items():
        if not isinstance(metric, Mapping):
            continue
        thresholds = metric.get("thresholds")
        if thresholds is None:
            continue
        if not isinstance(thresholds, Mapping):
            raise K6ExecutorError("K6_THRESHOLDS_INVALID:%s" % metric_name)
        for expression, result in thresholds.items():
            if not isinstance(result, Mapping) or result.get("ok") is not True:
                raise K6ExecutorError("K6_THRESHOLD_NOT_PASS:%s:%s" % (metric_name, expression))
            threshold_results.append({"metric": str(metric_name), "expression": str(expression), "ok": True})
    if not threshold_results:
        raise K6ExecutorError("K6_THRESHOLD_EVALUATION_REQUIRED")

    selected_metrics = {}
    for metric_name in ("iterations", "checks", "http_reqs", "http_req_duration", "vus", "vus_max"):
        metric = metrics.get(metric_name)
        if isinstance(metric, Mapping):
            selected_metrics[metric_name] = {
                "type": metric.get("type"),
                "contains": metric.get("contains"),
                "values": dict(metric.get("values") or {}) if isinstance(metric.get("values"), Mapping) else {},
            }
    return {
        "schema": "pfc.aitest.rc7.1.k6-summary.v1",
        "scenario_id": scenario_id,
        "iteration_count": iteration_count,
        "threshold_count": len(threshold_results),
        "thresholds": threshold_results,
        "metrics": selected_metrics,
    }


def execute_k6_scenario(
    *,
    script_path: str,
    scenario_id: str,
    target_id: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    """Execute a real k6 CLI run and validate its structured summary.

    A zero exit code is insufficient. The summary must prove at least one
    iteration and at least one evaluated threshold, with every threshold PASS.
    The script must be workspace-contained and the target binding exact.
    """
    scenario = str(scenario_id or "").strip()
    if not scenario:
        raise K6ExecutorError("K6_SCENARIO_ID_REQUIRED")
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > 7200:
        raise K6ExecutorError("K6_TIMEOUT_INVALID")
    if not isinstance(max_chars, int) or max_chars < 1000 or max_chars > 1000000:
        raise K6ExecutorError("K6_MAX_CHARS_INVALID")

    target = _target(target_id)
    script = _script(script_path)
    client = _resolve_client()
    summary_dir = _state_root() / "k6-summaries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    fd, summary_name = tempfile.mkstemp(prefix="k6-", suffix=".json", dir=str(summary_dir))
    os.close(fd)
    summary_path = Path(summary_name)
    try:
        summary_path.unlink()
    except OSError:
        pass

    command: Sequence[str] = [client] + _client_args() + [
        "run",
        "--summary-export",
        str(summary_path),
        str(script),
    ]
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(_workspace()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise K6ExecutorError("K6_EXECUTION_TIMEOUT") from exc
    except OSError as exc:
        raise K6ExecutorError("K6_EXECUTION_FAILED:%s" % type(exc).__name__) from exc

    stdout = _decode(proc.stdout or b"")
    stderr = _decode(proc.stderr or b"")
    if proc.returncode != 0:
        detail = (stderr or stdout or "k6 failed").strip()[:1000]
        raise K6ExecutorError("K6_CLIENT_EXIT_NONZERO:%s" % detail)
    if not summary_path.is_file():
        raise K6ExecutorError("K6_SUMMARY_NOT_PRODUCED")
    summary_bytes = summary_path.read_bytes()
    if not summary_bytes:
        raise K6ExecutorError("K6_SUMMARY_EMPTY")
    try:
        raw_summary = json.loads(summary_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise K6ExecutorError("K6_SUMMARY_JSON_INVALID") from exc
    summary = _validate_summary(raw_summary, scenario_id=scenario)

    script_sha256 = hashlib.sha256(script.read_bytes()).hexdigest()
    summary_sha256 = hashlib.sha256(summary_bytes).hexdigest()
    invocation_ref = "k6://%s/%s/%s" % (target, scenario, summary_sha256[:24])
    return {
        "tool": "k6",
        "implementation": "k6-cli",
        "target_id": target,
        "scenario_id": scenario,
        "client": Path(client).name,
        "script_ref": "workspace://" + str(script.relative_to(_workspace())).replace("\\", "/"),
        "script_sha256": script_sha256,
        "summary_sha256": summary_sha256,
        "summary": summary,
        "invocation_ref": invocation_ref,
        "stdout": _bounded(stdout, max_chars),
        "stderr": _bounded(stderr, min(max_chars, 50000)),
        "exit_code": int(proc.returncode),
        "shell": False,
        "summary_exported": True,
        "client_args_persisted": False,
    }
