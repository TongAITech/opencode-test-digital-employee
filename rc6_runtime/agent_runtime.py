from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import contracts as _contracts
from . import truth as _truth
from .authority import AuthorityRuntime, TaskLease, WorkerIdentity
from .intelligence import GateResult, RequirementSufficiencyEvaluator


class AgentRuntimeError(RuntimeError):
    pass


AGENT_RUNTIME_EVENT_TYPES = (
    "WORKER_ASSIGN_REQUESTED",
    "WORKER_ADMITTED",
    "WORKER_STARTED",
    "WORKER_TOOL_CALLED",
    "WORKER_OUTPUT_PRODUCED",
    "WORKER_COMPLETED",
    "HANDOFF_RETURNED",
    "SUFFICIENCY_STARTED",
    "SUFFICIENCY_GAP_FOUND",
    "REPAIR_REQUESTED",
    "WORKER_REASSIGNED",
    "SUFFICIENCY_REEVALUATED",
    "SUFFICIENCY_PASSED",
    "ROUTING_INTEGRITY_FAIL",
)

_REQUIRED_INVOCATION_FIELDS = (
    "worker_instance_id",
    "agent_id",
    "mission_id",
    "attempt_id",
    "assignment_id",
    "lease_id",
    "parent_worker_id",
    "scope",
    "input_refs",
    "tool_calls",
    "output_refs",
    "evidence_refs",
    "started_at",
    "finished_at",
    "result",
)


