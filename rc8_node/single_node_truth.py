"""Fail-closed Center/R1 truth verification for RC8 SINGLE_NODE full-loop proof.

This module does not execute work and cannot grant PASS. It verifies that the
identities observed by SingleNodeFullLoopProofRunner are backed by Center truth:
completed WorkItems, matching terminal Attempts, completed ArtifactManifests and
R1 ATTEMPT_STARTED -> ATTEMPT_COMPLETED event chains. A production proof may
additionally bind all durable producer identities to the exact node that held the
production claim/lease.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

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
    verified_r1_start_events: Tuple[str, ...] = ()
    status: str = "CENTER_R1_EVIDENCE_VERIFIED_NOT_AUTHORIZED"
    bank_reality_verified: bool = False
    release_status: str = "HOLD"


class SingleNodeCenterTruthVerifier:
    """Verify a traversal against Center durable/R1 truth without PASS authority."""

    def __init__(self, *, truth_reader: Any, expected_node_id: Optional[str] = None) -> None:
        required = ("get_work_item", "get_attempt", "get_artifact", "find_r1_attempt_completed")
        if str(expected_node_id or "").strip():
            required = required + ("find_r1_attempt_started",)
        missing = [name for name in required if not callable(getattr(truth_reader, name, None))]
        if missing:
            raise SingleNodeTruthError("CENTER_TRUTH_READER_INCOMPLETE:%s" % ",".join(missing))
        self.truth_reader = truth_reader
        self.expected_node_id = str(expected_node_id or "").strip() or None

    @staticmethod
    def _mapping(value: Any, code: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise SingleNodeTruthError(code)
        return value

    def _require_node(self, value: Mapping[str, Any], field: str, code: str) -> None:
        if self.expected_node_id is None:
            return
        if str(value.get(field) or "").strip() != self.expected_node_id:
            raise SingleNodeTruthError(code)

    @staticmethod
    def _require_worker_producer(value: Mapping[str, Any], field: str, code: str) -> None:
        if str(value.get(field) or "").strip().upper() != "WORKER":
            raise SingleNodeTruthError(code)

    @staticmethod
    def _require_r1_identity(
        event: Mapping[str, Any], *, event_type: str, test_run_id: str, work_item_id: str,
        attempt_id: str, stage: str
    ) -> None:
        if str(event.get("event_type") or "") != event_type:
            raise SingleNodeTruthError("R1_%s_INVALID:%s" % (event_type, stage))
        if (
            str(event.get("test_run_id") or "") != test_run_id
            or str(event.get("work_item_id") or "") != work_item_id
            or str(event.get("attempt_id") or "") != attempt_id
        ):
            raise SingleNodeTruthError("R1_%s_IDENTITY_MISMATCH:%s" % (event_type, stage))

    def verify(self, proof: SingleNodeFullLoopProof) -> SingleNodeTruthProof:
        if not isinstance(proof, SingleNodeFullLoopProof):
            raise SingleNodeTruthError("SINGLE_NODE_PROOF_REQUIRED")
        if not proof.test_run_id or not proof.work_item_ids:
            raise SingleNodeTruthError("SINGLE_NODE_PROOF_IDENTITY_INCOMPLETE")
        if not (
            len(proof.stages)
            == len(proof.work_item_ids)
            == len(proof.lease_ids)
            == len(proof.stage_instance_ids)
            == len(proof.attempt_ids)
            == len(proof.evidence_refs)
        ):
            raise SingleNodeTruthError("SINGLE_NODE_PROOF_DENOMINATOR_DIVERGED")

        for stage, lease_id, attempt_id in zip(proof.stages, proof.lease_ids, proof.attempt_ids):
            if str(lease_id or "").strip() != str(attempt_id or "").strip():
                raise SingleNodeTruthError("CENTER_LEASE_ATTEMPT_IDENTITY_MISMATCH:%s" % stage)

        r1_ids = []
        r1_start_ids = []
        artifact_ids = []
        for stage, work_item_id, stage_instance_id, attempt_id, artifact_ref in zip(
            proof.stages,
            proof.work_item_ids,
            proof.stage_instance_ids,
            proof.attempt_ids,
            proof.evidence_refs,
        ):
            work = self._mapping(self.truth_reader.get_work_item(work_item_id), "CENTER_WORK_ITEM_MISSING:%s" % stage)
            if str(work.get("test_run_id") or "") != proof.test_run_id or str(work.get("stage") or "") != stage:
                raise SingleNodeTruthError("CENTER_WORK_ITEM_IDENTITY_MISMATCH:%s" % stage)
            if str(work.get("status") or "") != "COMPLETED":
                raise SingleNodeTruthError("CENTER_WORK_ITEM_NOT_COMPLETED:%s" % stage)

            attempt = self._mapping(self.truth_reader.get_attempt(attempt_id), "CENTER_ATTEMPT_MISSING:%s" % stage)
            if (
                str(attempt.get("work_item_id") or "") != work_item_id
                or str(attempt.get("test_run_id") or "") != proof.test_run_id
                or str(attempt.get("stage_instance_id") or "") != stage_instance_id
            ):
                raise SingleNodeTruthError("CENTER_ATTEMPT_IDENTITY_MISMATCH:%s" % stage)
            if str(attempt.get("status") or "") != "COMPLETED":
                raise SingleNodeTruthError("CENTER_ATTEMPT_NOT_COMPLETED:%s" % stage)
            self._require_node(attempt, "producer_node_id", "CENTER_ATTEMPT_NODE_ID_MISMATCH:%s" % stage)

            artifact_id = str(artifact_ref or "").split("artifact:", 1)[-1].strip()
            if not artifact_ref.startswith("artifact:") or not artifact_id:
                raise SingleNodeTruthError("CENTER_ARTIFACT_REF_INVALID:%s" % stage)
            artifact = self._mapping(self.truth_reader.get_artifact(artifact_id), "CENTER_ARTIFACT_MISSING:%s" % stage)
            if (
                str(artifact.get("test_run_id") or "") != proof.test_run_id
                or str(artifact.get("work_item_id") or "") != work_item_id
                or str(artifact.get("attempt_id") or "") != attempt_id
            ):
                raise SingleNodeTruthError("CENTER_ARTIFACT_IDENTITY_MISMATCH:%s" % stage)
            if str(artifact.get("status") or "") != "COMPLETED":
                raise SingleNodeTruthError("CENTER_ARTIFACT_NOT_COMPLETED:%s" % stage)
            self._require_node(artifact, "node_id", "CENTER_ARTIFACT_NODE_ID_MISMATCH:%s" % stage)
            self._require_worker_producer(artifact, "producer_kind", "CENTER_ARTIFACT_NOT_WORKER_PRODUCED:%s" % stage)

            if self.expected_node_id is not None:
                started = self._mapping(
                    self.truth_reader.find_r1_attempt_started(
                        test_run_id=proof.test_run_id, work_item_id=work_item_id, attempt_id=attempt_id
                    ),
                    "R1_ATTEMPT_STARTED_MISSING:%s" % stage,
                )
                self._require_r1_identity(
                    started, event_type="ATTEMPT_STARTED", test_run_id=proof.test_run_id,
                    work_item_id=work_item_id, attempt_id=attempt_id, stage=stage,
                )
                self._require_node(started, "node_id", "R1_ATTEMPT_STARTED_NODE_ID_MISMATCH:%s" % stage)
                self._require_worker_producer(started, "producer_kind", "R1_ATTEMPT_STARTED_NOT_WORKER_PRODUCED:%s" % stage)
                started_id = str(started.get("event_id") or "").strip()
                if not started_id:
                    raise SingleNodeTruthError("R1_ATTEMPT_STARTED_EVENT_ID_MISSING:%s" % stage)
                r1_start_ids.append(started_id)

            event = self._mapping(
                self.truth_reader.find_r1_attempt_completed(
                    test_run_id=proof.test_run_id, work_item_id=work_item_id, attempt_id=attempt_id
                ),
                "R1_ATTEMPT_COMPLETED_MISSING:%s" % stage,
            )
            self._require_r1_identity(
                event, event_type="ATTEMPT_COMPLETED", test_run_id=proof.test_run_id,
                work_item_id=work_item_id, attempt_id=attempt_id, stage=stage,
            )
            self._require_node(event, "node_id", "R1_ATTEMPT_COMPLETED_NODE_ID_MISMATCH:%s" % stage)
            self._require_worker_producer(event, "producer_kind", "R1_ATTEMPT_COMPLETED_NOT_WORKER_PRODUCED:%s" % stage)
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                raise SingleNodeTruthError("R1_EVENT_ID_MISSING:%s" % stage)
            r1_ids.append(event_id)
            artifact_ids.append(artifact_id)

        if len(set(artifact_ids)) != len(artifact_ids):
            raise SingleNodeTruthError("CENTER_ARTIFACT_ID_REUSED")
        if len(set(r1_ids)) != len(r1_ids):
            raise SingleNodeTruthError("R1_EVENT_ID_REUSED")
        if len(set(r1_start_ids)) != len(r1_start_ids):
            raise SingleNodeTruthError("R1_ATTEMPT_STARTED_EVENT_ID_REUSED")
        if set(r1_start_ids).intersection(r1_ids):
            raise SingleNodeTruthError("R1_START_COMPLETION_EVENT_ID_COLLISION")
        return SingleNodeTruthProof(
            test_run_id=proof.test_run_id,
            verified_work_items=tuple(proof.work_item_ids),
            verified_attempts=tuple(proof.attempt_ids),
            verified_artifacts=tuple(artifact_ids),
            verified_r1_events=tuple(r1_ids),
            verified_r1_start_events=tuple(r1_start_ids),
        )
