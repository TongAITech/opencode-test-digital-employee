"""Real PostgreSQL smoke for RC8 evidence-backed traceability.

This is cloud/integration reality only. It must never be interpreted as bank
reality or TEST_SUFFICIENT.
"""
from __future__ import annotations

import os

from sqlalchemy import inspect

from rc8_center.code_source import CodeSourceSnapshot
from rc8_center.infrastructure.postgres import PostgresStore, build_engine
from rc8_center.infrastructure.postgres_traceability import PostgresTraceabilityRepository
from rc8_center.traceability import (
    TraceEdge,
    TraceEvidence,
    TraceNode,
    TraceNodeType,
    TraceRelationType,
    TraceVerificationState,
    TraceabilityGraph,
)


def main() -> None:
    database_url = os.environ["RC8_DATABASE_URL"]
    engine = build_engine(database_url)
    expected_tables = {
        "rc8_code_source_snapshot",
        "rc8_traceability_graph",
        "rc8_trace_node",
        "rc8_trace_edge",
        "rc8_trace_evidence",
    }
    tables = set(inspect(engine).get_table_names())
    missing = expected_tables - tables
    assert not missing, "missing traceability tables: %s" % sorted(missing)

    store = PostgresStore(engine)
    store.create_test_run(
        "TRACE-CI-RUN",
        production_batch_id="TRACE-CI-BATCH",
        test_round_id="TRACE-CI-ROUND-2",
        now=100,
    )
    repository = PostgresTraceabilityRepository(store)

    snapshot = CodeSourceSnapshot(
        snapshot_id="TRACE-CI-SOURCE-2",
        repository_id="cfg-data",
        repository_url="ssh://bank.invalid/pfc/cfg-data.git",
        application_id="cfg-data",
        base_commit_sha="1" * 40,
        commit_sha="2" * 40,
        subpath="service/core",
        created_at=101,
        payload={"smoke": "cloud-postgres"},
    )
    repository.freeze_code_source(
        snapshot,
        test_round_id="TRACE-CI-ROUND-2",
        scope_revision_id="TRACE-CI-SCOPE-R3",
        system_id="PFC",
        system_version="BLOAN-PF1.2.0",
    )

    graph = TraceabilityGraph(
        graph_id="TRACE-CI-GRAPH",
        test_run_id="TRACE-CI-RUN",
        test_round_id="TRACE-CI-ROUND-2",
        scope_revision_id="TRACE-CI-SCOPE-R3",
        code_source_snapshot_id=snapshot.snapshot_id,
        created_at=102,
    )
    repository.create_graph(graph)

    nodes = [
        TraceNode("TRACE-REQ", graph.graph_id, TraceNodeType.REQUIREMENT, "STBB19-320", "STBB19-320", 103),
        TraceNode("TRACE-PAGE", graph.graph_id, TraceNodeType.PAGE, "/credit/limit", "额度调整页面", 104),
        TraceNode("TRACE-API", graph.graph_id, TraceNodeType.API, "POST /credit/limit/adjust", "提交额度调整", 105),
        TraceNode("TRACE-SERVICE", graph.graph_id, TraceNodeType.SERVICE, "LimitAdjustService.adjust", "LimitAdjustService.adjust", 106),
        TraceNode("TRACE-TABLE", graph.graph_id, TraceNodeType.TABLE, "credit_limit", "credit_limit", 107),
    ]
    for node in nodes:
        repository.add_node(node)

    edges = [
        TraceEdge("TRACE-E1", graph.graph_id, "TRACE-REQ", "TRACE-PAGE", TraceRelationType.REQUIREMENT_AFFECTS, 108),
        TraceEdge("TRACE-E2", graph.graph_id, "TRACE-PAGE", "TRACE-API", TraceRelationType.PAGE_CALLS_API, 109),
        TraceEdge("TRACE-E3", graph.graph_id, "TRACE-API", "TRACE-SERVICE", TraceRelationType.API_IMPLEMENTED_BY, 110),
        TraceEdge("TRACE-E4", graph.graph_id, "TRACE-SERVICE", "TRACE-TABLE", TraceRelationType.WRITES_TABLE, 111),
    ]
    for edge in edges:
        repository.add_edge(edge)

    evidence = [
        TraceEvidence(
            "TRACE-EV1", graph.graph_id, "TRACE-E1", "REQUIREMENT_DOCUMENT",
            "artifact://requirement/STBB19-320", "TRACE-CI-RUN", snapshot.snapshot_id,
            112, "sha256:req",
        ),
        TraceEvidence(
            "TRACE-EV2", graph.graph_id, "TRACE-E2", "BROWSER_NETWORK",
            "controlled-browser://network/request-12", "TRACE-CI-RUN", snapshot.snapshot_id,
            113, "sha256:network",
        ),
        TraceEvidence(
            "TRACE-EV3", graph.graph_id, "TRACE-E3", "CODEGRAPH",
            "codegraph://query/api-service", "TRACE-CI-RUN", snapshot.snapshot_id,
            114, "sha256:graph",
        ),
        TraceEvidence(
            "TRACE-EV4", graph.graph_id, "TRACE-E4", "SQL",
            "source://CreditLimitMapper.xml#update", "TRACE-CI-RUN", snapshot.snapshot_id,
            115, "sha256:sql",
        ),
    ]
    for item in evidence:
        repository.append_evidence(item)

    repository.verify_edge("TRACE-E1", TraceVerificationState.STATIC_VERIFIED, confidence=1.0)
    repository.verify_edge("TRACE-E2", TraceVerificationState.RUNTIME_VERIFIED, confidence=1.0)
    repository.verify_edge("TRACE-E3", TraceVerificationState.STATIC_VERIFIED, confidence=1.0)
    repository.verify_edge("TRACE-E4", TraceVerificationState.STATIC_VERIFIED, confidence=1.0)

    forward_nodes, forward_edges = repository.query_impact(
        graph.graph_id, "TRACE-REQ", direction="forward"
    )
    reverse_nodes, reverse_edges = repository.query_impact(
        graph.graph_id, "TRACE-TABLE", direction="reverse"
    )
    expected_node_ids = {"TRACE-REQ", "TRACE-PAGE", "TRACE-API", "TRACE-SERVICE", "TRACE-TABLE"}
    expected_edge_ids = {"TRACE-E1", "TRACE-E2", "TRACE-E3", "TRACE-E4"}
    assert {node.node_id for node in forward_nodes} == expected_node_ids
    assert {edge.edge_id for edge in forward_edges} == expected_edge_ids
    assert {node.node_id for node in reverse_nodes} == expected_node_ids
    assert {edge.edge_id for edge in reverse_edges} == expected_edge_ids
    assert repository.find_nodes(
        graph.graph_id, node_type=TraceNodeType.TABLE, business_key="credit_limit"
    )[0].node_id == "TRACE-TABLE"
    assert repository.list_evidence("TRACE-E2")[0].evidence_type == "BROWSER_NETWORK"

    print("RC8_TRACEABILITY_REAL_POSTGRES_SMOKE_PASS")
    print("BANK_REALITY_VERIFIED=NO")
    print("TEST_SUFFICIENT=NO")


if __name__ == "__main__":
    main()
