"""R1-first trace ingestion for authoritative N3 runtime observations.

A browser/network observation is authorized against the current Center Attempt
and lease before it enters R1. R1 records the complete replay payload before
PostgreSQL TraceGraph projection is mutated. Recovery replays only canonical
TRACE_OBSERVATION_ACCEPTED events; it never asks an expired historical lease to
re-authorize evidence that R1 already accepted while that lease was current.
"""
from __future__ import annotations

from rc8_runtime import RuntimeEventEnvelope, RuntimeProducerKind

from .traceability import TraceNodeType, TraceRelationType, TraceVerificationState, TraceabilityError
from .traceability_ingestion import (
    CenterTraceabilityIngestion,
    RawTraceObservation,
    TraceEndpointObservation,
    TraceObservationSource,
)


class _CanonicalR1TraceProjector(CenterTraceabilityIngestion):
    """Projection-only boundary for events already authorized into canonical R1.

    This deliberately bypasses *live* lease authorization only during replay.
    Callers cannot submit raw observations here; the enclosing service builds
    observations exclusively from durable R1 envelopes after identity/schema
    checks. All Center verification policy and repository idempotency remain in
    the normal CenterTraceabilityIngestion implementation.
    """

    def _authorize_runtime_observation(self, observation, graph) -> None:
        return None


class R1BackedCenterTraceabilityIngestion(CenterTraceabilityIngestion):
    policy_version = "rc8.trace-ingestion-center.r1.v2"

    def __init__(self, repository, *, ledger, control_plane=None, attempt_snapshot_resolver=None) -> None:
        super().__init__(
            repository,
            control_plane=control_plane,
            attempt_snapshot_resolver=attempt_snapshot_resolver,
        )
        if ledger is None:
            raise ValueError("TRACE_R1_LEDGER_REQUIRED")
        self.ledger = ledger
        self._canonical_projector = _CanonicalR1TraceProjector(repository)

    def ingest(self, observation: RawTraceObservation):
        observation.validate()
        graph = self.repository.get_graph(observation.graph_id)
        if graph is None:
            raise TraceabilityError("TRACE_OBSERVATION_GRAPH_NOT_FOUND")

        if observation.source_kind == TraceObservationSource.BROWSER_NETWORK:
            self._authorize_runtime_observation(observation, graph)
            self.ledger.append_runtime(self._runtime_event(observation, graph.test_run_id))

        # Repeat live authority intentionally to close the authorization->R1->
        # PostgreSQL race. If it changed, R1 remains canonical and startup
        # replay repairs the projection without rewriting history.
        return super().ingest(observation)

    def replay_canonical_runtime_observations(self):
        """Rebuild missing PostgreSQL trace projection from canonical R1.

        R1 is append-only truth, so recovery never fabricates a new runtime
        event or reuses current lease state to judge a historical accepted
        event. Malformed canonical events fail closed and abort startup rather
        than being silently skipped.
        """
        receipts = []
        for event in self.ledger.runtime_events():
            if event.get("event_type") != "TRACE_OBSERVATION_ACCEPTED":
                continue
            observation = self._observation_from_canonical_event(event)
            receipts.append(self._canonical_projector.ingest(observation))
        return receipts

    @staticmethod
    def _observation_from_canonical_event(event):
        data = event.get("data")
        if not isinstance(data, dict) or data.get("schema") != "rc8.trace-observation.v1":
            raise TraceabilityError("R1_TRACE_OBSERVATION_SCHEMA_INVALID")
        observation_id = data.get("observation_id")
        if event.get("event_id") != "trace-observation:%s" % observation_id:
            raise TraceabilityError("R1_TRACE_OBSERVATION_IDENTITY_MISMATCH")
        for key in ("graph_id", "source_kind", "source_ref", "relation_type", "captured_at", "integrity_hash"):
            if data.get(key) in (None, ""):
                raise TraceabilityError("R1_TRACE_OBSERVATION_FIELD_REQUIRED:%s" % key)
        if int(event.get("occurred_at") or 0) != int(data["captured_at"]):
            raise TraceabilityError("R1_TRACE_OBSERVATION_TIME_MISMATCH")
        source = R1BackedCenterTraceabilityIngestion._endpoint_from_data(data.get("from_endpoint"), "FROM")
        target = R1BackedCenterTraceabilityIngestion._endpoint_from_data(data.get("to_endpoint"), "TO")
        return RawTraceObservation(
            observation_id=str(observation_id),
            graph_id=str(data["graph_id"]),
            source_kind=TraceObservationSource(data["source_kind"]),
            source_ref=str(data["source_ref"]),
            from_endpoint=source,
            to_endpoint=target,
            relation_type=TraceRelationType(data["relation_type"]),
            captured_at=int(data["captured_at"]),
            integrity_hash=str(data["integrity_hash"]),
            work_item_id=event.get("work_item_id"),
            attempt_id=event.get("attempt_id"),
            producer_node_id=event.get("node_id"),
            artifact_id=data.get("artifact_id"),
            requested_verification=TraceVerificationState.CANDIDATE,
            payload=dict(data.get("payload") or {}),
        )

    @staticmethod
    def _endpoint_from_data(raw, side):
        if not isinstance(raw, dict):
            raise TraceabilityError("R1_TRACE_%s_ENDPOINT_INVALID" % side)
        return TraceEndpointObservation(
            node_type=TraceNodeType(raw.get("node_type")),
            business_key=str(raw.get("business_key") or ""),
            display_name=str(raw.get("display_name") or ""),
            payload=dict(raw.get("payload") or {}),
        )

    @staticmethod
    def _runtime_event(observation: RawTraceObservation, test_run_id: str) -> RuntimeEventEnvelope:
        source = observation.from_endpoint
        target = observation.to_endpoint
        data = {
            "schema": "rc8.trace-observation.v1",
            "observation_id": observation.observation_id,
            "graph_id": observation.graph_id,
            "source_kind": observation.source_kind.value,
            "source_ref": observation.source_ref,
            "relation_type": observation.relation_type.value,
            "captured_at": int(observation.captured_at),
            "integrity_hash": observation.integrity_hash,
            "artifact_id": observation.artifact_id,
            "from_endpoint": {
                "node_type": source.node_type.value,
                "business_key": source.business_key,
                "display_name": source.display_name,
                "payload": dict(source.payload),
            },
            "to_endpoint": {
                "node_type": target.node_type.value,
                "business_key": target.business_key,
                "display_name": target.display_name,
                "payload": dict(target.payload),
            },
            "payload": dict(observation.payload),
        }
        refs = [observation.source_ref]
        if observation.artifact_id:
            refs.append(observation.artifact_id)
        return RuntimeEventEnvelope(
            event_id="trace-observation:%s" % observation.observation_id,
            test_run_id=test_run_id,
            work_item_id=observation.work_item_id,
            node_id=observation.producer_node_id,
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref="center:traceability-ingestion",
            event_type="TRACE_OBSERVATION_ACCEPTED",
            sequence=0,
            attempt_id=observation.attempt_id,
            refs=refs,
            data=data,
            occurred_at=int(observation.captured_at),
        )
