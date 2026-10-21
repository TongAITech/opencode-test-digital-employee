"""RC8 truth, identity and qualification contracts.

W0 deliberately adds durable cross-node identities and provenance without
rewriting RC7 execution tools. These contracts are transport/storage neutral;
W1+ adapters will persist them through the Center and R1 truth pipeline.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set


class RC8ContractError(ValueError):
    pass


class EventPlane(str, Enum):
    PLAN = "PLAN"
    RUNTIME = "RUNTIME"
    CONTROL = "CONTROL"


class RuntimeProducerKind(str, Enum):
    NODE_AGENT = "NODE_AGENT"
    WORKER = "WORKER"
    TOOL = "TOOL"


class ArtifactAvailability(str, Enum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADING = "UPLOADING"
    AVAILABLE = "AVAILABLE"
    UPLOAD_FAILED = "UPLOAD_FAILED"


class CapabilityState(str, Enum):
    DISCOVERED = "DISCOVERED"
    REGISTERED = "REGISTERED"
    PROBING = "PROBING"
    VERIFIED = "VERIFIED"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


_ALLOWED_CAPABILITY_TRANSITIONS = {
    CapabilityState.DISCOVERED: {CapabilityState.REGISTERED, CapabilityState.UNAVAILABLE},
    CapabilityState.REGISTERED: {CapabilityState.PROBING, CapabilityState.UNAVAILABLE},
    CapabilityState.PROBING: {CapabilityState.VERIFIED, CapabilityState.DEGRADED, CapabilityState.UNAVAILABLE},
    CapabilityState.VERIFIED: {CapabilityState.PROBING, CapabilityState.DEGRADED, CapabilityState.UNAVAILABLE},
    CapabilityState.DEGRADED: {CapabilityState.PROBING, CapabilityState.UNAVAILABLE},
    CapabilityState.UNAVAILABLE: {CapabilityState.DISCOVERED, CapabilityState.PROBING},
}


def _now() -> int:
    return int(time.time())


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RC8ContractError("%s_REQUIRED" % name.upper())
    return value.strip()


def _strings(values: Sequence[str], name: str) -> List[str]:
    if not isinstance(values, (list, tuple)):
        raise RC8ContractError("%s_MUST_BE_LIST" % name.upper())
    out = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise RC8ContractError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        out.append(value.strip())
    return out


def _nonnegative(value: int, name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise RC8ContractError("%s_INVALID" % name.upper())
    return value


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    operator_ref: str
    os_family: str
    architecture: str
    shell: str
    registered_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _required(self.node_id, "node_id"))
        object.__setattr__(self, "operator_ref", _required(self.operator_ref, "operator_ref"))
        os_family = _required(self.os_family, "os_family").lower()
        shell = _required(self.shell, "shell").lower()
        object.__setattr__(self, "os_family", os_family)
        object.__setattr__(self, "architecture", _required(self.architecture, "architecture").lower())
        object.__setattr__(self, "shell", shell)
        if os_family not in {"windows", "linux"}:
            raise RC8ContractError("NODE_OS_FAMILY_UNSUPPORTED")
        if os_family == "windows" and shell not in {"git-bash", "gitbash"}:
            raise RC8ContractError("WINDOWS_NODE_REQUIRES_GIT_BASH")
        if os_family == "linux" and shell != "bash":
            raise RC8ContractError("LINUX_NODE_REQUIRES_BASH")


@dataclass(frozen=True)
class ProductionBatch:
    production_batch_id: str
    production_date: str
    batch_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "production_batch_id", _required(self.production_batch_id, "production_batch_id"))
        object.__setattr__(self, "production_date", _required(self.production_date, "production_date"))
        object.__setattr__(self, "batch_code", _required(self.batch_code, "batch_code"))
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", self.production_date):
            raise RC8ContractError("PRODUCTION_DATE_MUST_BE_ISO_DATE")


@dataclass(frozen=True)
class RequirementIdentity:
    requirement_id: str
    requirement_no: str
    title: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_id", _required(self.requirement_id, "requirement_id"))
        object.__setattr__(self, "requirement_no", _required(self.requirement_no, "requirement_no"))
        object.__setattr__(self, "title", _required(self.title, "title"))


@dataclass(frozen=True)
class RequirementDeliveryScope:
    delivery_scope_id: str
    production_batch_id: str
    requirement_id: str
    system_version_id: str
    application_id: str
    sst_id: str

    def __post_init__(self) -> None:
        for name in (
            "delivery_scope_id",
            "production_batch_id",
            "requirement_id",
            "system_version_id",
            "application_id",
            "sst_id",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))


@dataclass(frozen=True)
class TestRunIdentity:
    test_run_id: str
    production_batch_id: str
    scope_refs: List[str]
    created_by: str
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "test_run_id", _required(self.test_run_id, "test_run_id"))
        object.__setattr__(self, "production_batch_id", _required(self.production_batch_id, "production_batch_id"))
        object.__setattr__(self, "created_by", _required(self.created_by, "created_by"))
        object.__setattr__(self, "scope_refs", _strings(self.scope_refs, "scope_refs"))
        if not self.scope_refs:
            raise RC8ContractError("TEST_RUN_SCOPE_REQUIRED")


@dataclass(frozen=True)
class WorkItemIdentity:
    work_item_id: str
    test_run_id: str
    stage: str
    scope_refs: List[str]
    required_capabilities: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "work_item_id", _required(self.work_item_id, "work_item_id"))
        object.__setattr__(self, "test_run_id", _required(self.test_run_id, "test_run_id"))
        object.__setattr__(self, "stage", _required(self.stage, "stage"))
        object.__setattr__(self, "scope_refs", _strings(self.scope_refs, "scope_refs"))
        object.__setattr__(self, "required_capabilities", _strings(self.required_capabilities, "required_capabilities"))


@dataclass(frozen=True)
class PlanEventEnvelope:
    event_id: str
    test_run_id: str
    work_item_id: str
    event_type: str
    producer_ref: str
    data: Dict[str, object] = field(default_factory=dict)
    occurred_at: int = field(default_factory=_now)
    plane: EventPlane = EventPlane.PLAN

    def __post_init__(self) -> None:
        if self.plane != EventPlane.PLAN:
            raise RC8ContractError("PLAN_EVENT_PLANE_REQUIRED")
        for name in ("event_id", "test_run_id", "work_item_id", "event_type", "producer_ref"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.data, dict):
            raise RC8ContractError("EVENT_DATA_MUST_BE_OBJECT")


@dataclass(frozen=True)
class RuntimeEventEnvelope:
    event_id: str
    test_run_id: str
    work_item_id: str
    node_id: str
    producer_kind: RuntimeProducerKind
    producer_ref: str
    event_type: str
    sequence: int
    case_id: Optional[str] = None
    attempt_id: Optional[str] = None
    step_id: Optional[str] = None
    refs: List[str] = field(default_factory=list)
    data: Dict[str, object] = field(default_factory=dict)
    occurred_at: int = field(default_factory=_now)
    plane: EventPlane = EventPlane.RUNTIME

    def __post_init__(self) -> None:
        if self.plane != EventPlane.RUNTIME:
            raise RC8ContractError("RUNTIME_EVENT_PLANE_REQUIRED")
        for name in ("event_id", "test_run_id", "work_item_id", "node_id", "producer_ref", "event_type"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.producer_kind, RuntimeProducerKind):
            raise RC8ContractError("RUNTIME_PRODUCER_KIND_INVALID")
        _nonnegative(self.sequence, "sequence")
        object.__setattr__(self, "refs", _strings(self.refs, "refs"))
        if not isinstance(self.data, dict):
            raise RC8ContractError("EVENT_DATA_MUST_BE_OBJECT")
        for name in ("case_id", "attempt_id", "step_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise RC8ContractError("%s_INVALID" % name.upper())


@dataclass(frozen=True)
class EvidenceManifest:
    artifact_id: str
    test_run_id: str
    work_item_id: str
    node_id: str
    kind: str
    producer_kind: RuntimeProducerKind
    producer_ref: str
    content_ref: str
    sha256: str
    size_bytes: int
    availability: ArtifactAvailability
    source_tool: Optional[str] = None
    case_id: Optional[str] = None
    attempt_id: Optional[str] = None
    step_id: Optional[str] = None
    assertion_refs: List[str] = field(default_factory=list)
    runtime_event_refs: List[str] = field(default_factory=list)
    created_at: int = field(default_factory=_now)

    def __post_init__(self) -> None:
        for name in (
            "artifact_id", "test_run_id", "work_item_id", "node_id", "kind",
            "producer_ref", "content_ref", "sha256",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.producer_kind, RuntimeProducerKind):
            raise RC8ContractError("EVIDENCE_PRODUCER_KIND_INVALID")
        if not isinstance(self.availability, ArtifactAvailability):
            raise RC8ContractError("ARTIFACT_AVAILABILITY_INVALID")
        if not re.match(r"^[0-9a-fA-F]{64}$", self.sha256):
            raise RC8ContractError("EVIDENCE_SHA256_INVALID")
        _nonnegative(self.size_bytes, "size_bytes")
        object.__setattr__(self, "assertion_refs", _strings(self.assertion_refs, "assertion_refs"))
        object.__setattr__(self, "runtime_event_refs", _strings(self.runtime_event_refs, "runtime_event_refs"))
        if self.source_tool is not None:
            object.__setattr__(self, "source_tool", _required(self.source_tool, "source_tool"))
        for name in ("case_id", "attempt_id", "step_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise RC8ContractError("%s_INVALID" % name.upper())


@dataclass(frozen=True)
class CapabilityQualification:
    node_id: str
    capability_id: str
    state: CapabilityState
    probe_ref: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    verified_at: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _required(self.node_id, "node_id"))
        object.__setattr__(self, "capability_id", _required(self.capability_id, "capability_id"))
        if not isinstance(self.state, CapabilityState):
            raise RC8ContractError("CAPABILITY_STATE_INVALID")
        object.__setattr__(self, "evidence_refs", _strings(self.evidence_refs, "evidence_refs"))
        if self.probe_ref is not None:
            object.__setattr__(self, "probe_ref", _required(self.probe_ref, "probe_ref"))
        if self.state == CapabilityState.VERIFIED:
            if self.probe_ref is None:
                raise RC8ContractError("VERIFIED_CAPABILITY_REQUIRES_REAL_PROBE")
            if not self.evidence_refs:
                raise RC8ContractError("VERIFIED_CAPABILITY_REQUIRES_EVIDENCE")
            if not isinstance(self.verified_at, int) or self.verified_at < 0:
                raise RC8ContractError("VERIFIED_CAPABILITY_REQUIRES_TIME")


@dataclass(frozen=True)
class CompletionClaim:
    test_run_id: str
    plan_complete: bool
    test_sufficient: bool
    unresolved_required_gaps: int
    evaluator_ref: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "test_run_id", _required(self.test_run_id, "test_run_id"))
        _nonnegative(self.unresolved_required_gaps, "unresolved_required_gaps")
        object.__setattr__(self, "evidence_refs", _strings(self.evidence_refs, "evidence_refs"))
        if self.evaluator_ref is not None:
            object.__setattr__(self, "evaluator_ref", _required(self.evaluator_ref, "evaluator_ref"))
        if self.test_sufficient:
            if self.unresolved_required_gaps != 0:
                raise RC8ContractError("TEST_SUFFICIENT_REQUIRES_ZERO_REQUIRED_GAPS")
            if self.evaluator_ref is None or not self.evidence_refs:
                raise RC8ContractError("TEST_SUFFICIENT_REQUIRES_EVALUATION_EVIDENCE")


def transition_capability(current: CapabilityState, target: CapabilityState) -> CapabilityState:
    if not isinstance(current, CapabilityState) or not isinstance(target, CapabilityState):
        raise RC8ContractError("CAPABILITY_STATE_INVALID")
    allowed = _ALLOWED_CAPABILITY_TRANSITIONS[current]
    if target not in allowed:
        raise RC8ContractError("CAPABILITY_TRANSITION_FORBIDDEN:%s->%s" % (current.value, target.value))
    return target


def require_pass_evidence(assertion_ids: Sequence[str], evidence: Sequence[EvidenceManifest]) -> None:
    """Fail closed unless every assertion has AVAILABLE execution evidence."""
    assertions = set(_strings(assertion_ids, "assertion_ids"))
    if not assertions:
        raise RC8ContractError("PASS_REQUIRES_ASSERTIONS")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        raise RC8ContractError("PASS_REQUIRES_EVIDENCE")

    covered: Set[str] = set()
    for item in evidence:
        if not isinstance(item, EvidenceManifest):
            raise RC8ContractError("PASS_EVIDENCE_MANIFEST_REQUIRED")
        if item.availability != ArtifactAvailability.AVAILABLE:
            continue
        covered.update(set(item.assertion_refs).intersection(assertions))

    missing = sorted(assertions.difference(covered))
    if missing:
        raise RC8ContractError("PASS_ASSERTION_EVIDENCE_MISSING:%s" % ",".join(missing))
