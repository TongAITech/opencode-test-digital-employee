"""RC6 Wave 2 durable truth, replay and query layer.

R1 JSONL is the sole durable truth. Projection is derived and disposable.
Live writes are atomic domain events. RC5 legacy batch payloads are accepted
only during replay and are deterministically expanded without emitting repair
events.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .contracts import DomainValidationError, validate_artifact


class EventValidationError(ValueError):
    pass


class ProjectionIntegrityError(RuntimeError):
    pass


EVENT_TYPES = {
    "TEST_INTENT_UPSERTED": ("test_intent", "id"),
    "TEST_CONDITION_UPSERTED": ("test_condition", "id"),
    "TEST_CASE_UPSERTED": ("test_case", "tc_id"),
}

LEGACY_BATCH_FIELDS = {
    "intents": ("TEST_INTENT_UPSERTED", "test_intent"),
    "conditions": ("TEST_CONDITION_UPSERTED", "test_condition"),
    "cases": ("TEST_CASE_UPSERTED", "test_case"),
}


@dataclass(frozen=True)
class PersistenceReceipt:
    status: str
    event_id: str
    seq: int
    entity_type: str
    entity_id: str
    entity_version: int
    requested_count: int
    persisted_count: int
    queryable_count: int


def _version_for(artifact_type: str, payload: Dict[str, Any]) -> int:
    if artifact_type == "test_case":
        return int(payload["case_version"])
    return int(payload.get("artifact_version", 1))


def _canonical_payload(event_type: str, payload: Dict[str, Any]) -> Tuple[str, str, int, Dict[str, Any]]:
    if event_type not in EVENT_TYPES:
        raise EventValidationError("UNSUPPORTED_EVENT_TYPE")
    artifact_type, identity_field = EVENT_TYPES[event_type]
    try:
        canonical = validate_artifact(artifact_type, payload)
    except DomainValidationError as exc:
        raise EventValidationError(str(exc)) from exc
    entity_id = str(canonical[identity_field])
    return artifact_type, entity_id, _version_for(artifact_type, canonical), canonical


class JsonlEventStore:
    """Append-only JSONL store with monotonic sequence numbers."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = threading.RLock()
        self._next_seq = self._scan_next_seq()

    def _scan_next_seq(self) -> int:
        last = 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                raw = json.loads(line)
                seq = raw.get("seq")
                if isinstance(seq, int):
                    last = max(last, seq)
        return last + 1

    def append(self, event_type: str, payload: Dict[str, Any], *, event_id: Optional[str] = None) -> Dict[str, Any]:
        artifact_type, entity_id, entity_version, canonical = _canonical_payload(event_type, payload)
        with self._lock:
            event = {
                "seq": self._next_seq,
                "event_id": event_id or str(uuid.uuid4()),
                "event_type": event_type,
                "entity_type": artifact_type,
                "entity_id": entity_id,
                "entity_version": entity_version,
                "payload": canonical,
            }
            encoded = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(encoded + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._next_seq += 1
            return deepcopy(event)

    def iter_raw(self) -> Iterator[Dict[str, Any]]:
        with self.path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EventValidationError(f"INVALID_JSON_EVENT_LINE_{line_no}") from exc
                if not isinstance(raw, dict):
                    raise EventValidationError(f"INVALID_EVENT_OBJECT_LINE_{line_no}")
                yield raw


class Projection:
    """Disposable deterministic projection built exclusively from R1 events."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.intents: Dict[str, Dict[str, Any]] = {}
        self.conditions: Dict[str, Dict[str, Any]] = {}
        self.cases: Dict[str, Dict[str, Any]] = {}
        self._versions: Dict[str, Dict[str, Dict[str, Any]]] = {
            "test_intent": {},
            "test_condition": {},
            "test_case": {},
        }

    @staticmethod
    def _bucket_name(artifact_type: str) -> str:
        return {
            "test_intent": "intents",
            "test_condition": "conditions",
            "test_case": "cases",
        }[artifact_type]

    @staticmethod
    def _identity_field(artifact_type: str) -> str:
        return "tc_id" if artifact_type == "test_case" else "id"

    def apply_atomic(self, event: Dict[str, Any]) -> None:
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise ProjectionIntegrityError("EVENT_PAYLOAD_NOT_OBJECT")
        try:
            artifact_type, entity_id, version, canonical = _canonical_payload(str(event_type), payload)
        except EventValidationError as exc:
            raise ProjectionIntegrityError(str(exc)) from exc

        version_key = f"{entity_id}@{version}"
        version_bucket = self._versions[artifact_type]
        previous = version_bucket.get(version_key)
        if previous is not None:
            if previous != canonical:
                raise ProjectionIntegrityError("CONFLICTING_SAME_ENTITY_VERSION")
            return
        version_bucket[version_key] = deepcopy(canonical)

        bucket = getattr(self, self._bucket_name(artifact_type))
        current = bucket.get(entity_id)
        if current is None or _version_for(artifact_type, canonical) > _version_for(artifact_type, current):
            bucket[entity_id] = deepcopy(canonical)
        elif _version_for(artifact_type, canonical) == _version_for(artifact_type, current) and current != canonical:
            raise ProjectionIntegrityError("CONFLICTING_LATEST_ENTITY_VERSION")

    def history(self, artifact_type: str, entity_id: str) -> List[Dict[str, Any]]:
        prefix = entity_id + "@"
        found = [v for k, v in self._versions[artifact_type].items() if k.startswith(prefix)]
        return sorted(found, key=lambda x: _version_for(artifact_type, x))

    def get(self, artifact_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
        bucket = getattr(self, self._bucket_name(artifact_type))
        value = bucket.get(entity_id)
        return deepcopy(value) if value is not None else None

    def query(self, artifact_type: str, **filters: Any) -> List[Dict[str, Any]]:
        bucket = getattr(self, self._bucket_name(artifact_type))
        rows = []
        for entity_id in sorted(bucket):
            item = bucket[entity_id]
            if all(item.get(k) == v for k, v in filters.items() if v is not None):
                rows.append(deepcopy(item))
        return rows

    def snapshot(self) -> Dict[str, Any]:
        def ordered(bucket: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
            return [deepcopy(bucket[k]) for k in sorted(bucket)]

        return {
            "intents": ordered(self.intents),
            "conditions": ordered(self.conditions),
            "cases": ordered(self.cases),
        }


def _legacy_children(raw_event: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    payload = raw_event.get("payload")
    if not isinstance(payload, dict):
        return None
    matched = [(field, meta) for field, meta in LEGACY_BATCH_FIELDS.items() if field in payload]
    if not matched:
        return None
    if len(matched) != 1:
        raise ProjectionIntegrityError("AMBIGUOUS_LEGACY_BATCH_EVENT")
    field, (event_type, artifact_type) = matched[0]
    items = payload[field]
    if not isinstance(items, list):
        raise ProjectionIntegrityError("LEGACY_BATCH_NOT_LIST")
    children: List[Dict[str, Any]] = []
    base_id = str(raw_event.get("event_id") or f"legacy-seq-{raw_event.get('seq', 'unknown')}")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ProjectionIntegrityError("LEGACY_BATCH_CHILD_NOT_OBJECT")
        try:
            _, entity_id, version, canonical = _canonical_payload(event_type, item)
        except EventValidationError as exc:
            raise ProjectionIntegrityError(f"LEGACY_CHILD_INVALID:{exc}") from exc
        children.append(
            {
                "seq": raw_event.get("seq"),
                "event_id": f"{base_id}:{artifact_type}:{index}",
                "event_type": event_type,
                "entity_type": artifact_type,
                "entity_id": entity_id,
                "entity_version": version,
                "payload": canonical,
                "legacy_parent_event_id": base_id,
            }
        )
    return children


def expand_for_replay(raw_event: Dict[str, Any], *, allow_legacy: bool = True) -> List[Dict[str, Any]]:
    """Return atomic replay units without mutating the durable event stream."""
    legacy = _legacy_children(raw_event) if allow_legacy else None
    if legacy is not None:
        return legacy
    payload = raw_event.get("payload")
    event_type = raw_event.get("event_type")
    if not isinstance(payload, dict):
        raise ProjectionIntegrityError("EVENT_PAYLOAD_NOT_OBJECT")
    try:
        artifact_type, entity_id, version, canonical = _canonical_payload(str(event_type), payload)
    except EventValidationError as exc:
        raise ProjectionIntegrityError(str(exc)) from exc
    event = deepcopy(raw_event)
    event["entity_type"] = artifact_type
    event["entity_id"] = entity_id
    event["entity_version"] = version
    event["payload"] = canonical
    return [event]


class TruthRuntime:
    """Atomic append + derived projection + read-after-write integrity."""

    def __init__(self, event_path: str | os.PathLike[str], *, allow_legacy_replay: bool = True):
        self.store = JsonlEventStore(event_path)
        self.allow_legacy_replay = allow_legacy_replay
        self.projection = Projection()
        self.rebuild_projection()

    def rebuild_projection(self) -> Dict[str, Any]:
        rebuilt = Projection()
        for raw in self.store.iter_raw():
            for atomic in expand_for_replay(raw, allow_legacy=self.allow_legacy_replay):
                rebuilt.apply_atomic(atomic)
        self.projection = rebuilt
        return self.projection.snapshot()

    def append_atomic(self, event_type: str, payload: Dict[str, Any]) -> PersistenceReceipt:
        artifact_type, entity_id, version, canonical = _canonical_payload(event_type, payload)
        event = self.store.append(event_type, canonical)
        self.projection.apply_atomic(event)
        persisted = self.projection.get(artifact_type, entity_id)
        if persisted != canonical:
            raise ProjectionIntegrityError("READ_AFTER_WRITE_ENTITY_MISMATCH")
        queryable = self.projection.query(
            artifact_type,
            release_id=canonical.get("release_id"),
            requirement_id=canonical.get("requirement_id"),
        )
        matching = [x for x in queryable if x.get("tc_id", x.get("id")) == entity_id]
        if len(matching) != 1:
            raise ProjectionIntegrityError("READ_AFTER_WRITE_QUERY_MISMATCH")
        return PersistenceReceipt(
            status="PERSISTENCE_VERIFIED",
            event_id=event["event_id"],
            seq=event["seq"],
            entity_type=artifact_type,
            entity_id=entity_id,
            entity_version=version,
            requested_count=1,
            persisted_count=1,
            queryable_count=1,
        )

    def inventory(self) -> Dict[str, int]:
        return {
            "intents": len(self.projection.intents),
            "conditions": len(self.projection.conditions),
            "cases": len(self.projection.cases),
        }

    def query_intents(self, **filters: Any) -> List[Dict[str, Any]]:
        return self.projection.query("test_intent", **filters)

    def query_conditions(self, **filters: Any) -> List[Dict[str, Any]]:
        return self.projection.query("test_condition", **filters)

    def query_cases(self, **filters: Any) -> List[Dict[str, Any]]:
        return self.projection.query("test_case", **filters)
