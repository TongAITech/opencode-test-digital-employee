from rc8_center.traceability import TraceNodeType, TraceRelationType, TraceVerificationState
from rc8_center.traceability_ingestion import (
    ControlledTraceIngestionService,
    TraceEvidenceSource,
    TraceObservation,
)


class RecordingSink:
    def __init__(self):
        self.items = []

    def persist_observation(self, observation, decision):
        self.items.append((observation, decision))


def observation(source, target, evidence_source, requested=None):
    return TraceObservation(
        source_type=source,
        target_type=target,
        relation_type=TraceRelationType.CALLS,
        evidence_source=evidence_source,
        evidence_ref="evidence://attempt/current/1",
        requested_verification_state=requested,
    )


def test_worker_cannot_self_promote_llm_candidate_to_verified():
    sink = RecordingSink()
    service = ControlledTraceIngestionService(sink)
    decision = service.ingest(
        observation(
            TraceNodeType.API,
            TraceNodeType.CONTROLLER,
            TraceEvidenceSource.LLM,
            TraceVerificationState.RUNTIME_VERIFIED,
        )
    )
    assert decision.verification_state is TraceVerificationState.CANDIDATE
    assert sink.items[0][1].verification_state is TraceVerificationState.CANDIDATE


def test_browser_edge_requires_controlled_network_evidence():
    sink = RecordingSink()
    service = ControlledTraceIngestionService(sink)
    candidate = service.ingest(
        observation(
            TraceNodeType.PAGE_ACTION,
            TraceNodeType.API,
            TraceEvidenceSource.SOURCE_CODE,
            TraceVerificationState.RUNTIME_VERIFIED,
        )
    )
    verified = service.ingest(
        observation(
            TraceNodeType.PAGE_ACTION,
            TraceNodeType.API,
            TraceEvidenceSource.BROWSER_NETWORK,
        )
    )
    assert candidate.verification_state is TraceVerificationState.CANDIDATE
    assert verified.verification_state is TraceVerificationState.RUNTIME_VERIFIED


def test_code_edge_requires_structured_code_evidence():
    sink = RecordingSink()
    service = ControlledTraceIngestionService(sink)
    candidate = service.ingest(
        observation(
            TraceNodeType.API,
            TraceNodeType.CONTROLLER,
            TraceEvidenceSource.BROWSER_NETWORK,
            TraceVerificationState.RUNTIME_VERIFIED,
        )
    )
    verified = service.ingest(
        observation(
            TraceNodeType.API,
            TraceNodeType.CONTROLLER,
            TraceEvidenceSource.CODEGRAPH,
        )
    )
    assert candidate.verification_state is TraceVerificationState.CANDIDATE
    assert verified.verification_state is TraceVerificationState.STATIC_VERIFIED


def test_persistence_edge_cannot_be_verified_from_llm_or_worker_request():
    sink = RecordingSink()
    service = ControlledTraceIngestionService(sink)
    candidate = service.ingest(
        observation(
            TraceNodeType.REPOSITORY,
            TraceNodeType.SQL,
            TraceEvidenceSource.WORKER_INFERENCE,
            TraceVerificationState.RUNTIME_VERIFIED,
        )
    )
    verified = service.ingest(
        observation(
            TraceNodeType.REPOSITORY,
            TraceNodeType.SQL,
            TraceEvidenceSource.SQL,
        )
    )
    assert candidate.verification_state is TraceVerificationState.CANDIDATE
    assert verified.verification_state is TraceVerificationState.STATIC_VERIFIED


def test_missing_evidence_reference_is_rejected_and_not_persisted():
    sink = RecordingSink()
    service = ControlledTraceIngestionService(sink)
    obs = TraceObservation(
        source_type=TraceNodeType.API,
        target_type=TraceNodeType.CONTROLLER,
        relation_type=TraceRelationType.CALLS,
        evidence_source=TraceEvidenceSource.CODEGRAPH,
        evidence_ref=" ",
        requested_verification_state=TraceVerificationState.RUNTIME_VERIFIED,
    )
    decision = service.ingest(obs)
    assert decision.accepted is False
    assert decision.verification_state is TraceVerificationState.CANDIDATE
    assert sink.items == []
