"""RC7.2 repeated-context detection over canonical model-call truth.

This module is observability only.  It detects exact context reuse that already
occurred and attributes it to explicit Mission/WorkItem/Attempt identities from
``rc72_token_call``.  It never infers lineage from IDs, prompts, node names or
scope strings, and it never blocks mandatory semantic work.

The detector intentionally stops before retry-amplification control or semantic
caching.  Cross-attempt and cross-workitem repetition are surfaced as candidates
for later policy; same WorkItem+Attempt repetition is only a waste *suspect*, not
a claim that no semantic progress occurred.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple

from rc6_runtime.truth import TruthRuntime

from .rc72_model_economy import install_rc72_token_economy_overlay


_EXECUTED_STATES = {"COMPLETED", "COMPLETED_UNKNOWN"}


class ContextRepetitionKind(str, Enum):
    SAME_WORKITEM_ATTEMPT = "SAME_WORKITEM_ATTEMPT"
    CROSS_ATTEMPT = "CROSS_ATTEMPT"
    CROSS_WORKITEM = "CROSS_WORKITEM"
    MIXED = "MIXED"


@dataclass(frozen=True)
class ContextRepetitionGroup:
    context_sha256: str
    call_ids: Tuple[str, ...]
    workitem_ids: Tuple[str, ...]
    attempt_ids: Tuple[str, ...]
    recorded_nodes: Tuple[str, ...]
    call_count: int
    duplicate_call_count: int
    context_bytes_per_call: Optional[int]
    repeated_context_bytes: Optional[int]
    repetition_kind: ContextRepetitionKind
    economy_signal: str
    progress_proven: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "context_sha256": self.context_sha256,
            "call_ids": list(self.call_ids),
            "workitem_ids": list(self.workitem_ids),
            "attempt_ids": list(self.attempt_ids),
            "recorded_nodes": list(self.recorded_nodes),
            "call_count": self.call_count,
            "duplicate_call_count": self.duplicate_call_count,
            "context_bytes_per_call": self.context_bytes_per_call,
            "repeated_context_bytes": self.repeated_context_bytes,
            "repetition_kind": self.repetition_kind.value,
            "economy_signal": self.economy_signal,
            "progress_proven": self.progress_proven,
        }


@dataclass(frozen=True)
class ContextRepetitionReport:
    mission_id: str
    executed_call_count: int
    unique_context_count: int
    repeated_group_count: int
    duplicate_call_count: int
    repeated_context_bytes: Optional[int]
    unknown_repeated_bytes_group_count: int
    same_attempt_suspect_group_count: int
    cross_attempt_group_count: int
    cross_workitem_group_count: int
    mixed_group_count: int
    groups: Tuple[ContextRepetitionGroup, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "executed_call_count": self.executed_call_count,
            "unique_context_count": self.unique_context_count,
            "repeated_group_count": self.repeated_group_count,
            "duplicate_call_count": self.duplicate_call_count,
            "repeated_context_bytes": self.repeated_context_bytes,
            "unknown_repeated_bytes_group_count": self.unknown_repeated_bytes_group_count,
            "same_attempt_suspect_group_count": self.same_attempt_suspect_group_count,
            "cross_attempt_group_count": self.cross_attempt_group_count,
            "cross_workitem_group_count": self.cross_workitem_group_count,
            "mixed_group_count": self.mixed_group_count,
            "groups": [group.as_dict() for group in self.groups],
        }


class ContextRepetitionDetector:
    """Detect exact repeated model contexts without changing Mission execution."""

    def __init__(self, truth: TruthRuntime) -> None:
        install_rc72_token_economy_overlay()
        self.truth = truth

    @staticmethod
    def _ordered_unique(rows: List[Mapping[str, Any]], field: str) -> Tuple[str, ...]:
        values: List[str] = []
        seen = set()
        for row in rows:
            value = str(row.get(field) or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
        return tuple(values)

    @staticmethod
    def _kind(workitems: Tuple[str, ...], attempts: Tuple[str, ...]) -> ContextRepetitionKind:
        if len(workitems) == 1 and len(attempts) == 1:
            return ContextRepetitionKind.SAME_WORKITEM_ATTEMPT
        if len(workitems) == 1 and len(attempts) > 1:
            return ContextRepetitionKind.CROSS_ATTEMPT
        if len(workitems) > 1 and len(attempts) == 1:
            return ContextRepetitionKind.CROSS_WORKITEM
        return ContextRepetitionKind.MIXED

    @staticmethod
    def _signal(kind: ContextRepetitionKind) -> str:
        if kind == ContextRepetitionKind.SAME_WORKITEM_ATTEMPT:
            return "POTENTIAL_NO_PROGRESS_REPEAT"
        if kind == ContextRepetitionKind.CROSS_ATTEMPT:
            return "RETRY_CONTEXT_AMPLIFICATION_CANDIDATE"
        if kind == ContextRepetitionKind.CROSS_WORKITEM:
            return "CROSS_WORKITEM_REUSE_CANDIDATE"
        return "MIXED_CONTEXT_REUSE_CANDIDATE"

    def report(self, mission_id: str) -> ContextRepetitionReport:
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("CONTEXT_REPETITION_MISSION_ID_REQUIRED")
        mission_id = mission_id.strip()
        rows = [
            row
            for row in self.truth.query("rc72_token_call", mission_id=mission_id)
            if str(row.get("state") or "").upper() in _EXECUTED_STATES
        ]
        rows.sort(key=lambda row: (int(row.get("created_at") or 0), str(row.get("call_id") or "")))

        by_digest: Dict[str, List[Mapping[str, Any]]] = {}
        for row in rows:
            digest = str(row.get("context_sha256") or "").strip()
            if not digest:
                # The token-call validator requires a digest, but fail conservative
                # if old/replayed truth predates that contract.
                continue
            by_digest.setdefault(digest, []).append(row)

        groups: List[ContextRepetitionGroup] = []
        for digest, grouped in by_digest.items():
            if len(grouped) < 2:
                continue
            call_ids = self._ordered_unique(grouped, "call_id")
            workitems = self._ordered_unique(grouped, "workitem_id")
            attempts = self._ordered_unique(grouped, "attempt_id")
            recorded_nodes = self._ordered_unique(grouped, "node")
            sizes = {
                int(row.get("context_bytes"))
                for row in grouped
                if isinstance(row.get("context_bytes"), int)
                and not isinstance(row.get("context_bytes"), bool)
                and int(row.get("context_bytes")) >= 0
            }
            if len(sizes) == 1:
                context_bytes = next(iter(sizes))
                repeated_bytes: Optional[int] = context_bytes * (len(grouped) - 1)
            else:
                context_bytes = None
                repeated_bytes = None
            kind = self._kind(workitems, attempts)
            groups.append(
                ContextRepetitionGroup(
                    context_sha256=digest,
                    call_ids=call_ids,
                    workitem_ids=workitems,
                    attempt_ids=attempts,
                    recorded_nodes=recorded_nodes,
                    call_count=len(grouped),
                    duplicate_call_count=len(grouped) - 1,
                    context_bytes_per_call=context_bytes,
                    repeated_context_bytes=repeated_bytes,
                    repetition_kind=kind,
                    economy_signal=self._signal(kind),
                    # Exact context equality alone does not prove semantic no-progress.
                    progress_proven=False,
                )
            )

        groups.sort(key=lambda item: (-item.duplicate_call_count, item.context_sha256))
        known_bytes = [group.repeated_context_bytes for group in groups if group.repeated_context_bytes is not None]
        unknown_bytes = sum(1 for group in groups if group.repeated_context_bytes is None)
        return ContextRepetitionReport(
            mission_id=mission_id,
            executed_call_count=len(rows),
            unique_context_count=len(by_digest),
            repeated_group_count=len(groups),
            duplicate_call_count=sum(group.duplicate_call_count for group in groups),
            repeated_context_bytes=(sum(known_bytes) if unknown_bytes == 0 else None),
            unknown_repeated_bytes_group_count=unknown_bytes,
            same_attempt_suspect_group_count=sum(
                1 for group in groups if group.repetition_kind == ContextRepetitionKind.SAME_WORKITEM_ATTEMPT
            ),
            cross_attempt_group_count=sum(
                1 for group in groups if group.repetition_kind == ContextRepetitionKind.CROSS_ATTEMPT
            ),
            cross_workitem_group_count=sum(
                1 for group in groups if group.repetition_kind == ContextRepetitionKind.CROSS_WORKITEM
            ),
            mixed_group_count=sum(
                1 for group in groups if group.repetition_kind == ContextRepetitionKind.MIXED
            ),
            groups=tuple(groups),
        )
