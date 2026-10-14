"""Small runtime helper used by generated/reused test scripts.

A runner process is not itself proof that API/DB/UI work happened. Scripts and
shared fixtures append structured real-tool-call and actual-result records to a
manifest path injected by RunnerAdapter through RC6_EXECUTION_MANIFEST.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


class RunnerManifestError(RuntimeError):
    pass


def _path() -> Path:
    raw = os.environ.get("RC6_EXECUTION_MANIFEST")
    if not raw:
        raise RunnerManifestError("RC6_EXECUTION_MANIFEST_NOT_BOUND")
    return Path(raw)


def _append(record: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def record_tool_call(tool_id: str, call_ref: str, evidence_ref: str) -> None:
    for value, code in ((tool_id, "TOOL_ID_REQUIRED"), (call_ref, "CALL_REF_REQUIRED"), (evidence_ref, "EVIDENCE_REF_REQUIRED")):
        if not isinstance(value, str) or not value.strip():
            raise RunnerManifestError(code)
    _append({
        "type": "tool_call",
        "tool_id": tool_id.strip(),
        "call_ref": call_ref.strip(),
        "evidence_ref": evidence_ref.strip(),
    })


def record_actual_result(value: Dict[str, Any]) -> None:
    if not isinstance(value, dict) or not value:
        raise RunnerManifestError("ACTUAL_RESULT_OBJECT_REQUIRED")
    _append({"type": "actual_result", "value": value})


def record_note(kind: str, ref: str) -> None:
    if not isinstance(kind, str) or not kind.strip() or not isinstance(ref, str) or not ref.strip():
        raise RunnerManifestError("NOTE_KIND_AND_REF_REQUIRED")
    _append({"type": "note", "kind": kind.strip(), "ref": ref.strip()})
