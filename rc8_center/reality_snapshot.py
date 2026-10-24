"""RC8 N1 immutable Reality Snapshot gate.

N1 freezes the execution reality for a mission/scope without introducing a
second capability registry. Only Center CapabilityQualification=VERIFIED with
probe/evidence/time can satisfy reality. Installed/configured/discovered state
never becomes executable truth by implication.

Downstream N2-N10 bind an immutable snapshot through MissionNodeRealityBinding;
the existing MissionNodeInstance contract remains backward compatible.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from rc8_runtime.contracts import CapabilityQualification, CapabilityState
from rc8_runtime.mission_nodes import MISSION_NODE_SEQUENCE, MissionNodeInstance, MissionNodeType

from .control_plane import CenterControlError, CenterRepository, NodeStatus


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CenterControlError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str], name: str) -> Tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise CenterControlError("%s_MUST_BE_LIST" % name.upper())
    result: List[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise CenterControlError("%s_MUST_CONTAIN_NONEMPTY_STRINGS" % name.upper())
        result.append(value.strip())
    return tuple(result)


def _downstream_nodes() -> Tuple[MissionNodeType, ...]:
    return tuple(value for value in MISSION_NODE_SEQUENCE if value != MissionNodeType.N1_REALITY_ENVIRONMENT_RECON)


@dataclass(frozen=True)
class RealityCapabilityRequirement:
    requirement_id: str
    capability_id: str
    execution_node_id: Optional[str] = None
    critical: bool = True
    affected_mission_nodes: Tuple[MissionNodeType, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_id", _required(self.requirement_id, "requirement_id"))
        object.__setattr__(self, "capability_id", _required(self.capability_id, "capability_id"))
        if self.execution_node_id is not None:
            object.__setattr__(self, "execution_node_id", _required(self.execution_node_id, "execution_node_id"))
        if not isinstance(self.critical, bool):
            raise CenterControlError("REALITY_REQUIREMENT_CRITICAL_INVALID")
        values = self.affected_mission_nodes
        if not isinstance(values, (list, tuple)):
            raise CenterControlError("REALITY_AFFECTED_MISSION_NODES_MUST_BE_LIST")
        if any(not isinstance(value, MissionNodeType) for value in values):
            raise CenterControlError("REALITY_AFFECTED_MISSION_NODE_INVALID")
        object.__setattr__(self, "affected_mission_nodes", tuple(values))


@dataclass(frozen=True)
class CapabilitySnapshot:
    requirement_id: str
    capability_id: str
    execution_node_id: str
    state: CapabilityState
    probe_ref: str
    evidence_refs: Tuple[str, ...]
    verified_at: int

    def __post_init__(self) -> None:
        for name in ("requirement_id", "capability_id", "execution_node_id", "probe_ref"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.state != CapabilityState.VERIFIED:
            raise CenterControlError("REALITY_CAPABILITY_SNAPSHOT_MUST_BE_VERIFIED")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise CenterControlError("REALITY_VERIFIED_CAPABILITY_REQUIRES_EVIDENCE")
        if not isinstance(self.verified_at, int) or self.verified_at < 0:
            raise CenterControlError("REALITY_VERIFIED_CAPABILITY_REQUIRES_TIME")


@dataclass(frozen=True)
class RealityBlocker:
    blocker_id: str
    requirement_id: str
    capability_id: str
    reason: str
    affected_mission_nodes: Tuple[MissionNodeType, ...]
    evidence_refs: Tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("blocker_id", "requirement_id", "capability_id", "reason"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not self.affected_mission_nodes or any(not isinstance(value, MissionNodeType) for value in self.affected_mission_nodes):
            raise CenterControlError("REALITY_BLOCKER_REQUIRES_AFFECTED_MISSION_NODES")
        object.__setattr__(self, "affected_mission_nodes", tuple(self.affected_mission_nodes))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "evidence_refs"))
        if not self.evidence_refs:
            raise CenterControlError("REALITY_BLOCKER_REQUIRES_EVIDENCE")


@dataclass(frozen=True)
class RealitySnapshot:
    snapshot_id: str
    test_run_id: str
    scope_version: str
    snapshot_version: int
    source_revision: str
    environment_refs: Tuple[str, ...]
    capabilities: Tuple[CapabilitySnapshot, ...]
    blockers: Tuple[RealityBlocker, ...]
    fingerprint: str
    created_at: int

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "test_run_id", "scope_version", "source_revision", "fingerprint"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.snapshot_version, int) or self.snapshot_version < 1:
            raise CenterControlError("REALITY_SNAPSHOT_VERSION_INVALID")
        if not isinstance(self.created_at, int) or self.created_at < 0:
            raise CenterControlError("REALITY_SNAPSHOT_CREATED_AT_INVALID")
        object.__setattr__(self, "environment_refs", _refs(self.environment_refs, "environment_refs"))
        if not self.environment_refs:
            raise CenterControlError("REALITY_ENVIRONMENT_EVIDENCE_REQUIRED")
        if any(not isinstance(value, CapabilitySnapshot) for value in self.capabilities):
            raise CenterControlError("REALITY_CAPABILITY_SNAPSHOT_INVALID")
        if any(not isinstance(value, RealityBlocker) for value in self.blockers):
            raise CenterControlError("REALITY_BLOCKER_INVALID")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "blockers", tuple(self.blockers))

    @property
    def ready(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class MissionNodeRealityBinding:
    binding_id: str
    test_run_id: str
    mission_node_id: str
    mission_node_type: MissionNodeType
    reality_snapshot_id: str
    reality_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("binding_id", "test_run_id", "mission_node_id", "reality_snapshot_id", "reality_fingerprint"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.mission_node_type, MissionNodeType):
            raise CenterControlError("MISSION_NODE_TYPE_INVALID")
        if self.mission_node_type == MissionNodeType.N1_REALITY_ENVIRONMENT_RECON:
            raise CenterControlError("N1_PRODUCES_REALITY_SNAPSHOT_NOT_BINDS_IT")


@dataclass(frozen=True)
class RealityChangeSet:
    previous_snapshot_id: str
    current_snapshot_id: str
    material: bool
    changed_requirement_ids: Tuple[str, ...]
    invalidate_mission_nodes: Tuple[MissionNodeType, ...]


class RealitySnapshotRepository(Protocol):
    def get_reality_snapshot(self, snapshot_id: str) -> Optional[RealitySnapshot]: ...
    def latest_reality_snapshot(self, test_run_id: str, scope_version: str) -> Optional[RealitySnapshot]: ...
    def save_reality_snapshot(self, snapshot: RealitySnapshot) -> None: ...


class MemoryRealitySnapshotRepository:
    """Unit-test adapter only; a durable adapter is required for production."""

    def __init__(self) -> None:
        self._items: Dict[str, RealitySnapshot] = {}

    def get_reality_snapshot(self, snapshot_id: str) -> Optional[RealitySnapshot]:
        return self._items.get(snapshot_id)

    def latest_reality_snapshot(self, test_run_id: str, scope_version: str) -> Optional[RealitySnapshot]:
        items = [value for value in self._items.values() if value.test_run_id == test_run_id and value.scope_version == scope_version]
        return sorted(items, key=lambda value: value.snapshot_version)[-1] if items else None

    def save_reality_snapshot(self, snapshot: RealitySnapshot) -> None:
        current = self._items.get(snapshot.snapshot_id)
        if current is not None and current != snapshot:
            raise CenterControlError("REALITY_SNAPSHOT_ID_CONFLICT")
        self._items[snapshot.snapshot_id] = snapshot


class CenterRealitySnapshotService:
    """Capture immutable N1 truth from existing Center capability evidence."""

    def __init__(self, center_repository: CenterRepository, snapshot_repository: RealitySnapshotRepository, *, now_fn=None) -> None:
        self.center_repository = center_repository
        self.snapshot_repository = snapshot_repository
        self._now = now_fn or (lambda: int(time.time()))

    def capture(
        self,
        *,
        test_run_id: str,
        scope_version: str,
        source_revision: str,
        requirements: Sequence[RealityCapabilityRequirement],
        environment_refs: Sequence[str],
    ) -> RealitySnapshot:
        test_run_id = _required(test_run_id, "test_run_id")
        scope_version = _required(scope_version, "scope_version")
        source_revision = _required(source_revision, "source_revision")
        environment_refs = _refs(environment_refs, "environment_refs")
        if not environment_refs:
            raise CenterControlError("REALITY_ENVIRONMENT_EVIDENCE_REQUIRED")
        if not isinstance(requirements, (list, tuple)) or not requirements:
            raise CenterControlError("REALITY_CAPABILITY_REQUIREMENTS_REQUIRED")
        if any(not isinstance(value, RealityCapabilityRequirement) for value in requirements):
            raise CenterControlError("REALITY_CAPABILITY_REQUIREMENT_INVALID")
        ids = [value.requirement_id for value in requirements]
        if len(ids) != len(set(ids)):
            raise CenterControlError("REALITY_REQUIREMENT_ID_DUPLICATE")

        capabilities: List[CapabilitySnapshot] = []
        blockers: List[RealityBlocker] = []
        for requirement in requirements:
            value = self._resolve(requirement)
            affected = requirement.affected_mission_nodes or _downstream_nodes()
            if value is None:
                if requirement.critical:
                    blockers.append(
                        RealityBlocker(
                            blocker_id="blocker:%s" % requirement.requirement_id,
                            requirement_id=requirement.requirement_id,
                            capability_id=requirement.capability_id,
                            reason="CAPABILITY_NOT_VERIFIED",
                            affected_mission_nodes=affected,
                            evidence_refs=("center://capability/%s/not-verified" % requirement.requirement_id,),
                        )
                    )
                continue
            capabilities.append(
                CapabilitySnapshot(
                    requirement_id=requirement.requirement_id,
                    capability_id=requirement.capability_id,
                    execution_node_id=value.node_id,
                    state=value.state,
                    probe_ref=value.probe_ref or "",
                    evidence_refs=tuple(value.evidence_refs),
                    verified_at=value.verified_at if value.verified_at is not None else -1,
                )
            )

        previous = self.snapshot_repository.latest_reality_snapshot(test_run_id, scope_version)
        version = 1 if previous is None else previous.snapshot_version + 1
        fingerprint = self._fingerprint(source_revision, environment_refs, capabilities, blockers)
        snapshot = RealitySnapshot(
            snapshot_id="reality:%s:%s:v%s" % (test_run_id, scope_version, version),
            test_run_id=test_run_id,
            scope_version=scope_version,
            snapshot_version=version,
            source_revision=source_revision,
            environment_refs=environment_refs,
            capabilities=tuple(sorted(capabilities, key=lambda value: value.requirement_id)),
            blockers=tuple(sorted(blockers, key=lambda value: value.requirement_id)),
            fingerprint=fingerprint,
            created_at=self._now(),
        )
        self.snapshot_repository.save_reality_snapshot(snapshot)
        return snapshot

    def bind_downstream(self, node: MissionNodeInstance, snapshot: RealitySnapshot) -> MissionNodeRealityBinding:
        if not isinstance(node, MissionNodeInstance) or not isinstance(snapshot, RealitySnapshot):
            raise CenterControlError("MISSION_NODE_AND_REALITY_SNAPSHOT_REQUIRED")
        if node.node_type == MissionNodeType.N1_REALITY_ENVIRONMENT_RECON:
            raise CenterControlError("N1_PRODUCES_REALITY_SNAPSHOT_NOT_BINDS_IT")
        if node.test_run_id != snapshot.test_run_id or node.scope_version != snapshot.scope_version:
            raise CenterControlError("REALITY_SNAPSHOT_SCOPE_MISMATCH")
        if not snapshot.ready:
            raise CenterControlError("REALITY_SNAPSHOT_BLOCKED")
        return MissionNodeRealityBinding(
            binding_id="reality-binding:%s:%s" % (node.mission_node_id, snapshot.snapshot_id),
            test_run_id=node.test_run_id,
            mission_node_id=node.mission_node_id,
            mission_node_type=node.node_type,
            reality_snapshot_id=snapshot.snapshot_id,
            reality_fingerprint=snapshot.fingerprint,
        )

    def compare(self, previous: RealitySnapshot, current: RealitySnapshot) -> RealityChangeSet:
        if not isinstance(previous, RealitySnapshot) or not isinstance(current, RealitySnapshot):
            raise CenterControlError("REALITY_SNAPSHOT_REQUIRED")
        if previous.test_run_id != current.test_run_id or previous.scope_version != current.scope_version:
            raise CenterControlError("REALITY_COMPARE_SCOPE_MISMATCH")
        before = self._facts(previous)
        after = self._facts(current)
        changed = tuple(sorted(key for key in set(before).union(after) if before.get(key) != after.get(key)))
        material = bool(changed or previous.source_revision != current.source_revision or previous.environment_refs != current.environment_refs)
        return RealityChangeSet(
            previous_snapshot_id=previous.snapshot_id,
            current_snapshot_id=current.snapshot_id,
            material=material,
            changed_requirement_ids=changed,
            invalidate_mission_nodes=_downstream_nodes() if material else tuple(),
        )

    def _resolve(self, requirement: RealityCapabilityRequirement) -> Optional[CapabilityQualification]:
        if requirement.execution_node_id is not None:
            node = self.center_repository.get_node(requirement.execution_node_id)
            if node is None or node.status in {NodeStatus.MAINTENANCE, NodeStatus.OFFLINE, NodeStatus.ERROR}:
                return None
            return self._verified(self.center_repository.get_capability(requirement.execution_node_id, requirement.capability_id))
        candidates: List[CapabilityQualification] = []
        for node in self.center_repository.list_nodes():
            if node.status in {NodeStatus.MAINTENANCE, NodeStatus.OFFLINE, NodeStatus.ERROR}:
                continue
            value = self._verified(self.center_repository.get_capability(node.identity.node_id, requirement.capability_id))
            if value is not None:
                candidates.append(value)
        candidates.sort(key=lambda value: (-(value.verified_at or 0), value.node_id))
        return candidates[0] if candidates else None

    @staticmethod
    def _verified(value: Optional[CapabilityQualification]) -> Optional[CapabilityQualification]:
        if value is None or value.state != CapabilityState.VERIFIED:
            return None
        if value.probe_ref is None or not value.evidence_refs or value.verified_at is None:
            return None
        return value

    @staticmethod
    def _facts(snapshot: RealitySnapshot) -> Dict[str, object]:
        result: Dict[str, object] = {}
        for value in snapshot.capabilities:
            result[value.requirement_id] = (value.capability_id, value.execution_node_id, value.probe_ref, value.evidence_refs, value.verified_at)
        for value in snapshot.blockers:
            result[value.requirement_id] = (value.capability_id, "BLOCKED", value.reason, value.evidence_refs)
        return result

    @staticmethod
    def _fingerprint(source_revision: str, environment_refs: Tuple[str, ...], capabilities: Sequence[CapabilitySnapshot], blockers: Sequence[RealityBlocker]) -> str:
        payload = {
            "source_revision": source_revision,
            "environment_refs": list(environment_refs),
            "capabilities": [
                [value.requirement_id, value.capability_id, value.execution_node_id, value.probe_ref, list(value.evidence_refs), value.verified_at]
                for value in sorted(capabilities, key=lambda item: item.requirement_id)
            ],
            "blockers": [
                [value.requirement_id, value.capability_id, value.reason, list(value.evidence_refs)]
                for value in sorted(blockers, key=lambda item: item.requirement_id)
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
