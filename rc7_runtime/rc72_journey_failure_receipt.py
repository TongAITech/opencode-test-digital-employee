"""Durable runtime-failure receipts; never manufacture evidence:// adapter errors.

These receipts prove the adapter/worker failure, not a SUT defect or field
replay. They allow N8 to classify a capability/runtime gap without claiming
that a missing browser screenshot was observed.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from .models import ContractError


def adapter_exception_receipt(truth: Any, *, step: Mapping[str, Any],
                              context: Mapping[str, Any], error: Exception) -> str:
    root = Path(str(truth.store.path) + ".journey-failures")
    identity = json.dumps({
        "run": context.get("execution_id") or context.get("replay_id"),
        "attempt_id": context.get("attempt_id"),
        "sequence": step.get("sequence"),
    }, sort_keys=True, separators=(",", ":"), default=str)
    name = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32] + ".json"
    path = root / name
    root.mkdir(parents=True, exist_ok=True)
    receipt = {
        "kind": "ADAPTER_RUNTIME_FAILURE_NOT_SUT_ASSERTION",
        "run_id": context.get("execution_id") or context.get("replay_id"),
        "attempt_id": context.get("attempt_id"),
        "source_step_id": step.get("source_step_id"),
        "sequence": step.get("sequence"),
        "error_type": type(error).__name__,
        "captured_at": int(time.time()),
        "field_verified": False,
    }
    raw = json.dumps(receipt, sort_keys=True, ensure_ascii=True).encode("utf-8")
    temp = path.with_suffix(".json.tmp")
    with temp.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temp), str(path))
    return path.resolve().as_uri()
