from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from .router import SessionRouter

ROTATE_MESSAGE_THRESHOLD=60
ROTATE_COMPACTION_THRESHOLD=1
ROTATE_CONTEXT_UTILIZATION_THRESHOLD=0.85

def utc_now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def _int_or_none(v): return int(v) if isinstance(v,(int,float)) and not isinstance(v,bool) else None
def _float_or_none(v): return float(v) if isinstance(v,(int,float)) and not isinstance(v,bool) else None

@dataclass(frozen=True)
class SessionObservation:
    session_id: str; observed_at: str; reachable: bool; healthy: bool|None
    message_count: int|None=None; compaction_count: int|None=None; context_used: int|None=None; context_limit: int|None=None
    context_utilization: float|None=None; last_activity_at: str|None=None; provider_state: Mapping[str,Any]=None
    def to_dict(self):
        return {"session_id":self.session_id,"observed_at":self.observed_at,"reachable":self.reachable,"healthy":self.healthy,
                "message_count":self.message_count,"compaction_count":self.compaction_count,"context_used":self.context_used,
                "context_limit":self.context_limit,"context_utilization":self.context_utilization,"last_activity_at":self.last_activity_at,
                "provider_state":dict(self.provider_state or {})}
    @classmethod
    def from_provider(cls, session_id: str, raw: Mapping[str,Any]):
        d=dict(raw); reachable=d.get("reachable") is True; healthy=d.get("healthy")
        if healthy is None and "unhealthy" in d: healthy=not bool(d.get("unhealthy"))
        used=_int_or_none(d.get("context_used")); limit=_int_or_none(d.get("context_limit")); util=_float_or_none(d.get("context_utilization"))
        if util is None and used is not None and limit and limit>0: util=used/limit
        return cls(session_id, str(d.get("observed_at") or utc_now()), reachable, healthy if isinstance(healthy,bool) else None,
                   _int_or_none(d.get("message_count")), _int_or_none(d.get("compaction_count")), used, limit, util,
                   d.get("last_activity_at") if isinstance(d.get("last_activity_at"),str) else None,
                   {"provider":d.get("provider"),"raw_digest":d.get("raw_digest"),"error":d.get("error")})

class RotationPolicy:
    def evaluate(self, obs: SessionObservation) -> list[str]:
        reasons=[]
        if not obs.reachable: reasons.append("SESSION_UNREACHABLE")
        elif obs.healthy is False: reasons.append("SESSION_UNHEALTHY")
        if obs.compaction_count is not None and obs.compaction_count>=ROTATE_COMPACTION_THRESHOLD: reasons.append("CONTEXT_COMPACTED")
        if obs.message_count is not None and obs.message_count>=ROTATE_MESSAGE_THRESHOLD: reasons.append("MESSAGE_THRESHOLD")
        if obs.context_utilization is not None and obs.context_utilization>=ROTATE_CONTEXT_UTILIZATION_THRESHOLD: reasons.append("CONTEXT_PRESSURE")
        return reasons