def _required_str(payload: Dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _contracts.DomainValidationError("MISSING_OR_INVALID_%s" % name.upper())
    return value.strip()


def _required_list(payload: Dict[str, Any], name: str) -> list:
    value = payload.get(name)
    if not isinstance(value, list):
        raise _contracts.DomainValidationError("MISSING_OR_INVALID_%s" % name.upper())
    return value


def validate_agent_runtime_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = deepcopy(payload)
    out["id"] = _required_str(out, "id")
    out["release_id"] = _required_str(out, "release_id")
    out["mission_id"] = _required_str(out, "mission_id")
    out["event_name"] = _required_str(out, "event_name").upper()
    if out["event_name"] not in AGENT_RUNTIME_EVENT_TYPES:
        raise _contracts.DomainValidationError("INVALID_AGENT_RUNTIME_EVENT")
    out["coordinator_instance_id"] = _required_str(out, "coordinator_instance_id")
    version = out.get("artifact_version", 1)
    if not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("INVALID_ARTIFACT_VERSION")
    out["artifact_version"] = version
    occurred_at = out.get("occurred_at")
    if not isinstance(occurred_at, int) or occurred_at < 0:
        raise _contracts.DomainValidationError("INVALID_OCCURRED_AT")
    out["artifact_type"] = "agent_runtime_event"
    if out["event_name"].startswith("WORKER_") or out["event_name"] == "HANDOFF_RETURNED":
        for name in _REQUIRED_INVOCATION_FIELDS:
            if name in {"input_refs", "tool_calls", "output_refs", "evidence_refs"}:
                _required_list(out, name)
            elif name in {"started_at", "finished_at"}:
                if not isinstance(out.get(name), int) or out[name] < 0:
                    raise _contracts.DomainValidationError("MISSING_OR_INVALID_%s" % name.upper())
            else:
                _required_str(out, name)
        if out["worker_instance_id"] == out["coordinator_instance_id"]:
            raise _contracts.DomainValidationError("COORDINATOR_WORKER_IDENTITY_COLLISION")
    return out


def validate_requirement_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = deepcopy(payload)
    for name in ("id", "release_id", "requirement_id", "subject_analysis_id", "reviewer_worker_id", "analyzer_worker_id", "decision"):
        out[name] = _required_str(out, name)
    out["decision"] = out["decision"].upper()
    if out["decision"] not in {"PASS", "GAPS"}:
        raise _contracts.DomainValidationError("INVALID_REQUIREMENT_REVIEW_DECISION")
    _required_list(out, "gap_ids")
    _required_list(out, "evidence_refs")
    version = out.get("artifact_version", 1)
    if not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("INVALID_ARTIFACT_VERSION")
    out["artifact_version"] = version
    out["artifact_type"] = "requirement_review"
    if out["reviewer_worker_id"] == out["analyzer_worker_id"]:
        raise _contracts.DomainValidationError("REVIEW_INDEPENDENCE_FAIL")
    return out


def validate_analysis_gap(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = deepcopy(payload)
    for name in ("id", "release_id", "requirement_id", "analysis_id", "gap_id", "source_review_id", "status"):
        out[name] = _required_str(out, name)
    out["status"] = out["status"].upper()
    if out["status"] not in {"OPEN", "CLOSED"}:
        raise _contracts.DomainValidationError("INVALID_ANALYSIS_GAP_STATUS")
    _required_list(out, "evidence_refs")
    version = out.get("artifact_version", 1)
    if not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("INVALID_ARTIFACT_VERSION")
    out["artifact_version"] = version
    out["artifact_type"] = "analysis_gap"
    return out


def _register_r1_extensions() -> None:
    # This is a narrow extension of the existing R1 contract. It does not create
    # a second qualification log: lifecycle proof lives in the same JSONL stream
    # as business truth and participates in deterministic replay/projection.
    _contracts.VALIDATORS.setdefault("agent_runtime_event", validate_agent_runtime_event)
    _contracts.VALIDATORS.setdefault("requirement_review", validate_requirement_review)
    _contracts.VALIDATORS.setdefault("analysis_gap", validate_analysis_gap)
    _truth.BUCKETS.setdefault("agent_runtime_event", "agent_runtime_events")
    _truth.BUCKETS.setdefault("requirement_review", "requirement_reviews")
    _truth.BUCKETS.setdefault("analysis_gap", "analysis_gaps")
    _truth.IDENTITY_FIELDS.setdefault("agent_runtime_event", "id")
    _truth.IDENTITY_FIELDS.setdefault("requirement_review", "id")
    _truth.IDENTITY_FIELDS.setdefault("analysis_gap", "id")
    for event_name in AGENT_RUNTIME_EVENT_TYPES:
        _truth.EVENT_TYPES.setdefault(event_name, ("agent_runtime_event", "id"))
    _truth.EVENT_TYPES.setdefault("REQUIREMENT_REVIEW_UPSERTED", ("requirement_review", "id"))
    _truth.EVENT_TYPES.setdefault("ANALYSIS_GAP_UPSERTED", ("analysis_gap", "id"))


_register_r1_extensions()


@dataclass(frozen=True)
class WorkerAssignment:
    identity: WorkerIdentity
    lease: TaskLease
    worker_instance_id: str
    agent_id: str
    mission_id: str
    attempt_id: str
    assignment_id: str
    parent_worker_id: str
    scope: str
    input_refs: Tuple[str, ...]
    allowed_artifact_types: Tuple[str, ...]
    allowed_tools: Tuple[str, ...]


@dataclass
class WorkerInvocation:
    worker_instance_id: str
    agent_id: str
    mission_id: str
    attempt_id: str
    assignment_id: str
    lease_id: str
    parent_worker_id: str
    scope: str
    input_refs: List[str]
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    output_refs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    started_at: int = 0
    finished_at: int = 0
    result: str = "PENDING"
    dsh_session_id: Optional[str] = None
    exit_code: Optional[int] = None

    def as_event_fields(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HeadlessRunResult:
    exit_code: int
    events: Tuple[Dict[str, Any], ...]
    session_id: str
    tool_calls: Tuple[Dict[str, Any], ...]
    output: Dict[str, Any]
    raw_output_ref: str


@dataclass(frozen=True)
class AgentRuntimeQualificationResult:
    status: str
    mission_id: str
    coordinator_instance_id: str
    reason: Optional[str]
    r1_event_count: int
    r1_proof_event_ids: Tuple[str, ...]
    worker_instance_ids: Tuple[str, ...]
    dsh_session_ids: Tuple[str, ...]
    first_gate_status: Optional[str]
    second_gate_status: Optional[str]


class IndependentRequirementSufficiencyGate:
    """Production-strength requirement gate overlay for agent runtime.

    The Wave-5 evaluator remains the base predicate. This overlay adds the P0
    guarantee exposed by field qualification: a missing boundary dimension can
    never be accepted merely because the reviewer/model says PASS.
    """

    def __init__(self) -> None:
        self._base = RequirementSufficiencyEvaluator()

    def evaluate(self, analysis: Dict[str, Any], review: Dict[str, Any]) -> GateResult:
        base = self._base.evaluate(analysis, review)
        reasons = list(base.reasons)
        metrics = dict(base.metrics)
        boundaries = analysis.get("boundaries")
        boundary_present = isinstance(boundaries, list) and bool(boundaries)
        metrics["boundary_rule_present"] = boundary_present
        if not boundary_present and "REQ_BOUNDARY_RULE_MISSING" not in reasons:
            reasons.append("REQ_BOUNDARY_RULE_MISSING")
        return GateResult(
            passed=not reasons,
            status="SUFFICIENT" if not reasons else "NOT_SUFFICIENT_CONTENT",
            reasons=reasons,
            metrics=metrics,
        )


class DshHeadlessWorkerLauncher:
    """Launch each professional worker in a fresh real DSH headless session.

    A launch is not considered complete unless DSH reports a fresh session,
    at least one real tool call, strict JSON output, and zero process exit code.
    There is deliberately no coordinator fallback path.
    """

    def __init__(
        self,
        *,
        dsh_bin: str,
        patch_path: str,
        cwd: str,
        truth: _truth.TruthRuntime,
        authority: AuthorityRuntime,
        coordinator_instance_id: str,
        release_id: str,
        state_root: str,
        timeout_seconds: int = 300,
        env: Optional[Dict[str, str]] = None,
        command_runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ) -> None:
        self.dsh_bin = dsh_bin
        self.patch_path = str(Path(patch_path).resolve())
        self.cwd = str(Path(cwd).resolve())
        self.truth = truth
        self.authority = authority
        self.coordinator_instance_id = coordinator_instance_id
        self.release_id = release_id
        self.state_root = Path(state_root).resolve()
        self.timeout_seconds = int(timeout_seconds)
        self.env = dict(env or {})
        self.command_runner = command_runner or subprocess.run
        self._known_sessions: set = set()
        self.state_root.mkdir(parents=True, exist_ok=True)

    def assign(
        self,
        *,
        agent_id: str,
        role: str,
        phase: str,
        mission_id: str,
        attempt_id: str,
        scope: str,
        input_refs: Sequence[str],
        allowed_artifact_types: Sequence[str],
        allowed_tools: Sequence[str],
        parent_worker_id: Optional[str] = None,
        generation: int = 0,
    ) -> WorkerAssignment:
        identity = self.authority.issue_identity(role, phase, None, generation, "runtime-assignment-" + uuid.uuid4().hex)
        assignment_id = "assign-" + uuid.uuid4().hex
        pending = WorkerInvocation(
            worker_instance_id=identity.worker_id,
            agent_id=agent_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            assignment_id=assignment_id,
            lease_id="PENDING",
            parent_worker_id=parent_worker_id or self.coordinator_instance_id,
            scope=scope,
            input_refs=list(input_refs),
        )
        self._emit("WORKER_ASSIGN_REQUESTED", pending)
        try:
            lease = self.authority.issue_lease(
                identity.worker_id,
                scope,
                allowed_artifact_types,
                allowed_tools,
                ttl_seconds=max(self.timeout_seconds + 120, 300),
            )
        except Exception as exc:
            self._emit_routing_fail(mission_id, "LEASE_ADMISSION_FAILED:%s" % exc)
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL") from exc
        pending.lease_id = lease.lease_id
        self._emit("WORKER_ADMITTED", pending)
        return WorkerAssignment(
            identity=identity,
            lease=lease,
            worker_instance_id=identity.worker_id,
            agent_id=agent_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            assignment_id=assignment_id,
            parent_worker_id=pending.parent_worker_id,
            scope=scope,
            input_refs=tuple(input_refs),
            allowed_artifact_types=tuple(allowed_artifact_types),
            allowed_tools=tuple(allowed_tools),
        )

    def execute(self, assignment: WorkerAssignment, prompt: str) -> Tuple[WorkerInvocation, Dict[str, Any]]:
        if not self._dsh_available():
            self._emit_routing_fail(assignment.mission_id, "DSH_NOT_AVAILABLE")
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:DSH_NOT_AVAILABLE")
        invocation = WorkerInvocation(
            worker_instance_id=assignment.worker_instance_id,
            agent_id=assignment.agent_id,
            mission_id=assignment.mission_id,
            attempt_id=assignment.attempt_id,
            assignment_id=assignment.assignment_id,
            lease_id=assignment.lease.lease_id,
            parent_worker_id=assignment.parent_worker_id,
            scope=assignment.scope,
            input_refs=list(assignment.input_refs),
            started_at=int(time.time()),
        )
        self._emit("WORKER_STARTED", invocation)
        command = [
            self.dsh_bin,
            "--profile", "headless",
            "--patch", self.patch_path,
            "--json",
            prompt,
        ]
        run_env = os.environ.copy()
        run_env.update(self.env)
        try:
            proc = self.command_runner(
                command,
                cwd=self.cwd,
                env=run_env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            invocation.finished_at = int(time.time())
            invocation.result = "ROUTING_INTEGRITY_FAIL"
            self._emit("WORKER_COMPLETED", invocation, extra={"failure": str(exc)})
            self._emit_routing_fail(assignment.mission_id, "DSH_LAUNCH_FAILED:%s" % type(exc).__name__)
            raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:DSH_LAUNCH_FAILED") from exc

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        raw_ref = self._persist_raw_worker_output(assignment, stdout, stderr)
        events = tuple(self._parse_json_lines(stdout))
        session_id = self._session_id(events)
        if not session_id:
            self._fail_invocation(invocation, proc.returncode, raw_ref, "DSH_SESSION_ID_MISSING")
        if session_id == self.coordinator_instance_id or session_id in self._known_sessions:
            self._fail_invocation(invocation, proc.returncode, raw_ref, "WORKER_SESSION_NOT_INDEPENDENT")
        self._known_sessions.add(session_id)
        invocation.dsh_session_id = session_id
        invocation.exit_code = int(proc.returncode)
        invocation.evidence_refs.append("dsh://session/%s" % session_id)
        invocation.evidence_refs.append(raw_ref)

        calls = self._tool_calls(events)
        invocation.tool_calls.extend(calls)
        for call in calls:
            self._emit("WORKER_TOOL_CALLED", invocation, extra={"tool_call": call})
        if not calls:
            self._fail_invocation(invocation, proc.returncode, raw_ref, "REAL_TOOL_CALL_MISSING")

        output = self._final_json(events)
        if not isinstance(output, dict) or not output:
            self._fail_invocation(invocation, proc.returncode, raw_ref, "STRICT_JSON_OUTPUT_MISSING")
        output_ref = "handoff://%s/%s" % (assignment.worker_instance_id, assignment.attempt_id)
        invocation.output_refs.append(output_ref)
        self._emit("WORKER_OUTPUT_PRODUCED", invocation, extra={"output_ref": output_ref})

        invocation.finished_at = int(time.time())
        if proc.returncode != 0:
            invocation.result = "FAIL"
            self._emit("WORKER_COMPLETED", invocation, extra={"exit_code": int(proc.returncode)})
            raise AgentRuntimeError("WORKER_PROCESS_FAILED")
        invocation.result = "PASS"
        self._emit("WORKER_COMPLETED", invocation)
        self._emit("HANDOFF_RETURNED", invocation)
        return invocation, output

    def emit_reassigned(self, previous: WorkerInvocation, successor: WorkerAssignment) -> None:
        invocation = WorkerInvocation(
            worker_instance_id=successor.worker_instance_id,
            agent_id=successor.agent_id,
            mission_id=successor.mission_id,
            attempt_id=successor.attempt_id,
            assignment_id=successor.assignment_id,
            lease_id=successor.lease.lease_id,
            parent_worker_id=successor.parent_worker_id,
            scope=successor.scope,
            input_refs=list(successor.input_refs),
        )
        self._emit(
            "WORKER_REASSIGNED",
            invocation,
            extra={"previous_worker_instance_id": previous.worker_instance_id},
        )

    def emit_control_event(self, event_name: str, mission_id: str, **extra: Any) -> Dict[str, Any]:
        if event_name not in AGENT_RUNTIME_EVENT_TYPES:
            raise AgentRuntimeError("UNKNOWN_AGENT_RUNTIME_EVENT")
        payload = {
            "id": "are-" + uuid.uuid4().hex,
            "release_id": self.release_id,
            "artifact_version": 1,
            "mission_id": mission_id,
            "event_name": event_name,
            "coordinator_instance_id": self.coordinator_instance_id,
            "occurred_at": int(time.time()),
        }
        payload.update(extra)
        receipt = self.truth.append_atomic(event_name, payload)
        return asdict(receipt)

    def _emit(self, event_name: str, invocation: WorkerInvocation, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "id": "are-" + uuid.uuid4().hex,
            "release_id": self.release_id,
            "artifact_version": 1,
            "mission_id": invocation.mission_id,
            "event_name": event_name,
            "coordinator_instance_id": self.coordinator_instance_id,
            "occurred_at": int(time.time()),
        }
        payload.update(invocation.as_event_fields())
        if extra:
            payload.update(extra)
        receipt = self.truth.append_atomic(event_name, payload)
        return asdict(receipt)

    def _emit_routing_fail(self, mission_id: str, reason: str) -> None:
        self.emit_control_event("ROUTING_INTEGRITY_FAIL", mission_id, reason=reason)

    def _fail_invocation(self, invocation: WorkerInvocation, exit_code: int, raw_ref: str, reason: str) -> None:
        invocation.finished_at = int(time.time())
        invocation.exit_code = int(exit_code)
        invocation.result = "FAIL"
        if raw_ref not in invocation.evidence_refs:
            invocation.evidence_refs.append(raw_ref)
        self._emit("WORKER_COMPLETED", invocation, extra={"failure": reason})
        raise AgentRuntimeError(reason)

    def _dsh_available(self) -> bool:
        path = self.dsh_bin
        if os.path.isabs(path) or os.sep in path or (os.altsep and os.altsep in path):
            return Path(path).is_file()
        return shutil.which(path) is not None

    def _persist_raw_worker_output(self, assignment: WorkerAssignment, stdout: str, stderr: str) -> str:
        folder = self.state_root / "worker-evidence" / assignment.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (assignment.assignment_id + ".jsonl")
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(stdout)
            if stderr:
                fh.write("\n")
                fh.write(json.dumps({"type": "stderr", "text": stderr}, ensure_ascii=False))
                fh.write("\n")
        return "file://" + path.as_posix()

    @staticmethod
    def _parse_json_lines(text: str) -> Iterable[Dict[str, Any]]:
        for raw in text.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value

    @classmethod
    def _session_id(cls, events: Sequence[Dict[str, Any]]) -> str:
        for event in events:
            kind = str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
            candidates = cls._walk_values(event, {"session_id", "sessionid", "id"})
            for value in candidates:
                if isinstance(value, str) and value.startswith("session-") and ("session" in kind or value):
                    return value
        return ""

    @classmethod
    def _tool_calls(cls, events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        calls: List[Dict[str, Any]] = []
        for index, event in enumerate(events):
            kind = str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
            has_tool_name = any(str(k).lower() in {"tool", "tool_name", "toolname", "name"} for k in event.keys())
            if "tool_call" not in kind and "toolcall" not in kind and not ("tool" in kind and "result" not in kind and has_tool_name):
                continue
            tool_name = ""
            for key in ("tool_name", "toolName", "tool", "name"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    tool_name = value.strip()
                    break
            if not tool_name:
                nested = cls._walk_values(event, {"tool_name", "toolname", "tool", "name"})
                tool_name = next((str(v) for v in nested if isinstance(v, str) and v.strip()), "unknown")
            calls.append({"call_ref": "dsh-event://tool-call/%d" % index, "tool_name": tool_name})
        return calls

    @classmethod
    def _final_json(cls, events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        strings: List[str] = []
        for event in events:
            kind = str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
            if kind in {"text", "final", "message", "assistant"} or "final" in kind or "text" in kind:
                strings.extend(str(v) for v in cls._walk_values(event, {"text", "content", "message", "output"}) if isinstance(v, str))
        for text in reversed(strings):
            obj = cls._last_json_object(text)
            if isinstance(obj, dict):
                if isinstance(obj.get("qualification_payload"), dict):
                    return obj["qualification_payload"]
                return obj
        return {}

    @staticmethod
    def _last_json_object(text: str) -> Optional[Dict[str, Any]]:
        decoder = json.JSONDecoder()
        candidates: List[Dict[str, Any]] = []
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                candidates.append(value)
        return candidates[-1] if candidates else None

    @staticmethod
    def _walk_values(value: Any, keys: set) -> List[Any]:
        found: List[Any] = []
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in keys:
                    found.append(child)
                found.extend(DshHeadlessWorkerLauncher._walk_values(child, keys))
        elif isinstance(value, list):
            for child in value:
                found.extend(DshHeadlessWorkerLauncher._walk_values(child, keys))
        return found


class AgentRuntimeProofValidator:
    REQUIRED_ORDER = (
        "WORKER_ASSIGN_REQUESTED",
        "WORKER_ADMITTED",
        "WORKER_STARTED",
        "WORKER_TOOL_CALLED",
        "WORKER_OUTPUT_PRODUCED",
        "WORKER_COMPLETED",
        "HANDOFF_RETURNED",
        "SUFFICIENCY_STARTED",
        "SUFFICIENCY_GAP_FOUND",
        "REPAIR_REQUESTED",
        "WORKER_REASSIGNED",
        "SUFFICIENCY_REEVALUATED",
        "SUFFICIENCY_PASSED",
    )

    def validate(self, truth: _truth.TruthRuntime, mission_id: str, coordinator_instance_id: str) -> Tuple[str, Tuple[str, ...]]:
        raw_events = [
            event for event in truth.store.iter_raw()
            if event.get("event_type") in AGENT_RUNTIME_EVENT_TYPES
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("mission_id") == mission_id
        ]
        names = [str(e.get("event_type")) for e in raw_events]
        cursor = -1
        for required in self.REQUIRED_ORDER:
            try:
                cursor = names.index(required, cursor + 1)
            except ValueError as exc:
                raise AgentRuntimeError("R1_PROOF_EVENT_MISSING_OR_OUT_OF_ORDER:%s" % required) from exc
        handoffs = [e["payload"] for e in raw_events if e.get("event_type") == "HANDOFF_RETURNED"]
        if len(handoffs) < 4:
            raise AgentRuntimeError("INSUFFICIENT_INDEPENDENT_WORKER_HANDOFFS")
        worker_ids = []
        sessions = []
        for payload in handoffs:
            for field_name in _REQUIRED_INVOCATION_FIELDS:
                if field_name not in payload:
                    raise AgentRuntimeError("WORKER_INVOCATION_FIELD_MISSING:%s" % field_name)
            worker_id = str(payload.get("worker_instance_id"))
            session_id = str(payload.get("dsh_session_id") or "")
            if worker_id == coordinator_instance_id:
                raise AgentRuntimeError("COORDINATOR_WORKER_IDENTITY_COLLISION")
            if not session_id or session_id == coordinator_instance_id:
                raise AgentRuntimeError("WORKER_SESSION_NOT_INDEPENDENT")
            worker_ids.append(worker_id)
            sessions.append(session_id)
            if not payload.get("tool_calls"):
                raise AgentRuntimeError("REAL_TOOL_CALL_MISSING")
            if not payload.get("output_refs") or not payload.get("evidence_refs"):
                raise AgentRuntimeError("WORKER_HANDOFF_PROOF_INCOMPLETE")
            if payload.get("result") != "PASS":
                raise AgentRuntimeError("WORKER_HANDOFF_NOT_PASS")
        if len(set(worker_ids)) != len(worker_ids):
            raise AgentRuntimeError("WORKER_INSTANCE_REUSED")
        if len(set(sessions)) != len(sessions):
            raise AgentRuntimeError("DSH_SESSION_REUSED")
        proof_ids = tuple(str(e.get("event_id")) for e in raw_events)
        return "PASS", proof_ids


def normalize_requirement_analysis(
    output: Dict[str, Any], *, release_id: str, requirement_id: str, worker: WorkerInvocation, attempt_number: int
) -> Dict[str, Any]:
    if not isinstance(output, dict):
        raise AgentRuntimeError("ANALYZER_OUTPUT_NOT_OBJECT")
    artifact = deepcopy(output)
    artifact_id = "req-analysis-%s-%d" % (worker.mission_id, attempt_number)
    artifact["id"] = artifact_id
    artifact["analysis_id"] = artifact_id
    artifact["release_id"] = release_id
    artifact["requirement_id"] = requirement_id
    artifact["analyzer_worker_id"] = worker.worker_instance_id
    refs = artifact.get("evidence_refs")
    if not isinstance(refs, list):
        raise AgentRuntimeError("ANALYZER_EVIDENCE_REFS_MISSING")
    artifact["evidence_refs"] = list(dict.fromkeys(refs + worker.evidence_refs + worker.output_refs))
    return artifact


def normalize_requirement_review(
    output: Dict[str, Any], *, release_id: str, requirement_id: str, analysis: Dict[str, Any], analyzer: WorkerInvocation, reviewer: WorkerInvocation, attempt_number: int
) -> Dict[str, Any]:
    if not isinstance(output, dict):
        raise AgentRuntimeError("REVIEWER_OUTPUT_NOT_OBJECT")
    review = deepcopy(output)
    review_id = "req-review-%s-%d" % (reviewer.mission_id, attempt_number)
    review["id"] = review_id
    review["review_id"] = review_id
    review["release_id"] = release_id
    review["requirement_id"] = requirement_id
    review["subject_analysis_id"] = analysis["analysis_id"]
    review["analyzer_worker_id"] = analyzer.worker_instance_id
    review["reviewer_worker_id"] = reviewer.worker_instance_id
    refs = review.get("evidence_refs")
    if not isinstance(refs, list):
        raise AgentRuntimeError("REVIEWER_EVIDENCE_REFS_MISSING")
    review["evidence_refs"] = list(dict.fromkeys(refs + reviewer.evidence_refs + reviewer.output_refs))
    return review


def append_requirement_analysis(truth: _truth.TruthRuntime, artifact: Dict[str, Any]) -> None:
    truth.append_atomic("REQUIREMENT_ANALYSIS_UPSERTED", artifact)


def append_requirement_review(truth: _truth.TruthRuntime, review: Dict[str, Any]) -> None:
    truth.append_atomic("REQUIREMENT_REVIEW_UPSERTED", review)


def append_gap(truth: _truth.TruthRuntime, review: Dict[str, Any], gap_id: str, status: str = "OPEN") -> str:
    artifact_id = "gap-%s-%s" % (review["id"], gap_id)
    truth.append_atomic("ANALYSIS_GAP_UPSERTED", {
        "id": artifact_id,
        "release_id": review["release_id"],
        "artifact_version": 1 if status == "OPEN" else 2,
        "requirement_id": review["requirement_id"],
        "analysis_id": review["subject_analysis_id"],
        "gap_id": gap_id,
        "source_review_id": review["id"],
        "status": status,
        "evidence_refs": list(review.get("evidence_refs") or []),
    })
    return artifact_id
