from __future__ import annotations

import pytest

from rc8_node.single_node_full_loop_proof import SingleNodeFullLoopProof
from rc8_node.single_node_truth import SingleNodeCenterTruthVerifier, SingleNodeTruthError


class TruthReader:
    def __init__(self, mutate=None):
        self.mutate = mutate

    @staticmethod
    def _index(value):
        return int(str(value).rsplit("-", 1)[-1])

    def get_work_item(self, work_item_id):
        i = self._index(work_item_id)
        value = {"test_run_id": "TR", "stage": ("SCOPE_INTAKE", "REPORT_RELEASE")[i], "status": "COMPLETED"}
        return self.mutate("work", i, value) if self.mutate else value

    def get_attempt(self, attempt_id):
        i = self._index(attempt_id)
        value = {"test_run_id": "TR", "work_item_id": "wi-%d" % i, "stage_instance_id": "stage-%d" % i, "producer_node_id": "node-a", "status": "COMPLETED"}
        return self.mutate("attempt", i, value) if self.mutate else value

    def get_artifact(self, artifact_id):
        i = self._index(artifact_id)
        value = {"test_run_id": "TR", "work_item_id": "wi-%d" % i, "attempt_id": "attempt-%d" % i, "node_id": "node-a", "producer_kind": "WORKER", "status": "COMPLETED"}
        return self.mutate("artifact", i, value) if self.mutate else value

    def find_r1_attempt_started(self, **identity):
        i = self._index(identity["attempt_id"])
        value = {"event_id": "start-%d" % i, "event_type": "ATTEMPT_STARTED", "test_run_id": "TR", "work_item_id": "wi-%d" % i, "attempt_id": "attempt-%d" % i, "node_id": "node-a", "producer_kind": "WORKER"}
        return self.mutate("r1_start", i, value) if self.mutate else value

    def find_r1_attempt_completed(self, **identity):
        i = self._index(identity["attempt_id"])
        value = {"event_id": "event-%d" % i, "event_type": "ATTEMPT_COMPLETED", "test_run_id": "TR", "work_item_id": "wi-%d" % i, "attempt_id": "attempt-%d" % i, "node_id": "node-a", "producer_kind": "WORKER"}
        return self.mutate("r1", i, value) if self.mutate else value


def proof():
    return SingleNodeFullLoopProof(test_run_id="TR", stages=("SCOPE_INTAKE", "REPORT_RELEASE"), work_item_ids=("wi-0", "wi-1"), lease_ids=("attempt-0", "attempt-1"), stage_instance_ids=("stage-0", "stage-1"), attempt_ids=("attempt-0", "attempt-1"), evidence_refs=("artifact:evidence-0", "artifact:evidence-1"))


def test_center_truth_verifier_requires_completed_work_attempt_artifact_and_r1():
    verified = SingleNodeCenterTruthVerifier(truth_reader=TruthReader()).verify(proof())
    assert verified.verified_work_items == ("wi-0", "wi-1")
    assert verified.verified_r1_events == ("event-0", "event-1")
    assert verified.verified_r1_start_events == ()
    assert verified.status == "CENTER_R1_EVIDENCE_VERIFIED_NOT_AUTHORIZED"
    assert verified.bank_reality_verified is False
    assert verified.release_status == "HOLD"


def test_center_truth_verifier_binds_attempt_start_completion_chain_to_expected_node():
    verified = SingleNodeCenterTruthVerifier(truth_reader=TruthReader(), expected_node_id="node-a").verify(proof())
    assert verified.verified_attempts == ("attempt-0", "attempt-1")
    assert verified.verified_r1_start_events == ("start-0", "start-1")
    assert verified.verified_r1_events == ("event-0", "event-1")


def test_center_truth_verifier_requires_start_reader_for_production_binding():
    class NoStartReader(TruthReader):
        find_r1_attempt_started = None
    with pytest.raises(SingleNodeTruthError, match="CENTER_TRUTH_READER_INCOMPLETE:find_r1_attempt_started"):
        SingleNodeCenterTruthVerifier(truth_reader=NoStartReader(), expected_node_id="node-a")


