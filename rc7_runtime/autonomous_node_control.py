"""Durable R1 control for RC7.1 autonomous node iterations and deliveries.

Node-local loops must survive process/session restart.  This module never creates
an in-memory shadow truth: iteration lineage, gaps, repair deltas and delivery
receipts are reconstructed from canonical rc7_control_event plus immutable
Artifact/Evidence records in the R1 Event Stream.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .autonomous_contract import NodeDeliveryPackage, NodeLoopState, require_node
from .autonomous_events import AutonomousEvent, require_autonomous_event
from .models import Artifact, EventRecord, Evidence
from .truth_overlay import append_entity


class AutonomousNodeControlError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: str, code: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise AutonomousNodeControlError(code)
    return value


@dataclass(frozen=True)
class NodeIterationSnapshot:
    mission_id: str
    run_id: str
    node_id: str
    iteration_count: int
    input_version: str
    state: str
    delta_hash: str
    start_event_id: str
    previous_iteration_event_id: str = ""


@dataclass(frozen=True)
class NodeDeliveryReceipt:
    mission_id: str
    run_id: str
    node_id: str
    iteration_count: int
    package_artifact_id: str
    package_evidence_id: str
    ready_event_id: str
    package_sha256: str


class AutonomousNodeControl:
    """R1-backed autonomous-loop lifecycle controller.

    The controller is disposable. A newly constructed instance reconstructs
    current iteration state from R1, proving restart does not reset the loop.
    """

    SUBJECT_TYPE = "AUTONOMOUS_NODE"
    PACKAGE_TYPE = "NODE_DELIVERY_PACKAGE"

    def __init__(self, truth: TruthRuntime, *, release_id: str, evidence_root: str) -> None:
        self.truth = truth
        self.release_id = _required(release_id, "RELEASE_ID_REQUIRED")
        self.evidence_root = Path(evidence_root).expanduser().resolve()

    @staticmethod
    def _subject_id(run_id: str, node_id: str) -> str:
        return "%s:%s" % (run_id, node_id)

    def _events(self, mission_id: str, run_id: str, node_id: str) -> Tuple[Mapping[str, Any], ...]:
        subject_id = self._subject_id(run_id, node_id)
        rows = [
            row for row in self.truth.query("rc7_control_event", mission_id=mission_id)
            if row.get("subject_type") == self.SUBJECT_TYPE
            and row.get("subject_id") == subject_id
            and isinstance(row.get("data"), dict)
            and row["data"].get("run_id") == run_id
            and row["data"].get("node_id") == node_id
        ]
        return tuple(rows)

    def latest_iteration(self, *, mission_id: str, run_id: str, node_id: str) -> Optional[NodeIterationSnapshot]:
        mission_id = _required(mission_id, "MISSION_ID_REQUIRED")
        run_id = _required(run_id, "RUN_ID_REQUIRED")
        node_id = require_node(node_id).value
        started = [
            row for row in self._events(mission_id, run_id, node_id)
            if row.get("event_type_name") == AutonomousEvent.NODE_ITERATION_STARTED.value
        ]
        if not started:
            return None
        by_iteration: Dict[int, Mapping[str, Any]] = {}
        for row in started:
            data = row["data"]
            iteration = data.get("iteration_count")
            if not isinstance(iteration, int) or iteration < 1:
                raise AutonomousNodeControlError("DURABLE_NODE_ITERATION_INVALID")
            if iteration in by_iteration:
                raise AutonomousNodeControlError("DURABLE_NODE_ITERATION_DUPLICATE:%d" % iteration)
            by_iteration[iteration] = row
        expected = tuple(range(1, max(by_iteration) + 1))
        if tuple(sorted(by_iteration)) != expected:
            raise AutonomousNodeControlError("DURABLE_NODE_ITERATION_SEQUENCE_GAP")
        row = by_iteration[max(by_iteration)]
        data = row["data"]
        return NodeIterationSnapshot(
            mission_id=mission_id,
            run_id=run_id,
            node_id=node_id,
            iteration_count=int(data["iteration_count"]),
            input_version=str(data.get("input_version") or ""),
            state=str(data.get("state") or NodeLoopState.IN_PROGRESS.value),
            delta_hash=str(data.get("delta_hash") or ""),
            start_event_id=str(row.get("event_id") or ""),
            previous_iteration_event_id=str(data.get("previous_iteration_event_id") or ""),
        )

    def start_iteration(
        self,
        *,
        mission_id: str,
        run_id: str,
        node_id: str,
        input_version: str,
        delta_hash: str,
    ) -> NodeIterationSnapshot:
        mission_id = _required(mission_id, "MISSION_ID_REQUIRED")
        run_id = _required(run_id, "RUN_ID_REQUIRED")
        node_id = require_node(node_id).value
        input_version = _required(input_version, "NODE_INPUT_VERSION_REQUIRED")
        delta_hash = _required(delta_hash, "NODE_ITERATION_DELTA_HASH_REQUIRED")

        prior = self.latest_iteration(mission_id=mission_id, run_id=run_id, node_id=node_id)
        iteration = 1 if prior is None else prior.iteration_count + 1
        previous_event_id = "" if prior is None else prior.start_event_id
        if prior is not None:
            if prior.input_version != input_version:
                # A new input snapshot is a legitimate delta, but it must still
                # have a distinct digest and preserve lineage.
                pass
            if prior.delta_hash == delta_hash:
                raise AutonomousNodeControlError("ITERATION_MUST_PRODUCE_DELTA")
            previous_events = [
                row for row in self._events(mission_id, run_id, node_id)
                if row.get("data", {}).get("iteration_count") == prior.iteration_count
            ]
            repairable = {
                AutonomousEvent.NODE_GAP_DETECTED.value,
                AutonomousEvent.NODE_REPAIR_COMPLETED.value,
                AutonomousEvent.DIRECTOR_NODE_REJECTED.value,
            }
            if not any(row.get("event_type_name") in repairable for row in previous_events):
                raise AutonomousNodeControlError("NEXT_ITERATION_REQUIRES_DURABLE_REPAIR_OR_REJECTION")

        event_id = _stable_id(
            "EVT-NODE-ITER",
            mission_id,
            run_id,
            node_id,
            iteration,
            input_version,
            delta_hash,
        )
        event = EventRecord(
            event_id=event_id,
            mission_id=mission_id,
            event_type=AutonomousEvent.NODE_ITERATION_STARTED.value,
            subject_type=self.SUBJECT_TYPE,
            subject_id=self._subject_id(run_id, node_id),
            refs=[previous_event_id] if previous_event_id else [],
            data={
                "run_id": run_id,
                "node_id": node_id,
                "iteration_count": iteration,
                "input_version": input_version,
                "state": NodeLoopState.IN_PROGRESS.value,
                "delta_hash": delta_hash,
                "previous_iteration_event_id": previous_event_id,
            },
        )
        append_entity(self.truth, event, release_id=self.release_id, artifact_version=iteration)
        return NodeIterationSnapshot(
            mission_id=mission_id,
            run_id=run_id,
            node_id=node_id,
            iteration_count=iteration,
            input_version=input_version,
            state=NodeLoopState.IN_PROGRESS.value,
            delta_hash=delta_hash,
            start_event_id=event_id,
            previous_iteration_event_id=previous_event_id,
        )

    def record_gap_detected(
        self,
        snapshot: NodeIterationSnapshot,
        *,
        gap_ids: Sequence[str],
        evidence_refs: Sequence[str],
    ) -> str:
        gaps = tuple(dict.fromkeys(_required(value, "NODE_GAP_ID_REQUIRED") for value in gap_ids))
        evidence = tuple(dict.fromkeys(_required(value, "NODE_GAP_EVIDENCE_REF_REQUIRED") for value in evidence_refs))
        if not gaps:
            raise AutonomousNodeControlError("NODE_GAP_REQUIRED")
        if not evidence:
            raise AutonomousNodeControlError("NODE_GAP_EVIDENCE_REQUIRED")
        for gap_id in gaps:
            rows = self.truth.query("rc7_gap", gap_id=gap_id)
            if len(rows) != 1 or rows[0].get("mission_id") != snapshot.mission_id:
                raise AutonomousNodeControlError("NODE_GAP_NOT_DURABLE:%s" % gap_id)
        event_id = _stable_id("EVT-NODE-GAP", snapshot.start_event_id, *gaps)
        event = EventRecord(
            event_id=event_id,
            mission_id=snapshot.mission_id,
            event_type=AutonomousEvent.NODE_GAP_DETECTED.value,
            subject_type=self.SUBJECT_TYPE,
            subject_id=self._subject_id(snapshot.run_id, snapshot.node_id),
            refs=list(gaps) + list(evidence) + [snapshot.start_event_id],
            data={
                "run_id": snapshot.run_id,
                "node_id": snapshot.node_id,
                "iteration_count": snapshot.iteration_count,
                "gap_ids": list(gaps),
                "evidence_refs": list(evidence),
                "state": NodeLoopState.GAP_DETECTED.value,
            },
        )
        append_entity(self.truth, event, release_id=self.release_id, artifact_version=snapshot.iteration_count)
        return event_id

    def record_repair_completed(
        self,
        snapshot: NodeIterationSnapshot,
        *,
        repair_refs: Sequence[str],
        delta_hash: str,
    ) -> str:
        refs = tuple(dict.fromkeys(_required(value, "NODE_REPAIR_REF_REQUIRED") for value in repair_refs))
        if not refs:
            raise AutonomousNodeControlError("NODE_REPAIR_REF_REQUIRED")
        delta_hash = _required(delta_hash, "NODE_REPAIR_DELTA_HASH_REQUIRED")
        if delta_hash == snapshot.delta_hash:
            raise AutonomousNodeControlError("REPAIR_MUST_PRODUCE_DELTA")
        event_id = _stable_id("EVT-NODE-REPAIR", snapshot.start_event_id, delta_hash, *refs)
        event = EventRecord(
            event_id=event_id,
            mission_id=snapshot.mission_id,
            event_type=AutonomousEvent.NODE_REPAIR_COMPLETED.value,
            subject_type=self.SUBJECT_TYPE,
            subject_id=self._subject_id(snapshot.run_id, snapshot.node_id),
            refs=list(refs) + [snapshot.start_event_id],
            data={
                "run_id": snapshot.run_id,
                "node_id": snapshot.node_id,
                "iteration_count": snapshot.iteration_count,
                "delta_hash": delta_hash,
                "state": NodeLoopState.REPAIRING.value,
            },
        )
        append_entity(self.truth, event, release_id=self.release_id, artifact_version=snapshot.iteration_count)
        return event_id

    def ready_for_director_review(
        self,
        snapshot: NodeIterationSnapshot,
        package: NodeDeliveryPackage,
        *,
        producer_task_id: str,
    ) -> NodeDeliveryReceipt:
        producer_task_id = _required(producer_task_id, "NODE_DELIVERY_PRODUCER_TASK_REQUIRED")
        if package.mission_id != snapshot.mission_id or package.run_id != snapshot.run_id or package.node_id != snapshot.node_id:
            raise AutonomousNodeControlError("NODE_DELIVERY_IDENTITY_MISMATCH")
        if package.input_version != snapshot.input_version or package.iteration_count != snapshot.iteration_count:
            raise AutonomousNodeControlError("NODE_DELIVERY_ITERATION_MISMATCH")
        if package.terminal_status != NodeLoopState.READY_FOR_DIRECTOR_REVIEW.value:
            raise AutonomousNodeControlError("NODE_DELIVERY_MUST_BE_READY_FOR_DIRECTOR_REVIEW")
        self._require_current_refs(snapshot.mission_id, package)

        payload = asdict(package)
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        folder = self.evidence_root / "node-delivery" / snapshot.mission_id / snapshot.run_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("%s-iteration-%d-%s.json" % (snapshot.node_id.lower(), snapshot.iteration_count, digest[:20]))
        if path.exists() and path.read_bytes() != encoded:
            raise AutonomousNodeControlError("NODE_DELIVERY_IMMUTABILITY_VIOLATION")
        if not path.exists():
            path.write_bytes(encoded)

        artifact_id = _stable_id("ART-NODE-DELIVERY", snapshot.mission_id, snapshot.run_id, snapshot.node_id, snapshot.iteration_count, digest)
        evidence_id = _stable_id("EVD-NODE-DELIVERY", snapshot.mission_id, snapshot.run_id, snapshot.node_id, snapshot.iteration_count, digest)
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=snapshot.mission_id,
            kind=self.PACKAGE_TYPE,
            source_ref="runtime://autonomous-node-control",
            content_ref="file://" + str(path),
            subject_refs=[artifact_id, producer_task_id, snapshot.start_event_id],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=snapshot.mission_id,
            artifact_type=self.PACKAGE_TYPE,
            producer_task_id=producer_task_id,
            content_ref="file://" + str(path),
            parent_refs=list(package.artifact_refs),
            evidence_refs=[evidence_id] + list(package.evidence_refs),
            content_hash="sha256:" + digest,
        )
        if not self.truth.query("rc7_evidence", evidence_id=evidence_id):
            append_entity(self.truth, evidence, release_id=self.release_id, artifact_version=snapshot.iteration_count)
        if not self.truth.query("rc7_artifact", artifact_id=artifact_id):
            append_entity(self.truth, artifact, release_id=self.release_id, artifact_version=snapshot.iteration_count)

        ready_event_id = _stable_id("EVT-NODE-READY", artifact_id, evidence_id)
        event = EventRecord(
            event_id=ready_event_id,
            mission_id=snapshot.mission_id,
            event_type=AutonomousEvent.NODE_READY_FOR_DIRECTOR_REVIEW.value,
            subject_type=self.SUBJECT_TYPE,
            subject_id=self._subject_id(snapshot.run_id, snapshot.node_id),
            refs=[snapshot.start_event_id, artifact_id, evidence_id] + list(package.r1_refs),
            data={
                "run_id": snapshot.run_id,
                "node_id": snapshot.node_id,
                "iteration_count": snapshot.iteration_count,
                "input_version": snapshot.input_version,
                "package_artifact_id": artifact_id,
                "package_evidence_id": evidence_id,
                "package_sha256": digest,
                "state": NodeLoopState.READY_FOR_DIRECTOR_REVIEW.value,
            },
        )
        if not self.truth.query("rc7_control_event", event_id=ready_event_id):
            append_entity(self.truth, event, release_id=self.release_id, artifact_version=snapshot.iteration_count)
        return NodeDeliveryReceipt(
            mission_id=snapshot.mission_id,
            run_id=snapshot.run_id,
            node_id=snapshot.node_id,
            iteration_count=snapshot.iteration_count,
            package_artifact_id=artifact_id,
            package_evidence_id=evidence_id,
            ready_event_id=ready_event_id,
            package_sha256=digest,
        )

    def _require_current_refs(self, mission_id: str, package: NodeDeliveryPackage) -> None:
        for artifact_id in package.artifact_refs:
            rows = self.truth.query("rc7_artifact", artifact_id=artifact_id)
            if len(rows) != 1 or rows[0].get("mission_id") != mission_id or rows[0].get("state") != "VALID":
                raise AutonomousNodeControlError("NODE_DELIVERY_ARTIFACT_NOT_CURRENT:%s" % artifact_id)
        for evidence_id in package.evidence_refs:
            rows = self.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1 or rows[0].get("mission_id") != mission_id:
                raise AutonomousNodeControlError("NODE_DELIVERY_EVIDENCE_NOT_CURRENT:%s" % evidence_id)
        for gap_id in package.unresolved_gap_ids:
            rows = self.truth.query("rc7_gap", gap_id=gap_id)
            if len(rows) != 1 or rows[0].get("mission_id") != mission_id or rows[0].get("state") in {"RESOLVED", "WAIVED", "DUPLICATE", "SUPERSEDED"}:
                raise AutonomousNodeControlError("NODE_DELIVERY_GAP_NOT_OPEN:%s" % gap_id)

    def latest_delivery(self, *, mission_id: str, run_id: str, node_id: str) -> Optional[NodeDeliveryReceipt]:
        mission_id = _required(mission_id, "MISSION_ID_REQUIRED")
        run_id = _required(run_id, "RUN_ID_REQUIRED")
        node_id = require_node(node_id).value
        rows = [
            row for row in self._events(mission_id, run_id, node_id)
            if row.get("event_type_name") == AutonomousEvent.NODE_READY_FOR_DIRECTOR_REVIEW.value
        ]
        if not rows:
            return None
        rows.sort(key=lambda row: int(row.get("data", {}).get("iteration_count") or 0))
        row = rows[-1]
        data = row["data"]
        return NodeDeliveryReceipt(
            mission_id=mission_id,
            run_id=run_id,
            node_id=node_id,
            iteration_count=int(data["iteration_count"]),
            package_artifact_id=str(data["package_artifact_id"]),
            package_evidence_id=str(data["package_evidence_id"]),
            ready_event_id=str(row["event_id"]),
            package_sha256=str(data["package_sha256"]),
        )
