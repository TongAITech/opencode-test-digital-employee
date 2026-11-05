"""C04 formal N9 professional disposition: approved RCA/fix/regression -> NodeGate.

Never promotes the original VALID_TEST_FAILURE just because an independent
reproduction found a mismatch or a defect row says CLOSED. A separate trusted
bank professional reviewer must accept the frozen evidence. The exact original
N9 qualification WorkItem is finished from verified REAL DSH output, then the
original Gap follows its legal R1 state transitions with an independent
evaluation. Only a subsequent re-audit may emit the N9 PASS Gate. This is not
bank field qualification or N10 Release convergence.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import asdict

from rc6_runtime import contracts, truth as registry

from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .models import (Artifact, ContractError, Evaluation, EvaluationResult,
                     Evidence, GapStatus)
from .rc72_domain import (AutonomousMissionNode as Node, MissionNodeState as State,
                          NodeDelivery, NodeGate, NodeGateDecision)
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash
from .rc72_n8_product_recovery import NativeN8ProductRecoveryService
from .rc72_n9_reproduction_resolution_audit import N9ApprovedReproductionResolutionAudit
from .rc72_state_machine import RC72StateMachine
from .state_machine import transition_gap
from .truth_overlay import append_entity

_KIND = "rc72_n9_professional_disposition_review"
_EVENT = "RC72_N9_PROFESSIONAL_DISPOSITION_REVIEW_UPSERTED"
_PURPOSE = "N9_INDEPENDENT_POST_FIX_PROFESSIONAL_DISPOSITION"
_CRITERIA = [
    "N9_CURRENT_N8_INDEPENDENT_GATE",
    "N9_ORIGINAL_FAILED_ATTEMPT_RETAINED",
    "N9_SIGNED_HUMAN_APPROVED_FRESH_REPRODUCTION",
    "N9_INDEPENDENT_PRODUCT_DEFECT_RCA",
    "N9_NEW_ORIGINAL_CASE_FIX_VERIFICATION",
    "N9_DISTINCT_IMPACT_REGRESSION",
    "N9_INDEPENDENT_PROFESSIONAL_DISPOSITION",
    "N9_ORIGINAL_GAP_FORMALLY_ADJUDICATED",
    "N9_QUALIFICATION_WORKITEM_EVALUATED",
    "N9_NO_OPEN_PROFESSIONAL_GAPS_OR_WORK",
]
_TERMINAL = {"RESOLVED", "WAIVED", "DUPLICATE", "SUPERSEDED"}
_PROFESSIONAL_TYPES = {
    "N9_DISCREPANCY_QUALIFICATION", "DEFECT_REPRODUCTION", "QUALIFY_DEFECT",
    "DEFECT_RCA", "DEFECT_REGRESSION", "DEFECT_RESOLUTION",
    "DEFECT_FIX_VERIFICATION", "DEFECT_IMPACT_REGRESSION",
}


def _unsigned(row):
    return {k: v for k, v in row.items()
            if k not in ("signature", "artifact_type", "artifact_version")}


def install_overlay():
    def validate(payload):
        row = dict(payload)
        for field in ("review_id", "request_id", "defect_id", "release_id",
                      "source_commit", "release_batch_id", "mission_id",
                      "original_gap_id", "qualification_workitem_id",
                      "reproduction_record_id", "reproduction_attempt_id",
                      "closure_evaluation_id", "proof_sha256", "reviewer_ref",
                      "attestation_ref", "signature"):
            contracts._require_str(row, field)
        if (row.get("purpose") != _PURPOSE
                or row.get("decision") != "APPROVED_POST_FIX_PROFESSIONAL_REVIEW"
                or row.get("state") != "REVIEW_ACCEPTED_GAP_STILL_PENDING"
                or not isinstance(row.get("evidence_refs"), list)
                or not row["evidence_refs"]
                or not isinstance(row.get("reviewed_at"), int)
                or any(k in row for k in (
                    "original_gap_resolved", "n9_pass", "n10_pass",
                    "field_verified", "bank_final", "product_fix_applied"))):
            raise contracts.DomainValidationError("N9_PROFESSIONAL_PREMATURE_PASS_FORBIDDEN")
        row["artifact_type"] = _KIND
        row["artifact_version"] = contracts._artifact_version(row)
        return row
    contracts.VALIDATORS[_KIND] = validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, "review_id")
    registry.IDENTITY_FIELDS[_KIND] = "review_id"
    registry.BUCKETS[_KIND] = "rc72_n9_professional_disposition_reviews"


class N9ProfessionalDispositionGateService:
    def __init__(self, n8, *, review_verifier, trusted_verifier_kinds=("BANK_N9_PROFESSIONAL_REVIEW",)):
        if (not isinstance(n8, NativeN8ProductRecoveryService)
                or n8.professional_dsh is None
                or n8.reproduction_executor is None
                or n8.reproduction_human_gate is None
                or n8.reproduction_executor.gate is not n8.reproduction_human_gate
                or n8.professional_dsh.pipeline is not n8.n7):
            raise ContractError("N9_PROFESSIONAL_REAL_N8_DSH_REPRODUCTION_REQUIRED")
        if (review_verifier is None
                or not callable(getattr(review_verifier, "resolve", None))
                or not isinstance(getattr(review_verifier, "verifier_kind", None), str)
                or review_verifier.verifier_kind not in trusted_verifier_kinds):
            raise ContractError("N9_PROFESSIONAL_TRUSTED_REVIEW_VERIFIER_REQUIRED")
        self.n8, self.pipeline = n8, n8.n7
        self.truth, self.release_id, self.source_commit = (
            n8.truth, n8.release_id, n8.source_commit)
        self.authority = n8.reproduction_executor.authority
        self.reviewer = review_verifier
        self.runtime = RC72StateMachine(self.truth, release_id=self.release_id)
        self.resolution = N9ApprovedReproductionResolutionAudit(n8.reproduction_executor)
        install_overlay()

    def _one(self, kind, **scope):
        rows = self.truth.query(kind, **scope)
        if len(rows) != 1:
            raise ContractError("N9_PROFESSIONAL_R1_NOT_UNIQUE:" + kind)
        return rows[0]

    def _proof(self, release_batch_id, request_id, defect_id):
        result = self.resolution.audit(
            release_batch_id=release_batch_id,
            request_id=request_id, defect_id=defect_id)
        if result.get("status") != "VERIFIED_DEFECT_CLOSED":
            raise ContractError("N9_PROFESSIONAL_REAL_DEFECT_RESOLUTION_REQUIRED")
        request = self._one("rc72_n9_reproduction_authorization_request", request_id=request_id)
        analysis = self.n8.professional_dsh._receipt(self._one(
            "rc72_n9_professional_dsh_analysis", analysis_id=request["analysis_id"]))
        diagnosis = self.n8.diagnosis._verify(self._one(
            "rc72_n8_process_diagnosis", diagnosis_id=request["diagnosis_id"]))
        node = self.runtime.node_by_type(request["mission_id"], Node.N8_DIAGNOSIS_RECOVERY)
        n8_gate_id = "N8GATE-" + _hash([request["diagnosis_id"],
                                       diagnosis["input_sha256"]])[:24]
        gate = self._one("rc72_node_gate", gate_id=n8_gate_id)
        self.n8.professional_dsh.intake._assert_current_n8_delivery(
            node, diagnosis, gate, request["mission_id"])
        qual = self._one("rc7_task", task_id=request["qualification_workitem_id"])
        prepared = self._one("rc72_n7_execution_preparation",
                             preparation_id=request["preparation_id"])
        if (node["state"] != "PASS" or n8_gate_id not in node["gate_refs"]
                or gate["decision"] != "PASS" or gate["delivery_id"] != diagnosis["delivery_id"]
                or analysis["qualification_workitem_id"] != qual["task_id"]
                or analysis["worker_id"] != qual["lease_owner"]
                or analysis["original_attempt_id"] != request["original_attempt_id"]
                or analysis["original_gap_id"] != request["original_gap_id"]
                or prepared["attempt_id"] != request["original_attempt_id"]
                or prepared["mission_id"] != request["mission_id"]
                or qual["mission_id"] != request["mission_id"]
                or qual["task_type"] != "N9_DISCREPANCY_QUALIFICATION"
                or qual["gap_refs"] != [request["original_gap_id"]]
                or analysis["candidate"]["finding"] != "POSSIBLE_PRODUCT_CAUSE"):
            raise ContractError("N9_PROFESSIONAL_ORIGINAL_N8_DSH_OWNER_CHANGED")
        return result, request, analysis, qual, n8_gate_id

    def _review_id(self, request_id, defect_id):
        return "N9PROFREVIEW-" + _hash([
            self.release_id, self.source_commit, request_id, defect_id])[:24]

    def _review_row(self, release_batch_id, request_id, defect_id):
        row = self._one(_KIND, review_id=self._review_id(request_id, defect_id))
        if not hmac.compare_digest(row.get("signature", ""),
                                   self.authority._sign(_unsigned(row))):
            raise ContractError("N9_PROFESSIONAL_REVIEW_SIGNATURE_CHANGED")
        if (row["release_batch_id"] != release_batch_id
                or row["request_id"] != request_id or row["defect_id"] != defect_id
                or row["release_id"] != self.release_id
                or row["source_commit"] != self.source_commit):
            raise ContractError("N9_PROFESSIONAL_REVIEW_SCOPE_CHANGED")
        return row

    def review(self, *, release_batch_id, request_id, defect_id, attestation_ref):
        """Verify real independent bank attestation; no Gap, Task or Gate changes."""
        proof, request, analysis, qual, n8_gate = self._proof(
            release_batch_id, request_id, defect_id)
        att = self.reviewer.resolve(attestation_ref)
        if not isinstance(att, dict):
            raise ContractError("N9_PROFESSIONAL_REVIEW_RECORD_REQUIRED")
        now = int(time.time())
        closure = self._one("rc7_evaluation",
                            evaluation_id=proof["closure_evaluation_id"])
        evidence = list(dict.fromkeys([proof["reproduction_evidence_id"]] +
                                      list(closure["evidence_refs"])))
        reviewer = att.get("reviewer_ref")
        if (att.get("actor_type") != "HUMAN"
                or att.get("decision") != "APPROVED_POST_FIX_PROFESSIONAL_REVIEW"
                or att.get("attestation_ref") != attestation_ref
                or att.get("release_batch_id") != release_batch_id
                or att.get("request_id") != request_id
                or att.get("defect_id") != defect_id
                or att.get("original_gap_id") != proof["original_gap_id"]
                or att.get("reproduction_record_id") != proof["reproduction_record_id"]
                or att.get("closure_evaluation_id") != proof["closure_evaluation_id"]
                or att.get("proof_sha256") != _hash(proof)
                or not isinstance(reviewer, str) or not reviewer.strip()
                or reviewer in (analysis["worker_id"], request["analysis_worker_id"],
                                prepared_worker(self.truth, request))
                or type(att.get("issued_at")) is not int
                or type(att.get("expires_at")) is not int
                or not att["issued_at"] <= now < att["expires_at"]
                or att["expires_at"] - att["issued_at"] > 600
                or not isinstance(att.get("rationale"), str)
                or not att["rationale"].strip()
                or set(att.get("evidence_refs", [])) != set(evidence)):
            raise ContractError("N9_PROFESSIONAL_FRESH_INDEPENDENT_REVIEW_REQUIRED")
        expected = dict(
            review_id=self._review_id(request_id, defect_id),
            purpose=_PURPOSE, state="REVIEW_ACCEPTED_GAP_STILL_PENDING",
            decision="APPROVED_POST_FIX_PROFESSIONAL_REVIEW",
            release_id=self.release_id, source_commit=self.source_commit,
            release_batch_id=release_batch_id, mission_id=request["mission_id"],
            request_id=request_id, defect_id=defect_id,
            original_gap_id=proof["original_gap_id"],
            qualification_workitem_id=qual["task_id"],
            reproduction_record_id=proof["reproduction_record_id"],
            reproduction_attempt_id=proof["reproduction_attempt_id"],
            closure_evaluation_id=proof["closure_evaluation_id"],
            proof_sha256=_hash(proof), reviewer_ref=reviewer,
            attestation_ref=attestation_ref, evidence_refs=evidence,
            reviewed_at=now)
        with ledger_lock(self.truth, busy="N9_PROFESSIONAL_REVIEW_LEDGER_BUSY"):
            rows = self.truth.query(_KIND, review_id=expected["review_id"])
            if len(rows) > 1:
                raise ContractError("N9_PROFESSIONAL_REVIEW_NOT_UNIQUE")
            if rows:
                row = self._review_row(release_batch_id, request_id, defect_id)
                if any(row.get(k) != v for k, v in expected.items()
                       if k != "reviewed_at"):
                    raise ContractError("N9_PROFESSIONAL_REVIEW_REPLAY_CHANGED")
            else:
                self.truth.append_atomic(_EVENT, dict(
                    expected, signature=self.authority._sign(expected),
                    artifact_version=1))
        return dict(status="HOLD",
                    reason="N9_REVIEW_ACCEPTED_QUALIFICATION_AND_GAP_STILL_PENDING",
                    review_id=expected["review_id"], request_id=request_id,
                    defect_id=defect_id, n9_gate_pass=False,
                    field_verified=False, bank_final=False)

    def accept_reviewed_resolution(self, *, release_batch_id, request_id, defect_id):
        """Explicit host settlement of signed review, real DSH WorkItem and original gap.

        This is not an automatic consequence of reproduction or CLOSED. The
        approval has already been independently recorded by review(). A
        crash is resumed by inspecting exact immutable R1 IDs, not by invoking
        the business operation, DSH model or any new worker.
        """
        proof, request, analysis, task, n8_gate = self._proof(
            release_batch_id, request_id, defect_id)
        row = self._review_row(release_batch_id, request_id, defect_id)
        if (row["proof_sha256"] != _hash(proof)
                or row["original_gap_id"] != proof["original_gap_id"]
                or row["qualification_workitem_id"] != task["task_id"]
                or row["reproduction_record_id"] != proof["reproduction_record_id"]
                or row["closure_evaluation_id"] != proof["closure_evaluation_id"]):
            raise ContractError("N9_PROFESSIONAL_REVIEW_PROOF_CHANGED")
        original = self._one("rc7_gap", gap_id=proof["original_gap_id"])
        if original["state"] in ("WAIVED", "DUPLICATE", "SUPERSEDED", "BLOCKED", "HUMAN_REQUIRED"):
            raise ContractError("N9_PROFESSIONAL_ORIGINAL_GAP_UNSETTLEABLE")
        evidence_id = "N9DSHEVD-" + _hash([row["review_id"], analysis["analysis_id"]])[:24]
        artifact_id = "N9DSHART-" + _hash([row["review_id"], analysis["analysis_id"]])[:24]
        worker_eval_id = "N9QUALREV-" + _hash([row["review_id"], task["task_id"]])[:24]
        source_eval_id = "N9SOURCEEVAL-" + _hash([row["review_id"], proof["original_gap_id"]])[:24]
        evidence = Evidence(
            evidence_id=evidence_id, mission_id=request["mission_id"],
            kind="N9_ACTUAL_DSH_PROFESSIONAL_ANALYSIS",
            source_ref="runtime://rc72/n9/observed-dsh-worker",
            content_ref=analysis["raw_output_ref"],
            content_hash="sha256:" + analysis["raw_output_sha256"],
            subject_refs=[task["task_id"], analysis["analysis_id"],
                          request["original_attempt_id"]])
        artifact = Artifact(
            artifact_id=artifact_id, mission_id=request["mission_id"],
            artifact_type="N9_DSH_PROFESSIONAL_ANALYSIS",
            producer_task_id=task["task_id"],
            content_ref=analysis["raw_output_ref"],
            evidence_refs=[evidence_id],
            content_hash="sha256:" + analysis["raw_output_sha256"])
        control = ClosedLoopControlPlane(
            self.truth, self.release_id, request["mission_id"])
        with ledger_lock(self.truth, busy="N9_PROFESSIONAL_RESOLUTION_LEDGER_BUSY"):
            signed = self._review_row(release_batch_id, request_id, defect_id)
            if signed["proof_sha256"] != row["proof_sha256"]:
                raise ContractError("N9_PROFESSIONAL_REVIEW_RACE_CHANGED")
            task = self._one("rc7_task", task_id=row["qualification_workitem_id"])
            gap = control._gap(row["original_gap_id"])
            if task["state"] == "RUNNING":
                if (task["lease_owner"] != analysis["worker_id"]
                        or self.truth.query("rc7_artifact", artifact_id=artifact_id)
                        or self.truth.query("rc7_evidence", evidence_id=evidence_id)):
                    raise ContractError("N9_PROFESSIONAL_DSH_OUTPUT_UNRECONCILED")
                control.submit_worker_output(WorkerOutput(
                    task_id=task["task_id"], worker_ref=analysis["worker_id"],
                    artifacts=(artifact,), evidence=(evidence,)))
                evaluated = Evaluation(
                    evaluation_id=worker_eval_id,
                    mission_id=request["mission_id"], node="DEFECT",
                    artifact_refs=[artifact_id], result=EvaluationResult.PASS,
                    evaluator_ref=row["reviewer_ref"],
                    dimensions=dict(
                        purpose="N9_INDEPENDENT_PROFESSIONAL_QUALIFICATION",
                        original_gap_id=row["original_gap_id"],
                        reproduction_record_id=row["reproduction_record_id"],
                        defect_id=defect_id, proof_sha256=row["proof_sha256"]),
                    evidence_refs=[evidence_id, proof["reproduction_evidence_id"]])
                control.accept_evaluation(task["task_id"], evaluation=evaluated)
            elif task["state"] != "PASS" or task.get("evaluation_id") != worker_eval_id:
                raise ContractError("N9_PROFESSIONAL_QUALIFICATION_NOT_ACCEPTED")
            qual_eval = self._one("rc7_evaluation", evaluation_id=worker_eval_id)
            if (qual_eval["result"] != "PASS"
                    or qual_eval["evaluator_ref"] != row["reviewer_ref"]
                    or qual_eval["artifact_refs"] != [artifact_id]
                    or qual_eval["dimensions"].get("proof_sha256") != row["proof_sha256"]):
                raise ContractError("N9_PROFESSIONAL_QUALIFICATION_EVALUATION_CHANGED")
            existing = self.truth.query("rc7_evaluation", evaluation_id=source_eval_id)
            source = Evaluation(
                evaluation_id=source_eval_id, mission_id=request["mission_id"],
                node=gap.source_node,
                artifact_refs=[artifact_id, proof["verification_artifact_id"]] +
                              list(proof["regression_artifact_ids"]),
                result=EvaluationResult.PASS, evaluator_ref=row["reviewer_ref"],
                dimensions=dict(
                    purpose="N9_ORIGINAL_DISCREPANCY_POST_FIX_ADJUDICATION",
                    review_id=row["review_id"], request_id=request_id,
                    defect_id=defect_id, original_gap_id=row["original_gap_id"],
                    reproduction_record_id=row["reproduction_record_id"],
                    closure_evaluation_id=row["closure_evaluation_id"],
                    proof_sha256=row["proof_sha256"]),
                evidence_refs=list(dict.fromkeys(
                    row["evidence_refs"] + [evidence_id])))
            if not existing:
                append_entity(self.truth, source, release_id=self.release_id)
            elif len(existing) != 1 or existing[0].get("dimensions") != source.dimensions:
                raise ContractError("N9_PROFESSIONAL_SOURCE_EVALUATION_CHANGED")
            if gap.state == GapStatus.OPEN:
                transition_gap(gap, GapStatus.PLANNED)
                control._persist_gap(gap)
            if gap.state == GapStatus.PLANNED:
                transition_gap(gap, GapStatus.REPAIRING)
                control._persist_gap(gap)
            if gap.state == GapStatus.REPAIRING:
                transition_gap(gap, GapStatus.EVIDENCE_PENDING)
                control._persist_gap(gap)
            if gap.state == GapStatus.EVIDENCE_PENDING:
                transition_gap(gap, GapStatus.RESOLVED,
                               resolution_evaluation_id=source_eval_id)
                control._persist_gap(gap)
            if (gap.state != GapStatus.RESOLVED
                    or gap.resolution_evaluation_id != source_eval_id):
                raise ContractError("N9_PROFESSIONAL_ORIGINAL_GAP_NOT_PROVEN_RESOLVED")
            control._sync_mission(control._mission())
        return dict(status="ADJUDICATED", review_id=row["review_id"],
                    original_gap_id=proof["original_gap_id"],
                    qualification_evaluation_id=worker_eval_id,
                    original_gap_evaluation_id=source_eval_id,
                    n9_gate_pass=False, field_verified=False, bank_final=False)

    def _audit_accepted(self, release_batch_id, request_id, defect_id):
        proof, request, analysis, task, n8_gate = self._proof(
            release_batch_id, request_id, defect_id)
        review = self._review_row(release_batch_id, request_id, defect_id)
        if (review["proof_sha256"] != _hash(proof)
                or review["original_gap_id"] != proof["original_gap_id"]
                or review["qualification_workitem_id"] != task["task_id"]
                or review["reproduction_record_id"] != proof["reproduction_record_id"]
                or review["closure_evaluation_id"] != proof["closure_evaluation_id"]):
            raise ContractError("N9_PROFESSIONAL_REVIEW_LINEAGE_CHANGED")
        gap = self._one("rc7_gap", gap_id=review["original_gap_id"])
        work_eval_id = "N9QUALREV-" + _hash([review["review_id"], task["task_id"]])[:24]
        source_eval_id = "N9SOURCEEVAL-" + _hash([review["review_id"],
                                                 review["original_gap_id"]])[:24]
        blockers = []
        if gap["state"] != "RESOLVED" or gap.get("resolution_evaluation_id") != source_eval_id:
            blockers.append("original-gap-not-independently-adjudicated:" + gap["gap_id"])
        if task["state"] != "PASS" or task.get("evaluation_id") != work_eval_id:
            blockers.append("professional-qualification-not-reviewed:" + task["task_id"])
        if not blockers:
            q = self._one("rc7_evaluation", evaluation_id=work_eval_id)
            e = self._one("rc7_evaluation", evaluation_id=source_eval_id)
            artifact_id = "N9DSHART-" + _hash(
                [review["review_id"], analysis["analysis_id"]])[:24]
            evidence_id = "N9DSHEVD-" + _hash(
                [review["review_id"], analysis["analysis_id"]])[:24]
            artifact = self._one("rc7_artifact", artifact_id=artifact_id)
            evd = self._one("rc7_evidence", evidence_id=evidence_id)
            if (q["mission_id"] != request["mission_id"]
                    or q["node"] != "DEFECT" or q["result"] != "PASS"
                    or q["evaluator_ref"] != review["reviewer_ref"]
                    or q["artifact_refs"] != [artifact_id]
                    or q["dimensions"].get("proof_sha256") != review["proof_sha256"]
                    or e["mission_id"] != request["mission_id"]
                    or e["node"] != gap["source_node"] or e["result"] != "PASS"
                    or e["evaluator_ref"] != review["reviewer_ref"]
                    or e["dimensions"].get("purpose") !=
                    "N9_ORIGINAL_DISCREPANCY_POST_FIX_ADJUDICATION"
                    or e["dimensions"].get("review_id") != review["review_id"]
                    or e["dimensions"].get("proof_sha256") != review["proof_sha256"]
                    or e["artifact_refs"] != [artifact_id,
                                                proof["verification_artifact_id"]] +
                                               list(proof["regression_artifact_ids"])
                    or proof["reproduction_evidence_id"] not in e["evidence_refs"]
                    or evidence_id not in e["evidence_refs"]
                    or artifact["producer_task_id"] != task["task_id"]
                    or artifact["content_ref"] != analysis["raw_output_ref"]
                    or artifact["content_hash"] != "sha256:" + analysis["raw_output_sha256"]
                    or evd["content_ref"] != analysis["raw_output_ref"]
                    or evd["content_hash"] != artifact["content_hash"]
                    or evd["source_ref"] != "runtime://rc72/n9/observed-dsh-worker"):
                raise ContractError("N9_PROFESSIONAL_ORIGINAL_DISPOSITION_PROOF_CHANGED")
        for item in self.truth.query("rc7_gap", mission_id=request["mission_id"]):
            if item["state"] not in _TERMINAL:
                blockers.append("open-gap:" + item["gap_id"])
            elif item["category"] in {"VALID_TEST_FAILURE", "PRODUCT_DEFECT"} and (
                    item["state"] != "RESOLVED" or not item.get("resolution_evaluation_id")):
                blockers.append("unreviewed-professional-gap:" + item["gap_id"])
        for item in self.truth.query("rc7_task", mission_id=request["mission_id"]):
            if (item["node"] in {"DEFECT", "N9_DEFECT"}
                    or item["task_type"] in _PROFESSIONAL_TYPES):
                if item["state"] != "PASS":
                    blockers.append("open-professional-workitem:" + item["task_id"])
        return proof, review, sorted(set(blockers)), n8_gate

    def complete(self, *, release_batch_id):
        """Only signed, fully reviewed, zero-blocker R1 enters native N9 Gate."""
        reviews = self.truth.query(_KIND, release_batch_id=release_batch_id)
        if not reviews:
            return dict(status="HOLD",
                        reason="N9_INDEPENDENT_POST_FIX_PROFESSIONAL_REVIEW_REQUIRED",
                        field_verified=False, bank_final=False)
        if len(reviews) != 1:
            raise ContractError("N9_PROFESSIONAL_REVIEW_SCOPE_NOT_UNIQUE")
        review = reviews[0]
        proof, signed, blockers, n8_gate = self._audit_accepted(
            release_batch_id, review["request_id"], review["defect_id"])
        if blockers:
            return dict(status="HOLD", reason="N9_PROFESSIONAL_DISPOSITION_INCOMPLETE",
                        blockers=blockers, field_verified=False, bank_final=False)
        request = self._one("rc72_n9_reproduction_authorization_request",
                            request_id=review["request_id"])
        node = self.runtime.node_by_type(request["mission_id"], Node.N9_DEFECT)
        if node["state"] not in {"READY", "RUNNING", "REVIEW_PENDING", "PASS"}:
            return dict(status="HOLD", reason="N9_PROFESSIONAL_NODE_NOT_READY",
                        field_verified=False, bank_final=False)
        receipt_id = signed["review_id"]
        did = "N9PROFDEL-" + _hash([receipt_id, n8_gate])[:24]
        gid = "N9PROFGATE-" + _hash([receipt_id, n8_gate])[:24]
        snapshots = [self.truth.query(kind, **scope) for kind, scope in (
            ("rc7_gap", {"mission_id": request["mission_id"]}),
            ("rc7_defect", {"mission_id": request["mission_id"]}),
            ("rc7_task", {"mission_id": request["mission_id"]}),
            ("rc7_evaluation", {"mission_id": request["mission_id"]}))]
        snapshot_hash = _hash(snapshots)
        with ledger_lock(self.truth, busy="N9_PROFESSIONAL_GATE_LEDGER_BUSY"):
            now_snapshots = [self.truth.query(kind, **scope) for kind, scope in (
                ("rc7_gap", {"mission_id": request["mission_id"]}),
                ("rc7_defect", {"mission_id": request["mission_id"]}),
                ("rc7_task", {"mission_id": request["mission_id"]}),
                ("rc7_evaluation", {"mission_id": request["mission_id"]}))]
            if _hash(now_snapshots) != snapshot_hash:
                raise ContractError("N9_PROFESSIONAL_GATE_R1_CHANGED_DURING_REVIEW")
            node = self.runtime.node_by_type(request["mission_id"], Node.N9_DEFECT)
            delivery_rows = self.truth.query("rc72_node_delivery", delivery_id=did)
            if len(delivery_rows) > 1:
                raise ContractError("N9_PROFESSIONAL_DELIVERY_NOT_UNIQUE")
            if delivery_rows:
                version = delivery_rows[0]["version"]
            else:
                previous = self.truth.query(
                    "rc72_node_delivery", mission_node_id=node["mission_node_id"])
                version = max([row["version"] for row in previous] + [0]) + 1
            delivery = NodeDelivery(
                delivery_id=did, mission_id=request["mission_id"],
                mission_node_id=node["mission_node_id"], node_type=Node.N9_DEFECT,
                version=version,
                producer_ref="rc72-independent-professional-disposition-auditor",
                input_refs=[n8_gate, receipt_id, proof["reproduction_record_id"]],
                artifact_refs=[proof["verification_artifact_id"]] +
                              list(proof["regression_artifact_ids"]),
                evidence_refs=list(dict.fromkeys(
                    signed["evidence_refs"] +
                    [proof["reproduction_evidence_id"]])),
                created_by_workitems=[signed["qualification_workitem_id"]])
            expected = {k: v for k, v in asdict(delivery).items() if k != "created_at"}
            expected["node_type"] = Node.N9_DEFECT.value
            if delivery_rows:
                if any(delivery_rows[0].get(k) != v for k, v in expected.items()):
                    raise ContractError("N9_PROFESSIONAL_DELIVERY_CHANGED")
            if node["state"] == "READY":
                self.runtime.transition_state(
                    node["mission_node_id"], State.RUNNING,
                    reason="verified independent professional RCA/fix/regression")
                node = self.runtime.node(node["mission_node_id"])
            if node["state"] == "RUNNING":
                if delivery_rows:
                    self.runtime._persist_node_state(
                        node, State.REVIEW_PENDING,
                        reason="resume signed N9 professional delivery",
                        active_delivery_version=version,
                        delivery_refs=list(dict.fromkeys(
                            node["delivery_refs"] + [did])))
                else:
                    self.runtime.submit_delivery(delivery)
                node = self.runtime.node(node["mission_node_id"])
            if (node["active_delivery_version"] != version
                    or did not in node["delivery_refs"]):
                raise ContractError("N9_PROFESSIONAL_ACTIVE_DELIVERY_CHANGED")
            gate = NodeGate(
                gate_id=gid, mission_id=request["mission_id"],
                mission_node_id=node["mission_node_id"], node_type=Node.N9_DEFECT,
                delivery_id=did, decision=NodeGateDecision.PASS,
                reviewer_worker_id="bank-n9-professional-review/" + signed["reviewer_ref"],
                reviewer_session_id=signed["attestation_ref"],
                criteria=list(_CRITERIA), passed=list(_CRITERIA),
                evidence_refs=[receipt_id, proof["reproduction_evidence_id"],
                               proof["closure_evaluation_id"]],
                reason="independent RCA, fix verification, impact regression and original discrepancy formally reviewed")
            gate_rows = self.truth.query("rc72_node_gate", gate_id=gid)
            if len(gate_rows) > 1:
                raise ContractError("N9_PROFESSIONAL_GATE_NOT_UNIQUE")
            expect_gate = {k: v for k, v in asdict(gate).items() if k != "created_at"}
            expect_gate.update(node_type=Node.N9_DEFECT.value, decision="PASS")
            if gate_rows and any(gate_rows[0].get(k) != v for k, v in expect_gate.items()):
                raise ContractError("N9_PROFESSIONAL_GATE_CHANGED")
            if node["state"] == "REVIEW_PENDING":
                if not gate_rows:
                    self.runtime.apply_gate(gate)
                else:
                    self.runtime._persist_node_state(
                        node, State.PASS,
                        reason="resume reviewed N9 professional gate",
                        gate_refs=list(dict.fromkeys(node["gate_refs"] + [gid])),
                        exited_at=gate_rows[0]["created_at"],
                        bypass_direct_transition=True)
            elif node["state"] != "PASS" or gid not in node["gate_refs"]:
                raise ContractError("N9_PROFESSIONAL_GATE_STATE_CHANGED")
            transitions = self.truth.query(
                "rc72_node_transition", source_gate_id=gid)
            if transitions:
                if (len(transitions) != 1
                        or transitions[0].get("kind") != "FORWARD"
                        or transitions[0].get("mission_id") != request["mission_id"]
                        or transitions[0].get("from_node_type") != "N9_DEFECT"
                        or transitions[0].get("to_node_type") != "N10_RELEASE_CONVERGENCE"):
                    raise ContractError("N9_PROFESSIONAL_N10_FORWARD_CHANGED")
            else:
                self.runtime.forward(
                    Node.N9_DEFECT, Node.N10_RELEASE_CONVERGENCE,
                    source_gate_id=gid, mission_id=request["mission_id"])
        return dict(status="PASS", state="N9_PASS", gate_id=gid,
                    review_id=receipt_id, next_node="N10_RELEASE_CONVERGENCE",
                    n9_gate_pass=True, field_verified=False, bank_final=False)


def prepared_worker(truth, request):
    rows = truth.query("rc72_n7_execution_preparation",
                       preparation_id=request["preparation_id"])
    return rows[0]["worker_id"] if len(rows) == 1 else None


install_overlay()
