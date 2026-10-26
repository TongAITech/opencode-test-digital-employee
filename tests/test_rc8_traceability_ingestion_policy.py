import pytest

from rc8_center.traceability import TraceNodeType, TraceRelationType, TraceVerificationState, TraceabilityError
from rc8_center.traceability_ingestion import CenterTraceabilityIngestion, RawTraceObservation, TraceEndpointObservation, TraceObservationSource


def raw_observation(source_kind, source_type, target_type, relation_type, requested=TraceVerificationState.CANDIDATE, payload=None):
    return RawTraceObservation(
        observation_id="obs-1", graph_id="graph-1", source_kind=source_kind,
        source_ref="evidence://attempt/current/1",
        from_endpoint=TraceEndpointObservation(source_type, "source", "source"),
        to_endpoint=TraceEndpointObservation(target_type, "target", "target"),
        relation_type=relation_type, captured_at=1, integrity_hash="sha256:test",
        requested_verification=requested, payload=payload or {},
    )


def test_worker_cannot_request_verification_upgrade():
    observation = raw_observation(TraceObservationSource.LLM_INFERENCE, TraceNodeType.API, TraceNodeType.CONTROLLER, TraceRelationType.API_IMPLEMENTED_BY, requested=TraceVerificationState.RUNTIME_VERIFIED)
    with pytest.raises(TraceabilityError, match="WORKER_VERIFICATION_REQUEST_FORBIDDEN"):
        observation.validate()


def test_llm_inference_remains_candidate_only():
    service = CenterTraceabilityIngestion(repository=None)
    observation = raw_observation(TraceObservationSource.LLM_INFERENCE, TraceNodeType.API, TraceNodeType.CONTROLLER, TraceRelationType.API_IMPLEMENTED_BY)
    state, policy, confidence, evidence_type = service._policy(observation)
    assert state == TraceVerificationState.CANDIDATE
    assert policy == "LLM_CANDIDATE_ONLY"
    assert confidence < 1.0
    assert evidence_type == "LLM_INFERENCE"


def test_browser_network_is_only_runtime_page_api_policy():
    service = CenterTraceabilityIngestion(repository=None)
    observation = raw_observation(TraceObservationSource.BROWSER_NETWORK, TraceNodeType.PAGE_ACTION, TraceNodeType.API, TraceRelationType.PAGE_CALLS_API)
    state, policy, confidence, evidence_type = service._policy(observation)
    assert state == TraceVerificationState.RUNTIME_VERIFIED
    assert policy == "BROWSER_NETWORK_PAGE_API"
    assert confidence == 1.0
    assert evidence_type == "BROWSER_NETWORK"
    forbidden = raw_observation(TraceObservationSource.SOURCE_CODE, TraceNodeType.PAGE_ACTION, TraceNodeType.API, TraceRelationType.PAGE_CALLS_API)
    with pytest.raises(TraceabilityError, match="STATIC_CODE_RELATION_FORBIDDEN"):
        service._policy(forbidden)


def test_codegraph_verifies_code_but_llm_cannot_guess_table():
    service = CenterTraceabilityIngestion(repository=None)
    code = raw_observation(TraceObservationSource.CODEGRAPH, TraceNodeType.API, TraceNodeType.CONTROLLER, TraceRelationType.API_IMPLEMENTED_BY)
    state, policy, _, _ = service._policy(code)
    assert state == TraceVerificationState.STATIC_VERIFIED
    assert policy == "STATIC_API_IMPLEMENTATION"
    guessed = raw_observation(TraceObservationSource.LLM_INFERENCE, TraceNodeType.SQL, TraceNodeType.TABLE, TraceRelationType.READS_TABLE)
    with pytest.raises(TraceabilityError, match="PERSISTENCE_GUESS_FORBIDDEN"):
        service._policy(guessed)


def test_jdbc_requires_explicit_sql_before_static_verification():
    service = CenterTraceabilityIngestion(repository=None)
    missing = raw_observation(TraceObservationSource.JDBC, TraceNodeType.REPOSITORY, TraceNodeType.SQL, TraceRelationType.EXECUTES_SQL)
    with pytest.raises(TraceabilityError, match="JDBC_EXPLICIT_SQL_REQUIRED"):
        service._policy(missing)
    explicit = raw_observation(TraceObservationSource.JDBC, TraceNodeType.REPOSITORY, TraceNodeType.SQL, TraceRelationType.EXECUTES_SQL, payload={"sql_text": "select id from t_account where id = ?"})
    state, policy, confidence, evidence_type = service._policy(explicit)
    assert state == TraceVerificationState.STATIC_VERIFIED
    assert policy == "EXPLICIT_PERSISTENCE_SQL"
    assert confidence == 1.0
    assert evidence_type == "SQL"
