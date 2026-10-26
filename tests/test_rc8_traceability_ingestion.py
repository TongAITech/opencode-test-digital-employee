import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine

from rc8_center.code_source import CodeSourceSnapshot
from rc8_center.code_sufficiency import CenterCodeSufficiencyEvaluator
from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_traceability import PostgresTraceabilityRepository
from rc8_center.runtime_attempt_authority import RuntimeAttemptAuthoritySnapshot
from rc8_center.traceability import (
    TraceNodeType,
    TraceRelationType,
    TraceVerificationState,
    TraceabilityError,
    TraceabilityGraph,
)
from rc8_center.traceability_ingestion import (
    CenterTraceabilityIngestion,
    RawTraceObservation,
    TraceEndpointObservation,
    TraceObservationSource,
)


class _ControlPlane:
    def authorize_work_item_write(self, *, test_run_id, work_item_id, node_id):
        if test_run_id != "run-1" or work_item_id != "work-code" or node_id != "node-1":
            raise RuntimeError("TEST_RUNTIME_AUTHORITY_MISMATCH")
        return SimpleNamespace(lease_owner_node_id="node-1", lease_expires_at=200)

    @staticmethod
    def _now():
        return 100


class CenterTraceabilityIngestionTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        database = Path(self.tmpdir.name) / "center.db"
        self.engine = create_engine("sqlite+pysqlite:///%s" % database.as_posix(), future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.store = PostgresStore(self.engine)
        self.store.create_test_run("run-1", test_round_id="round-1", now=1)
        self.repo = PostgresTraceabilityRepository(self.store)
        snapshot = CodeSourceSnapshot(
            snapshot_id="code-1", repository_id="pfc", repository_url="git://pfc",
            application_id="cfg-center", base_commit_sha="base", commit_sha="head", created_at=1,
            payload={"changed_java_files": ["src/A.java"], "changed_methods": ["A#m"]},
        )
        self.repo.freeze_code_source(snapshot, test_round_id="round-1", scope_revision_id="scope-1")
        self.repo.create_graph(TraceabilityGraph(
            graph_id="graph-1", test_run_id="run-1", test_round_id="round-1",
            scope_revision_id="scope-1", code_source_snapshot_id="code-1", created_at=1,
            payload={"cross_service_applicable": False, "cross_service_evidence_ref": "evidence://cross-service-na",
                     "unknown_impacts": [], "unknown_impact_evidence_ref": "evidence://unknown-zero"},
        ))
        authority = RuntimeAttemptAuthoritySnapshot(
            work_item_id="work-code", attempt_id="attempt-code", producer_node_id="node-1",
            attempt_started_at=50, lease_owner_node_id="node-1", lease_expires_at=200,
        )
        self.ingestion = CenterTraceabilityIngestion(
            self.repo, control_plane=_ControlPlane(), attempt_snapshot_resolver=lambda work_item_id: authority,
        )

    @staticmethod
    def endpoint(node_type, key, name=None, **payload):
        return TraceEndpointObservation(node_type=node_type, business_key=key, display_name=name or key, payload=payload)

    def observation(self, observation_id, source, source_node, target_node, relation, **payload):
        return RawTraceObservation(
            observation_id=observation_id, graph_id="graph-1", source_kind=source,
            source_ref="source://%s" % observation_id, from_endpoint=source_node, to_endpoint=target_node,
            relation_type=relation, captured_at=100, integrity_hash="sha256:%s" % observation_id,
            stage_id="stage-code", work_item_id="work-code", attempt_id="attempt-code",
            producer_node_id="node-1", payload=payload,
        )

    def test_browser_network_is_only_runtime_page_api_authority(self):
        obs = self.observation("browser-1", TraceObservationSource.BROWSER_NETWORK,
            self.endpoint(TraceNodeType.PAGE_ACTION, "page:customer#submit"), self.endpoint(TraceNodeType.API, "POST /customer"),
            TraceRelationType.PAGE_CALLS_API)
        receipt = self.ingestion.ingest(obs)
        self.assertEqual(TraceVerificationState.RUNTIME_VERIFIED, receipt.verification_state)
        self.assertEqual("CENTER_VERIFIED", receipt.disposition)
        with self.assertRaisesRegex(TraceabilityError, "STATIC_CODE_RELATION_FORBIDDEN"):
            self.ingestion.ingest(self.observation("source-page-api", TraceObservationSource.SOURCE_CODE,
                self.endpoint(TraceNodeType.PAGE_ACTION, "page:x#submit"), self.endpoint(TraceNodeType.API, "POST /x"),
                TraceRelationType.PAGE_CALLS_API))

    def test_worker_requested_verification_upgrade_is_rejected(self):
        obs = self.observation("worker-upgrade", TraceObservationSource.BROWSER_NETWORK,
            self.endpoint(TraceNodeType.PAGE, "page:x"), self.endpoint(TraceNodeType.API, "GET /x"), TraceRelationType.PAGE_CALLS_API)
        obs = RawTraceObservation(**dict(obs.__dict__, requested_verification=TraceVerificationState.RUNTIME_VERIFIED))
        with self.assertRaisesRegex(TraceabilityError, "WORKER_VERIFICATION_REQUEST_FORBIDDEN"):
            self.ingestion.ingest(obs)

    def test_llm_is_candidate_only_and_persistence_guess_is_forbidden(self):
        receipt = self.ingestion.ingest(self.observation("llm-call", TraceObservationSource.LLM_INFERENCE,
            self.endpoint(TraceNodeType.SERVICE, "svc:A"), self.endpoint(TraceNodeType.SERVICE, "svc:B"), TraceRelationType.CALLS))
        self.assertEqual(TraceVerificationState.CANDIDATE, receipt.verification_state)
        self.assertEqual("CANDIDATE_ONLY", receipt.disposition)
        with self.assertRaisesRegex(TraceabilityError, "PERSISTENCE_GUESS_FORBIDDEN"):
            self.ingestion.ingest(self.observation("llm-table", TraceObservationSource.LLM_INFERENCE,
                self.endpoint(TraceNodeType.SQL, "sql:guess"), self.endpoint(TraceNodeType.TABLE, "table:guessed"), TraceRelationType.READS_TABLE))

    def test_replay_is_idempotent_and_provenance_is_durable(self):
        obs = self.observation("browser-replay", TraceObservationSource.BROWSER_NETWORK,
            self.endpoint(TraceNodeType.PAGE, "page:query"), self.endpoint(TraceNodeType.API, "GET /query"),
            TraceRelationType.PAGE_CALLS_API, request_id="req-1")
        first = self.ingestion.ingest(obs)
        second = self.ingestion.ingest(obs)
        self.assertEqual(first.edge_id, second.edge_id)
        self.assertEqual("IDEMPOTENT_REPLAY", second.disposition)
        evidence = self.repo.list_evidence(first.edge_id)
        self.assertEqual(1, len(evidence))
        self.assertEqual("BROWSER_NETWORK", evidence[0].payload["raw_source_kind"])
        self.assertEqual("req-1", evidence[0].payload["request_id"])
        self.assertEqual("work-code", evidence[0].work_item_id)

    def test_explicit_jdbc_requires_sql_and_can_verify_persistence(self):
        with self.assertRaisesRegex(TraceabilityError, "JDBC_EXPLICIT_SQL_REQUIRED"):
            self.ingestion.ingest(self.observation("jdbc-missing-sql", TraceObservationSource.JDBC,
                self.endpoint(TraceNodeType.REPOSITORY, "repo:A"), self.endpoint(TraceNodeType.SQL, "sql:A"), TraceRelationType.EXECUTES_SQL))
        receipt = self.ingestion.ingest(self.observation("jdbc-explicit", TraceObservationSource.JDBC,
            self.endpoint(TraceNodeType.REPOSITORY, "repo:A"), self.endpoint(TraceNodeType.SQL, "sql:A"),
            TraceRelationType.EXECUTES_SQL, sql="select * from t_a where id=?"))
        self.assertEqual(TraceVerificationState.STATIC_VERIFIED, receipt.verification_state)
        evidence = self.repo.list_evidence(receipt.edge_id)[0]
        self.assertEqual("JDBC", evidence.payload["raw_source_kind"])
        self.assertEqual("SQL", evidence.evidence_type)

    def test_controlled_ingestion_feeds_existing_code_sufficiency(self):
        method = self.endpoint(TraceNodeType.METHOD, "A#m", source_file="src/A.java", method="A#m")
        api = self.endpoint(TraceNodeType.API, "POST /a")
        service = self.endpoint(TraceNodeType.SERVICE, "service:A", source_file="src/A.java")
        repository = self.endpoint(TraceNodeType.REPOSITORY, "repository:A", source_file="src/A.java")
        sql = self.endpoint(TraceNodeType.SQL, "sql:A")
        table = self.endpoint(TraceNodeType.TABLE, "table:t_a")
        observations = [
            self.observation("cg-api", TraceObservationSource.CODEGRAPH, api, method, TraceRelationType.API_IMPLEMENTED_BY, source_file="src/A.java"),
            self.observation("cg-method-service", TraceObservationSource.CODEGRAPH, method, service, TraceRelationType.CALLS, source_file="src/A.java"),
            self.observation("cg-service-repo", TraceObservationSource.CODEGRAPH, service, repository, TraceRelationType.CALLS, source_file="src/A.java"),
            self.observation("mybatis-sql", TraceObservationSource.MYBATIS_MAPPING, repository, sql, TraceRelationType.EXECUTES_SQL, mapping="A.select", source_file="src/A.java"),
            self.observation("sql-table", TraceObservationSource.SQL, sql, table, TraceRelationType.READS_TABLE, sql="select * from t_a", table="t_a"),
        ]
        for observation in observations:
            receipt = self.ingestion.ingest(observation)
            self.assertEqual(TraceVerificationState.STATIC_VERIFIED, receipt.verification_state)
        result = CenterCodeSufficiencyEvaluator(self.repo).evaluate(test_run_id="run-1", stage_instance_id="stage-code-sufficiency", graph_id="graph-1")
        self.assertEqual("SUFFICIENT", result.evaluation.result.value)
        self.assertTrue(all(item.state.value in {"SATISFIED", "NOT_APPLICABLE"} for item in result.assessments))


if __name__ == "__main__":
    unittest.main()