def test_center_truth_verifier_rejects_missing_or_stale_attempt_start():
    class MissingStartReader(TruthReader):
        def find_r1_attempt_started(self, **identity):
            return None
    with pytest.raises(SingleNodeTruthError, match="R1_ATTEMPT_STARTED_MISSING:SCOPE_INTAKE"):
        SingleNodeCenterTruthVerifier(truth_reader=MissingStartReader(), expected_node_id="node-a").verify(proof())

    def mutate(kind, index, payload):
        if kind == "r1_start" and index == 0:
            payload = dict(payload); payload["attempt_id"] = "stale-attempt"
        return payload
    with pytest.raises(SingleNodeTruthError, match="R1_ATTEMPT_STARTED_IDENTITY_MISMATCH:SCOPE_INTAKE"):
        SingleNodeCenterTruthVerifier(truth_reader=TruthReader(mutate=mutate), expected_node_id="node-a").verify(proof())


def test_center_truth_verifier_rejects_reused_attempt_start_event_identity():
    def mutate(kind, index, payload):
        if kind == "r1_start":
            payload = dict(payload); payload["event_id"] = "same-start"
        return payload
    with pytest.raises(SingleNodeTruthError, match="R1_ATTEMPT_STARTED_EVENT_ID_REUSED"):
        SingleNodeCenterTruthVerifier(truth_reader=TruthReader(mutate=mutate), expected_node_id="node-a").verify(proof())


def test_center_truth_verifier_rejects_claimed_stage_instance_not_backed_by_attempt():
    def mutate(kind, index, payload):
        if kind == "attempt" and index == 0:
            payload = dict(payload); payload["stage_instance_id"] = "stage-from-another-claim"
        return payload
    with pytest.raises(SingleNodeTruthError, match="CENTER_ATTEMPT_IDENTITY_MISMATCH:SCOPE_INTAKE"):
        SingleNodeCenterTruthVerifier(truth_reader=TruthReader(mutate=mutate)).verify(proof())


def test_center_truth_verifier_includes_claim_identity_in_denominator():
    divergent = SingleNodeFullLoopProof(
        test_run_id="TR", stages=("SCOPE_INTAKE", "REPORT_RELEASE"), work_item_ids=("wi-0", "wi-1"),
        lease_ids=("attempt-0",), stage_instance_ids=("stage-0", "stage-1"),
        attempt_ids=("attempt-0", "attempt-1"), evidence_refs=("artifact:evidence-0", "artifact:evidence-1"),
    )
    with pytest.raises(SingleNodeTruthError, match="SINGLE_NODE_PROOF_DENOMINATOR_DIVERGED"):
        SingleNodeCenterTruthVerifier(truth_reader=TruthReader()).verify(divergent)


def test_center_truth_verifier_rejects_attempt_not_issued_by_observed_center_lease():
    stitched = SingleNodeFullLoopProof(
        test_run_id="TR", stages=("SCOPE_INTAKE", "REPORT_RELEASE"), work_item_ids=("wi-0", "wi-1"),
        lease_ids=("lease-from-claim-0", "attempt-1"), stage_instance_ids=("stage-0", "stage-1"),
        attempt_ids=("attempt-0", "attempt-1"), evidence_refs=("artifact:evidence-0", "artifact:evidence-1"),
    )
    with pytest.raises(SingleNodeTruthError, match="CENTER_LEASE_ATTEMPT_IDENTITY_MISMATCH:SCOPE_INTAKE"):
        SingleNodeCenterTruthVerifier(truth_reader=TruthReader()).verify(stitched)


