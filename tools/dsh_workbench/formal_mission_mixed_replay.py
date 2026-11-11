"""Detached qualification of an already pinned mixed R1 byte snapshot."""

from rc6_runtime.truth import Projection, ProjectionIntegrityError, expand_for_replay

from .formal_mission_receipt import _iter_formal_sources
from .r1_snapshot_events import iter_r1_snapshot_records


class FormalMissionReplayHold(ValueError):
    """The snapshot failed formal replay qualification."""


def replay_formal_mission_snapshot(snapshot, formal_authority_ref):
    """Build an internal, disposable projection with the active native overlays.

    The caller pins the configured physical authority and initializes the
    applicable legacy overlays through normal runtime setup. This component
    registers no event type and performs no I/O. The projection is internal
    data, and a successful replay grants no authorization or production access.
    """
    if type(formal_authority_ref) is not str or not formal_authority_ref:
        raise FormalMissionReplayHold("FORMAL_MISSION_REPLAY_HOLD")
    projection = Projection()
    event_ids = set()
    sequences = set()
    try:
        for record, formal in _iter_formal_sources(iter_r1_snapshot_records(snapshot), formal_authority_ref):
            raw = record.event
            event_id = raw.get("event_id")
            seq = raw.get("seq")
            # Old batch envelopes may omit these fields. When present, they
            # must identify distinct physical records for formal qualification.
            if "event_id" in raw:
                if type(event_id) is not str or not event_id or event_id in event_ids:
                    raise FormalMissionReplayHold("FORMAL_MISSION_REPLAY_HOLD")
                event_ids.add(event_id)
            if "seq" in raw:
                if type(seq) is not int or not 1 <= seq <= 9223372036854775807 or seq in sequences:
                    raise FormalMissionReplayHold("FORMAL_MISSION_REPLAY_HOLD")
                sequences.add(seq)
            if formal is not None:
                projection._apply_validated("rc7_mission", formal.scope.mission_id, 1, raw["payload"])
                continue
            for unit in expand_for_replay(raw):
                payload = unit["payload"]
                if unit["entity_type"] == "rc7_mission" and (
                        "scope_binding" in payload or "runtime_batch_mapping" in payload):
                    raise FormalMissionReplayHold("FORMAL_MISSION_REPLAY_HOLD")
                projection._apply_validated(unit["entity_type"], unit["entity_id"], unit["entity_version"], payload)
    except FormalMissionReplayHold:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, ProjectionIntegrityError) as error:
        raise FormalMissionReplayHold("FORMAL_MISSION_REPLAY_HOLD") from error
    return projection
