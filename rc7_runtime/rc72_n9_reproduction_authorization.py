"""C04: durable *request* for independent N9 reproduction, never execution.

A DSH professional's POSSIBLE_PRODUCT_CAUSE is only a hypothesis. This
native product route consumes the current signed N8 assertion, the original
frozen Case and the exact independent N9 raw/session/tool evidence before
creating one signed, read-only reproduction-authorization request.

No caller boolean, model text or previous N7 lease can authorize fresh
business I/O. A separate approved reproduction service must later establish
Human/Team authority, data safety, fresh Attempt and independent Oracle.
"""
from __future__ import annotations

import hmac

from rc6_runtime import contracts, truth as registry
from .models import ContractError
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash

_KIND = "rc72_n9_reproduction_authorization_request"
_EVENT = "RC72_N9_REPRODUCTION_AUTHORIZATION_REQUESTED"
_PURPOSE = "N9_SEPARATE_REPRODUCTION_AUTHORIZATION_REQUIRED"
_STATE = "AWAITING_INDEPENDENT_APPROVAL_AND_FRESH_EXECUTION"
_GUARDS = [
    "Independent reviewer approves the exact original Case, Oracle and evidence",
    "Confirm previous business side effects before a new operation",
    "Create a fresh scoped ETU WorkItem, Worker and signed TaskLease",
    "Create a new Attempt distinct from the blocked N7 Attempt",
    "Use a fresh approved data snapshot, execution evidence and business Oracle",
    "Do not create PRODUCT_DEFECT until independent reproduction is conclusive",
]


def install_overlay():
    def validate(payload):
        row = dict(payload)
        for key in (
            "request_id", "release_id", "source_commit", "release_batch_id",
            "mission_id", "preparation_id", "original_attempt_id",
            "original_case_id", "original_contract_id", "original_etu_id",
            "original_workitem_id", "original_gap_id", "diagnosis_id",
            "qualification_workitem_id", "analysis_id", "analysis_worker_id",
            "analysis_session_id", "analysis_raw_sha256", "analysis_candidate_sha256",
            "candidate_finding", "signature",
        ):
            contracts._require_str(row, key)
        if (row.get("purpose") != _PURPOSE or row.get("state") != _STATE
                or row.get("candidate_finding") != "POSSIBLE_PRODUCT_CAUSE"
                or row.get("required_guards") != _GUARDS
                or not isinstance(row.get("approved_case_artifact_refs"), list)
                or not row["approved_case_artifact_refs"]
                or len(set(row["approved_case_artifact_refs"])) != len(row["approved_case_artifact_refs"])
                or not isinstance(row.get("analysis_tool_refs"), list)
                or not row["analysis_tool_refs"]
                or len(set(row["analysis_tool_refs"])) != len(row["analysis_tool_refs"])
                or any(key in row for key in (
                    "reproduction_pass", "reproduced", "product_defect",
                    "defect_confirmed", "rca_approved", "n9_pass", "bank_final",
                    "field_verified", "human_approved", "permission_granted",
                    "fresh_attempt_id", "new_worker_lease_id", "authority_secret"))):
            raise contracts.DomainValidationError(
                "N9_REPRODUCTION_REQUEST_PREMATURE_VERDICT_FORBIDDEN")
        row["artifact_type"] = _KIND
        row["artifact_version"] = contracts._artifact_version(row)
        return row
    contracts.VALIDATORS[_KIND] = validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, "request_id")
    registry.IDENTITY_FIELDS[_KIND] = "request_id"
    registry.BUCKETS[_KIND] = "rc72_n9_reproduction_authorization_requests"


def _unsigned(row):
    return {key: value for key, value in row.items()
            if key not in ("signature", "artifact_type", "artifact_version")}


