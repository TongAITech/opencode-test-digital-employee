"""Durable RC7 session handoff contract.

A session is disposable.  The handoff contains only durable references required
to continue the same Task; it deliberately contains no chat transcript or
worker payload body.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class SessionHandoffStatus(str, Enum):
    PREPARED = "PREPARED"
    ACTIVATED = "ACTIVATED"


@dataclass
class SessionHandoff:
    handoff_id: str
    mission_id: str
    task_id: str
    generation: int
    predecessor_session_ref: str
    successor_session_ref: Optional[str] = None
    status: SessionHandoffStatus = SessionHandoffStatus.PREPARED
    task_state: str = "RUNNING"
    artifact_refs: List[str] = field(default_factory=list)
    gap_refs: List[str] = field(default_factory=list)
    created_at: int = field(default_factory=lambda: int(time.time()))
    activated_at: Optional[int] = None

    def __post_init__(self) -> None:
        for name in ("handoff_id", "mission_id", "task_id", "predecessor_session_ref", "task_state"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s_REQUIRED" % name.upper())
        if not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("SESSION_HANDOFF_GENERATION_INVALID")
        if self.successor_session_ref is not None and (
            not isinstance(self.successor_session_ref, str) or not self.successor_session_ref.strip()
        ):
            raise ValueError("SUCCESSOR_SESSION_REF_INVALID")
        for field_name in ("artifact_refs", "gap_refs"):
            values = getattr(self, field_name)
            if not isinstance(values, list) or not all(isinstance(x, str) and x.strip() for x in values):
                raise ValueError("%s_INVALID" % field_name.upper())
