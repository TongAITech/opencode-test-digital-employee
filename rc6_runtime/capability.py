"""RC6 Wave 4 staged tool capability broker.

A discovered binary is not READY. Readiness is computed for a specific worker
and TargetIdentity and requires real probe evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional


class ToolCapabilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class CapabilityAdmission:
    ready: bool
    worker_id: str
    target_id: str
    required_tools: List[str]
    blocked: Dict[str, List[str]]


@dataclass(frozen=True)
class ToolCallEvidence:
    tool_id: str
    worker_id: str
    target_id: str
    call_ref: str
    evidence_ref: str

    def as_dict(self):
        return asdict(self)


class ToolCapabilityBroker:
    STAGES = (
        "DISCOVERED",
        "EXECUTABLE",
        "REGISTERED",
        "VISIBLE_TO_WORKER",
        "PERMISSION_OK",
        "PROBE_PASS",
        "TARGET_READY",
    )

    def __init__(self):
        self.tools: Dict[str, Dict] = {}

    def _tool(self, tool_id: str) -> Dict:
        if tool_id not in self.tools:
            raise ToolCapabilityError(f"TOOL_NOT_DISCOVERED:{tool_id}")
        return self.tools[tool_id]

    def discover(self, tool_id: str, locator: str) -> None:
        if not tool_id or not locator:
            raise ToolCapabilityError("INVALID_TOOL_DISCOVERY")
        self.tools[tool_id] = {
            "tool_id": tool_id,
            "locator": locator,
            "executable_ref": None,
            "registration_ref": None,
            "probe": None,
            "workers": {},
            "targets": {},
        }

    def mark_executable(self, tool_id: str, executable_ref: str) -> None:
        tool = self._tool(tool_id)
        if not executable_ref:
            raise ToolCapabilityError("EXECUTABLE_REF_REQUIRED")
        tool["executable_ref"] = executable_ref

    def register(self, tool_id: str, registration_ref: str) -> None:
        tool = self._tool(tool_id)
        if not tool.get("executable_ref"):
            raise ToolCapabilityError("TOOL_NOT_EXECUTABLE")
        if not registration_ref:
            raise ToolCapabilityError("REGISTRATION_REF_REQUIRED")
        tool["registration_ref"] = registration_ref

    def bind_worker(self, tool_id: str, worker_id: str, *, visible: bool, permitted: bool) -> None:
        tool = self._tool(tool_id)
        if not worker_id:
            raise ToolCapabilityError("WORKER_ID_REQUIRED")
        tool["workers"][worker_id] = {"visible": bool(visible), "permitted": bool(permitted)}

    def record_probe(
        self,
        tool_id: str,
        *,
        success: bool,
        tool_call_ref: Optional[str],
        evidence_ref: Optional[str],
    ) -> None:
        tool = self._tool(tool_id)
        if not tool.get("registration_ref"):
            raise ToolCapabilityError("TOOL_NOT_REGISTERED")
        if success and (not tool_call_ref or not evidence_ref):
            raise ToolCapabilityError("REAL_PROBE_EVIDENCE_REQUIRED")
        tool["probe"] = {
            "success": bool(success),
            "tool_call_ref": tool_call_ref,
            "evidence_ref": evidence_ref,
        }

    def mark_target_ready(self, tool_id: str, target_id: str, readiness_ref: str) -> None:
        tool = self._tool(tool_id)
        if not target_id or not readiness_ref:
            raise ToolCapabilityError("TARGET_READINESS_EVIDENCE_REQUIRED")
        tool["targets"][target_id] = readiness_ref

    def readiness(self, tool_id: str, worker_id: str, target_id: str) -> Dict[str, bool]:
        tool = self._tool(tool_id)
        worker = tool["workers"].get(worker_id, {})
        probe = tool.get("probe") or {}
        states = {
            "DISCOVERED": bool(tool.get("locator")),
            "EXECUTABLE": bool(tool.get("executable_ref")),
            "REGISTERED": bool(tool.get("registration_ref")),
            "VISIBLE_TO_WORKER": bool(worker.get("visible")),
            "PERMISSION_OK": bool(worker.get("permitted")),
            "PROBE_PASS": bool(probe.get("success") and probe.get("tool_call_ref") and probe.get("evidence_ref")),
            "TARGET_READY": target_id in tool.get("targets", {}),
        }
        states["READY"] = all(states[x] for x in self.STAGES)
        return states

    def admit(self, worker_id: str, required_tools: Iterable[str], target_id: str) -> CapabilityAdmission:
        required = list(required_tools)
        blocked: Dict[str, List[str]] = {}
        for tool_id in required:
            try:
                states = self.readiness(tool_id, worker_id, target_id)
            except ToolCapabilityError:
                blocked[tool_id] = ["DISCOVERED"]
                continue
            missing = [stage for stage in self.STAGES if not states[stage]]
            if missing:
                blocked[tool_id] = missing
        return CapabilityAdmission(
            ready=not blocked,
            worker_id=worker_id,
            target_id=target_id,
            required_tools=required,
            blocked=blocked,
        )

    def record_tool_call(
        self,
        tool_id: str,
        *,
        worker_id: str,
        target_id: str,
        call_ref: str,
        evidence_ref: str,
    ) -> ToolCallEvidence:
        admission = self.admit(worker_id, [tool_id], target_id)
        if not admission.ready:
            raise ToolCapabilityError(f"TOOL_NOT_READY:{tool_id}:{admission.blocked.get(tool_id)}")
        if not call_ref or not evidence_ref:
            raise ToolCapabilityError("TOOL_CALL_EVIDENCE_REQUIRED")
        return ToolCallEvidence(tool_id, worker_id, target_id, call_ref, evidence_ref)
