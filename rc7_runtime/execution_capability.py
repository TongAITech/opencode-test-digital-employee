"""Strict RC7.1 execution capability evidence loader.

The execution Autopilot must not turn packaged binaries into READY tools.  This
loader accepts only a field/runtime-generated capability snapshot and rebuilds
ToolCapabilityBroker from explicit discovery, executable, registration, real
probe and target-readiness evidence.

Expected JSON::

  {
    "schema": "pfc.aitest.rc7.1.execution-capabilities.v1",
    "target_id": "...",
    "tools": {
      "maven": {
        "locator": "...",
        "executable_ref": "file://...",
        "registration_ref": "...",
        "probe": {"success": true, "tool_call_ref": "...", "evidence_ref": "..."},
        "target_readiness_ref": "..."
      }
    }
  }

Worker visibility/permission is deliberately NOT stored here because execution
worker ids are runtime-issued. ClosedLoopRuntimeExecutionService binds the
new worker after identity issuance and before ToolCapabilityBroker.admit().
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping, Tuple

from rc6_runtime.capability import ToolCapabilityBroker


SCHEMA = "pfc.aitest.rc7.1.execution-capabilities.v1"


class ExecutionCapabilityEvidenceError(RuntimeError):
    pass


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionCapabilityEvidenceError(code)
    return value.strip()


def _require_evidence_ref(value: object, code: str) -> str:
    ref = _text(value, code)
    if ref.startswith("file://"):
        path = Path(ref[len("file://"):]).expanduser().resolve()
        if not path.is_file():
            raise ExecutionCapabilityEvidenceError(code + ":FILE_MISSING:" + str(path))
    return ref


class ExecutionCapabilityBrokerFactory:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise ExecutionCapabilityEvidenceError("EXECUTION_CAPABILITY_SNAPSHOT_REQUIRED:%s" % self.path)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExecutionCapabilityEvidenceError("EXECUTION_CAPABILITY_SNAPSHOT_INVALID") from exc
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise ExecutionCapabilityEvidenceError("EXECUTION_CAPABILITY_SCHEMA_INVALID")
        self.payload = payload
        self.target_id = _text(payload.get("target_id"), "EXECUTION_CAPABILITY_TARGET_REQUIRED")
        tools = payload.get("tools")
        if not isinstance(tools, dict):
            raise ExecutionCapabilityEvidenceError("EXECUTION_CAPABILITY_TOOLS_REQUIRED")
        self.tools: Dict[str, Mapping[str, object]] = {}
        for tool_id, raw in tools.items():
            if not isinstance(raw, dict):
                raise ExecutionCapabilityEvidenceError("EXECUTION_CAPABILITY_TOOL_OBJECT_REQUIRED:%s" % tool_id)
            self.tools[_text(tool_id, "EXECUTION_CAPABILITY_TOOL_ID_REQUIRED")] = raw

    def build(self, *, target_id: str, required_tools: Tuple[str, ...]) -> ToolCapabilityBroker:
        target_id = _text(target_id, "EXECUTION_TARGET_REQUIRED")
        if target_id != self.target_id:
            raise ExecutionCapabilityEvidenceError(
                "EXECUTION_CAPABILITY_TARGET_MISMATCH:%s:%s" % (self.target_id, target_id)
            )
        broker = ToolCapabilityBroker()
        for tool_id in required_tools:
            raw = self.tools.get(tool_id)
            if raw is None:
                raise ExecutionCapabilityEvidenceError("EXECUTION_CAPABILITY_TOOL_MISSING:%s" % tool_id)
            locator = _text(raw.get("locator"), "EXECUTION_TOOL_LOCATOR_REQUIRED:%s" % tool_id)
            executable_ref = _require_evidence_ref(
                raw.get("executable_ref"), "EXECUTION_TOOL_EXECUTABLE_EVIDENCE_REQUIRED:%s" % tool_id
            )
            registration_ref = _require_evidence_ref(
                raw.get("registration_ref"), "EXECUTION_TOOL_REGISTRATION_EVIDENCE_REQUIRED:%s" % tool_id
            )
            probe = raw.get("probe")
            if not isinstance(probe, dict) or probe.get("success") is not True:
                raise ExecutionCapabilityEvidenceError("EXECUTION_TOOL_REAL_PROBE_REQUIRED:%s" % tool_id)
            probe_call_ref = _require_evidence_ref(
                probe.get("tool_call_ref"), "EXECUTION_TOOL_PROBE_CALL_REQUIRED:%s" % tool_id
            )
            probe_evidence_ref = _require_evidence_ref(
                probe.get("evidence_ref"), "EXECUTION_TOOL_PROBE_EVIDENCE_REQUIRED:%s" % tool_id
            )
            target_ready = _require_evidence_ref(
                raw.get("target_readiness_ref"), "EXECUTION_TOOL_TARGET_READY_EVIDENCE_REQUIRED:%s" % tool_id
            )
            broker.discover(tool_id, locator)
            broker.mark_executable(tool_id, executable_ref)
            broker.register(tool_id, registration_ref)
            broker.record_probe(
                tool_id,
                success=True,
                tool_call_ref=probe_call_ref,
                evidence_ref=probe_evidence_ref,
            )
            broker.mark_target_ready(tool_id, target_id, target_ready)
        return broker
