"""PostgreSQL persistence and deterministic query/verification for RC8 traceability."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import BigInteger, Float, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.code_source import CodeSourceSnapshot
from rc8_center.traceability import (
    TraceEdge,
    TraceEvidence,
    TraceNode,
    TraceNodeType,
    TraceRelationType,
    TraceVerificationState,
    TraceabilityError,
    TraceabilityGraph,
)

from .postgres import Base, PostgresStore, TestRunRow


STATIC_EVIDENCE_TYPES = {
    "REQUIREMENT_DOCUMENT",
    "SPRING_MAPPING",
    "CODEGRAPH",
    "SOURCE_CODE",
    "MYBATIS_MAPPING",
    "SQL",
    "DATABASE_METADATA",
}
RUNTIME_EVIDENCE_TYPES = {
    "BROWSER_NETWORK",
    "PAGE_RUNTIME",
    "APPLICATION_LOG",
    "STARLINK",
    "TEST_EXECUTION",
}


class CodeSourceSnapshotRow(Base):
    __tablename__ = "rc8_code_source_snapshot"

    snapshot_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    identity: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    repository_id: Mapped[str] = mapped_column(String(240), nullable=False)
    repository_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    application_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    base_commit_sha: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    commit_sha: Mapped[str] = mapped_column(String(160), nullable=False)
    subpath: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    test_round_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    scope_revision_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    system_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    system_version: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class TraceabilityGraphRow(Base):
    __tablename__ = "rc8_traceability_graph"
    __table_args__ = (
        UniqueConstraint("test_run_id", "scope_revision_id", "code_source_snapshot_id", name="uq_rc8_trace_graph_frozen_scope"),
    )

    graph_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    test_round_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    scope_revision_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    code_source_snapshot_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class TraceNodeRow(Base):
    __tablename__ = "rc8_trace_node"
    __table_args__ = (
        UniqueConstraint("graph_id", "node_type", "business_key", name="uq_rc8_trace_node_business_key"),
    )

    node_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    business_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    display_name: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_snapshot_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    scope_revision_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class TraceEdgeRow(Base):
    __tablename__ = "rc8_trace_edge"
    __table_args__ = (
        UniqueConstraint("graph_id", "from_node_id", "to_node_id", "relation_type", name="uq_rc8_trace_edge_relation"),
    )

    edge_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    from_node_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    to_node_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    verification_state: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evidence_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class TraceEvidenceRow(Base):
    __tablename__ = "rc8_trace_evidence"

    evidence_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    edge_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(1000), nullable=False)
    artifact_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stage_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    work_item_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    attempt_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    code_source_snapshot_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    captured_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    integrity_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class PostgresTraceabilityRepository:
    """Durable graph projection with fail-closed evidence verification."""

    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def freeze_code_source(
        self,
        snapshot: CodeSourceSnapshot,
        *,
        test_round_id: str,
        scope_revision_id: str,
        system_id: Optional[str] = None,
        system_version: Optional[str] = None,
    ) -> CodeSourceSnapshotRow:
        snapshot.validate()
        if not test_round_id.strip():
            raise TraceabilityError("CODE_SOURCE_TEST_ROUND_ID_REQUIRED")
        if not scope_revision_id.strip():
            raise TraceabilityError("CODE_SOURCE_SCOPE_REVISION_ID_REQUIRED")
        with self.store.session() as session:
            existing = session.get(CodeSourceSnapshotRow, snapshot.snapshot_id)
            if existing is not None:
                if (
                    existing.identity != snapshot.identity
                    or existing.test_round_id != test_round_id
                    or existing.scope_revision_id != scope_revision_id
                ):
                    raise TraceabilityError("CODE_SOURCE_SNAPSHOT_IMMUTABLE")
                return existing
            row = CodeSourceSnapshotRow(
                snapshot_id=snapshot.snapshot_id,
                identity=snapshot.identity,
                repository_id=snapshot.repository_id,
                repository_url=snapshot.repository_url,
                application_id=snapshot.application_id,
                base_commit_sha=snapshot.base_commit_sha,
                commit_sha=snapshot.commit_sha,
                subpath=snapshot.subpath,
                test_round_id=test_round_id,
                scope_revision_id=scope_revision_id,
                system_id=system_id,
                system_version=system_version,
                created_at=int(snapshot.created_at),
                payload=dict(snapshot.payload),
            )
            session.add(row)
            return row

    def get_code_source(self, snapshot_id: str) -> Optional[CodeSourceSnapshotRow]:
        with self.store.session() as session:
            return session.get(CodeSourceSnapshotRow, snapshot_id)

    def create_graph(self, value: TraceabilityGraph) -> TraceabilityGraph:
        value.validate()
        with self.store.session() as session:
            if session.get(TraceabilityGraphRow, value.graph_id) is not None:
                raise TraceabilityError("TRACE_GRAPH_ALREADY_EXISTS")
            run = session.get(TestRunRow, value.test_run_id)
            if run is None:
                raise TraceabilityError("TRACE_TEST_RUN_NOT_FOUND")
            if run.test_round_id and run.test_round_id != value.test_round_id:
                raise TraceabilityError("TRACE_TEST_ROUND_MISMATCH")
            source = session.get(CodeSourceSnapshotRow, value.code_source_snapshot_id)
            if source is None:
                raise TraceabilityError("TRACE_CODE_SOURCE_SNAPSHOT_NOT_FOUND")
            if source.test_round_id != value.test_round_id:
                raise TraceabilityError("TRACE_CODE_SOURCE_TEST_ROUND_MISMATCH")
            if source.scope_revision_id != value.scope_revision_id:
                raise TraceabilityError("TRACE_CODE_SOURCE_SCOPE_REVISION_MISMATCH")
            session.add(
                TraceabilityGraphRow(
                    graph_id=value.graph_id,
                    test_run_id=value.test_run_id,
                    test_round_id=value.test_round_id,
                    scope_revision_id=value.scope_revision_id,
                    code_source_snapshot_id=value.code_source_snapshot_id,
                    created_at=value.created_at,
                    payload=dict(value.payload),
                )
            )
        return value

    def add_node(self, value: TraceNode) -> TraceNode:
        value.validate()
        with self.store.session() as session:
            graph = session.get(TraceabilityGraphRow, value.graph_id)
            if graph is None:
                raise TraceabilityError("TRACE_GRAPH_NOT_FOUND")
            if session.get(TraceNodeRow, value.node_id) is not None:
                raise TraceabilityError("TRACE_NODE_ALREADY_EXISTS")
            session.add(
                TraceNodeRow(
                    node_id=value.node_id,
                    graph_id=value.graph_id,
                    node_type=TraceNodeType(value.node_type).value,
                    business_key=value.business_key,
                    display_name=value.display_name,
                    source_snapshot_id=value.source_snapshot_id or graph.code_source_snapshot_id,
                    scope_revision_id=value.scope_revision_id or graph.scope_revision_id,
                    created_at=value.created_at,
                    payload=dict(value.payload),
                )
            )
        return value

    def add_edge(self, value: TraceEdge) -> TraceEdge:
        value.validate()
        if TraceVerificationState(value.verification_state) != TraceVerificationState.CANDIDATE:
            raise TraceabilityError("TRACE_EDGE_MUST_START_AS_CANDIDATE")
        if int(value.evidence_count) != 0:
            raise TraceabilityError("TRACE_EDGE_CANDIDATE_CANNOT_HAVE_EVIDENCE_COUNT")
        with self.store.session() as session:
            graph = session.get(TraceabilityGraphRow, value.graph_id)
            if graph is None:
                raise TraceabilityError("TRACE_GRAPH_NOT_FOUND")
            source = session.get(TraceNodeRow, value.from_node_id)
            target = session.get(TraceNodeRow, value.to_node_id)
            if source is None or target is None:
                raise TraceabilityError("TRACE_EDGE_NODE_NOT_FOUND")
            if source.graph_id != value.graph_id or target.graph_id != value.graph_id:
                raise TraceabilityError("TRACE_EDGE_CROSS_GRAPH_FORBIDDEN")
            if session.get(TraceEdgeRow, value.edge_id) is not None:
                raise TraceabilityError("TRACE_EDGE_ALREADY_EXISTS")
            session.add(
                TraceEdgeRow(
                    edge_id=value.edge_id,
                    graph_id=value.graph_id,
                    from_node_id=value.from_node_id,
                    to_node_id=value.to_node_id,
                    relation_type=TraceRelationType(value.relation_type).value,
                    verification_state=TraceVerificationState.CANDIDATE.value,
                    confidence=float(value.confidence),
                    evidence_count=0,
                    created_at=value.created_at,
                    payload=dict(value.payload),
                )
            )
        return value

    def append_evidence(self, value: TraceEvidence) -> TraceEvidence:
        value.validate()
        with self.store.session() as session:
            if session.get(TraceEvidenceRow, value.evidence_id) is not None:
                raise TraceabilityError("TRACE_EVIDENCE_ALREADY_EXISTS")
            graph = session.get(TraceabilityGraphRow, value.graph_id)
            edge = session.get(TraceEdgeRow, value.edge_id)
            if graph is None or edge is None or edge.graph_id != value.graph_id:
                raise TraceabilityError("TRACE_EVIDENCE_EDGE_NOT_FOUND")
            if graph.test_run_id != value.test_run_id:
                raise TraceabilityError("TRACE_EVIDENCE_TEST_RUN_MISMATCH")
            if graph.code_source_snapshot_id != value.code_source_snapshot_id:
                raise TraceabilityError("TRACE_EVIDENCE_CODE_SOURCE_MISMATCH")
            session.add(
                TraceEvidenceRow(
                    evidence_id=value.evidence_id,
                    graph_id=value.graph_id,
                    edge_id=value.edge_id,
                    evidence_type=value.evidence_type.strip().upper(),
                    source=value.source,
                    artifact_id=value.artifact_id,
                    test_run_id=value.test_run_id,
                    stage_id=value.stage_id,
                    work_item_id=value.work_item_id,
                    attempt_id=value.attempt_id,
                    code_source_snapshot_id=value.code_source_snapshot_id,
                    captured_at=value.captured_at,
                    integrity_hash=value.integrity_hash,
                    payload=dict(value.payload),
                )
            )
            edge.evidence_count = int(edge.evidence_count) + 1
        return value

    def verify_edge(
        self,
        edge_id: str,
        target_state: TraceVerificationState,
        *,
        confidence: float,
    ) -> TraceEdge:
        state = TraceVerificationState(target_state)
        if state not in {
            TraceVerificationState.STATIC_VERIFIED,
            TraceVerificationState.RUNTIME_VERIFIED,
            TraceVerificationState.MULTI_SOURCE_VERIFIED,
        }:
            raise TraceabilityError("TRACE_VERIFICATION_TARGET_INVALID")
        if not 0.0 <= float(confidence) <= 1.0:
            raise TraceabilityError("TRACE_EDGE_CONFIDENCE_INVALID")
        with self.store.session() as session:
            edge = session.get(TraceEdgeRow, edge_id)
            if edge is None:
                raise TraceabilityError("TRACE_EDGE_NOT_FOUND")
            types = {
                str(value).upper()
                for value in session.scalars(
                    select(TraceEvidenceRow.evidence_type).where(TraceEvidenceRow.edge_id == edge_id)
                )
            }
            has_static = bool(types & STATIC_EVIDENCE_TYPES)
            has_runtime = bool(types & RUNTIME_EVIDENCE_TYPES)
            if state == TraceVerificationState.STATIC_VERIFIED and not has_static:
                raise TraceabilityError("TRACE_STATIC_EVIDENCE_REQUIRED")
            if state == TraceVerificationState.RUNTIME_VERIFIED and not has_runtime:
                raise TraceabilityError("TRACE_RUNTIME_EVIDENCE_REQUIRED")
            if state == TraceVerificationState.MULTI_SOURCE_VERIFIED and not (has_static and has_runtime):
                raise TraceabilityError("TRACE_MULTI_SOURCE_EVIDENCE_REQUIRED")
            edge.verification_state = state.value
            edge.confidence = float(confidence)
            return self._edge(edge)

    def mark_edge_state(self, edge_id: str, state: TraceVerificationState) -> TraceEdge:
        target = TraceVerificationState(state)
        if target not in {TraceVerificationState.CONFLICTED, TraceVerificationState.INVALIDATED}:
            raise TraceabilityError("TRACE_EDGE_STATE_TRANSITION_NOT_ALLOWED")
        with self.store.session() as session:
            row = session.get(TraceEdgeRow, edge_id)
            if row is None:
                raise TraceabilityError("TRACE_EDGE_NOT_FOUND")
            row.verification_state = target.value
            return self._edge(row)

    def get_graph(self, graph_id: str) -> Optional[TraceabilityGraph]:
        with self.store.session() as session:
            row = session.get(TraceabilityGraphRow, graph_id)
            return self._graph(row) if row is not None else None

    def find_nodes(
        self,
        graph_id: str,
        *,
        node_type: Optional[TraceNodeType] = None,
        business_key: Optional[str] = None,
    ) -> List[TraceNode]:
        with self.store.session() as session:
            query = select(TraceNodeRow).where(TraceNodeRow.graph_id == graph_id)
            if node_type is not None:
                query = query.where(TraceNodeRow.node_type == TraceNodeType(node_type).value)
            if business_key is not None:
                query = query.where(TraceNodeRow.business_key == business_key)
            rows = session.scalars(query.order_by(TraceNodeRow.node_type, TraceNodeRow.business_key))
            return [self._node(row) for row in rows]

    def list_edges(self, graph_id: str) -> List[TraceEdge]:
        with self.store.session() as session:
            rows = session.scalars(
                select(TraceEdgeRow).where(TraceEdgeRow.graph_id == graph_id).order_by(TraceEdgeRow.created_at, TraceEdgeRow.edge_id)
            )
            return [self._edge(row) for row in rows]

    def list_evidence(self, edge_id: str) -> List[TraceEvidence]:
        with self.store.session() as session:
            rows = session.scalars(
                select(TraceEvidenceRow).where(TraceEvidenceRow.edge_id == edge_id).order_by(TraceEvidenceRow.captured_at, TraceEvidenceRow.evidence_id)
            )
            return [self._evidence(row) for row in rows]

    def query_impact(
        self,
        graph_id: str,
        root_node_id: str,
        *,
        direction: str = "both",
        max_depth: int = 8,
    ) -> Tuple[List[TraceNode], List[TraceEdge]]:
        """Return deterministic forward/reverse/bidirectional reachable subgraph."""
        if direction not in {"forward", "reverse", "both"}:
            raise TraceabilityError("TRACE_QUERY_DIRECTION_INVALID")
        if max_depth < 0 or max_depth > 32:
            raise TraceabilityError("TRACE_QUERY_DEPTH_INVALID")
        with self.store.session() as session:
            root = session.get(TraceNodeRow, root_node_id)
            if root is None or root.graph_id != graph_id:
                raise TraceabilityError("TRACE_QUERY_ROOT_NOT_FOUND")
            all_nodes = list(session.scalars(select(TraceNodeRow).where(TraceNodeRow.graph_id == graph_id)))
            all_edges = list(session.scalars(select(TraceEdgeRow).where(TraceEdgeRow.graph_id == graph_id)))

        node_map = {row.node_id: row for row in all_nodes}
        visited = {root_node_id}
        selected_edges: Dict[str, TraceEdgeRow] = {}
        frontier = {root_node_id}
        for _ in range(max_depth):
            next_frontier = set()
            for edge in all_edges:
                follow = False
                candidate = None
                if direction in {"forward", "both"} and edge.from_node_id in frontier:
                    follow = True
                    candidate = edge.to_node_id
                if direction in {"reverse", "both"} and edge.to_node_id in frontier:
                    follow = True
                    candidate = edge.from_node_id if candidate is None else candidate
                if follow:
                    selected_edges[edge.edge_id] = edge
                    if candidate is not None and candidate not in visited:
                        next_frontier.add(candidate)
            if not next_frontier:
                break
            visited.update(next_frontier)
            frontier = next_frontier
        nodes = [self._node(node_map[node_id]) for node_id in sorted(visited) if node_id in node_map]
        edges = [self._edge(row) for _, row in sorted(selected_edges.items())]
        return nodes, edges

    @staticmethod
    def _graph(row: TraceabilityGraphRow) -> TraceabilityGraph:
        return TraceabilityGraph(
            graph_id=row.graph_id,
            test_run_id=row.test_run_id,
            test_round_id=row.test_round_id,
            scope_revision_id=row.scope_revision_id,
            code_source_snapshot_id=row.code_source_snapshot_id,
            created_at=int(row.created_at),
            payload=dict(row.payload or {}),
        )

    @staticmethod
    def _node(row: TraceNodeRow) -> TraceNode:
        return TraceNode(
            node_id=row.node_id,
            graph_id=row.graph_id,
            node_type=TraceNodeType(row.node_type),
            business_key=row.business_key,
            display_name=row.display_name,
            source_snapshot_id=row.source_snapshot_id,
            scope_revision_id=row.scope_revision_id,
            created_at=int(row.created_at),
            payload=dict(row.payload or {}),
        )

    @staticmethod
    def _edge(row: TraceEdgeRow) -> TraceEdge:
        return TraceEdge(
            edge_id=row.edge_id,
            graph_id=row.graph_id,
            from_node_id=row.from_node_id,
            to_node_id=row.to_node_id,
            relation_type=TraceRelationType(row.relation_type),
            verification_state=TraceVerificationState(row.verification_state),
            confidence=float(row.confidence),
            evidence_count=int(row.evidence_count),
            created_at=int(row.created_at),
            payload=dict(row.payload or {}),
        )

    @staticmethod
    def _evidence(row: TraceEvidenceRow) -> TraceEvidence:
        return TraceEvidence(
            evidence_id=row.evidence_id,
            graph_id=row.graph_id,
            edge_id=row.edge_id,
            evidence_type=row.evidence_type,
            source=row.source,
            artifact_id=row.artifact_id,
            test_run_id=row.test_run_id,
            stage_id=row.stage_id,
            work_item_id=row.work_item_id,
            attempt_id=row.attempt_id,
            code_source_snapshot_id=row.code_source_snapshot_id,
            captured_at=int(row.captured_at),
            integrity_hash=row.integrity_hash,
            payload=dict(row.payload or {}),
        )
