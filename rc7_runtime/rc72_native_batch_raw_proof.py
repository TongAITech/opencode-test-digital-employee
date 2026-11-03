"""C10 native DSH on-disk evidence attestation for shared model batches.

The invocation object is not itself raw execution proof: independently check
the persisted JSONL that the native DSH process wrote. Exact tool refs and
session identity must agree with that file, whose digest is stored in R1.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Set, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher

from .models import ContractError


class NativeRawProofError(ContractError):
    pass


def _path(raw_ref: str, *, root: Path) -> Path:
    if not isinstance(raw_ref, str) or not raw_ref.startswith("file://"):
        raise NativeRawProofError("NATIVE_BATCH_RAW_FILE_REF_REQUIRED")
    file_name = raw_ref[len("file://"):]
    if not file_name:
        raise NativeRawProofError("NATIVE_BATCH_RAW_PATH_REQUIRED")
    target = Path(file_name)
    if target.is_symlink() or not target.is_file():
        raise NativeRawProofError("NATIVE_BATCH_RAW_FILE_NOT_REGULAR")
    try:
        target.resolve().relative_to(Path(root).resolve())
    except ValueError as exc:
        raise NativeRawProofError("NATIVE_BATCH_RAW_OUTSIDE_WORKER_ROOT") from exc
    return target


def attest_native_raw(
    launcher: DshHeadlessWorkerLauncher, *,
    raw_ref: str, session_id: str, expected_tool_refs: Iterable[str],
) -> Dict[str, Any]:
    """Return SHA/tool-call refs only from the real native JSONL file.

    Do not trust the model JSON's claimed tool refs or a launcher invocation
    object until they match independently parsed raw events.
    """
    if not isinstance(launcher, DshHeadlessWorkerLauncher):
        raise NativeRawProofError("NATIVE_BATCH_NATIVE_DSH_REQUIRED")
    if not isinstance(session_id, str) or not session_id.strip():
        raise NativeRawProofError("NATIVE_BATCH_REAL_SESSION_REQUIRED")
    target = _path(raw_ref, root=launcher.state_root)
    try:
        raw = target.read_bytes()
        decoded = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise NativeRawProofError("NATIVE_BATCH_RAW_UNREADABLE") from exc
    if not raw:
        raise NativeRawProofError("NATIVE_BATCH_RAW_EMPTY")
    events = []
    for line in decoded.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict):
            events.append(event)
    if not events:
        raise NativeRawProofError("NATIVE_BATCH_RAW_JSONL_MISSING")
    actual_session = DshHeadlessWorkerLauncher._session_id(events)
    if actual_session != session_id:
        raise NativeRawProofError("NATIVE_BATCH_RAW_SESSION_MISMATCH")
    tools = DshHeadlessWorkerLauncher._tool_calls(events)
    actual_refs: Set[str] = {
        tool["call_ref"] for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("call_ref"), str)
    }
    expected = tuple(expected_tool_refs)
    if (
        not expected
        or len(set(expected)) != len(expected)
        or any(not isinstance(ref, str) or not ref.startswith("dsh-event://tool-call/")
               for ref in expected)
        or not set(expected).issubset(actual_refs)
    ):
        raise NativeRawProofError("NATIVE_BATCH_RAW_TOOL_CALL_MISMATCH")
    return {
        "raw_output_sha256": hashlib.sha256(raw).hexdigest(),
        "tool_refs": tuple(sorted(actual_refs)),
        "session_id": actual_session,
    }


def verify_native_raw_digest(*, raw_ref: str, expected_sha256: str) -> None:
    """Re-check already accepted R1 raw file has not been edited or replaced."""
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or not isinstance(raw_ref, str)
        or not raw_ref.startswith("file://")
    ):
        raise NativeRawProofError("NATIVE_BATCH_RAW_DIGEST_UNAVAILABLE")
    target = Path(raw_ref[len("file://"):])
    if target.is_symlink() or not target.is_file():
        raise NativeRawProofError("NATIVE_BATCH_RAW_FILE_MISSING")
    try:
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError as exc:
        raise NativeRawProofError("NATIVE_BATCH_RAW_UNREADABLE") from exc
    if actual != expected_sha256:
        raise NativeRawProofError("NATIVE_BATCH_RAW_DIGEST_CHANGED")
