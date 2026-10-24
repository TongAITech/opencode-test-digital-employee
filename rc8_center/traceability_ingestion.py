"""RC8 Center-controlled traceability ingestion.

Workers/LLMs submit raw observations only. This service is the sole policy
boundary allowed to materialize those observations into the existing durable
TraceGraph and upgrade CANDIDATE edges. It never creates a second graph model.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

from .runtime_attempt_authority import RuntimeAttemptAuthority, RuntimeAttemptAuthoritySnapshot, RuntimeEvidenceAuthorityContext
from .traceability import TraceEdge, TraceEvidence, TraceNode, TraceNodeType, TraceRelationType, TraceVerificationState, TraceabilityError


class TraceObservationSource(str, Enum):
    BROWSER_NETWORK = "BROWSER_NETWORK"
    CODEGRAPH = "CODEGRAPH"
    SPRING_MAPPING = "SPRING_MAPPING"
    SOURCE_CODE = "SOURCE_CODE"
    MYBATIS_MAPPING = "MYBATIS_MAPPING"
    JDBC = "JDBC"
    ORM_MAPPING = "ORM_MAPPING"
    SQL = "SQL"
    DATABASE_METADATA = "DATABASE_METADATA"
    LLM_INFERENCE = "LLM_INFERENCE"


@dataclass(frozen=True)
class TraceEndpointObservation:
    node_type: TraceNodeType
    business_key: str
    display_name: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "TraceEndpointObservation":
        TraceNodeType(self.node_type)
        if not str(self.business_key or "").strip():
            raise TraceabilityError("TRACE_OBSERVATION_ENDPOINT_BUSINESS_KEY_REQUIRED")
        if not str(self.display_name or "").strip():
            raise TraceabilityError("TRACE_OBSERVATION_ENDPOINT_DISPLAY_NAME_REQUIRED")
        return self


@dataclass(frozen=True)
class RawTraceObservation:
    observation_id: str
    graph_id: str
    source_kind: TraceObservationSource
    source_ref: str
    from_endpoint: TraceEndpointObservation
    to_endpoint: TraceEndpointObservation
    relation_type: TraceRelationType
    captured_at: int
    integrity_hash: str
    stage_id: Optional[str] = None
    work_item_id: Optional[str] = None
    attempt_id: Optional[str] = None
    producer_node_id: Optional[str] = None
    artifact_id: Optional[str] = None
    requested_verification: TraceVerificationState = TraceVerificationState.CANDIDATE
    payload: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "RawTraceObservation":
        for error, value in (
            ("TRACE_OBSERVATION_ID_REQUIRED", self.observation_id),
            ("TRACE_OBSERVATION_GRAPH_ID_REQUIRED", self.graph_id),
            ("TRACE_OBSERVATION_SOURCE_REF_REQUIRED", self.source_ref),
            ("TRACE_OBSERVATION_INTEGRITY_HASH_REQUIRED", self.integrity_hash),
        ):
            if not str(value or "").strip():
                raise TraceabilityError(error)
        TraceObservationSource(self.source_kind)
        TraceRelationType(self.relation_type)
        TraceVerificationState(self.requested_verification)
        if self.requested_verification != TraceVerificationState.CANDIDATE:
            raise TraceabilityError("WORKER_VERIFICATION_REQUEST_FORBIDDEN")
        if int(self.captured_at) <= 0:
            raise TraceabilityError("TRACE_OBSERVATION_CAPTURED_AT_REQUIRED")
        self.from_endpoint.validate()
        self.to_endpoint.validate()
        return self


@dataclass(frozen=True)
class TraceIngestionReceipt:
    observation_id: str
    graph_id: str
    edge_id: str
    evidence_id: str
    verification_state: TraceVerificationState
    disposition: str
    policy_code: str


_CODE_NODE_TYPES = {TraceNodeType.CONTROLLER, TraceNodeType.METHOD, TraceNodeType.SERVICE, TraceNodeType.REPOSITORY, TraceNodeType.MAPPER}
_PERSISTENCE_ORIGINS = {TraceNodeType.REPOSITORY, TraceNodeType.MAPPER}
_RUNTIME_SOURCES = {TraceObservationSource.BROWSER_NETWORK}


class CenterTraceabilityIngestion:
    policy_version = "rc8.trace-ingestion-center.v2"

    def __init__(self, repository, *, control_plane=None, attempt_snapshot_resolver: Optional[Callable[[str], RuntimeAttemptAuthoritySnapshot]] = None) -> None:
        self.repository = repository
        self.control_plane = control_plane
        self.attempt_snapshot_resolver = attempt_snapshot_resolver

    def ingest(self, observation: RawTraceObservation) -> TraceIngestionReceipt:
        observation.validate()
        graph = self.repository.get_graph(observation.graph_id)
        if graph is None:
            raise TraceabilityError("TRACE_OBSERVATION_GRAPH_NOT_FOUND")
        self._authorize_runtime_observation(observation, graph)
        target_state, policy_code, confidence, evidence_type = self._policy(observation)
        source = self._upsert_node(observation.graph_id, graph, observation.from_endpoint, observation.captured_at)
        target = self._upsert_node(observation.graph_id, graph, observation.to_endpoint, observation.captured_at)
        edge = self._upsert_edge(observation, source, target)
        evidence_id = "trace-evidence:%s" % observation.observation_id

        prior = self._find_evidence_by_id(observation.graph_id, evidence_id)
        if prior is not None:
            if prior.edge_id != edge.edge_id or prior.integrity_hash != observation.integrity_hash or prior.source != observation.source_ref:
                raise TraceabilityError("TRACE_OBSERVATION_ID_CONFLICT")
            current = self._edge_by_id(observation.graph_id, edge.edge_id)
            return TraceIngestionReceipt(observation.observation_id, observation.graph_id, edge.edge_id, evidence_id, current.verification_state, "IDEMPOTENT_REPLAY", policy_code)

        payload = dict(observation.payload)
        payload.update({
            "center_policy": self.policy_version,
            "raw_source_kind": observation.source_kind.value,
            "from_payload": dict(observation.from_endpoint.payload),
            "to_payload": dict(observation.to_endpoint.payload),
        })
        if observation.source_kind in _RUNTIME_SOURCES:
            payload.update({
                "runtime_authority": "CURRENT_ATTEMPT_AND_ACTIVE_LEASE",
                "producer_node_id": observation.producer_node_id,
            })
        evidence = TraceEvidence(
            evidence_id=evidence_id,
            graph_id=observation.graph_id,
            edge_id=edge.edge_id,
            evidence_type=evidence_type,
            source=observation.source_ref,
            artifact_id=observation.artifact_id,
            test_run_id=graph.test_run_id,
            stage_id=observation.stage_id,
            work_item_id=observation.work_item_id,
            attempt_id=observation.attempt_id,
            code_source_snapshot_id=graph.code_source_snapshot_id,
            captured_at=observation.captured_at,
            integrity_hash=observation.integrity_hash,
            payload=payload,
        )
        self.repository.append_evidence(evidence)
        if target_state == TraceVerificationState.CANDIDATE:
            state, disposition = target_state, "CANDIDATE_ONLY"
        else:
            state = self.repository.verify_edge(edge.edge_id, target_state, confidence=confidence).verification_state
            disposition = "CENTER_VERIFIED"
        return TraceIngestionReceipt(observation.observation_id, observation.graph_id, edge.edge_id, evidence_id, state, disposition, policy_code)

    def _authorize_runtime_observation(self, observation, graph) -> None:
        if observation.source_kind not in _RUNTIME_SOURCES:
            return
        if self.control_plane is None or self.attempt_snapshot_resolver is None:
            raise TraceabilityError("RUNTIME_TRACE_AUTHORITY_NOT_CONFIGURED")
        for error, value in (
            ("RUNTIME_TRACE_WORK_ITEM_REQUIRED", observation.work_item_id),
            ("RUNTIME_TRACE_ATTEMPT_REQUIRED", observation.attempt_id),
            ("RUNTIME_TRACE_PRODUCER_NODE_REQUIRED", observation.producer_node_id),
        ):
            if not str(value or "").strip():
                raise TraceabilityError(error)

        # CenterControlPlane resolves the active lease from Center-owned state;
        # no lease identity supplied by a worker is trusted here.
        work = self.control_plane.authorize_work_item_write(
            test_run_id=graph.test_run_id,
            work_item_id=observation.work_item_id,
            node_id=observation.producer_node_id,
        )
        current = self.attempt_snapshot_resolver(observation.work_item_id)
        if current is None:
            raise TraceabilityError("CURRENT_ATTEMPT_AUTHORITY_NOT_FOUND")
        if work.lease_owner_node_id != current.lease_owner_node_id:
            raise TraceabilityError("ATTEMPT_LEASE_OWNER_DRIFT")
        if work.lease_expires_at is None or int(work.lease_expires_at) != int(current.lease_expires_at):
            raise TraceabilityError("ATTEMPT_LEASE_WINDOW_DRIFT")
        try:
            RuntimeAttemptAuthority.authorize(
                current=current,
                evidence=RuntimeEvidenceAuthorityContext(
                    work_item_id=observation.work_item_id,
                    attempt_id=observation.attempt_id,
                    producer_node_id=observation.producer_node_id,
                    observed_at=observation.captured_at,
                ),
                now=int(self.control_plane._now()),
            )
        except RuntimeError as exc:
            raise TraceabilityError(str(exc)) from exc

    def _policy(self, observation: RawTraceObservation) -> Tuple[TraceVerificationState, str, float, str]:
        source, src, dst, relation = observation.source_kind, observation.from_endpoint.node_type, observation.to_endpoint.node_type, observation.relation_type
        if source == TraceObservationSource.LLM_INFERENCE:
            if dst == TraceNodeType.TABLE or relation in {TraceRelationType.EXECUTES_SQL, TraceRelationType.READS_TABLE, TraceRelationType.WRITES_TABLE}:
                raise TraceabilityError("PERSISTENCE_GUESS_FORBIDDEN")
            return TraceVerificationState.CANDIDATE, "LLM_CANDIDATE_ONLY", 0.25, "LLM_INFERENCE"
        if source == TraceObservationSource.BROWSER_NETWORK:
            if relation != TraceRelationType.PAGE_CALLS_API or src not in {TraceNodeType.PAGE, TraceNodeType.PAGE_ACTION} or dst != TraceNodeType.API:
                raise TraceabilityError("BROWSER_NETWORK_RELATION_FORBIDDEN")
            return TraceVerificationState.RUNTIME_VERIFIED, "BROWSER_NETWORK_PAGE_API", 1.0, "BROWSER_NETWORK"
        if source in {TraceObservationSource.CODEGRAPH, TraceObservationSource.SPRING_MAPPING, TraceObservationSource.SOURCE_CODE}:
            if relation == TraceRelationType.API_IMPLEMENTED_BY and src == TraceNodeType.API and dst in {TraceNodeType.CONTROLLER, TraceNodeType.METHOD}:
                return TraceVerificationState.STATIC_VERIFIED, "STATIC_API_IMPLEMENTATION", 1.0, source.value
            if relation == TraceRelationType.CALLS and src in _CODE_NODE_TYPES and dst in _CODE_NODE_TYPES and source != TraceObservationSource.SPRING_MAPPING:
                return TraceVerificationState.STATIC_VERIFIED, "STATIC_CODE_CALL_CHAIN", 1.0, source.value
            raise TraceabilityError("STATIC_CODE_RELATION_FORBIDDEN")
        if source in {TraceObservationSource.MYBATIS_MAPPING, TraceObservationSource.JDBC, TraceObservationSource.ORM_MAPPING, TraceObservationSource.SQL, TraceObservationSource.DATABASE_METADATA}:
            if relation == TraceRelationType.EXECUTES_SQL and src in _PERSISTENCE_ORIGINS and dst == TraceNodeType.SQL:
                if source == TraceObservationSource.JDBC and not any(key in observation.payload for key in ("sql", "sql_text", "statement")):
                    raise TraceabilityError("JDBC_EXPLICIT_SQL_REQUIRED")
                if source == TraceObservationSource.ORM_MAPPING and not any(key in observation.payload for key in ("table", "mapping", "entity_table")):
                    raise TraceabilityError("ORM_EXPLICIT_MAPPING_REQUIRED")
                evidence_type = "SQL" if source == TraceObservationSource.JDBC else ("DATABASE_METADATA" if source == TraceObservationSource.ORM_MAPPING else source.value)
                return TraceVerificationState.STATIC_VERIFIED, "EXPLICIT_PERSISTENCE_SQL", 1.0, evidence_type
            if relation in {TraceRelationType.READS_TABLE, TraceRelationType.WRITES_TABLE} and src == TraceNodeType.SQL and dst == TraceNodeType.TABLE:
                evidence_type = "DATABASE_METADATA" if source == TraceObservationSource.ORM_MAPPING else ("SQL" if source == TraceObservationSource.JDBC else source.value)
                return TraceVerificationState.STATIC_VERIFIED, "EXPLICIT_SQL_TABLE", 1.0, evidence_type
            raise TraceabilityError("PERSISTENCE_RELATION_FORBIDDEN")
        raise TraceabilityError("TRACE_OBSERVATION_SOURCE_UNSUPPORTED")

    def _upsert_node(self, graph_id, graph, endpoint, created_at):
        matches = self.repository.find_nodes(graph_id, node_type=endpoint.node_type, business_key=endpoint.business_key)
        if len(matches) > 1:
            raise TraceabilityError("TRACE_NODE_BUSINESS_KEY_AMBIGUOUS")
        if matches:
            return matches[0]
        node = TraceNode(
            node_id=self._stable_id("node", graph_id, endpoint.node_type.value, endpoint.business_key), graph_id=graph_id,
            node_type=endpoint.node_type, business_key=endpoint.business_key, display_name=endpoint.display_name, created_at=created_at,
            source_snapshot_id=graph.code_source_snapshot_id, scope_revision_id=graph.scope_revision_id, payload=dict(endpoint.payload),
        )
        return self.repository.add_node(node)

    def _upsert_edge(self, observation, source, target):
        for edge in self.repository.list_edges(observation.graph_id):
            if edge.from_node_id == source.node_id and edge.to_node_id == target.node_id and edge.relation_type == observation.relation_type:
                return edge
        edge = TraceEdge(
            edge_id=self._stable_id("edge", observation.graph_id, source.node_id, target.node_id, observation.relation_type.value),
            graph_id=observation.graph_id, from_node_id=source.node_id, to_node_id=target.node_id,
            relation_type=observation.relation_type, created_at=observation.captured_at,
            verification_state=TraceVerificationState.CANDIDATE, confidence=0.0, evidence_count=0,
            payload={"created_by": self.policy_version},
        )
        return self.repository.add_edge(edge)

    def _edge_by_id(self, graph_id, edge_id):
        for edge in self.repository.list_edges(graph_id):
            if edge.edge_id == edge_id:
                return edge
        raise TraceabilityError("TRACE_EDGE_NOT_FOUND")

    def _find_evidence_by_id(self, graph_id, evidence_id):
        for edge in self.repository.list_edges(graph_id):
            for evidence in self.repository.list_evidence(edge.edge_id):
                if evidence.evidence_id == evidence_id:
                    return evidence
        return None

    @staticmethod
    def _stable_id(*parts):
        digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
        return "trace-%s-%s" % (parts[0], digest)
