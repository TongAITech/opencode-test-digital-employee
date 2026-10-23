import pytest
from sqlalchemy import create_engine

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
    TraceabilityError,
    TraceabilityGraph,
)


def _repo():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    store.create_test_run(
        "run-1",
        production_batch_id="batch-2026-11-15",
        test_round_id="round-2",
        now=1,
    )
    return PostgresTraceabilityRepository(store)


def _snapshot():
    return CodeSourceSnapshot(
        snapshot_id="source-2",
        repository_id="cfg-data",
        repository_url="ssh://git.example.invalid/pfc/cfg-data.git",
        application_id="cfg-data",
        base_commit_sha="1" * 40,
        commit_sha="2" * 40,
        subpath="service/core",
        created_at=2,
    )


def _graph(repo):
    repo.freeze_code_source(
        _snapshot(),
        test_round_id="round-2",
        scope_revision_id="scope-r3",
        system_id="PFC",
        system_version="BLOAN-PF1.2.0",
    )
    value = TraceabilityGraph(
        graph_id="graph-1",
        test_run_id="run-1",
        test_round_id="round-2",
        scope_revision_id="scope-r3",
        code_source_snapshot_id="source-2",
        created_at=3,
    )
    repo.create_graph(value)
    return value


def _node(node_id, node_type, business_key, name, created_at):
    return TraceNode(
        node_id=node_id,
        graph_id="graph-1",
        node_type=node_type,
        business_key=business_key,
        display_name=name,
        created_at=created_at,
    )


def test_code_source_snapshot_is_durable_and_immutable_per_round_scope():
    repo = _repo()
    repo.freeze_code_source(
        _snapshot(),
        test_round_id="round-2",
        scope_revision_id="scope-r3",
    )
    stored = repo.get_code_source("source-2")
    assert stored is not None
    assert stored.identity == _snapshot().identity
    assert stored.commit_sha == "2" * 40

    changed = CodeSourceSnapshot(
        snapshot_id="source-2",
        repository_id="cfg-data",
        repository_url="ssh://git.example.invalid/pfc/cfg-data.git",
        commit_sha="3" * 40,
        created_at=4,
    )
    with pytest.raises(TraceabilityError, match="CODE_SOURCE_SNAPSHOT_IMMUTABLE"):
        repo.freeze_code_source(
            changed,
            test_round_id="round-2",
            scope_revision_id="scope-r3",
        )


def test_graph_is_bound_to_test_run_round_scope_and_frozen_code_source():
    repo = _repo()
    graph = _graph(repo)
    stored = repo.get_graph(graph.graph_id)
    assert stored == graph

    wrong_scope = TraceabilityGraph(
        graph_id="graph-wrong",
        test_run_id="run-1",
        test_round_id="round-2",
        scope_revision_id="scope-other",
        code_source_snapshot_id="source-2",
        created_at=3,
    )
    with pytest.raises(TraceabilityError, match="TRACE_CODE_SOURCE_SCOPE_REVISION_MISMATCH"):
        repo.create_graph(wrong_scope)


def test_candidate_relation_cannot_claim_verification_without_matching_evidence():
    repo = _repo()
    _graph(repo)
    repo.add_node(_node("page", TraceNodeType.PAGE, "/limit", "额度调整页面", 4))
    repo.add_node(_node("api", TraceNodeType.API, "POST /credit/limit/adjust", "提交额度调整", 5))
    repo.add_edge(
        TraceEdge(
            edge_id="page-api",
            graph_id="graph-1",
            from_node_id="page",
            to_node_id="api",
            relation_type=TraceRelationType.PAGE_CALLS_API,
            created_at=6,
        )
    )

    with pytest.raises(TraceabilityError, match="TRACE_RUNTIME_EVIDENCE_REQUIRED"):
        repo.verify_edge("page-api", TraceVerificationState.RUNTIME_VERIFIED, confidence=0.9)

    repo.append_evidence(
        TraceEvidence(
            evidence_id="network-1",
            graph_id="graph-1",
            edge_id="page-api",
            evidence_type="BROWSER_NETWORK",
            source="controlled-browser/network.har#req-12",
            test_run_id="run-1",
            code_source_snapshot_id="source-2",
            captured_at=7,
            integrity_hash="sha256:network",
            stage_id="stage-code-analysis",
            work_item_id="work-browser-map",
            attempt_id="attempt-1",
        )
    )
    verified = repo.verify_edge(
        "page-api", TraceVerificationState.RUNTIME_VERIFIED, confidence=1.0
    )
    assert verified.verification_state == TraceVerificationState.RUNTIME_VERIFIED
    assert verified.evidence_count == 1


