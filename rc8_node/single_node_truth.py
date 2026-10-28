"""Fail-closed Center/R1 truth verification for RC8 SINGLE_NODE full-loop proof.

This module does not execute work and cannot grant PASS.  It verifies that the
identities observed by SingleNodeFullLoopProofRunner are backed by Center truth:
completed WorkItems, matching terminal Attempts, completed ArtifactManifests and
R1 ATTEMPT_COMPLETED events.  A caller must provide a production Center truth
reader (HTTP/repository adapter); missing truth is UNKNOWN and fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Tuple

from .single_node_full_loop_proof import SingleNodeFullLoopProof


class SingleNodeTruthError(RuntimeError):
    pass


@dataclass(frozen=True)
class SingleNodeTruthProof:
    test_run_id: str
    verified_work_items: Tuple[str, ...]
    verified_attempts: Tuple[str, ...]
    verified_artifacts: Tuple[str, ...]
    verified_r1_events: Tuple[str, ...]
    status: str = "CENTER_R1_EVIDENCE_VERIFIED_NOT_AUTHORIZED"
    bank_reality_verified: bool = False
    release_status: str = "HOLD"


class SingleNodeCenterTruthVerifier:
    """Verify a traversal against Center durable/R1 truth without PASS authority."""

    def __init__(self, *, truth_reader: Any) -> None:
        required = ("get_work_item", "get_attempt", "get_artifact", "find_r1_attempt_completed")
        missing = [name for name in required if not callable(getattr(truth_reader, name, None))]
        if missing:
            raise SingleNodeTruthError("CENTER_TRUTH_READER_INCOMPLETE:%s" % ",".join(missing))
        self.truth_reader = truth_reader

    @staticmethod
    def _mapping(value: Any, code: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise SingleNodeTruthError(code)
        return value

    def verify(self, proof: SingleNodeFullLoopProof) -> SingleNodeTruthProof:
        if not isinstance(proof, SingleNodeFullLoopProof):
            raise SingleNodeTruthError("SINGLE_NODE_PROOF_REQUIRED")
        if not proof.test_run_id or not proof.work_item_ids:
            raise SingleNodeTruthError("SINGLE_NODE_PROOF_IDENTITY_INCOMPLETE")
        if not (len(proof.stages) == len(proof.work_item_ids) == len(proof.attempt_ids) == len(proof.evidence_refs)):
            raise SingleNodeTruthError("SINGLE_NODE_PROOF_DENOMINATOR_DIVERGED")

        r1_ids = []
        artifact_ids = []
        for stage, work_item_id, attempt_id, artifact_ref in zip(
            proof.stages, proof.work_item_ids, proof.attempt_ids, proof.evidence_refs
        ):
            work = self._mapping(self.truth_reader.get_work_item(work_item_id), "CENTER_WORK_ITEM_MISSING:%s" % stage)
            if str(work.get("test_run_id") or "") != proof.test_run_id or str(work.get("stage") or "") != stage:
                raise SingleNodeTruthError("CENTER_WORK_ITEM_IDENTITY_MISMATCH:%s" % stage)
            if str(work.get("status") or "") != "COMPLETED":
                raise SingleNodeTruthError("CENTER_WORK_ITEM_NOT_COMPLETED:%s" % stage)

            attempt = self._mapping(self.truth_reader.get_attempt(attempt_id), "CENTER_ATTEMPT_MISSING:%s" % stage)
            if str(attempt.get("work_item_id") or "") != work_item_id or str(attempt.get("test_run_id") or "") != proof.test_run_id:
                raise SingleNodeTruthError("CENTER_ATTEMPT_IDENTITY_MISMATCH:%s" % stage)
            if str(attempt.get("status") or "") != "COMPLETED":
                raise SingleNodeTruthError("CENTER_ATTEMPT_NOT_COMPLETED:%s" % stage)

            artifact_id = str(artifact_ref or "").split("artifact:", 1)[-1].strip()
            if not artifact_ref.startswith("artifact:") or not artifact_id:
                raise SingleNodeTruthError("CENTER_ARTIFACT_REF_INVALID:%s" % stage)
            artifact = self._mapping(self.truth_reader.get_artifact(artifact_id), "CENTER_ARTIFACT_MISSING:%s" % stage)
            if str(artifact.get("work_item_id") or "") != work_item_id or str(artifact.get("attempt_id") or "") != attempt_id:
                raise SingleNodeTruthError("CENTER_ARTIFACT_IDENTITY_MISMATCH:%s" % stage)
            if str(artifact.get("status") or "") != "COMPLETED":
                raise SingleNodeTruthError("CENTER_ARTIFACT_NOT_COMPLETED:%s" % stage)

            event = self._mapping(
                self.truth_reader.find_r1_attempt_completed(
                    test_run_id=proof.test_run_id, work_item_id=work_item_id, attempt_id=attempt_id
                ),
                "R1_ATTEMPT_COMPLETED_MISSING:%s" % stage,
            )
            if str(event.get("event_type") or "") != "ATTEMPT_COMPLETED":
                raise SingleNodeTruthError("R1_ATTEMPT_COMPLETED_INVALID:%s" % stage)
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                raise SingleNodeTruthError("R1_EVENT_ID_MISSING:%s" % stage)
            r1_ids.append(event_id)
            artifact_ids.append(artifact_id)

        if len(set(r1_ids)) != len(r1_ids):
            raise SingleNodeTruthError("R1_EVENT_ID_REUSED")
        return SingleNodeTruthProof(
            test_run_id=proof.test_run_id,
            verified_work_items=tuple(proof.work_item_ids),
            verified_attempts=tuple(proof.attempt_ids),
            verified_artifacts=tuple(artifact_ids),
            verified_r1_events=tuple(r1_ids),
        )