@pytest.mark.parametrize(
    "kind,field,value,error",
    [
        ("work", "status", "READY", "CENTER_WORK_ITEM_NOT_COMPLETED:SCOPE_INTAKE"),
        ("attempt", "work_item_id", "wrong", "CENTER_ATTEMPT_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("attempt", "stage_instance_id", "stale-stage-instance", "CENTER_ATTEMPT_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("artifact", "attempt_id", "stale", "CENTER_ARTIFACT_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("artifact", "test_run_id", "STALE_RUN", "CENTER_ARTIFACT_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("artifact", "producer_kind", "CENTER", "CENTER_ARTIFACT_NOT_WORKER_PRODUCED:SCOPE_INTAKE"),
        ("r1", "event_type", "ATTEMPT_STARTED", "R1_ATTEMPT_COMPLETED_INVALID:SCOPE_INTAKE"),
        ("r1", "test_run_id", "STALE_RUN", "R1_ATTEMPT_COMPLETED_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("r1", "work_item_id", "wrong", "R1_ATTEMPT_COMPLETED_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("r1", "attempt_id", "wrong", "R1_ATTEMPT_COMPLETED_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("r1", "producer_kind", "CENTER", "R1_ATTEMPT_COMPLETED_NOT_WORKER_PRODUCED:SCOPE_INTAKE"),
    ],
)
def test_center_truth_verifier_fails_closed_on_missing_stale_or_non_worker_truth(kind, field, value, error):
    def mutate(actual_kind, index, payload):
        if actual_kind == kind and index == 0:
            payload = dict(payload); payload[field] = value
        return payload
    with pytest.raises(SingleNodeTruthError, match=error):
        SingleNodeCenterTruthVerifier(truth_reader=TruthReader(mutate=mutate)).verify(proof())


@pytest.mark.parametrize(
    "kind,field,error",
    [
        ("attempt", "producer_node_id", "CENTER_ATTEMPT_NODE_ID_MISMATCH:SCOPE_INTAKE"),
        ("artifact", "node_id", "CENTER_ARTIFACT_NODE_ID_MISMATCH:SCOPE_INTAKE"),
        ("r1_start", "node_id", "R1_ATTEMPT_STARTED_NODE_ID_MISMATCH:SCOPE_INTAKE"),
        ("r1", "node_id", "R1_ATTEMPT_COMPLETED_NODE_ID_MISMATCH:SCOPE_INTAKE"),
    ],
)
def test_center_truth_verifier_rejects_split_node_durable_truth(kind, field, error):
    def mutate(actual_kind, index, payload):
        if actual_kind == kind and index == 0:
            payload = dict(payload); payload[field] = "node-b"
        return payload
    with pytest.raises(SingleNodeTruthError, match=error):
        SingleNodeCenterTruthVerifier(truth_reader=TruthReader(mutate=mutate), expected_node_id="node-a").verify(proof())


def test_center_truth_verifier_rejects_reused_artifact_identity():
    duplicated = SingleNodeFullLoopProof(test_run_id="TR", stages=("SCOPE_INTAKE", "REPORT_RELEASE"), work_item_ids=("wi-0", "wi-1"), lease_ids=("attempt-0", "attempt-1"), stage_instance_ids=("stage-0", "stage-1"), attempt_ids=("attempt-0", "attempt-1"), evidence_refs=("artifact:evidence-0", "artifact:evidence-0"))
    class ReusedArtifactReader(TruthReader):
        def get_artifact(self, artifact_id):
            return {"test_run_id": "TR", "work_item_id": "wi-0", "attempt_id": "attempt-0", "node_id": "node-a", "producer_kind": "WORKER", "status": "COMPLETED"}
    with pytest.raises(SingleNodeTruthError):
        SingleNodeCenterTruthVerifier(truth_reader=ReusedArtifactReader()).verify(duplicated)


def test_center_truth_verifier_rejects_reused_r1_event_identity():
    def mutate(kind, index, payload):
        if kind == "r1":
            payload = dict(payload); payload["event_id"] = "same-event"
        return payload
    with pytest.raises(SingleNodeTruthError, match="R1_EVENT_ID_REUSED"):
        SingleNodeCenterTruthVerifier(truth_reader=TruthReader(mutate=mutate)).verify(proof())
