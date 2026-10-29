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
        value = {"test_run_id": "TR", "work_item_id": "wi-%d" % i, "producer_node_id": "node-a", "status": "COMPLETED"}
        return self.mutate("attempt", i, value) if self.mutate else value

    def get_artifact(self, artifact_id):
        i = self._index(artifact_id)
        value = {"test_run_id": "TR", "work_item_id": "wi-%d" % i, "attempt_id": "attempt-%d" % i, "node_id": "node-a", "status": "COMPLETED"}
        return self.mutate("artifact", i, value) if self.mutate else value

    def find_r1_attempt_completed(self, **identity):
        i = self._index(identity["attempt_id"])
        value = {"event_id": "event-%d" % i, "event_type": "ATTEMPT_COMPLETED", "test_run_id": "TR", "work_item_id": "wi-%d" % i, "attempt_id": "attempt-%d" % i, "node_id": "node-a"}
        return self.mutate("r1", i, value) if self.mutate else value


def proof():
    return SingleNodeFullLoopProof(test_run_id="TR", stages=("SCOPE_INTAKE", "REPORT_RELEASE"), work_item_ids=("wi-0", "wi-1"), attempt_ids=("attempt-0", "attempt-1"), evidence_refs=("artifact:evidence-0", "artifact:evidence-1"))


def test_center_truth_verifier_requires_completed_work_attempt_artifact_and_r1():
    verified = SingleNodeCenterTruthVerifier(truth_reader=TruthReader()).verify(proof())
    assert verified.verified_work_items == ("wi-0", "wi-1")
    assert verified.verified_r1_events == ("event-0", "event-1")
    assert verified.status == "CENTER_R1_EVIDENCE_VERIFIED_NOT_AUTHORIZED"
    assert verified.bank_reality_verified is False
    assert verified.release_status == "HOLD"


def test_center_truth_verifier_binds_attempt_artifact_and_r1_to_expected_node():
    verified = SingleNodeCenterTruthVerifier(truth_reader=TruthReader(), expected_node_id="node-a").verify(proof())
    assert verified.verified_attempts == ("attempt-0", "attempt-1")


@pytest.mark.parametrize(
    "kind,field,value,error",
    [
        ("work", "status", "READY", "CENTER_WORK_ITEM_NOT_COMPLETED:SCOPE_INTAKE"),
        ("attempt", "work_item_id", "wrong", "CENTER_ATTEMPT_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("artifact", "attempt_id", "stale", "CENTER_ARTIFACT_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("artifact", "test_run_id", "STALE_RUN", "CENTER_ARTIFACT_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("r1", "event_type", "ATTEMPT_STARTED", "R1_ATTEMPT_COMPLETED_INVALID:SCOPE_INTAKE"),
        ("r1", "test_run_id", "STALE_RUN", "R1_ATTEMPT_COMPLETED_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("r1", "work_item_id", "wrong", "R1_ATTEMPT_COMPLETED_IDENTITY_MISMATCH:SCOPE_INTAKE"),
        ("r1", "attempt_id", "wrong", "R1_ATTEMPT_COMPLETED_IDENTITY_MISMATCH:SCOPE_INTAKE"),
    ],
)
def test_center_truth_verifier_fails_closed_on_missing_or_stale_truth(kind, field, value, error):
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
    duplicated = SingleNodeFullLoopProof(test_run_id="TR", stages=("SCOPE_INTAKE", "REPORT_RELEASE"), work_item_ids=("wi-0", "wi-1"), attempt_ids=("attempt-0", "attempt-1"), evidence_refs=("artifact:evidence-0", "artifact:evidence-0"))
    class ReusedArtifactReader(TruthReader):
        def get_artifact(self, artifact_id):
            return {"test_run_id": "TR", "work_item_id": "wi-0", "attempt_id": "attempt-0", "node_id": "node-a", "status": "COMPLETED"}
    with pytest.raises(SingleNodeTruthError):
        SingleNodeCenterTruthVerifier(truth_reader=ReusedArtifactReader()).verify(duplicated)


def test_center_truth_verifier_rejects_reused_r1_event_identity():
    def mutate(kind, index, payload):
        if kind == "r1":
            payload = dict(payload); payload["event_id"] = "same-event"
        return payload
    with pytest.raises(SingleNodeTruthError, match="R1_EVENT_ID_REUSED"):
        SingleNodeCenterTruthVerifier(truth_reader=TruthReader(mutate=mutate)).verify(proof())
