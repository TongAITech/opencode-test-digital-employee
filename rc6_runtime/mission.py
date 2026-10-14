from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class MissionState:
    mission_id: str
    release_id: str
    stage: str = "REGISTERED"
    completed_gates: List[str] = field(default_factory=list)
    artifact_refs: List[str] = field(default_factory=list)
    open_gaps: List[str] = field(default_factory=list)
    active_leases: List[str] = field(default_factory=list)
    target_identity_ref: Optional[str] = None
    checkpoint_seq: int = 0
    coordinator_generation: int = 0
    updated_at: int = 0


@dataclass(frozen=True)
class ResumeEnvelope:
    mission_id: str
    release_id: str
    stage: str
    completed_gates: tuple
    artifact_refs: tuple
    open_gaps: tuple
    active_leases: tuple
    target_identity_ref: Optional[str]
    checkpoint_seq: int
    coordinator_generation: int


class MissionRuntime:
    """Durable Mission state independent of chat/session history."""

    def __init__(self, root_dir: str):
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, mission_id: str, release_id: str) -> MissionState:
        path = self._path(mission_id)
        if path.exists():
            raise RuntimeError("MISSION_ALREADY_EXISTS")
        state = MissionState(mission_id=mission_id, release_id=release_id, updated_at=int(time.time()))
        self.save(state)
        return state

    def load(self, mission_id: str) -> MissionState:
        path = self._path(mission_id)
        if not path.exists():
            raise RuntimeError("MISSION_NOT_FOUND")
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return MissionState(**data)

    def save(self, state: MissionState) -> None:
        state.updated_at = int(time.time())
        target = self._path(state.mission_id)
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(asdict(state), fh, ensure_ascii=False, sort_keys=True, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def checkpoint(self, state: MissionState) -> ResumeEnvelope:
        state.checkpoint_seq += 1
        state.coordinator_generation += 1
        self.save(state)
        return self.resume_envelope(state)

    def resume_envelope(self, state: MissionState) -> ResumeEnvelope:
        # Deliberately contains no conversation transcript or worker payload bodies.
        return ResumeEnvelope(
            mission_id=state.mission_id,
            release_id=state.release_id,
            stage=state.stage,
            completed_gates=tuple(state.completed_gates),
            artifact_refs=tuple(state.artifact_refs),
            open_gaps=tuple(state.open_gaps),
            active_leases=tuple(state.active_leases),
            target_identity_ref=state.target_identity_ref,
            checkpoint_seq=state.checkpoint_seq,
            coordinator_generation=state.coordinator_generation,
        )

    def _path(self, mission_id: str) -> Path:
        safe = "".join(c for c in mission_id if c.isalnum() or c in "-_.")
        if not safe or safe != mission_id:
            raise ValueError("INVALID_MISSION_ID")
        return self.root / (safe + ".json")
