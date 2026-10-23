from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rc8_center.api import create_app
from rc8_center.code_source import CodeSourceSnapshot
from rc8_center.infrastructure.postgres import Base, PostgresStore
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


def _client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    store.create_test_run(
        "run-trace-api",
        production_batch_id="batch-2026-11-15",
        test_round_id="round-2",
        now=1,
    )
    repository = PostgresTraceabilityRepository(store)
    snapshot = CodeSourceSnapshot(
        snapshot_id="source-api-2",
        repository_id="cfg-data",
        repository_url="ssh://bank.invalid/pfc/cfg-data.git",
        application_id="cfg-data",
        base_commit_sha="1" * 40,
        commit_sha="2" * 40,
        created_at=2,
    )
    repository.freeze_code_source(
        snapshot,
        test_round_id="round-2",
        scope_revision_id="scope-r3",
        system_id="PFC",
        system_version="BLOAN-PF1.2.0",
    )
    repository.create_graph(
        TraceabilityGraph(
            graph_id="graph-api",
            test_run_id="run-trace-api",
            test_round_id="round-2",
            scope_revision_id="scope-r3",
            code_source_snapshot_id=snapshot.snapshot_id,
            created_at=3,
        )
    )
    nodes = [
        TraceNode("req", "graph-api", TraceNodeType.REQUIREMENT, "STBB19-320", "STBB19-320", 4),
        TraceNode("page", "graph-api", TraceNodeType.PAGE, "/credit/limit", "额度调整页面", 5),
        TraceNode("api", "graph-api", TraceNodeType.API, "POST /credit/limit/adjust", "提交额度调整", 6),
        TraceNode("service", "graph-api", TraceNodeType.SERVICE, "LimitAdjustService.adjust", "LimitAdjustService.adjust", 7),
        TraceNode("table", "graph-api", TraceNodeType.TABLE, "credit_limit", "credit_limit", 8),
    ]
    for node in nodes:
        repository.add_node(node)
    edges = [
        TraceEdge("e1", "graph-api", "req", "page", TraceRelationType.REQUIREMENT_AFFECTS, 9),
        TraceEdge("e2", "graph-api", "page", "api", TraceRelationType.PAGE_CALLS_API, 10),
        TraceEdge("e3", "graph-api", "api", "service", TraceRelationType.API_IMPLEMENTED_BY, 11),
        TraceEdge("e4", "graph-api", "service", "table", TraceRelationType.WRITES_TABLE, 12),
    ]
    for edge in edges:
        repository.add_edge(edge)
    repository.append_evidence(
        TraceEvidence(
            evidence_id="network-1",
            graph_id="graph-api",
            edge_id="e2",
            evidence_type="BROWSER_NETWORK",
            source="controlled-browser://network/request-12",
            test_run_id="run-trace-api",
            code_source_snapshot_id=snapshot.snapshot_id,
            captured_at=13,
            integrity_hash="sha256:network",
        )
    )
    repository.verify_edge("e2", TraceVerificationState.RUNTIME_VERIFIED, confidence=1.0)
    app = create_app(postgres=store)
    return TestClient(app)


def test_business_user_lists_graph_by_test_run_and_round():
    client = _client()
    response = client.get("/api/v1/test-runs/run-trace-api/traceability-graphs")
    assert response.status_code == 200
    graph = response.json()["graphs"][0]
    assert graph["graph_id"] == "graph-api"
    assert graph["test_round_id"] == "round-2"
    assert graph["scope_revision_id"] == "scope-r3"
    assert graph["code_source_snapshot_id"] == "source-api-2"

    response = client.get("/api/v1/test-rounds/round-2/traceability-graphs")
    assert response.status_code == 200
    assert [item["graph_id"] for item in response.json()["graphs"]] == ["graph-api"]


def test_requirement_query_returns_forward_impact_chain_without_internal_node_id_input():
    client = _client()
    response = client.get(
        "/api/v1/traceability-graphs/graph-api/impact",
        params={
            "node_type": "REQUIREMENT",
            "business_key": "STBB19-320",
            "direction": "forward",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["root"]["business_key"] == "STBB19-320"
    assert {node["node_type"] for node in body["nodes"]} == {
        "REQUIREMENT",
        "PAGE",
        "API",
        "SERVICE",
        "TABLE",
    }
    assert body["summary"]["node_count"] == 5
    assert body["summary"]["edge_count"] == 4
    assert body["summary"]["verified_count"] == 1
    assert body["summary"]["candidate_count"] == 3


def test_table_reverse_query_reaches_requirement_and_evidence_is_drillable():
    client = _client()
    response = client.get(
        "/api/v1/traceability-graphs/graph-api/impact",
        params={
            "node_type": "TABLE",
            "business_key": "credit_limit",
            "direction": "reverse",
        },
    )
    assert response.status_code == 200
    assert {node["business_key"] for node in response.json()["nodes"]} == {
        "STBB19-320",
        "/credit/limit",
        "POST /credit/limit/adjust",
        "LimitAdjustService.adjust",
        "credit_limit",
    }

    evidence = client.get(
        "/api/v1/traceability-graphs/graph-api/edges/e2/evidence"
    )
    assert evidence.status_code == 200
    item = evidence.json()["evidence"][0]
    assert item["evidence_type"] == "BROWSER_NETWORK"
    assert item["source"] == "controlled-browser://network/request-12"


def test_unknown_business_subject_fails_closed():
    client = _client()
    response = client.get(
        "/api/v1/traceability-graphs/graph-api/impact",
        params={"node_type": "TABLE", "business_key": "guessed_table"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "TRACE_QUERY_SUBJECT_NOT_FOUND"
