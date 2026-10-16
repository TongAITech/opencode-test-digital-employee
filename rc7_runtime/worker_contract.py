from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rc6_runtime.agent_runtime import (
    AgentRuntimeError,
    DshHeadlessWorkerLauncher,
    WorkerAssignment,
    WorkerInvocation,
)


class RC7WorkerContractError(AgentRuntimeError):
    pass


@dataclass(frozen=True)
class WorkerRuntimeCoordinates:
    dsh_session_id: Optional[str]
    subagent_ids: Tuple[str, ...]
    background_job_ids: Tuple[str, ...]
    skill_name: str
    skill_tool_call_proven: bool


def compose_skill_bound_prompt(assignment: WorkerAssignment, prompt: str) -> str:
    """Make professional-role loading explicit without granting authority in text."""
    skill = assignment.agent_id.strip()
    if not skill:
        raise RC7WorkerContractError("WORKER_SKILL_NAME_REQUIRED")
    return (
        "RC7_WORKER_CONTRACT\n"
        "ASSIGNMENT_ID=%s\nMISSION_ID=%s\nAGENT_ID=%s\n"
        "Before any professional action you MUST call the DSH `skill` tool with "
        "the exact skill name `%s`. Do not merely claim that the skill is loaded. "
        "The runtime will verify the real tool-call arguments from the DSH JSON event stream. "
        "If the skill is unavailable, stop and return a blocked result; do not emulate the skill.\n"
        "After loading the skill, execute only the leased assignment and return the strict JSON handoff contract.\n\n"
        "TASK:\n%s"
        % (
            assignment.assignment_id,
            assignment.mission_id,
            skill,
            skill,
            prompt,
        )
    )


def _walk(value: Any) -> Iterable[Tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _event_kind(event: Dict[str, Any]) -> str:
    return str(event.get("type") or event.get("event") or event.get("kind") or "").lower()


def _tool_name(event: Dict[str, Any]) -> str:
    for key in ("tool_name", "toolName", "tool", "name"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key, value in _walk(event):
        if key.lower() in {"tool_name", "toolname", "tool"} and isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _contains_exact_string(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value.strip() == expected
    if isinstance(value, dict):
        return any(_contains_exact_string(child, expected) for child in value.values())
    if isinstance(value, list):
        return any(_contains_exact_string(child, expected) for child in value)
    return False


def _skill_call_matches(event: Dict[str, Any], expected_skill: str) -> bool:
    kind = _event_kind(event)
    if "tool_call" not in kind and "toolcall" not in kind and "tool" not in kind:
        return False
    name = _tool_name(event).lower().replace("-", "_")
    if not (name == "skill" or name.endswith("__skill") or name.endswith("_skill")):
        return False
    for key in ("arguments", "args", "input", "params", "payload"):
        if key in event and _contains_exact_string(event[key], expected_skill):
            return True
    # Some DSH event envelopes nest call details under data/content.
    for key, value in _walk(event):
        if key.lower() in {"arguments", "args", "input", "params"} and _contains_exact_string(value, expected_skill):
            return True
    return False


def _raw_evidence_path(invocation: WorkerInvocation) -> Path:
    refs = [ref for ref in invocation.evidence_refs if isinstance(ref, str) and ref.startswith("file://")]
    if not refs:
        raise RC7WorkerContractError("WORKER_RAW_DSH_EVIDENCE_MISSING")
    path = Path(refs[-1][len("file://"):])
    if not path.is_file():
        raise RC7WorkerContractError("WORKER_RAW_DSH_EVIDENCE_NOT_FOUND")
    return path


def inspect_worker_runtime(invocation: WorkerInvocation, expected_skill: str) -> WorkerRuntimeCoordinates:
    path = _raw_evidence_path(invocation)
    events: List[Dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)

    skill_proven = any(_skill_call_matches(event, expected_skill) for event in events)
    subagents: List[str] = []
    jobs: List[str] = []
    for event in events:
        for key, value in _walk(event):
            lowered = key.lower().replace("-", "_")
            if not isinstance(value, str) or not value.strip():
                continue
            text = value.strip()
            if lowered in {"subagent_id", "subagentid", "child_agent_id"}:
                subagents.append(text)
            elif lowered in {"background_job_id", "job_id", "jobid"}:
                jobs.append(text)
    return WorkerRuntimeCoordinates(
        dsh_session_id=invocation.dsh_session_id,
        subagent_ids=tuple(dict.fromkeys(subagents)),
        background_job_ids=tuple(dict.fromkeys(jobs)),
        skill_name=expected_skill,
        skill_tool_call_proven=skill_proven,
    )


class RC7SkillBoundWorkerLauncher(DshHeadlessWorkerLauncher):
    """RC7 worker launcher that proves exact professional-skill loading.

    The base runtime already proves an independent DSH session and real tool
    activity.  RC7 additionally requires a real `skill` tool call for the
    assigned professional skill before HANDOFF_RETURNED is allowed into R1.
    """

    def execute(self, assignment: WorkerAssignment, prompt: str):
        return super().execute(assignment, compose_skill_bound_prompt(assignment, prompt))

    def _emit(
        self,
        event_name: str,
        invocation: WorkerInvocation,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        enriched = dict(extra or {})
        if event_name == "HANDOFF_RETURNED":
            try:
                coordinates = inspect_worker_runtime(invocation, invocation.agent_id)
            except RC7WorkerContractError as exc:
                self._emit_routing_fail(invocation.mission_id, str(exc))
                raise
            if not coordinates.skill_tool_call_proven:
                self._emit_routing_fail(
                    invocation.mission_id,
                    "REQUIRED_WORKER_SKILL_TOOL_CALL_MISSING:%s" % invocation.agent_id,
                )
                raise RC7WorkerContractError(
                    "ROUTING_INTEGRITY_FAIL:REQUIRED_WORKER_SKILL_TOOL_CALL_MISSING"
                )
            enriched.update(
                {
                    "required_skill": coordinates.skill_name,
                    "skill_tool_call_proven": True,
                    "dsh_subagent_ids": list(coordinates.subagent_ids),
                    "dsh_background_job_ids": list(coordinates.background_job_ids),
                }
            )
        return super()._emit(event_name, invocation, enriched)


def worker_parallelism() -> int:
    """Bank-safe default prevents burst spawning from exhausting model quota."""
    raw = os.environ.get("PFC_RC7_WORKER_MAX_PARALLEL", "1").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RC7WorkerContractError("WORKER_MAX_PARALLEL_INVALID") from exc
    if value < 1 or value > 8:
        raise RC7WorkerContractError("WORKER_MAX_PARALLEL_OUT_OF_RANGE")
    return value


def is_provider_backpressure(text: str) -> bool:
    lowered = str(text or "").lower()
    markers = (
        "quota_exceeded",
        "quota exceeded",
        "too many requests",
        "http 429",
        "code: 429",
        "badrequester",
    )
    return any(marker in lowered for marker in markers)
