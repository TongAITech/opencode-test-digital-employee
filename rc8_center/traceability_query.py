"""Product-facing traceability read model for RC8.

Business users query by TestRun/TestRound and business keys. Internal graph/node
identities remain implementation details returned for drill-down, not required
inputs on the normal product path.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List, Optional

from sqlalchemy import select

from rc8_center.infrastructure.postgres_traceability import (
    PostgresTraceabilityRepository,
    TraceabilityGraphRow,
)
from rc8_center.traceability import TraceNodeType, TraceabilityError


class TraceabilityQueryService:
    def __init__(self, repository: PostgresTraceabilityRepository) -> None:
        self.repository = repository

    def list_for_test_run(self, test_run_id: str) -> List[Dict[str, object]]:
        return self._list_graphs(test_run_id=test_run_id)

    def list_for_test_round(self, test_round_id: str) -> List[Dict[str, object]]:
        return self._list_graphs(test_round_id=test_round_id)

    def _list_graphs(
        self,
        *,
        test_run_id: Optional[str] = None,
        test_round_id: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        with self.repository.store.session() as session:
            query = select(TraceabilityGraphRow)
            if test_run_id is not None:
                query = query.where(TraceabilityGraphRow.test_run_id == test_run_id)
            if test_round_id is not None:
                query = query.where(TraceabilityGraphRow.test_round_id == test_round_id)
            rows = list(
                session.scalars(
                    query.order_by(
                        TraceabilityGraphRow.scope_revision_id,
                        TraceabilityGraphRow.code_source_snapshot_id,
                    )
                )
            )
        return [
            {
                "graph_id": row.graph_id,
                "test_run_id": row.test_run_id,
                "test_round_id": row.test_round_id,
                "scope_revision_id": row.scope_revision_id,
                "code_source_snapshot_id": row.code_source_snapshot_id,
                "created_at": int(row.created_at),
                "payload": dict(row.payload or {}),
            }
            for row in rows
        ]

    def impact(
        self,
        graph_id: str,
        *,
        node_type: TraceNodeType,
        business_key: str,
        direction: str = "both",
        max_depth: int = 8,
    ) -> Dict[str, object]:
        graph = self.repository.get_graph(graph_id)
        if graph is None:
            raise TraceabilityError("TRACE_GRAPH_NOT_FOUND")
        matches = self.repository.find_nodes(
            graph_id,
            node_type=TraceNodeType(node_type),
            business_key=business_key,
        )
        if not matches:
            raise TraceabilityError("TRACE_QUERY_SUBJECT_NOT_FOUND")
        if len(matches) != 1:
            raise TraceabilityError("TRACE_QUERY_SUBJECT_AMBIGUOUS")
        root = matches[0]
        nodes, edges = self.repository.query_impact(
            graph_id,
            root.node_id,
            direction=direction,
            max_depth=max_depth,
        )
        return {
            "graph": asdict(graph),
            "root": asdict(root),
            "nodes": [asdict(node) for node in nodes],
            "edges": [asdict(edge) for edge in edges],
            "summary": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "candidate_count": sum(1 for edge in edges if edge.verification_state.value == "CANDIDATE"),
                "verified_count": sum(1 for edge in edges if edge.verification_state.value.endswith("VERIFIED")),
                "conflicted_count": sum(1 for edge in edges if edge.verification_state.value == "CONFLICTED"),
                "invalidated_count": sum(1 for edge in edges if edge.verification_state.value == "INVALIDATED"),
            },
        }

    def evidence(self, graph_id: str, edge_id: str) -> List[Dict[str, object]]:
        graph = self.repository.get_graph(graph_id)
        if graph is None:
            raise TraceabilityError("TRACE_GRAPH_NOT_FOUND")
        edge_ids = {edge.edge_id for edge in self.repository.list_edges(graph_id)}
        if edge_id not in edge_ids:
            raise TraceabilityError("TRACE_EDGE_NOT_FOUND")
        return [asdict(value) for value in self.repository.list_evidence(edge_id)]
