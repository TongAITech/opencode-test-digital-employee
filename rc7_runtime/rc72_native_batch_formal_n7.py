"""C10 formal bridge: only accepted real N7 proof can complete batch results.

The batch producer/reviewer are *semantic candidates*. This bridge reads the
A-owned N7 audited full-denominator business truth, without minting PASS,
Oracle, Attempt, Evidence, TestObligation or NodeGate itself.
"""
from __future__ import annotations

from typing import Any, Dict

from .models import ContractError
from .rc72_n7_pipeline import N7PipelineService
from .rc72_obligation_execution_proof import AcceptedObligationExecutionProof
from .rc72_safe_execution_batch import (
    ExecutionBatchMemberResult, SafeExecutionBatchService,
)
from .rc72_native_batch_raw_proof import verify_native_raw_digest


class NativeBatchFormalN7Error(ContractError):
    pass


def _one(truth: Any, kind: str, **filters: Any) -> Dict[str, Any]:
    rows = truth.query(kind, **filters)
    if len(rows) != 1:
        raise NativeBatchFormalN7Error("NATIVE_BATCH_FORMAL_%s_NOT_UNIQUE" % kind.upper())
    return rows[0]


class NativeBatchFormalN7Reconciler:
    """Read-only accepted N7 proof, then member-wise SafeBatch result receipt."""

    def __init__(self, pipeline: N7PipelineService) -> None:
        if not isinstance(pipeline, N7PipelineService):
            raise NativeBatchFormalN7Error("NATIVE_BATCH_FORMAL_N7_PIPELINE_REQUIRED")
        self.pipeline = pipeline
        self.truth = pipeline.truth
        self.release_id = pipeline.release_id
        self.batch = SafeExecutionBatchService(self.truth, release_id=self.release_id)

    def reconcile(
        self, *, release_batch_id: str, batch_receipt_id: str,
        candidate_id: str, review_id: str,
    ) -> Dict[str, Any]:
        if any(not isinstance(v, str) or not v.strip() for v in (
            release_batch_id, batch_receipt_id, candidate_id, review_id,
        )):
            raise NativeBatchFormalN7Error("NATIVE_BATCH_FORMAL_IDS_REQUIRED")
        receipt = _one(self.truth, "rc72_execution_batch_receipt",
                       batch_receipt_id=batch_receipt_id)
        candidate = _one(self.truth, "rc72_native_batch_candidate",
                         candidate_id=candidate_id)
        review = _one(self.truth, "rc72_native_batch_review",
                      review_id=review_id)
        if (
            receipt.get("release_id") != self.release_id
            or candidate.get("release_id") != self.release_id
            or review.get("release_id") != self.release_id
            or len(receipt.get("members", [])) < 2
            or receipt.get("member_count") != len(receipt["members"])
            or receipt["batch_receipt_id"] != candidate.get("batch_receipt_id")
            or candidate.get("candidate_id") != review.get("candidate_id")
            or receipt.get("mission_id") != candidate.get("mission_id")
            or receipt.get("mission_id") != review.get("mission_id")
            or receipt.get("batch_id") != candidate.get("batch_id")
            or receipt.get("batch_id") != review.get("batch_id")
            or candidate.get("status") != "UNVERIFIED"
            or review.get("status") != "UNVERIFIED_INDEPENDENT_REVIEW"
        ):
            raise NativeBatchFormalN7Error("NATIVE_BATCH_FORMAL_SOURCE_LINEAGE_MISMATCH")
        # Re-read both native raw DSH files before trusting a historic R1
        # candidate/reviewer. A replaced file cannot be used to reconcile
        # any TestObligation to a formal member result.
        verify_native_raw_digest(
            raw_ref=candidate["raw_output_ref"],
            expected_sha256=candidate.get("raw_output_sha256"),
        )
        verify_native_raw_digest(
            raw_ref=review["raw_output_ref"],
            expected_sha256=review.get("raw_output_sha256"),
        )
        intended = {(m["workitem_id"], m["attempt_id"], m["case_id"])
                    for m in receipt["members"]}
        intended_pairs = {(w, a) for w, a, _ in intended}
        from_candidate = {(m["workitem_id"], m["attempt_id"]) for m in candidate["members"]}
        from_review = {(m["workitem_id"], m["attempt_id"]) for m in review["members"]}
        if (
            len(intended) != len(receipt["members"])
            or len(from_candidate) != len(candidate["members"])
            or len(from_review) != len(review["members"])
            or from_candidate != intended_pairs or from_review != intended_pairs
            or any(m["evidence_adequacy"] != "SUFFICIENT_CANDIDATE"
                   for m in review["members"])
        ):
            raise NativeBatchFormalN7Error("NATIVE_BATCH_FORMAL_MEMBER_OR_REVIEW_GAP")

        # Authoritative N7 full-release source, reviewer, lifecycle and
        # deterministic-Oracle audit. No supplied PASS flag is accepted.
        accepted = AcceptedObligationExecutionProof(self.pipeline).audit(
            release_batch_id=release_batch_id,
        )
        if (
            accepted.get("mission_id") != receipt["mission_id"]
            or accepted.get("source_commit") != self.pipeline.source_commit
        ):
            raise NativeBatchFormalN7Error("NATIVE_BATCH_FORMAL_ACCEPTED_SCOPE_MISMATCH")
        bundle = _one(self.truth, "rc72_n7_evidence_bundle",
                      bundle_id=accepted["bundle_id"])
        if (
            bundle.get("mission_id") != receipt["mission_id"]
            or bundle.get("release_batch_id") != release_batch_id
            or bundle.get("source_commit") != self.pipeline.source_commit
        ):
            raise NativeBatchFormalN7Error("NATIVE_BATCH_FORMAL_BUNDLE_SCOPE_MISMATCH")
        formal = {(x["workitem_id"], x["attempt_id"], x["case_id"]): x
                  for x in bundle["case_results"]}
        if len(formal) != len(bundle["case_results"]) or not intended.issubset(set(formal)):
            raise NativeBatchFormalN7Error("NATIVE_BATCH_FORMAL_CASE_DENOMINATOR_MISMATCH")

        results = []
        for member in receipt["members"]:
            item = formal[(member["workitem_id"], member["attempt_id"], member["case_id"])]
            attempt = _one(self.truth, "execution_attempt", attempt_id=member["attempt_id"])
            assertion = _one(self.truth, "assertion", id=item["assertion_ref"])
            if (
                attempt.get("mission_id") != receipt["mission_id"]
                or attempt.get("workitem_id") != member["workitem_id"]
                or attempt.get("tc_id") != member["case_id"]
                or attempt.get("status") != "PASS"
                or attempt.get("assertion_ref") != item["assertion_ref"]
                or assertion.get("passed") is not True
                or assertion.get("attempt_id") != member["attempt_id"]
                or assertion.get("tc_id") != member["case_id"]
                or not isinstance(attempt.get("tool_call_refs"), list)
                or not attempt["tool_call_refs"]
                or not isinstance(attempt.get("evidence_refs"), list)
                or not attempt["evidence_refs"]
            ):
                raise NativeBatchFormalN7Error("NATIVE_BATCH_FORMAL_ORACLE_PROOF_MISSING")
            results.append(ExecutionBatchMemberResult(
                workitem_id=member["workitem_id"],
                attempt_id=member["attempt_id"],
                actual_result_ref="r1://artifact/" + item["dispatch_id"],
                assertion_result="PASS",
                evidence_refs=tuple(attempt["evidence_refs"]), gap_refs=(),
            ))

        return self.batch.record_results(batch_receipt_id, results)
