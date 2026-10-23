from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rc8_center.code_source import CodeSourceSnapshot
from rc8_center.code_sufficiency import CenterCodeSufficiencyEvaluator
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_traceability import PostgresTraceabilityRepository
from rc8_center.traceability import TraceEdge, TraceEvidence, TraceNode, TraceNodeType, TraceRelationType, TraceVerificationState, TraceabilityGraph
from rc8_runtime.governance import SufficiencyResult
from rc8_runtime.sufficiency import DimensionState


FILE1 = "src/main/java/com/pfc/LimitAdjustService.java"
FILE2 = "src/main/java/com/pfc/LimitAuditService.java"
METHOD1 = "LimitAdjustService.adjust"


def _repo(snapshot_payload, graph_payload=None):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    store.create_test_run("run-1", production_batch_id="PB", test_round_id="round-1", now=1)
    repo = PostgresTraceabilityRepository(store)
    snapshot = CodeSourceSnapshot(
        snapshot_id="snap-1",
        repository_id="cfg-data",
        repository_url="ssh://git.invalid/cfg-data.git",
        application_id="cfg-data",
        base_commit_sha="1" * 40,
        commit_sha="2" * 40,
        created_at=2,
        payload=dict(snapshot_payload),
    )
    repo.freeze_code_source(snapshot, test_round_id="round-1", scope_revision_id="scope-r1")
    repo.create_graph(TraceabilityGraph(
        graph_id="graph-1",
        test_run_id="run-1",
        test_round_id="round-1",
        scope_revision_id="scope-r1",
        code_source_snapshot_id="snap-1",
        created_at=3,
        payload=dict(graph_payload or {}),
    ))
    return repo


def _node(repo, node_id, node_type, key, *, file=None, at=4):
    repo.add_node(TraceNode(
        node_id=node_id,
        graph_id="graph-1",
        node_type=node_type,
        business_key=key,
        display_name=key,
        created_at=at,
        payload={"source_file": file} if file else {},
    ))


def _edge(repo, edge_id, source, target, relation, evidence_type, evidence_id, source_ref, *, file=None, at=10):
    repo.add_edge(TraceEdge(edge_id=edge_id, graph_id="graph-1", from_node_id=source, to_node_id=target, relation_type=relation, created_at=at))
    repo.append_evidence(TraceEvidence(
        evidence_id=evidence_id,
        graph_id="graph-1",
        edge_id=edge_id,
        evidence_type=evidence_type,
        source=source_ref,
        test_run_id="run-1",
        code_source_snapshot_id="snap-1",
        captured_at=at + 1,
        integrity_hash="sha256:%s" % evidence_id,
        payload={"source_file": file} if file else {},
    ))
    repo.verify_edge(edge_id, TraceVerificationState.STATIC_VERIFIED, confidence=1.0)


def _full_graph(repo):
    _node(repo, "api", TraceNodeType.API, "POST /credit/adjust", at=4)
    _node(repo, "controller", TraceNodeType.CONTROLLER, "LimitController.adjust", file=FILE1, at=5)
    _node(repo, "method", TraceNodeType.METHOD, METHOD1, file=FILE1, at=6)
    _node(repo, "service", TraceNodeType.SERVICE, METHOD1, file=FILE1, at=7)
    _node(repo, "table", TraceNodeType.TABLE, "credit_limit", at=8)
    _edge(repo, "api-controller", "api", "controller", TraceRelationType.API_IMPLEMENTED_BY, "SPRING_MAPPING", "spring-1", "src/LimitController.java#adjust", at=10)
    _edge(repo, "controller-service", "controller", "service", TraceRelationType.CALLS, "CODEGRAPH", "codegraph-1", "codegraph://call/adjust", file=FILE1, at=12)
    _edge(repo, "service-table", "service", "table", TraceRelationType.WRITES_TABLE, "SQL", "sql-1", "mapper/LimitMapper.xml#update", file=FILE1, at=14)


def _evaluate(repo):
    return CenterCodeSufficiencyEvaluator(repo).evaluate(
        test_run_id="run-1",
        stage_instance_id="code-suff-1",
        graph_id="graph-1",
        worker_claimed_sufficient=True,
    )


