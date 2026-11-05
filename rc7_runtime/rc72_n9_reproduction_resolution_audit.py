"""C04: independent R1 audit linking an approved real reproduction to a real fix.

This is a read-only provenance gate, NOT a defect generator, repair executor,
N9 NodeGate or field acceptance. An independent defect producer must create a
PRODUCT_DEFECT gap containing the signed reproduction lineage. Existing native
DefectResolutionControl audits RCA, fix revision, a fresh original-Case PASS
and distinct impact-regression PASS; labels are never accepted as proof.
"""
from __future__ import annotations

from .closed_loop_control import ClosedLoopControlPlane
from .defect_resolution_control import DefectResolutionControl, DefectResolutionControlError
from .models import ContractError
from .rc72_n9_approved_reproduction_execution import N9ApprovedReproductionExecutionService


class N9ApprovedReproductionResolutionAudit:
    def __init__(self, reproduction):
        if not isinstance(reproduction, N9ApprovedReproductionExecutionService):
            raise ContractError("N9_REPRO_RESOLUTION_TRUSTED_PRODUCER_REQUIRED")
        self.reproduction = reproduction
        self.truth = reproduction.truth
        self.release_id = reproduction.release_id
        self.source_commit = reproduction.source_commit

    def _one(self, kind, **scope):
        rows = self.truth.query(kind, **scope)
        if len(rows) != 1:
            raise ContractError("N9_REPRO_RESOLUTION_R1_NOT_UNIQUE:" + kind)
        return rows[0]

    def audit(self, *, release_batch_id, request_id, defect_id):
        """Verify exact original->approved fresh reproduction->defect->RCA/fix/retet.

        Never initiates HTTP, a retry, a worker, a defect or a product fix.
        A positive result is only an independently audited defect lifecycle;
        the N9/N10 canonical gates and bank field qualification remain separate.
        """
        if not all(isinstance(x, str) and x for x in
                   (release_batch_id, request_id, defect_id)):
            raise ContractError("N9_REPRO_RESOLUTION_EXACT_SCOPE_REQUIRED")
        proof = self.reproduction.audit(request_id=request_id)
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        request = self._one("rc72_n9_reproduction_authorization_request",
                            request_id=request_id)
        record = self._one("rc72_n9_approved_reproduction_execution",
                           request_id=request_id)
        if (record.get("state") != "EXECUTED_WITH_DURABLE_EVIDENCE"
                or request["release_batch_id"] != release_batch_id
                or record["release_batch_id"] != release_batch_id
                or request["release_id"] != self.release_id
                or request["source_commit"] != self.source_commit
                or record["source_commit"] != self.source_commit
                or batch["release_id"] != self.release_id
                or request["mission_id"] != batch["mission_id"]
                or record["mission_id"] != batch["mission_id"]):
            raise ContractError("N9_REPRO_RESOLUTION_SIGNED_RELEASE_SCOPE_CHANGED")
        if (proof.get("reproduced") is not True
                or proof.get("conclusive") is not True
                or record.get("reproduced") is not True
                or record.get("conclusive") is not True):
            return dict(
                status="HOLD", reason="N9_REPRO_PRODUCT_MISMATCH_NOT_CONFIRMED",
                request_id=request_id, defect_id=defect_id,
                n9_gate_pass=False, field_verified=False, bank_final=False)

        defect = self._one("rc7_defect", defect_id=defect_id)
        gap = self._one("rc7_gap", gap_id=defect["source_gap_id"])
        original = self._one("rc7_gap", gap_id=request["original_gap_id"])
        formal = [self._one("rc7_evidence", evidence_id=eid)
                  for eid in record["evidence_ids"]]
        formal = [item for item in formal
                  if item.get("kind") == "RUNTIME_EXECUTION_RECORD"
                  and item.get("content_ref") ==
                  self._one("rc7_artifact",
                            artifact_id=record["execution_artifact_id"])["content_ref"]
                  and record["reproduction_attempt_id"] in item.get("subject_refs", [])]
        if len(formal) != 1:
            raise ContractError("N9_REPRO_RESOLUTION_ORIGINAL_FORMAL_RECORD_REQUIRED")
        # A separate, explicitly qualified product gap must point back to the
        # exact approved attempt AND the original N8 discrepancy. A CLOSED tag
        # or unrelated defect with a passing regression cannot supply lineage.
        required_subjects = {
            request["original_gap_id"], record["record_id"],
            record["reproduction_attempt_id"], request["original_case_id"]}
        if (original.get("mission_id") != batch["mission_id"]
                or original.get("category") != "VALID_TEST_FAILURE"
                or original.get("target_node") != "N9_DEFECT"
                or gap.get("mission_id") != batch["mission_id"]
                or gap.get("category") != "PRODUCT_DEFECT"
                or gap.get("target_node") != "DEFECT"
                or not required_subjects.issubset(set(gap.get("subject_refs", [])))
                or formal[0]["evidence_id"] not in gap.get("evidence_refs", [])
                or defect.get("mission_id") != batch["mission_id"]
                or request["original_case_id"] not in defect.get("test_case_ids", [])
                or not {request["original_attempt_id"],
                        record["reproduction_attempt_id"]}.issubset(
                            set(defect.get("execution_attempt_ids", [])))
                or formal[0]["evidence_id"] not in defect.get("evidence_refs", [])):
            raise ContractError("N9_REPRO_RESOLUTION_INDEPENDENT_DEFECT_LINEAGE_REQUIRED")

        control = ClosedLoopControlPlane(
            self.truth, self.release_id, request["mission_id"])
        try:
            closed = DefectResolutionControl().audit_closed(control, defect_id)
        except (DefectResolutionControlError, ValueError, KeyError, TypeError) as exc:
            raise ContractError(
                "N9_REPRO_RESOLUTION_REAL_RCA_FIX_REGRESSION_REQUIRED:" + str(exc)) from exc
        if closed["source_gap_id"] != defect["source_gap_id"]:
            raise ContractError("N9_REPRO_RESOLUTION_CLOSED_GAP_CHANGED")
        # This only audits actual R1. N9's original VALID_TEST_FAILURE gap is
        # NOT silently RESOLVED; separate professional disposition is required.
        return dict(
            status="VERIFIED_DEFECT_CLOSED",
            reason="N9_REPRO_INDEPENDENT_RCA_FIX_AND_REGRESSION_AUDITED",
            release_batch_id=release_batch_id,
            request_id=request_id, defect_id=defect_id,
            reproduction_record_id=record["record_id"],
            original_gap_id=request["original_gap_id"],
            original_attempt_id=request["original_attempt_id"],
            reproduction_attempt_id=record["reproduction_attempt_id"],
            reproduction_evidence_id=formal[0]["evidence_id"],
            closure_evaluation_id=closed["closure_evaluation_id"],
            verification_artifact_id=closed["verification_artifact_id"],
            regression_artifact_ids=closed["regression_artifact_ids"],
            n9_gate_pass=False, field_verified=False, bank_final=False)
