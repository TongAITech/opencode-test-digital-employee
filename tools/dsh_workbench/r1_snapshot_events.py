"""Read strict JSONL events from an already pinned R1 byte snapshot."""

import io
import json
import math
from typing import NamedTuple


class R1SnapshotDecodeError(ValueError):
    pass


class R1SnapshotRecord(NamedTuple):
    line_number: int
    raw_line: bytes
    event: dict


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        key.encode("utf-8", "strict")
        value[key] = item
    return value


def _finite_number(raw):
    number = float(raw)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _check_unicode(value):
    if type(value) is str:
        value.encode("utf-8", "strict")
    elif type(value) is list:
        for item in value:
            _check_unicode(item)
    elif type(value) is dict:
        for item in value.values():
            _check_unicode(item)


def iter_r1_snapshot_records(snapshot):
    """Yield original line bytes including the terminator, with decoded envelopes.

    Callers must consume the complete iterator before accepting any result and
    enforce the snapshot byte limit when reading from the original ledger.
    """
    if type(snapshot) is not bytes:
        raise R1SnapshotDecodeError("R1_SNAPSHOT_BYTES_REQUIRED")
    if snapshot and not snapshot.endswith(b"\n"):
        raise R1SnapshotDecodeError("R1_SNAPSHOT_INCOMPLETE_TAIL")
    for number, raw in enumerate(io.BytesIO(snapshot), 1):
        if not raw.strip(b" \t\r\n"):
            continue
        try:
            value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_object,
                               parse_float=_finite_number, parse_constant=_finite_number)
            if type(value) is not dict:
                raise ValueError("event must be an object")
            _check_unicode(value)
        except (ValueError, RecursionError) as error:
            raise R1SnapshotDecodeError("R1_SNAPSHOT_EVENT_INVALID_LINE_%d" % number) from error
        yield R1SnapshotRecord(number, raw, value)


def iter_r1_snapshot_events(snapshot):
    """Yield decoded envelopes while retaining distinct source records."""
    for record in iter_r1_snapshot_records(snapshot):
        yield record.event
