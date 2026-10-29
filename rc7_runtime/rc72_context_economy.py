"""RC7.2 bounded-context and semantic execution-batch planning.

This module deliberately does not mutate canonical Task/ETU/TestObligation truth.
It projects READY WorkItems into an execution-only description so fine business
and scheduling granularity can remain intact while compatible semantic work
shares a bounded context envelope.

Frozen rule:

    business task granularity
        != scheduling granularity
        != execution-batch granularity
        != model-call granularity

The planner is conservative: missing affinity means no cross-WorkItem batching.
Retry envelopes are delta-first and never silently rehydrate unchanged full
upstream context.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .models import Task
from .rc72_model_economy import MissionCriticality, SemanticCostClass


class ContextEconomyError(ValueError):
    pass


class ExecutionMode(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    SEMANTIC = "SEMANTIC"
    HYBRID = "HYBRID"


@dataclass(frozen=True)
class ContextAffinity:
    """Execution-only grouping keys; none of these replace business lineage."""

    requirement_id: str = "UNKNOWN"
    sst_id: str = "UNKNOWN"
    service: str = "UNKNOWN"
    environment: str = "UNKNOWN"
    data_domain: str = "UNKNOWN"
    oracle_family: str = "UNKNOWN"
    tool_family: str = "UNKNOWN"

    def normalized(self) -> Tuple[str, ...]:
        return tuple(
            str(value or "UNKNOWN").strip() or "UNKNOWN"
            for value in (
                self.requirement_id,
                self.sst_id,
                self.service,
                self.environment,
                self.data_domain,
                self.oracle_family,
                self.tool_family,
            )
        )

    @property
    def batchable(self) -> bool:
        # Requirement + SST are mandatory to prevent unrelated business work
        # being merged simply because technical context looks similar.
        requirement_id, sst_id, *_ = self.normalized()
        return requirement_id != "UNKNOWN" and sst_id != "UNKNOWN"


@dataclass(frozen=True)
class RetryDelta:
    previous_attempt_summary_ref: str
    explicit_gap_refs: Tuple[str, ...]
    delta_evidence_refs: Tuple[str, ...]
    changed_dependency_refs: Tuple[str, ...]
    full_context_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.previous_attempt_summary_ref, str) or not self.previous_attempt_summary_ref.strip():
            raise ContextEconomyError("PREVIOUS_ATTEMPT_SUMMARY_REF_REQUIRED")
        if self.full_context_reason is not None and not str(self.full_context_reason).strip():
            raise ContextEconomyError("FULL_CONTEXT_REASON_MUST_BE_NONEMPTY")

    @property
    def requires_full_context(self) -> bool:
        return bool(self.full_context_reason)

    def refs(self) -> Tuple[str, ...]:
        ordered = [self.previous_attempt_summary_ref]
        ordered.extend(self.explicit_gap_refs)
        ordered.extend(self.delta_evidence_refs)
        ordered.extend(self.changed_dependency_refs)
        return _dedupe(ordered)


@dataclass(frozen=True)
class SemanticWorkDescriptor:
    """Execution projection for one canonical WorkItem/Task."""

    workitem_id: str
    mission_id: str
    node: str
    stage: str
    execution_mode: ExecutionMode
    mission_criticality: MissionCriticality
    semantic_cost_class: SemanticCostClass
    affinity: ContextAffinity
    input_refs: Tuple[str, ...]
    gap_refs: Tuple[str, ...] = ()
    retry_delta: Optional[RetryDelta] = None
    batch_eligible: bool = True

    def __post_init__(self) -> None:
        for name in ("workitem_id", "mission_id", "node", "stage"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContextEconomyError("%s_REQUIRED" % name.upper())
        if not isinstance(self.execution_mode, ExecutionMode):
            object.__setattr__(self, "execution_mode", ExecutionMode(str(self.execution_mode).upper()))
        if not isinstance(self.mission_criticality, MissionCriticality):
            object.__setattr__(
                self,
                "mission_criticality",
                MissionCriticality(str(self.mission_criticality).upper()),
            )
        if not isinstance(self.semantic_cost_class, SemanticCostClass):
            object.__setattr__(
                self,
                "semantic_cost_class",
                SemanticCostClass(str(self.semantic_cost_class).upper()),
            )
        object.__setattr__(self, "input_refs", _dedupe(self.input_refs))
        object.__setattr__(self, "gap_refs", _dedupe(self.gap_refs))

    @classmethod
    def from_task(
        cls,
        task: Task,
        *,
        stage: Optional[str] = None,
        execution_mode: ExecutionMode = ExecutionMode.SEMANTIC,
        mission_criticality: MissionCriticality = MissionCriticality.UNKNOWN,
        semantic_cost_class: SemanticCostClass = SemanticCostClass.UNKNOWN,
        affinity: Optional[ContextAffinity] = None,
        retry_delta: Optional[RetryDelta] = None,
        batch_eligible: bool = True,
    ) -> "SemanticWorkDescriptor":
        return cls(
            workitem_id=task.task_id,
            mission_id=task.mission_id,
            node=task.node,
            stage=stage or task.node,
            execution_mode=execution_mode,
            mission_criticality=mission_criticality,
            semantic_cost_class=semantic_cost_class,
            affinity=affinity or ContextAffinity(),
            input_refs=tuple(task.input_artifact_refs),
            gap_refs=tuple(task.gap_refs),
            retry_delta=retry_delta,
            batch_eligible=batch_eligible,
        )

    def compatibility_key(self) -> Tuple[str, ...]:
        return (
            self.mission_id,
            self.node,
            self.stage,
            *self.affinity.normalized(),
        )


@dataclass(frozen=True)
class ContextEnvelope:
    envelope_id: str
    mission_id: str
    workitem_ids: Tuple[str, ...]
    shared_refs: Tuple[str, ...]
    workitem_refs: Mapping[str, Tuple[str, ...]]
    retry_delta_refs: Mapping[str, Tuple[str, ...]]
    context_sha256: str
    full_context_workitem_ids: Tuple[str, ...] = ()

    def as_prompt_projection(self) -> Dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "mission_id": self.mission_id,
            "workitem_ids": list(self.workitem_ids),
            "shared_refs": list(self.shared_refs),
            "workitem_refs": {key: list(value) for key, value in self.workitem_refs.items()},
            "retry_delta_refs": {key: list(value) for key, value in self.retry_delta_refs.items()},
            "full_context_workitem_ids": list(self.full_context_workitem_ids),
            "context_sha256": self.context_sha256,
            "context_rule": (
                "Hydrate only refs required for the current semantic decision. "
                "For retries, use retry_delta_refs by default; unchanged upstream refs remain references."
            ),
        }


@dataclass(frozen=True)
class ExecutionBatch:
    batch_id: str
    mission_id: str
    node: str
    stage: str
    workitem_ids: Tuple[str, ...]
    context_envelope: ContextEnvelope
    mission_criticality: MissionCriticality
    semantic_cost_class: SemanticCostClass

    @property
    def member_count(self) -> int:
        return len(self.workitem_ids)


@dataclass(frozen=True)
class ExecutionBatchPlan:
    batches: Tuple[ExecutionBatch, ...]
    deterministic_workitem_ids: Tuple[str, ...]
    unbatched_semantic_workitem_ids: Tuple[str, ...]


class ContextEnvelopeBuilder:
    """Build a minimal reference envelope without copying source documents."""

    @staticmethod
    def build(items: Sequence[SemanticWorkDescriptor]) -> ContextEnvelope:
        if not items:
            raise ContextEconomyError("CONTEXT_ENVELOPE_ITEMS_REQUIRED")
        mission_ids = {item.mission_id for item in items}
        if len(mission_ids) != 1:
            raise ContextEconomyError("CROSS_MISSION_CONTEXT_ENVELOPE_FORBIDDEN")
        workitem_ids = tuple(item.workitem_id for item in items)
        if len(set(workitem_ids)) != len(workitem_ids):
            raise ContextEconomyError("DUPLICATE_WORKITEM_IN_CONTEXT_ENVELOPE")

        retry_delta_refs: Dict[str, Tuple[str, ...]] = {}
        full_context_workitem_ids: List[str] = []
        effective_refs: Dict[str, Tuple[str, ...]] = {}
        for item in items:
            if item.retry_delta is not None and not item.retry_delta.requires_full_context:
                delta_refs = item.retry_delta.refs()
                retry_delta_refs[item.workitem_id] = delta_refs
                effective_refs[item.workitem_id] = delta_refs
            else:
                effective_refs[item.workitem_id] = _dedupe((*item.input_refs, *item.gap_refs))
                if item.retry_delta is not None and item.retry_delta.requires_full_context:
                    retry_delta_refs[item.workitem_id] = item.retry_delta.refs()
                    full_context_workitem_ids.append(item.workitem_id)

        ref_counts: Dict[str, int] = {}
        for refs in effective_refs.values():
            for ref in refs:
                ref_counts[ref] = ref_counts.get(ref, 0) + 1
        shared_refs = tuple(sorted(ref for ref, count in ref_counts.items() if count == len(items)))
        shared_set = set(shared_refs)
        workitem_refs = {
            workitem_id: tuple(ref for ref in refs if ref not in shared_set)
            for workitem_id, refs in effective_refs.items()
        }
        payload = {
            "mission_id": next(iter(mission_ids)),
            "workitem_ids": workitem_ids,
            "shared_refs": shared_refs,
            "workitem_refs": workitem_refs,
            "retry_delta_refs": retry_delta_refs,
            "full_context_workitem_ids": tuple(full_context_workitem_ids),
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ContextEnvelope(
            envelope_id="CTX-%s" % digest[:20],
            mission_id=next(iter(mission_ids)),
            workitem_ids=workitem_ids,
            shared_refs=shared_refs,
            workitem_refs=workitem_refs,
            retry_delta_refs=retry_delta_refs,
            full_context_workitem_ids=tuple(full_context_workitem_ids),
            context_sha256=digest,
        )


class ExecutionBatchPlanner:
    """Conservatively batch compatible semantic work while preserving members."""

    def __init__(self, *, max_batch_size: int = 8) -> None:
        if not isinstance(max_batch_size, int) or isinstance(max_batch_size, bool) or max_batch_size < 1:
            raise ContextEconomyError("MAX_BATCH_SIZE_INVALID")
        self.max_batch_size = max_batch_size

    @staticmethod
    def _aggregate_criticality(items: Sequence[SemanticWorkDescriptor]) -> MissionCriticality:
        if any(item.mission_criticality == MissionCriticality.BLOCKING for item in items):
            return MissionCriticality.BLOCKING
        if all(item.mission_criticality == MissionCriticality.NON_BLOCKING for item in items):
            return MissionCriticality.NON_BLOCKING
        return MissionCriticality.UNKNOWN

    @staticmethod
    def _aggregate_cost(items: Sequence[SemanticWorkDescriptor]) -> SemanticCostClass:
        rank = {
            SemanticCostClass.UNKNOWN: 0,
            SemanticCostClass.LOW: 1,
            SemanticCostClass.MEDIUM: 2,
            SemanticCostClass.HIGH: 3,
        }
        return max((item.semantic_cost_class for item in items), key=lambda value: rank[value])

    @staticmethod
    def _batch_id(items: Sequence[SemanticWorkDescriptor], envelope: ContextEnvelope) -> str:
        raw = "\x1f".join([envelope.context_sha256, *[item.workitem_id for item in items]])
        return "BATCH-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    def plan(self, items: Sequence[SemanticWorkDescriptor]) -> ExecutionBatchPlan:
        deterministic: List[str] = []
        semantic_singletons: List[SemanticWorkDescriptor] = []
        groups: Dict[Tuple[str, ...], List[SemanticWorkDescriptor]] = {}

        for item in items:
            if item.execution_mode == ExecutionMode.DETERMINISTIC:
                deterministic.append(item.workitem_id)
                continue
            if not item.batch_eligible or not item.affinity.batchable:
                semantic_singletons.append(item)
                continue
            groups.setdefault(item.compatibility_key(), []).append(item)

        batches: List[ExecutionBatch] = []
        unbatched: List[str] = []

        for item in semantic_singletons:
            envelope = ContextEnvelopeBuilder.build([item])
            batches.append(
                ExecutionBatch(
                    batch_id=self._batch_id([item], envelope),
                    mission_id=item.mission_id,
                    node=item.node,
                    stage=item.stage,
                    workitem_ids=(item.workitem_id,),
                    context_envelope=envelope,
                    mission_criticality=item.mission_criticality,
                    semantic_cost_class=item.semantic_cost_class,
                )
            )
            unbatched.append(item.workitem_id)

        for grouped in groups.values():
            for start in range(0, len(grouped), self.max_batch_size):
                chunk = grouped[start : start + self.max_batch_size]
                envelope = ContextEnvelopeBuilder.build(chunk)
                batches.append(
                    ExecutionBatch(
                        batch_id=self._batch_id(chunk, envelope),
                        mission_id=chunk[0].mission_id,
                        node=chunk[0].node,
                        stage=chunk[0].stage,
                        workitem_ids=tuple(item.workitem_id for item in chunk),
                        context_envelope=envelope,
                        mission_criticality=self._aggregate_criticality(chunk),
                        semantic_cost_class=self._aggregate_cost(chunk),
                    )
                )
                if len(chunk) == 1:
                    unbatched.append(chunk[0].workitem_id)

        return ExecutionBatchPlan(
            batches=tuple(batches),
            deterministic_workitem_ids=tuple(deterministic),
            unbatched_semantic_workitem_ids=tuple(unbatched),
        )


def build_retry_delta(
    *,
    previous_attempt_summary_ref: str,
    explicit_gap_refs: Iterable[str],
    delta_evidence_refs: Iterable[str],
    changed_dependency_refs: Iterable[str] = (),
    full_context_reason: Optional[str] = None,
) -> RetryDelta:
    return RetryDelta(
        previous_attempt_summary_ref=previous_attempt_summary_ref,
        explicit_gap_refs=_dedupe(explicit_gap_refs),
        delta_evidence_refs=_dedupe(delta_evidence_refs),
        changed_dependency_refs=_dedupe(changed_dependency_refs),
        full_context_reason=full_context_reason,
    )


def _dedupe(values: Iterable[str]) -> Tuple[str, ...]:
    out: List[str] = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ContextEconomyError("CONTEXT_REF_MUST_BE_NONEMPTY_STRING")
        normalized = value.strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return tuple(out)
