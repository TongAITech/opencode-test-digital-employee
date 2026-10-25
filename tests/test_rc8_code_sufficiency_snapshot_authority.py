from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rc8_center.code_source import CodeSourceSnapshot
from rc8_center.code_sufficiency import CenterCodeSufficiencyEvaluator
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_traceability import PostgresTraceabilityRepository
from rc8_center.traceability import TraceEdge, TraceEvidence, TraceNode, TraceNodeType, TraceRelationType, TraceVerificationState, TraceabilityGraph
from rc8_runtime.governance import SufficiencyResult
from rc8_runtime.sufficiency import DimensionState

FILE = "src/main/java/com/pfc/LimitAdjustService.java"
METHOD = "LimitAdjustService.adjust"


def _repo():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    store.create_test_run("run-1", production_batch_id="PB", test_round_id="round-1", now=1)
    repo = PostgresTraceabilityRepository(store)
    repo.freeze_code_source(CodeSourceSnapshot(snapshot_id="snap-current", repository_id="cfg-data", repository_url="ssh://git.invalid/cfg-data.git", application_id="cfg-data", base_commit_sha="1" * 40, commit_sha="2" * 40, created_at=2, payload={"changed_java_files": [FILE], "changed_methods": [METHOD]}), test_round_id="round-1", scope_revision_id="scope-r1")
    repo.create_graph(TraceabilityGraph(graph_id="graph-1", test_run_id="run-1", test_round_id="round-1", scope_revision_id="scope-r1", code_source_snapshot_id="snap-current", created_at=3, payload={"api_impact_not_applicable": True, "api_impact_evidence_ref": "artifact:no-api", "persistence_not_applicable": True, "persistence_evidence_ref": "artifact:no-db", "cross_service_applicable": False, "cross_service_evidence_ref": "artifact:no-cross", "unknown_impacts": [], "unknown_impact_evidence_ref": "artifact:no-unknown"}))
    repo.add_node(TraceNode(node_id="method", graph_id="graph-1", node_type=TraceNodeType.METHOD, business_key=METHOD, display_name=METHOD, created_at=4, payload={"source_file": FILE}))
    repo.add_node(TraceNode(node_id="service", graph_id="graph-1", node_type=TraceNodeType.SERVICE, business_key=METHOD, display_name=METHOD, created_at=5, payload={"source_file": FILE}))
    repo.add_edge(TraceEdge(edge_id="call", graph_id="graph-1", from_node_id="method", to_node_id="service", relation_type=TraceRelationType.CALLS, created_at=6))
    return repo


def _append_codegraph(repo, evidence_id, snapshot_id):
    repo.append_evidence(TraceEvidence(evidence_id=evidence_id, graph_id="graph-1", edge_id="call", evidence_type="CODEGRAPH", source="codegraph://call/adjust", test_run_id="run-1", code_source_snapshot_id=snapshot_id, captured_at=7, integrity_hash="sha256:%s" % evidence_id, payload={"source_file": FILE}))
    repo.verify_edge("call", TraceVerificationState.STATIC_VERIFIED, confidence=1.0)


def _evaluate(repo):
    return CenterCodeSufficiencyEvaluator(repo).evaluate(test_run_id="run-1", stage_instance_id="code-suff-1", graph_id="graph-1", worker_claimed_sufficient=True)


def test_verified_codegraph_from_previous_snapshot_cannot_satisfy_current_frozen_snapshot():
    repo = _repo()
    _append_codegraph(repo, "old-codegraph", "snap-previous")
    result = _evaluate(repo)
    states = {item.dimension_id: item.state for item in result.assessments}
    assert result.evaluation.result == SufficiencyResult.INSUFFICIENT
    assert states["code:codegraph-file:%s" % FILE] == DimensionState.UNKNOWN
    assert states["code:call-chain-impact"] == DimensionState.UNKNOWN


def test_verified_codegraph_from_current_snapshot_can_satisfy_source_bound_dimensions():
    repo = _repo()
    _append_codegraph(repo, "current-codegraph", "snap-current")
    result = _evaluate(repo)
    states = {item.dimension_id: item.state for item in result.assessments}
    assert result.evaluation.result == SufficiencyResult.SUFFICIENT
    assert states["code:codegraph-file:%s" % FILE] == DimensionState.SATISFIED
    assert states["code:call-chain-impact"] == DimensionState.SATISFIED
