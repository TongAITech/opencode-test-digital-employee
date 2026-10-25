"""R1-first trace ingestion for authoritative N3 runtime observations.

A browser/network observation is authorized against the current Center Attempt
and lease before it enters R1.  R1 then records the complete replay payload
before the PostgreSQL TraceGraph projection is mutated.  This keeps R1 as the
runtime truth: a PostgreSQL failure can be repaired by replaying the accepted
observation, while a stale/unauthorized observation never reaches R1.
"""
from __future__ import annotations

from rc8_runtime import RuntimeEventEnvelope, RuntimeProducerKind

from .traceability_ingestion import (
    CenterTraceabilityIngestion,
    RawTraceObservation,
    TraceObservationSource,
)


class R1BackedCenterTraceabilityIngestion(CenterTraceabilityIngestion):
    policy_version = "rc8.trace-ingestion-center.r1.v1"

    def __init__(self, repository, *, ledger, control_plane=None, attempt_snapshot_resolver=None) -> None:
        super().__init__(
            repository,
            control_plane=control_plane,
            attempt_snapshot_resolver=attempt_snapshot_resolver,
        )
        if ledger is None:
            raise ValueError("TRACE_R1_LEDGER_REQUIRED")
        self.ledger = ledger

    def ingest(self, observation: RawTraceObservation):
        observation.validate()
        graph = self.repository.get_graph(observation.graph_id)
        if graph is None:
            from .traceability import TraceabilityError
            raise TraceabilityError("TRACE_OBSERVATION_GRAPH_NOT_FOUND")

        # Only live browser/network evidence is runtime truth.  Static source
        # analysis remains governed by its source snapshot/TraceGraph contract.
        if observation.source_kind == TraceObservationSource.BROWSER_NETWORK:
            # Fail closed before R1: stale Attempt, wrong producer, expired or
            # drifted lease must never become canonical runtime truth.
            self._authorize_runtime_observation(observation, graph)
            self.ledger.append_runtime(self._runtime_event(observation, graph.test_run_id))

        # Existing ingestion repeats authority checks intentionally.  This
        # closes the race between R1 authorization and PostgreSQL projection;
        # if authority changed, projection fails and R1 remains replayable.
        return super().ingest(observation)

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
