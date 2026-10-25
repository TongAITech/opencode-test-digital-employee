from __future__ import annotations

import hashlib
import json
import locale
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


class E2EExecutorError(RuntimeError):
    pass


_DEFAULT_TIMEOUT_SECONDS = 300
_DEFAULT_MAX_CHARS = 200000
_FORBIDDEN_REF_PREFIXES = ("engineering-fixture://", "fixture://", "mock://")


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
    path = Path(configured).expanduser().resolve()
    if not path.is_dir():
        raise E2EExecutorError("E2E_WORKSPACE_NOT_FOUND")
    return path


def _resolve_client() -> str:
    configured = str(os.environ.get("PFC_E2E_CLIENT_BIN") or "").strip()
    if not configured:
        raise E2EExecutorError("E2E_CLIENT_NOT_CONFIGURED")
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    found = shutil.which(configured)
    if found:
        return found
    raise E2EExecutorError("E2E_CLIENT_NOT_FOUND")


def _client_args() -> List[str]:
    raw = str(os.environ.get("PFC_E2E_CLIENT_ARGS_JSON") or "[]").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise E2EExecutorError("E2E_CLIENT_ARGS_JSON_INVALID") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise E2EExecutorError("E2E_CLIENT_ARGS_MUST_BE_STRING_LIST")
    if any("\x00" in item or "\r" in item or "\n" in item for item in parsed):
        raise E2EExecutorError("E2E_CLIENT_ARG_INVALID")
    return list(parsed)


def _target(target_id: object) -> str:
    target = str(target_id or "").strip()
    if not target:
        raise E2EExecutorError("E2E_TARGET_ID_REQUIRED")
    configured = str(os.environ.get("PFC_E2E_TARGET_ID") or "").strip()
    if not configured:
        raise E2EExecutorError("E2E_TARGET_NOT_CONFIGURED")
    if configured != target:
        raise E2EExecutorError("E2E_TARGET_MISMATCH")
    return target