class N9ReproductionAuthorizationRequestService:
    """Idempotent signed no-I/O preparation to an independent reproduction."""

    def __init__(self, analyst):
        from .rc72_n9_professional_dsh import NativeN9ProfessionalDshAnalysisService
        if not isinstance(analyst, NativeN9ProfessionalDshAnalysisService):
            raise ContractError("N9_REPRODUCTION_SIGNED_PROFESSIONAL_REQUIRED")
        self.analyst = analyst
        self.pipeline = analyst.pipeline
        self.truth = analyst.truth
        self.authority = self.pipeline.preparation.authority
        self.release_id = analyst.release_id
        self.source_commit = analyst.source_commit
        install_overlay()

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError("N9_REPRODUCTION_R1_NOT_UNIQUE:" + kind)
        return rows[0]

    def request(self, *, preparation_id, diagnosis_id, analysis_id):
        # Real N8/Oracle and current Gate provenance verification owns its
        # own global OS lock. Never call this while holding the write lock.
        scope = self.analyst.intake.queue_reproduction(
            preparation_id=preparation_id, diagnosis_id=diagnosis_id)
        prepared = self._one("rc72_n7_execution_preparation",
                             preparation_id=preparation_id)
        analysis = self.analyst._receipt(self._one(
            "rc72_n9_professional_dsh_analysis", analysis_id=analysis_id))
        task = self._one("rc7_task", task_id=scope["qualification_workitem_id"])
        plan = self._one("rc72_n7_execution_plan", plan_id=prepared["plan_id"])
        members = [item for item in plan["items"]
                   if item["workitem_id"] == prepared["workitem_id"]
                   and item["case_id"] == prepared["case_id"]
                   and item["contract_id"] == prepared["contract_id"]]
        if len(members) != 1:
            raise ContractError("N9_REPRODUCTION_ORIGINAL_CASE_NOT_UNIQUE")
        original = members[0]
        batch = self._one("rc72_release_batch",
                          release_batch_id=prepared["release_batch_id"])
        if (analysis["release_id"] != self.release_id
                or analysis["source_commit"] != self.source_commit
                or analysis["mission_id"] != prepared["mission_id"]
                or analysis["preparation_id"] != preparation_id
                or analysis["diagnosis_id"] != diagnosis_id
                or analysis["qualification_workitem_id"] != task["task_id"]
                or analysis["original_attempt_id"] != prepared["attempt_id"]
                or analysis["original_gap_id"] != scope["gap_id"]
                or analysis["candidate"]["finding"] not in (
                    "POSSIBLE_PRODUCT_CAUSE", "INCONCLUSIVE",
                    "POSSIBLE_TEST_ORACLE_PROBLEM", "POSSIBLE_ENVIRONMENT_CAUSE")
                or analysis["worker_id"] == prepared["worker_id"]
                or analysis["worker_id"] != task["lease_owner"]
                or task["node"] != "DEFECT"
                or task["task_type"] != "N9_DISCREPANCY_QUALIFICATION"
                or task["gap_refs"] != [scope["gap_id"]]
                or task["state"] != "RUNNING"
                or original["etu_id"] != prepared["etu_id"]
                or original["input_artifact_refs"] != task["input_artifact_refs"]
                or batch["mission_id"] != prepared["mission_id"]
                or batch["release_id"] != self.release_id):
            raise ContractError("N9_REPRODUCTION_FROZEN_ANALYSIS_SCOPE_CHANGED")
        if analysis["candidate"]["finding"] != "POSSIBLE_PRODUCT_CAUSE":
            return dict(status="HOLD",
                        reason="N9_CAUSAL_HYPOTHESIS_NOT_PRODUCT_REPRODUCTION_READY",
                        analysis_id=analysis_id,
                        candidate_finding=analysis["candidate"]["finding"],
                        defect_confirmed=False, reproduction_completed=False,
                        field_verified=False, bank_final=False)

        tool_refs = [call["call_ref"] for call in analysis["tool_calls"]]
        request_id = "N9REPRO-" + _hash([
            self.release_id, prepared["mission_id"],
            prepared["attempt_id"], diagnosis_id, analysis_id])[:24]
        expected = dict(
            request_id=request_id, purpose=_PURPOSE, state=_STATE,
            release_id=self.release_id, source_commit=self.source_commit,
            release_batch_id=prepared["release_batch_id"],
            mission_id=prepared["mission_id"],
            preparation_id=preparation_id,
            original_attempt_id=prepared["attempt_id"],
            original_case_id=prepared["case_id"],
            original_contract_id=prepared["contract_id"],
            original_etu_id=prepared["etu_id"],
            original_workitem_id=prepared["workitem_id"],
            original_gap_id=scope["gap_id"],
            diagnosis_id=diagnosis_id,
            qualification_workitem_id=scope["qualification_workitem_id"],
            approved_case_artifact_refs=list(original["input_artifact_refs"]),
            analysis_id=analysis_id,
            analysis_worker_id=analysis["worker_id"],
            analysis_session_id=analysis["dsh_session_id"],
            analysis_raw_sha256=analysis["raw_output_sha256"],
            analysis_candidate_sha256=analysis["candidate_sha256"],
            analysis_tool_refs=tool_refs,
            candidate_finding=analysis["candidate"]["finding"],
            required_guards=list(_GUARDS))
        # This ledger transaction records precisely one immutable request.
        # It NEVER allocates another WorkItem, new data, TaskLease, Worker or
        # business Attempt; there is no re-execution side effect to replay.
        with ledger_lock(self.truth, busy="N9_REPRODUCTION_REQUEST_LEDGER_BUSY"):
            if self.analyst.truth is not self.truth or self.pipeline.truth is not self.truth:
                raise ContractError("N9_REPRODUCTION_RUNTIME_CHANGED")
            rows = self.truth.query(_KIND, request_id=request_id)
            if len(rows) > 1:
                raise ContractError("N9_REPRODUCTION_REQUEST_NOT_UNIQUE")
            if rows:
                row = rows[0]
                if not hmac.compare_digest(
                        row.get("signature", ""), self.authority._sign(_unsigned(row))):
                    raise ContractError("N9_REPRODUCTION_REQUEST_SIGNATURE_CHANGED")
                if any(row.get(key) != value for key, value in expected.items()):
                    raise ContractError("N9_REPRODUCTION_REQUEST_SCOPE_CHANGED")
            else:
                self.truth.append_atomic(_EVENT, dict(
                    expected, signature=self.authority._sign(expected),
                    artifact_version=1))
        return dict(
            status="HOLD",
            reason="N9_INDEPENDENT_REPRODUCTION_AUTHORIZATION_REQUIRED",
            request_id=request_id, analysis_id=analysis_id,
            original_attempt_id=prepared["attempt_id"],
            original_case_id=prepared["case_id"],
            qualification_workitem_id=scope["qualification_workitem_id"],
            defect_confirmed=False, reproduction_completed=False,
            field_verified=False, bank_final=False)


install_overlay()
