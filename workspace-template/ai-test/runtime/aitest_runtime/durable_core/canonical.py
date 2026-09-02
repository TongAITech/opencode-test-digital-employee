from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from .contracts import CommandEnvelope


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _plain(value.to_dict())
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def command_fingerprint(command: CommandEnvelope) -> str:
    return canonical_sha256(
        {
            "type": command.type,
            "mission_id": command.mission_id,
            "session_id": command.session_id,
            "expected_seq": command.expected_seq,
            "actor": command.actor.to_dict(),
            "payload": dict(command.payload),
            "schema_version": command.schema_version,
        }
    )


class Clock(Protocol):
    def now(self) -> str:
        ...


class SystemClock:
    def now(self) -> str:
        value = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        return value.replace("+00:00", "Z")
