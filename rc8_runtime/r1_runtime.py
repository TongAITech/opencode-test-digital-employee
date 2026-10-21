"""RC8 central R1 runtime ledger.

The ledger is deliberately small and transport-neutral. It is the durable
append-only runtime truth boundary used by the future Center writer service.
Plans are explicitly rejected. PostgreSQL/UI projections are downstream and
rebuildable; they are not allowed to manufacture execution truth.

This module remains Python 3.8 compatible for bank portability.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from .contracts import EventPlane, RC8ContractError, RuntimeEventEnvelope, RuntimeProducerKind


class R1TruthError(ValueError):
    pass


class R1ConflictError(R1TruthError):
    pass


def _runtime_payload(event: RuntimeEventEnvelope) -> Dict[str, object]:
    if not isinstance(event, RuntimeEventEnvelope):
        raise R1TruthError("RUNTIME_EVENT_ENVELOPE_REQUIRED")
    if event.plane != EventPlane.RUNTIME:
        raise R1TruthError("R1_RUNTIME_ONLY")
    payload = asdict(event)
    payload["plane"] = event.plane.value
    payload["producer_kind"] = event.producer_kind.value
    return payload


class CentralR1RuntimeLedger:
    """Append-only, idempotent runtime-event ledger with deterministic replay.

    W0 uses a JSONL implementation because RC7 already treats R1 JSONL as the
    canonical durable runtime truth. W1+ Center services may serialize writes
    through one service and maintain PostgreSQL projections, while this event
    contract remains authoritative.
    """

    def __init__(self, path: str) -> None:
        if not isinstance(path, str) or not path.strip():
            raise R1TruthError("R1_PATH_REQUIRED")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = threading.RLock()
        self._by_event_id: Dict[str, Dict[str, object]] = {}
        self._next_seq = 1
        self._reindex()

    def _reindex(self) -> None:
        last_seq = 0
        by_event_id: Dict[str, Dict[str, object]] = {}
        for raw in self.iter_raw():
            seq = raw.get("seq")
            if not isinstance(seq, int) or seq < 1:
                raise R1TruthError("R1_SEQUENCE_INVALID")
            if seq <= last_seq:
                raise R1TruthError("R1_SEQUENCE_NOT_MONOTONIC")
            last_seq = seq
            event = raw.get("event")
            if not isinstance(event, dict):
                raise R1TruthError("R1_EVENT_OBJECT_REQUIRED")
            if event.get("plane") != EventPlane.RUNTIME.value:
                raise R1TruthError("R1_CONTAINS_NON_RUNTIME_EVENT")
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise R1TruthError("R1_EVENT_ID_REQUIRED")
            previous = by_event_id.get(event_id)
            if previous is not None and previous != event:
                raise R1ConflictError("R1_EVENT_ID_CONFLICT:%s" % event_id)
            by_event_id[event_id] = event
        self._by_event_id = by_event_id
        self._next_seq = last_seq + 1

    def append_runtime(self, event: RuntimeEventEnvelope) -> Dict[str, object]:
        payload = _runtime_payload(event)
        with self._lock:
            previous = self._by_event_id.get(event.event_id)
            if previous is not None:
                if previous != payload:
                    raise R1ConflictError("R1_EVENT_ID_CONFLICT:%s" % event.event_id)
                return {
                    "status": "IDEMPOTENT_REPLAY",
                    "event_id": event.event_id,
                    "seq": self._sequence_for(event.event_id),
                }

            record: Dict[str, object] = {
                "seq": self._next_seq,
                "event": payload,
            }
            encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(encoded + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._by_event_id[event.event_id] = payload
            self._next_seq += 1
            return {
                "status": "PERSISTENCE_VERIFIED",
                "event_id": event.event_id,
                "seq": record["seq"],
            }

    def append_plan(self, _event: object) -> None:
        """Plans have a different store/plane and can never enter runtime truth."""
        raise R1TruthError("PLAN_EVENT_FORBIDDEN_IN_R1_RUNTIME")

    def _sequence_for(self, event_id: str) -> int:
        for raw in self.iter_raw():
            event = raw.get("event")
            if isinstance(event, dict) and event.get("event_id") == event_id:
                seq = raw.get("seq")
                if isinstance(seq, int):
                    return seq
        raise R1TruthError("R1_EVENT_SEQUENCE_NOT_FOUND")

    def iter_raw(self) -> Iterator[Dict[str, object]]:
        with self.path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except ValueError as exc:
                    raise R1TruthError("R1_INVALID_JSON_LINE_%s" % line_no) from exc
                if not isinstance(raw, dict):
                    raise R1TruthError("R1_RECORD_OBJECT_REQUIRED")
                yield raw

    def runtime_events(
        self,
        *,
        test_run_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        found: List[Dict[str, object]] = []
        for raw in self.iter_raw():
            event = raw["event"]
            if not isinstance(event, dict):
                continue
            if test_run_id is not None and event.get("test_run_id") != test_run_id:
                continue
            if work_item_id is not None and event.get("work_item_id") != work_item_id:
                continue
            if node_id is not None and event.get("node_id") != node_id:
                continue
            found.append(dict(event))
        return found

    def latest_node_sequence(self, *, test_run_id: str, node_id: str) -> int:
        latest = -1
        for event in self.runtime_events(test_run_id=test_run_id, node_id=node_id):
            value = event.get("sequence")
            if isinstance(value, int):
                latest = max(latest, value)
        return latest

    def assert_next_node_sequence(self, event: RuntimeEventEnvelope) -> None:
        latest = self.latest_node_sequence(test_run_id=event.test_run_id, node_id=event.node_id)
        if event.sequence <= latest and event.event_id not in self._by_event_id:
            raise R1TruthError("NODE_EVENT_SEQUENCE_STALE")


def runtime_event(
    *,
    event_id: str,
    test_run_id: str,
    work_item_id: str,
    node_id: str,
    producer_kind: RuntimeProducerKind,
    producer_ref: str,
    event_type: str,
    sequence: int,
    **kwargs: object
) -> RuntimeEventEnvelope:
    """Small constructor used by Node/Center adapters without session coupling."""
    return RuntimeEventEnvelope(
        event_id=event_id,
        test_run_id=test_run_id,
        work_item_id=work_item_id,
        node_id=node_id,
        producer_kind=producer_kind,
        producer_ref=producer_ref,
        event_type=event_type,
        sequence=sequence,
        case_id=kwargs.get("case_id") if isinstance(kwargs.get("case_id"), str) else None,
        attempt_id=kwargs.get("attempt_id") if isinstance(kwargs.get("attempt_id"), str) else None,
        step_id=kwargs.get("step_id") if isinstance(kwargs.get("step_id"), str) else None,
        refs=list(kwargs.get("refs") or []),
        data=dict(kwargs.get("data") or {}),
    )
