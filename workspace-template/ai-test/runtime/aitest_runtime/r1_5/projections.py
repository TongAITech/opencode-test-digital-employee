from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeService, canonical_sha256

from .contracts import PROJECTION_SCHEMA_VERSION, R1_5_CONTRACT_VERSION, redact, utc_now


@dataclass(frozen=True)
class ProjectionEnvelope:
    projection_type: str
    mission_id: str
    as_of_seq: int
    observed_at: str
    freshness: str
    payload: Mapping[str, Any]
    projection_schema_version: str = PROJECTION_SCHEMA_VERSION
    contract_version: str = R1_5_CONTRACT_VERSION

    @property
    def digest(self) -> str:
        return canonical_sha256(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "projection_schema_version": self.projection_schema_version,
            "contract_version": self.contract_version,
            "projection_type": self.projection_type,
            "mission_id": self.mission_id,
            "as_of_seq": self.as_of_seq,
            "observed_at": self.observed_at,
            "freshness": self.freshness,
            "canonical": False,
            "rebuildable": True,
            "truth_source": "EVENT_STREAM",
            "payload": redact(dict(self.payload)),
        }
        if include_digest:
            result["digest"] = canonical_sha256(result)
        return result


def mission_projection(runtime: RuntimeService, mission_id: str) -> ProjectionEnvelope:
    state = runtime.get_composed_state(mission_id)
    head = runtime.get_head_seq(mission_id)
    return ProjectionEnvelope(
        projection_type="MISSION_RUNTIME",
        mission_id=mission_id,
        as_of_seq=state.seq,
        observed_at=utc_now(),
        freshness="CURRENT" if state.seq == head else "STALE",
        payload=state.to_dict(),
    )