def test_complete_frozen_code_denominator_can_be_center_sufficient():
    repo = _repo(
        {"changed_java_files": [FILE1], "changed_methods": [METHOD1]},
        {
            "cross_service_applicable": False,
            "cross_service_evidence_ref": "artifact:cross-service-assessment",
            "unknown_impacts": [],
            "unknown_impact_evidence_ref": "artifact:unknown-impact-inventory",
        },
    )
    _full_graph(repo)
    result = _evaluate(repo)
    assert result.evaluation.result == SufficiencyResult.SUFFICIENT
    assert result.evaluation.evaluator_id == "RC8_CENTER_SUFFICIENCY_LEDGER"
    assert result.evaluation.policy_version.startswith("center-ledger:")
    assert all(item.state in {DimensionState.SATISFIED, DimensionState.NOT_APPLICABLE} for item in result.assessments)


def test_rc7_style_changed_file_shrink_attack_is_insufficient():
    repo = _repo(
        {"changed_java_files": [FILE1, FILE2], "changed_methods": [METHOD1]},
        {
            "cross_service_applicable": False,
            "cross_service_evidence_ref": "artifact:cross-service-assessment",
            "unknown_impacts": [],
            "unknown_impact_evidence_ref": "artifact:unknown-impact-inventory",
        },
    )
    _full_graph(repo)
    result = _evaluate(repo)
    assert result.evaluation.result == SufficiencyResult.INSUFFICIENT
    states = {item.dimension_id: item.state for item in result.assessments}
    assert states["code:changed-file:%s" % FILE2] == DimensionState.UNKNOWN
    assert states["code:codegraph-file:%s" % FILE2] == DimensionState.UNKNOWN
    assert "code:changed-file:%s" % FILE2 in result.evaluation.unsatisfied_requirement_refs


def test_missing_changed_method_inventory_never_means_no_changed_methods():
    repo = _repo(
        {"changed_java_files": [FILE1], "changed_methods": []},
        {
            "cross_service_applicable": False,
            "cross_service_evidence_ref": "artifact:cross-service-assessment",
            "unknown_impacts": [],
            "unknown_impact_evidence_ref": "artifact:unknown-impact-inventory",
        },
    )
    _full_graph(repo)
    result = _evaluate(repo)
    states = {item.dimension_id: item.state for item in result.assessments}
    assert result.evaluation.result == SufficiencyResult.INSUFFICIENT
    assert states["code:changed-method-inventory"] == DimensionState.UNKNOWN


def test_candidate_codegraph_relation_cannot_satisfy_code_sufficiency():
    repo = _repo(
        {"changed_java_files": [FILE1], "changed_methods": [METHOD1]},
        {
            "api_impact_not_applicable": True,
            "api_impact_evidence_ref": "artifact:no-api",
            "persistence_not_applicable": True,
            "persistence_evidence_ref": "artifact:no-db",
            "cross_service_applicable": False,
            "cross_service_evidence_ref": "artifact:no-cross-service",
            "unknown_impacts": [],
            "unknown_impact_evidence_ref": "artifact:unknown-impact-inventory",
        },
    )
    _node(repo, "method", TraceNodeType.METHOD, METHOD1, file=FILE1, at=4)
    _node(repo, "service", TraceNodeType.SERVICE, METHOD1, file=FILE1, at=5)
    repo.add_edge(TraceEdge(edge_id="candidate-call", graph_id="graph-1", from_node_id="method", to_node_id="service", relation_type=TraceRelationType.CALLS, created_at=6))
    repo.append_evidence(TraceEvidence(
        evidence_id="candidate-codegraph",
        graph_id="graph-1",
        edge_id="candidate-call",
        evidence_type="CODEGRAPH",
        source="codegraph://candidate",
        test_run_id="run-1",
        code_source_snapshot_id="snap-1",
        captured_at=7,
        integrity_hash="sha256:candidate",
        payload={"source_file": FILE1},
    ))
    result = _evaluate(repo)
    states = {item.dimension_id: item.state for item in result.assessments}
    assert result.evaluation.result == SufficiencyResult.INSUFFICIENT
    assert states["code:codegraph-file:%s" % FILE1] == DimensionState.UNKNOWN
    assert states["code:call-chain-impact"] == DimensionState.UNKNOWN


def test_unknown_impact_inventory_blocks_worker_green():
    repo = _repo(
        {"changed_java_files": [FILE1], "changed_methods": [METHOD1]},
        {
            "cross_service_applicable": False,
            "cross_service_evidence_ref": "artifact:cross-service-assessment",
            "unknown_impacts": ["reflection target unresolved"],
            "unknown_impact_evidence_ref": "artifact:unknown-impact-inventory",
        },
    )
    _full_graph(repo)
    result = _evaluate(repo)
    states = {item.dimension_id: item.state for item in result.assessments}
    assert result.evaluation.result == SufficiencyResult.INSUFFICIENT
    assert states["code:unknown-impact-zero"] == DimensionState.UNSATISFIED
