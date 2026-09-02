from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandEnvelope, CommandResult, RuntimeService, canonical_sha256
from aitest_runtime.r3_e1 import KnowledgeRetrievalResult

from .contracts import (
    ARCHITECTURE_BASELINE_REF,
    BUILD_PAGE_GRAPH,
    CHECKPOINT_JOURNEY,
    DEFINE_JOURNEY,
    EXTENSION_ID,
    RECORD_TRANSITION,
    RECORD_VERIFICATION,
    BusinessJourney,
    JourneyCheckpoint,
    JourneyTransition,
    JourneyVerification,
    PageGraph,
    R35State,
)
from .e2e import lifecycle_status
from .errors import R35Error
from .journey import (
    checkpoint_journey,
    define_journey,
    record_journey_transition,
)
from .page_intelligence import PageGraphBuildRequest, PageGraphBuildResult, build_page_graph
from .reconciliation import reconcile_page_runtime
from .workset import KnowledgeRetrievalPort, WorkSetRequest, WorkSetResult, retrieve_workset


@dataclass(frozen=True)
class R35OperationResult:
    command: CommandResult
    entity_id: str
    entity_kind: str

    @property
    def ok(self) -> bool:
        return self.command.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_kind": self.entity_kind,
            "entity_id": self.entity_id,
            "command": self.command.to_dict(),
        }


class R35ApplicationService:
    """Thin application seam over the canonical R1 Event Stream and R3.E1 retrieval."""

    def __init__(self, runtime: RuntimeService) -> None:
        if runtime is None:
            raise R35Error("R3_5_SCHEMA_INVALID", "RuntimeService is required")
        try:
            runtime.extension_registry.manifest(EXTENSION_ID)
        except Exception as exc:
            raise R35Error("R3_5_EXTENSION_REQUIRED", "R3.5 requires its registered durable extension") from exc
        self.runtime = runtime

    @staticmethod
    def _entity(value: Any, cls: type[Any], name: str) -> Any:
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls.from_dict(value)
        raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be a typed R3.5 entity or mapping")

    def _persist(
        self,
        command_type: str,
        entity_kind: str,
        entity_id: str,
        entity_key: str,
        entity: Any,
        mission_id: str,
        *,
        actor: ActorRef | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        origin_lineage: Mapping[str, Any] | None = None,
    ) -> R35OperationResult:
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise R35Error("R3_5_SCOPE_MISMATCH", "mission_id is required")
        lineage = dict(origin_lineage or {})
        lineage["mission_id"] = mission_id
        lineage.setdefault("architecture_baseline_ref", ARCHITECTURE_BASELINE_REF)
        payload_without_digest = {
            entity_key: entity.to_dict(),
            "origin_lineage": lineage,
        }
        payload = {
            **payload_without_digest,
            "payload_digest": canonical_sha256(payload_without_digest),
        }
        command_id = f"r3.5:{command_type}:{entity_kind.lower()}:{entity_id}"
        expected_seq = self.runtime.get_head_seq(mission_id)
        # The frozen R1 command fingerprint includes expected_seq. Reuse the
        # original stream position for an idempotent retry, discovered only
        # through the canonical R1 Event Stream; no local receipt cache exists.
        for event in self.runtime.list_events(mission_id):
            if (
                event.entity_type == entity_kind
                and event.entity_id == entity_id
                and event.payload.get(entity_key) == entity.to_dict()
                and event.payload.get("payload_digest") == payload["payload_digest"]
            ):
                expected_seq = event.seq - 1
                break
        result = self.runtime.execute(
            CommandEnvelope(
                command_id=command_id,
                type=command_type,
                mission_id=mission_id,
                expected_seq=expected_seq,
                actor=actor or ActorRef("R3_5_APPLICATION_SERVICE", "r3_5"),
                payload=payload,
                session_id=session_id,
                idempotency_key=idempotency_key or command_id,
                correlation_id=correlation_id or command_id,
            )
        )
        return R35OperationResult(result, entity_id, entity_kind)

    def record_page_graph(
        self,
        graph: PageGraph | Mapping[str, Any],
        mission_id: str,
        **kwargs: Any,
    ) -> R35OperationResult:
        value = self._entity(graph, PageGraph, "graph")
        return self._persist(
            BUILD_PAGE_GRAPH,
            "PAGE_GRAPH",
            f"{value.graph_id}:v{value.graph_version}",
            "graph",
            value,
            mission_id,
            **kwargs,
        )

    def record_journey(
        self,
        journey: BusinessJourney | Mapping[str, Any],
        mission_id: str,
        **kwargs: Any,
    ) -> R35OperationResult:
        value = define_journey(journey) if isinstance(journey, Mapping) else self._entity(journey, BusinessJourney, "journey")
        return self._persist(
            DEFINE_JOURNEY,
            "BUSINESS_JOURNEY",
            f"{value.journey_id}:v{value.journey_version}",
            "journey",
            value,
            mission_id,
            **kwargs,
        )

    def record_journey_transition(
        self,
        transition: JourneyTransition | Mapping[str, Any],
        journey: BusinessJourney,
        mission_id: str,
        **kwargs: Any,
    ) -> R35OperationResult:
        value = record_journey_transition(transition, journey=journey)
        return self._persist(
            RECORD_TRANSITION,
            "JOURNEY_TRANSITION",
            value.transition_id,
            "transition",
            value,
            mission_id,
            **kwargs,
        )

    def record_journey_checkpoint(
        self,
        checkpoint: JourneyCheckpoint | Mapping[str, Any],
        mission_id: str,
        **kwargs: Any,
    ) -> R35OperationResult:
        value = checkpoint_journey(checkpoint)
        return self._persist(
            CHECKPOINT_JOURNEY,
            "JOURNEY_CHECKPOINT",
            value.checkpoint_id,
            "checkpoint",
            value,
            mission_id,
            **kwargs,
        )

    def record_journey_verification(
        self,
        verification: JourneyVerification | Mapping[str, Any],
        mission_id: str,
        **kwargs: Any,
    ) -> R35OperationResult:
        value = self._entity(verification, JourneyVerification, "verification")
        return self._persist(
            RECORD_VERIFICATION,
            "JOURNEY_VERIFICATION",
            value.verification_id,
            "verification",
            value,
            mission_id,
            **kwargs,
        )

    def state(self, mission_id: str) -> R35State:
        state = self.runtime.replay_composed(mission_id).extension_state(EXTENSION_ID)
        if not isinstance(state, R35State):
            raise R35Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.5 replay state")
        return state

    def page_graph(self, mission_id: str, graph_id: str, graph_version: int | None = None) -> PageGraph | None:
        return self.state(mission_id).page_graph(graph_id, graph_version)

    @staticmethod
    def build_page_graph(
        request: PageGraphBuildRequest | Mapping[str, Any],
        *,
        knowledge_result: WorkSetResult | KnowledgeRetrievalResult | None = None,
    ) -> PageGraphBuildResult:
        return build_page_graph(request, knowledge_result=knowledge_result)

    @staticmethod
    def retrieve_workset(request: WorkSetRequest, retriever: KnowledgeRetrievalPort) -> WorkSetResult:
        return retrieve_workset(request, retriever)

    @staticmethod
    def reconcile_page_runtime(*args: Any, **kwargs: Any) -> Any:
        return reconcile_page_runtime(*args, **kwargs)

    @staticmethod
    def lifecycle(**kwargs: Any) -> str:
        return lifecycle_status(**kwargs)


R3_5ApplicationService = R35ApplicationService