def test_multi_source_verification_requires_static_and_runtime_evidence():
    repo = _repo()
    _graph(repo)
    repo.add_node(_node("api", TraceNodeType.API, "POST /credit/limit/adjust", "提交额度调整", 4))
    repo.add_node(_node("controller", TraceNodeType.CONTROLLER, "LimitAdjustController.submit", "LimitAdjustController.submit", 5))
    repo.add_edge(
        TraceEdge(
            edge_id="api-controller",
            graph_id="graph-1",
            from_node_id="api",
            to_node_id="controller",
            relation_type=TraceRelationType.API_IMPLEMENTED_BY,
            created_at=6,
        )
    )
    repo.append_evidence(
        TraceEvidence(
            evidence_id="spring-map",
            graph_id="graph-1",
            edge_id="api-controller",
            evidence_type="SPRING_MAPPING",
            source="src/LimitAdjustController.java#submit",
            test_run_id="run-1",
            code_source_snapshot_id="source-2",
            captured_at=7,
            integrity_hash="sha256:spring",
        )
    )
    with pytest.raises(TraceabilityError, match="TRACE_MULTI_SOURCE_EVIDENCE_REQUIRED"):
        repo.verify_edge("api-controller", TraceVerificationState.MULTI_SOURCE_VERIFIED, confidence=1.0)

    repo.append_evidence(
        TraceEvidence(
            evidence_id="runtime-log",
            graph_id="graph-1",
            edge_id="api-controller",
            evidence_type="APPLICATION_LOG",
            source="starlink://trace/abc",
            test_run_id="run-1",
            code_source_snapshot_id="source-2",
            captured_at=8,
            integrity_hash="sha256:runtime",
        )
    )
    verified = repo.verify_edge(
        "api-controller", TraceVerificationState.MULTI_SOURCE_VERIFIED, confidence=1.0
    )
    assert verified.verification_state == TraceVerificationState.MULTI_SOURCE_VERIFIED
    assert verified.evidence_count == 2


def test_forward_and_reverse_queries_return_same_real_chain_from_opposite_ends():
    repo = _repo()
    _graph(repo)
    nodes = [
        _node("req", TraceNodeType.REQUIREMENT, "STBB19-320", "STBB19-320", 4),
        _node("page", TraceNodeType.PAGE, "/limit", "额度调整页面", 5),
        _node("api", TraceNodeType.API, "POST /credit/limit/adjust", "提交额度调整", 6),
        _node("service", TraceNodeType.SERVICE, "LimitAdjustService.adjust", "LimitAdjustService.adjust", 7),
        _node("table", TraceNodeType.TABLE, "credit_limit", "credit_limit", 8),
        _node("case", TraceNodeType.TEST_CASE, "TC-320-001", "额度调整正常流程", 9),
    ]
    for value in nodes:
        repo.add_node(value)
    edges = [
        ("e1", "req", "page", TraceRelationType.REQUIREMENT_AFFECTS),
        ("e2", "page", "api", TraceRelationType.PAGE_CALLS_API),
        ("e3", "api", "service", TraceRelationType.API_IMPLEMENTED_BY),
        ("e4", "service", "table", TraceRelationType.WRITES_TABLE),
        ("e5", "case", "req", TraceRelationType.TEST_COVERS),
    ]
    for index, (edge_id, source, target, relation) in enumerate(edges, start=10):
        repo.add_edge(
            TraceEdge(
                edge_id=edge_id,
                graph_id="graph-1",
                from_node_id=source,
                to_node_id=target,
                relation_type=relation,
                created_at=index,
            )
        )

    forward_nodes, forward_edges = repo.query_impact("graph-1", "req", direction="forward")
    assert {n.node_id for n in forward_nodes} == {"req", "page", "api", "service", "table"}
    assert {e.edge_id for e in forward_edges} == {"e1", "e2", "e3", "e4"}

    reverse_nodes, reverse_edges = repo.query_impact("graph-1", "table", direction="reverse")
    assert {n.node_id for n in reverse_nodes} == {"req", "page", "api", "service", "table", "case"}
    assert {e.edge_id for e in reverse_edges} == {"e1", "e2", "e3", "e4", "e5"}

    matched = repo.find_nodes("graph-1", node_type=TraceNodeType.TABLE, business_key="credit_limit")
    assert [n.node_id for n in matched] == ["table"]
