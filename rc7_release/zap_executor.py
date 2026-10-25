from __future__ import annotations

import hashlib
import json
import locale
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple
from urllib.parse import urlsplit


class ZapExecutorError(RuntimeError):
    pass


_DEFAULT_TIMEOUT_SECONDS = 1800
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
        raise ZapExecutorError("ZAP_WORKSPACE_NOT_FOUND")
    return root


def _resolve_workspace_file(value: object, *, missing_code: str, escape_code: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ZapExecutorError(missing_code)
    root = _workspace()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ZapExecutorError(escape_code) from exc
    return resolved


def _plan(plan_path: object) -> Path:
    path = _resolve_workspace_file(
        plan_path,
        missing_code="ZAP_PLAN_PATH_REQUIRED",
        escape_code="ZAP_PLAN_PATH_ESCAPE",
    )
    if not path.is_file():
        raise ZapExecutorError("ZAP_PLAN_NOT_FOUND")
    return path


def _report_path() -> Path:
    path = _resolve_workspace_file(
        os.environ.get("PFC_ZAP_REPORT_PATH"),
        missing_code="ZAP_REPORT_PATH_NOT_CONFIGURED",
        escape_code="ZAP_REPORT_PATH_ESCAPE",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_client() -> str:
    configured = str(os.environ.get("PFC_ZAP_BIN") or "").strip()
    if not configured:
        raise ZapExecutorError("ZAP_CLIENT_NOT_CONFIGURED")
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    found = shutil.which(configured)
    if found:
        return found
    raise ZapExecutorError("ZAP_CLIENT_NOT_FOUND")


def _client_args() -> List[str]:
    raw = str(os.environ.get("PFC_ZAP_ARGS_JSON") or "[]").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ZapExecutorError("ZAP_CLIENT_ARGS_JSON_INVALID") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ZapExecutorError("ZAP_CLIENT_ARGS_MUST_BE_STRING_LIST")
    if any("\x00" in item or "\r" in item or "\n" in item for item in parsed):
        raise ZapExecutorError("ZAP_CLIENT_ARG_INVALID")
    return list(parsed)


def _target_id(target_id: object) -> str:
    target = str(target_id or "").strip()
    if not target:
        raise ZapExecutorError("ZAP_TARGET_ID_REQUIRED")
    configured = str(os.environ.get("PFC_ZAP_TARGET_ID") or "").strip()
    if not configured:
        raise ZapExecutorError("ZAP_TARGET_NOT_CONFIGURED")
    if configured != target:
        raise ZapExecutorError("ZAP_TARGET_MISMATCH")
    return target


def _origin(value: object, code: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ZapExecutorError(code)
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise ZapExecutorError(code)
    port = parsed.port
    default_port = 443 if scheme == "https" else 80
    authority = host if port in {None, default_port} else "%s:%d" % (host, port)
    return "%s://%s" % (scheme, authority)


def _configured_target_origin() -> str:
    return _origin(os.environ.get("PFC_ZAP_TARGET_URL"), "ZAP_TARGET_URL_NOT_CONFIGURED_OR_INVALID")


def _site_origin(site: Mapping[str, Any]) -> str:
    for key in ("@name", "name", "url"):
        value = site.get(key)
        if value:
            return _origin(value, "ZAP_REPORT_SITE_URL_INVALID")
    raise ZapExecutorError("ZAP_REPORT_SITE_URL_REQUIRED")


def _risk_bucket(alert: Mapping[str, Any]) -> str:
    raw_code = str(alert.get("riskcode") or alert.get("riskCode") or "").strip()
    if raw_code in {"0", "1", "2", "3"}:
        return {"0": "informational", "1": "low", "2": "medium", "3": "high"}[raw_code]
    raw = str(alert.get("riskdesc") or alert.get("risk") or "").strip().lower()
    for name in ("high", "medium", "low", "informational", "info"):
        if raw.startswith(name):
            return "informational" if name == "info" else name
    return "unknown"


def _validate_report(raw: object, *, target_origin: str, scan_id: str) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ZapExecutorError("ZAP_REPORT_MUST_BE_OBJECT")
    sites = raw.get("site")
    if not isinstance(sites, list) or not sites:
        raise ZapExecutorError("ZAP_REPORT_SITE_REQUIRED")

    matched_sites = []
    findings = []
    for site in sites:
        if not isinstance(site, Mapping):
            raise ZapExecutorError("ZAP_REPORT_SITE_INVALID")
        origin = _site_origin(site)
        if origin != target_origin:
            continue
        matched_sites.append(origin)
        alerts = site.get("alerts") or []
        if not isinstance(alerts, list):
            raise ZapExecutorError("ZAP_REPORT_ALERTS_INVALID")
        for alert in alerts:
            if not isinstance(alert, Mapping):
                raise ZapExecutorError("ZAP_REPORT_ALERT_INVALID")
            findings.append({
                "plugin_id": str(alert.get("pluginid") or alert.get("pluginId") or ""),
                "alert_ref": str(alert.get("alertRef") or alert.get("alertref") or ""),
                "name": str(alert.get("alert") or alert.get("name") or ""),
                "risk": _risk_bucket(alert),
                "confidence": str(alert.get("confidence") or ""),
                "instance_count": len(alert.get("instances") or []) if isinstance(alert.get("instances") or [], list) else 0,
            })
    if not matched_sites:
        raise ZapExecutorError("ZAP_REPORT_TARGET_SITE_NOT_FOUND")

    counts = {"high": 0, "medium": 0, "low": 0, "informational": 0, "unknown": 0}
    for finding in findings:
        counts[finding["risk"]] = counts.get(finding["risk"], 0) + 1
    return {
        "schema": "pfc.aitest.rc7.1.zap-report-summary.v1",
        "scan_id": scan_id,
        "target_origin": target_origin,
        "matched_site_count": len(matched_sites),
        "finding_count": len(findings),
        "risk_counts": counts,
        "findings": findings,
        "findings_are_product_security_actual_not_executor_failure": True,
    }


def execute_zap_scan(
    *,
    plan_path: str,
    scan_id: str,
    target_id: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    """Execute a real ZAP Automation Framework scan and validate its fresh report.

    Findings do not make executor provenance fail: they are product/security
    Actual and must flow to Oracle/diagnosis/defect policy. Execution fails only
    when the real scan/report/target evidence is invalid or absent.
    """
    scan = str(scan_id or "").strip()
    if not scan:
        raise ZapExecutorError("ZAP_SCAN_ID_REQUIRED")
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > 7200:
        raise ZapExecutorError("ZAP_TIMEOUT_INVALID")
    if not isinstance(max_chars, int) or max_chars < 1000 or max_chars > 1000000:
        raise ZapExecutorError("ZAP_MAX_CHARS_INVALID")

    target = _target_id(target_id)
    target_origin = _configured_target_origin()
    plan = _plan(plan_path)
    report = _report_path()
    client = _resolve_client()

    if report.exists():
        try:
            report.unlink()
        except OSError as exc:
            raise ZapExecutorError("ZAP_STALE_REPORT_CANNOT_BE_REMOVED") from exc

    command: Sequence[str] = [client] + _client_args() + ["-cmd", "-autorun", str(plan)]
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
        raise ZapExecutorError("ZAP_EXECUTION_TIMEOUT") from exc
    except OSError as exc:
        raise ZapExecutorError("ZAP_EXECUTION_FAILED:%s" % type(exc).__name__) from exc

    stdout = _decode(proc.stdout or b"")
    stderr = _decode(proc.stderr or b"")
    if proc.returncode != 0:
        detail = (stderr or stdout or "zap failed").strip()[:1000]
        raise ZapExecutorError("ZAP_CLIENT_EXIT_NONZERO:%s" % detail)
    if not report.is_file():
        raise ZapExecutorError("ZAP_FRESH_REPORT_NOT_PRODUCED")
    report_bytes = report.read_bytes()
    if not report_bytes:
        raise ZapExecutorError("ZAP_REPORT_EMPTY")
    try:
        raw_report = json.loads(report_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ZapExecutorError("ZAP_REPORT_JSON_INVALID") from exc
    summary = _validate_report(raw_report, target_origin=target_origin, scan_id=scan)

    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    plan_sha256 = hashlib.sha256(plan.read_bytes()).hexdigest()
    invocation_ref = "zap://%s/%s/%s" % (target, scan, report_sha256[:24])
    return {
        "tool": "zap",
        "implementation": "zap-automation-framework",
        "target_id": target,
        "target_origin": target_origin,
        "scan_id": scan,
        "client": Path(client).name,
        "plan_ref": "workspace://" + str(plan.relative_to(_workspace())).replace("\\", "/"),
        "plan_sha256": plan_sha256,
        "report_ref": "workspace://" + str(report.relative_to(_workspace())).replace("\\", "/"),
        "report_sha256": report_sha256,
        "summary": summary,
        "invocation_ref": invocation_ref,
        "stdout": _bounded(stdout, max_chars),
        "stderr": _bounded(stderr, min(max_chars, 50000)),
        "exit_code": int(proc.returncode),
        "shell": False,
        "fresh_report_required": True,
        "client_args_persisted": False,
    }
