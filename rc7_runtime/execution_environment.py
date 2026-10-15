"""Evidence-backed external environment admission for RC7 Execution.

Skills/prompts are not executable runtime providers.  A field environment must
supply an explicit Python adapter that performs real target/tool probes and the
precondition/data operations used by PreparationRuntime.  Static JSON claiming
`success=true` is deliberately not an admission surface.

Runtime secrets (cookies/tokens/passwords) may be returned by execution_env()
for the launched process, but are never serialized by this module.  Durable R1
truth records only adapter identity, non-secret probe metadata and evidence
references.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.execution import ExecutionProfileRegistry

from .closed_loop_control import ClosedLoopControlPlane
from .models import Artifact, Evidence, TaskStatus
from .truth_overlay import append_entity


class ExecutionEnvironmentError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class ToolProbeResult:
    tool_id: str
    success: bool
    locator_ref: str
    executable_ref: str
    registration_ref: str
    tool_call_ref: Optional[str]
    evidence_ref: Optional[str]
    target_readiness_ref: Optional[str]


@dataclass(frozen=True)
class ExecutionEnvironmentAdmission:
    adapter_id: str
    target_id: str
    layer: str
    required_tools: Tuple[str, ...]
    probe_results: Tuple[ToolProbeResult, ...]
    broker: ToolCapabilityBroker
    artifact_id: str
    evidence_ids: Tuple[str, ...]
    content_ref: str
    content_hash: str


class ExecutionEnvironmentAdapter(ABC):
    """Executable field adapter contract; implementations may wrap 4A/DB/UI/etc."""

    @property
    @abstractmethod
    def adapter_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def probe_tool(self, *, tool_id: str, target_id: str, layer: str) -> ToolProbeResult:
        """Run a real probe for one required execution tool."""
        raise NotImplementedError

    @abstractmethod
    def resolve_precondition(self, spec: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def prepare_data(
        self,
        requirement: Dict[str, Any],
        context: Dict[str, Any],
        *,
        strategy: str,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def verify_data(
        self,
        requirement: Dict[str, Any],
        binding: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def request_human_gate(self, request: Dict[str, Any]) -> Optional[str]:
        """Return an externally issued approval evidence ref, or None to deny."""
        del request
        return None

    def execution_env(self, *, target_id: str, layer: str) -> Mapping[str, str]:
        """Ephemeral process environment. Values are intentionally not persisted."""
        del target_id, layer
        return {}


class ExecutionEnvironmentAdmissionService:
    def __init__(self, *, evidence_root: str) -> None:
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    def admit(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        *,
        adapter: ExecutionEnvironmentAdapter,
        target_id: str,
        layer: str,
    ) -> ExecutionEnvironmentAdmission:
        task = control.scheduler.task(task_id)
        if task.node != "EXECUTION":
            raise ExecutionEnvironmentError("ENVIRONMENT_ADMISSION_REQUIRES_EXECUTION_TASK")
        if task.state != TaskStatus.READY:
            raise ExecutionEnvironmentError("ENVIRONMENT_ADMISSION_REQUIRES_READY_TASK")
        if not isinstance(adapter, ExecutionEnvironmentAdapter):
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_ADAPTER_REQUIRED")
        adapter_id = str(adapter.adapter_id or "").strip()
        if not adapter_id:
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_ADAPTER_ID_REQUIRED")
        if not isinstance(target_id, str) or not target_id.strip():
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_TARGET_REQUIRED")
        target_id = target_id.strip()
        layer = str(layer or "").upper()
        profile = ExecutionProfileRegistry().get(layer)
        required_tools = tuple(profile.required_tools)

        broker = ToolCapabilityBroker()
        probes = []
        evidence = []
        for tool_id in required_tools:
            result = adapter.probe_tool(tool_id=tool_id, target_id=target_id, layer=layer)
            self._validate_probe(result, tool_id=tool_id)
            if not result.success:
                raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_PROBE_FAILED:%s" % tool_id)
            broker.discover(tool_id, result.locator_ref)
            broker.mark_executable(tool_id, result.executable_ref)
            broker.register(tool_id, result.registration_ref)
            broker.record_probe(
                tool_id,
                success=True,
                tool_call_ref=result.tool_call_ref,
                evidence_ref=result.evidence_ref,
            )
            broker.mark_target_ready(tool_id, target_id, str(result.target_readiness_ref))
            probes.append(result)
            evidence.append(
                Evidence(
                    evidence_id=_stable_id(
                        "EVD-ENV-PROBE",
                        control.mission_id,
                        task_id,
                        target_id,
                        layer,
                        tool_id,
                        str(result.tool_call_ref),
                        str(result.evidence_ref),
                    ),
                    mission_id=control.mission_id,
                    kind="EXECUTION_TOOL_PROBE",
                    source_ref="adapter://%s/%s" % (adapter_id, tool_id),
                    content_ref=str(result.evidence_ref),
                    subject_refs=[task_id, target_id, layer, tool_id, str(result.tool_call_ref)],
                )
            )

        folder = self.evidence_root / "environment-admission" / control.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (_stable_id("ENV", task_id, target_id, layer, adapter_id) + ".json")
        payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "task_id": task_id,
            "adapter_id": adapter_id,
            "target_id": target_id,
            "layer": layer,
            "required_tools": list(required_tools),
            "probes": [asdict(item) for item in probes],
            # execution_env is intentionally omitted: it may contain secrets.
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if path.exists() and path.read_bytes() != encoded:
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_ADMISSION_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)
        record_evidence = Evidence(
            evidence_id=_stable_id("EVD-ENV-ADMISSION", control.mission_id, task_id, target_id, layer, digest),
            mission_id=control.mission_id,
            kind="EXECUTION_ENVIRONMENT_ADMISSION",
            source_ref="runtime://execution-environment-admission",
            content_ref="file://" + str(path),
            subject_refs=[task_id, target_id, layer, adapter_id],
            content_hash="sha256:" + digest,
        )
        evidence.append(record_evidence)
        for item in evidence:
            if not control.truth.query("rc7_evidence", evidence_id=item.evidence_id):
                append_entity(control.truth, item, release_id=control.release_id)
        evidence_ids = tuple(item.evidence_id for item in evidence)
        artifact = Artifact(
            artifact_id=_stable_id("ART-ENV-ADMISSION", control.mission_id, task_id, target_id, layer, digest),
            mission_id=control.mission_id,
            artifact_type="EXECUTION_ENVIRONMENT_ADMISSION",
            producer_task_id=task_id,
            content_ref="file://" + str(path),
            evidence_refs=list(evidence_ids),
            content_hash="sha256:" + digest,
        )
        existing = control.truth.query("rc7_artifact", artifact_id=artifact.artifact_id)
        if not existing:
            append_entity(control.truth, artifact, release_id=control.release_id, artifact_version=1)
        elif len(existing) != 1 or existing[0].get("content_hash") != artifact.content_hash:
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_ADMISSION_ARTIFACT_CONFLICT")
        return ExecutionEnvironmentAdmission(
            adapter_id=adapter_id,
            target_id=target_id,
            layer=layer,
            required_tools=required_tools,
            probe_results=tuple(probes),
            broker=broker,
            artifact_id=artifact.artifact_id,
            evidence_ids=evidence_ids,
            content_ref=artifact.content_ref,
            content_hash=artifact.content_hash or "",
        )

    @staticmethod
    def preparation_callbacks(
        adapter: ExecutionEnvironmentAdapter,
        case: Mapping[str, Any],
    ) -> Tuple[
        Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        Callable[[Dict[str, Any]], Optional[str]],
    ]:
        if not isinstance(case, Mapping):
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_CASE_REQUIRED")
        precondition_types = set()
        raw_preconditions = case.get("preconditions", [])
        if not isinstance(raw_preconditions, Sequence) or isinstance(raw_preconditions, (str, bytes)):
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_PRECONDITIONS_INVALID")
        for item in raw_preconditions:
            if not isinstance(item, Mapping):
                raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_PRECONDITION_INVALID")
            value = item.get("type")
            if not isinstance(value, str) or not value.strip():
                raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_PRECONDITION_TYPE_REQUIRED")
            precondition_types.add(value.strip())

        strategies = set()
        test_data = case.get("test_data", {})
        if test_data is None:
            test_data = {}
        if not isinstance(test_data, Mapping):
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_TEST_DATA_INVALID")
        for group in ("initial_state", "input_data"):
            rows = test_data.get(group, [])
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_DATA_GROUP_INVALID:%s" % group)
            for requirement in rows:
                if not isinstance(requirement, Mapping):
                    raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_DATA_REQUIREMENT_INVALID")
                allowed = requirement.get("allowed_strategies", [])
                if not isinstance(allowed, Sequence) or isinstance(allowed, (str, bytes)):
                    raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_DATA_STRATEGIES_INVALID")
                for strategy in allowed:
                    if not isinstance(strategy, str) or not strategy.strip():
                        raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_DATA_STRATEGY_INVALID")
                    strategies.add(strategy.strip().upper())

        precondition_resolvers = {
            name: adapter.resolve_precondition for name in sorted(precondition_types)
        }

        def provider_for(strategy: str):
            def provider(requirement: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
                return adapter.prepare_data(requirement, context, strategy=strategy)
            return provider

        data_strategies = {name: provider_for(name) for name in sorted(strategies)}
        return (
            precondition_resolvers,
            data_strategies,
            adapter.verify_data,
            adapter.request_human_gate,
        )

    @staticmethod
    def _validate_probe(result: object, *, tool_id: str) -> None:
        if not isinstance(result, ToolProbeResult):
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_TOOL_PROBE_RESULT_REQUIRED:%s" % tool_id)
        if result.tool_id != tool_id:
            raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_TOOL_PROBE_ID_MISMATCH:%s" % tool_id)
        for field in ("locator_ref", "executable_ref", "registration_ref"):
            value = getattr(result, field)
            if not isinstance(value, str) or not value.strip():
                raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_PROBE_FIELD_REQUIRED:%s:%s" % (tool_id, field))
        if result.success:
            for field in ("tool_call_ref", "evidence_ref", "target_readiness_ref"):
                value = getattr(result, field)
                if not isinstance(value, str) or not value.strip():
                    raise ExecutionEnvironmentError("EXECUTION_ENVIRONMENT_REAL_PROBE_EVIDENCE_REQUIRED:%s:%s" % (tool_id, field))