def _required_text(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise E2EExecutorError(code)
    return text


def _require_nonfixture_ref(value: object, code: str) -> str:
    ref = _required_text(value, code)
    if ref.startswith(_FORBIDDEN_REF_PREFIXES):
        raise E2EExecutorError("E2E_FIXTURE_REFERENCE_FORBIDDEN")
    return ref


def _require_sha256(value: object, code: str) -> str:
    digest = _required_text(value, code).lower()
    if digest.startswith("sha256:"):
        digest = digest[7:]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise E2EExecutorError(code)
    return digest


def _validated_receipt(raw: object, *, target_id: str) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise E2EExecutorError("E2E_RECEIPT_MUST_BE_OBJECT")
    receipt_target = _required_text(raw.get("target_id"), "E2E_RECEIPT_TARGET_REQUIRED")
    if receipt_target != target_id:
        raise E2EExecutorError("E2E_RECEIPT_TARGET_MISMATCH")
    journey_id = _required_text(raw.get("journey_id"), "E2E_JOURNEY_ID_REQUIRED")
    hops = raw.get("hops")
    if not isinstance(hops, list) or len(hops) < 2:
        raise E2EExecutorError("E2E_REQUIRES_AT_LEAST_TWO_HOPS")

    canonical_hops = []
    system_ids = []
    for index, hop in enumerate(hops):
        if not isinstance(hop, Mapping):
            raise E2EExecutorError("E2E_HOP_MUST_BE_OBJECT:%d" % index)
        system_id = _required_text(hop.get("system_id"), "E2E_HOP_SYSTEM_REQUIRED:%d" % index)
        tool_id = _required_text(hop.get("tool_id"), "E2E_HOP_TOOL_REQUIRED:%d" % index)
        status = _required_text(hop.get("status"), "E2E_HOP_STATUS_REQUIRED:%d" % index).upper()
        if status != "SUCCESS":
            raise E2EExecutorError("E2E_HOP_NOT_SUCCESS:%d" % index)
        invocation_ref = _require_nonfixture_ref(
            hop.get("invocation_ref"), "E2E_HOP_INVOCATION_REF_REQUIRED:%d" % index
        )
        result_sha256 = _require_sha256(
            hop.get("result_sha256"), "E2E_HOP_RESULT_SHA256_INVALID:%d" % index
        )
        canonical_hops.append({
            "system_id": system_id,
            "tool_id": tool_id,
            "status": "SUCCESS",
            "invocation_ref": invocation_ref,
            "result_sha256": result_sha256,
        })
        system_ids.append(system_id)
    if len(set(system_ids)) < 2:
        raise E2EExecutorError("E2E_REQUIRES_DISTINCT_SYSTEMS")

    oracle = raw.get("final_oracle")
    if not isinstance(oracle, Mapping):
        raise E2EExecutorError("E2E_FINAL_ORACLE_REQUIRED")
    oracle_id = _required_text(oracle.get("oracle_id"), "E2E_ORACLE_ID_REQUIRED")
    if oracle.get("passed") is not True:
        raise E2EExecutorError("E2E_FINAL_ORACLE_NOT_PASS")
    if "expected" not in oracle or "actual" not in oracle:
        raise E2EExecutorError("E2E_FINAL_ORACLE_EXPECTED_ACTUAL_REQUIRED")
    evidence_ref = _require_nonfixture_ref(oracle.get("evidence_ref"), "E2E_ORACLE_EVIDENCE_REF_REQUIRED")
    evidence_sha256 = _require_sha256(oracle.get("evidence_sha256"), "E2E_ORACLE_EVIDENCE_SHA256_INVALID")

    return {
        "schema": "pfc.aitest.rc7.1.cross-system-e2e-receipt.v1",
        "journey_id": journey_id,
        "target_id": target_id,
        "hop_count": len(canonical_hops),
        "system_ids": system_ids,
        "hops": canonical_hops,
        "final_oracle": {
            "oracle_id": oracle_id,
            "passed": True,
            "expected": oracle.get("expected"),
            "actual": oracle.get("actual"),
            "evidence_ref": evidence_ref,
            "evidence_sha256": evidence_sha256,
        },
    }


def execute_e2e_journey(
    *,
    journey: Mapping[str, Any],
    target_id: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> Dict[str, Any]:
    """Invoke the configured cross-system E2E orchestrator and verify its receipt.

    A zero exit code is insufficient. The external orchestrator must prove at
    least two distinct successful system hops plus a deterministic final Oracle.
    Fixture/mock refs are rejected. Only a validated receipt is eligible for
    current-attempt REAL_EXECUTOR_INVOCATION provenance at the MCP boundary.
    """
    if not isinstance(journey, Mapping) or not journey:
        raise E2EExecutorError("E2E_JOURNEY_REQUIRED")
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > 1800:
        raise E2EExecutorError("E2E_TIMEOUT_INVALID")
    if not isinstance(max_chars, int) or max_chars < 1000 or max_chars > 1000000:
        raise E2EExecutorError("E2E_MAX_CHARS_INVALID")
    target = _target(target_id)
    client = _resolve_client()
    request_body = (json.dumps(dict(journey), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    request_sha256 = hashlib.sha256(request_body).hexdigest()
    command: Sequence[str] = [client] + _client_args()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(_workspace()),
            input=request_body,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise E2EExecutorError("E2E_EXECUTION_TIMEOUT") from exc
    except OSError as exc:
        raise E2EExecutorError("E2E_EXECUTION_FAILED:%s" % type(exc).__name__) from exc

    stdout = _decode(proc.stdout or b"")
    stderr = _decode(proc.stderr or b"")
    if proc.returncode != 0:
        detail = (stderr or stdout or "e2e orchestrator failed").strip()[:1000]
        raise E2EExecutorError("E2E_CLIENT_EXIT_NONZERO:%s" % detail)
    try:
        raw_receipt = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise E2EExecutorError("E2E_RECEIPT_JSON_INVALID") from exc
    receipt = _validated_receipt(raw_receipt, target_id=target)
    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    client_name = Path(client).name
    invocation_ref = "e2e-orchestrator://%s/%s/%s" % (target, client_name, receipt_sha256[:24])
    return {
        "tool": "e2e-orchestrator",
        "implementation": "external-cross-system-orchestrator",
        "target_id": target,
        "client": client_name,
        "exit_code": int(proc.returncode),
        "request_sha256": request_sha256,
        "receipt_sha256": receipt_sha256,
        "invocation_ref": invocation_ref,
        "journey_receipt": receipt,
        "stderr": _bounded(stderr, min(max_chars, 50000)),
        "shell": False,
        "request_transport": "STDIN_JSON",
        "receipt_transport": "STDOUT_JSON",
        "client_args_persisted": False,
    }
