"""C04 independently verified human disposition of a signed N9 reproduction REQUEST.

Human approval is a *prerequisite*, never a reproduction or PRODUCT_DEFECT.
The verifier must be a trusted bank Host adapter, and the decision must bind
the frozen Case, N7 Attempt, N8 discrepancy and raw N9 professional analysis.
A possible prior business write is UNKNOWN unless an independent HUMAN has
reviewed side effects. R1 cold re-entry never invents approval or replays IO.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping

from rc6_runtime import contracts, truth as registry
from .models import ContractError
from .rc72_ledger_lock import ledger_lock
from .rc72_n9_reproduction_authorization import (
    N9ReproductionAuthorizationRequestService, _unsigned,
)

_KIND = "rc72_n9_reproduction_human_decision"
_EVENT = "RC72_N9_REPRODUCTION_HUMAN_DECISION_RECORDED"
_DECISIONS = {"APPROVED", "REJECTED"}
_SIDE_EFFECTS = {"SAFE_TO_REPRODUCE", "UNKNOWN_OR_POSSIBLY_COMMITTED"}
_SCOPE_FIELDS = (
    "request_id", "release_id", "source_commit", "release_batch_id",
    "mission_id", "preparation_id", "original_attempt_id",
    "original_case_id", "original_contract_id", "original_etu_id",
    "original_gap_id", "diagnosis_id", "analysis_id", "analysis_raw_sha256",
    "analysis_candidate_sha256", "approved_case_artifact_refs",
)


def request_scope_digest(request, contract):
    values = {name: request[name] for name in _SCOPE_FIELDS}
    values["original_contract_sha256"] = contract["contract_sha256"]
    values["request_signature"] = request["signature"]
    raw = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _signed_payload(row):
    return {k: v for k, v in row.items()
            if k not in {"signature", "artifact_type", "artifact_version"}}


def install_overlay():
    def validate(payload):
        row = dict(payload)
        for key in (
            "decision_id", "request_id", "release_id", "source_commit",
            "release_batch_id", "mission_id", "original_attempt_id",
            "original_case_id", "original_gap_id", "analysis_id",
            "decision", "side_effects_disposition", "human_actor_ref",
            "attestation_ref", "verifier_kind", "scope_digest",
            "rationale", "signature",
        ):
            contracts._require_str(row, key)
        if (row["decision"] not in _DECISIONS
                or row["side_effects_disposition"] not in _SIDE_EFFECTS
                or row.get("actor_type") != "HUMAN"
                or row.get("field_verified") is not True
                or row.get("status") != "HUMAN_DISPOSITION_ONLY"
                or not isinstance(row.get("evidence_refs"), list)
                or not row["evidence_refs"]
                or len(set(row["evidence_refs"])) != len(row["evidence_refs"])
                or any(not isinstance(x, str) or not x.strip() for x in row["evidence_refs"])
                or any(type(row.get(key)) is not int or row[key] < 1
                       for key in ("issued_at", "expires_at", "reviewed_at"))
                or row["expires_at"] <= row["issued_at"]
                or any(key in row for key in (
                    "reproduced", "product_defect", "defect_confirmed",
                    "new_worker_id", "fresh_attempt_id", "rca_approved",
                    "permission_granted", "n9_pass", "bank_final"))):
            raise contracts.DomainValidationError("N9_HUMAN_DECISION_PREMATURE_CLAIM_FORBIDDEN")
        row["artifact_type"] = _KIND
        row["artifact_version"] = contracts._artifact_version(row)
        return row
    contracts.VALIDATORS[_KIND] = validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, "decision_id")
    registry.IDENTITY_FIELDS[_KIND] = "decision_id"
    registry.BUCKETS[_KIND] = "rc72_n9_reproduction_human_decisions"


class N9ReproductionHumanGateService:
    """Trusted Host-resolved human Gate for the *existing* signed R1 request."""

    def __init__(self, request_service, *, approval_verifier,
                 trusted_field_verifier_kinds):
        if not isinstance(request_service, N9ReproductionAuthorizationRequestService):
            raise ContractError("N9_HUMAN_CANONICAL_REPRODUCTION_REQUEST_SERVICE_REQUIRED")
        kind = getattr(approval_verifier, "verifier_kind", None)
        if (not isinstance(kind, str) or not kind
                or not callable(getattr(approval_verifier, "resolve", None))
                or not isinstance(trusted_field_verifier_kinds, (tuple, list, frozenset))
                or kind not in trusted_field_verifier_kinds):
            raise ContractError("N9_HUMAN_TRUSTED_BANK_VERIFIER_REQUIRED")
        self.requests = request_service
        self.truth, self.authority = request_service.truth, request_service.authority
        self.release_id, self.source_commit = request_service.release_id, request_service.source_commit
        self.verifier, self.verifier_kind = approval_verifier, kind
        install_overlay()

    def _one(self, kind, **scope):
        rows = self.truth.query(kind, **scope)
        if len(rows) != 1:
            raise ContractError("N9_HUMAN_CANONICAL_R1_NOT_UNIQUE:" + kind)
        return rows[0]

    def _audited_request(self, request_id):
        row = self._one("rc72_n9_reproduction_authorization_request", request_id=request_id)
        if (row["release_id"] != self.release_id
                or row["source_commit"] != self.source_commit
                or not hmac.compare_digest(
                    row.get("signature", ""),
                    self.authority._sign(_unsigned(row)))):
            raise ContractError("N9_HUMAN_ORIGINAL_REQUEST_SIGNATURE_CHANGED")
        # Re-audit the *current* N8 Gate/Case and exact DSH raw proof. An R1
        # signed historical hypothesis is insufficient after a source change.
        verified = self.requests.request(
            preparation_id=row["preparation_id"], diagnosis_id=row["diagnosis_id"],
            analysis_id=row["analysis_id"])
        if verified.get("request_id") != request_id:
            raise ContractError("N9_HUMAN_ORIGINAL_REQUEST_SCOPE_CHANGED")
        contract = self._one("rc72_n6_executable_contract",
                             contract_id=row["original_contract_id"])
        if (contract["case_id"] != row["original_case_id"]
                or contract["release_id"] != self.release_id
                or contract["source_commit"] != self.source_commit):
            raise ContractError("N9_HUMAN_FROZEN_ORACLE_CHANGED")
        return row, contract

    def review(self, *, request_id, attestation_ref):
        if not isinstance(request_id, str) or not request_id.strip():
            raise ContractError("N9_HUMAN_REQUEST_ID_REQUIRED")
        if not isinstance(attestation_ref, str) or not attestation_ref.strip():
            raise ContractError("N9_HUMAN_ATTESTATION_REFERENCE_REQUIRED")
        request, contract = self._audited_request(request_id)
        try:
            resolved = self.verifier.resolve(attestation_ref)
        except Exception:
            raise ContractError("N9_HUMAN_FIELD_ATTESTATION_UNVERIFIED") from None
        if not isinstance(resolved, Mapping):
            raise ContractError("N9_HUMAN_FIELD_ATTESTATION_REQUIRED")
        att = dict(resolved)
        scope_digest = request_scope_digest(request, contract)
        expected = dict(
            attestation_ref=attestation_ref,
            request_id=request_id,
            release_batch_id=request["release_batch_id"],
            mission_id=request["mission_id"],
            original_attempt_id=request["original_attempt_id"],
            original_case_id=request["original_case_id"],
            original_gap_id=request["original_gap_id"],
            analysis_id=request["analysis_id"],
            scope_digest=scope_digest)
        if any(att.get(k) != v for k, v in expected.items()):
            raise ContractError("N9_HUMAN_STALE_OR_FOREIGN_SCOPE_FORBIDDEN")
        if (att.get("actor_type") != "HUMAN"
                or not isinstance(att.get("human_actor_ref"), str)
                or not att["human_actor_ref"].strip()
                or att["human_actor_ref"] in {
                    request["analysis_worker_id"],
                    request["original_workitem_id"],
                }
                or att.get("field_verified") is not True
                or not isinstance(att.get("rationale"), str)
                or not att["rationale"].strip()
                or not isinstance(att.get("evidence_refs"), (list, tuple))
                or not att["evidence_refs"]
                or any(not isinstance(x, str) or not x.strip()
                       for x in att["evidence_refs"])):
            raise ContractError("N9_HUMAN_INDEPENDENT_FIELD_EVIDENCE_REQUIRED")
        decision, effects = att.get("decision"), att.get("side_effects_disposition")
        if decision not in _DECISIONS or effects not in _SIDE_EFFECTS:
            raise ContractError("N9_HUMAN_EXPLICIT_DECISION_AND_EFFECTS_REQUIRED")
        now = int(time.time())
        issued, expires = att.get("issued_at"), att.get("expires_at")
        if (type(issued) is not int or type(expires) is not int
                or issued > now + 5 or issued < now - 300
                or expires <= now or expires <= issued
                or expires > now + 3600):
            raise ContractError("N9_HUMAN_FRESH_ATTESTATION_REQUIRED")
        # A human can reject/hold a potentially committed action; no verifier
        # may mark it as approved while its side-effect disposition is UNKNOWN.
        if decision == "APPROVED" and effects != "SAFE_TO_REPRODUCE":
            raise ContractError("N9_HUMAN_POSSIBLE_BUSINESS_WRITE_NO_REEXECUTION")
        expected_row = dict(
            decision_id="N9HUMAN-" + hashlib.sha256(request_id.encode()).hexdigest()[:24],
            request_id=request_id, release_id=self.release_id,
            source_commit=self.source_commit,
            release_batch_id=request["release_batch_id"], mission_id=request["mission_id"],
            original_attempt_id=request["original_attempt_id"],
            original_case_id=request["original_case_id"],
            original_gap_id=request["original_gap_id"],
            analysis_id=request["analysis_id"],
            decision=decision, side_effects_disposition=effects,
            status="HUMAN_DISPOSITION_ONLY", actor_type="HUMAN",
            human_actor_ref=att["human_actor_ref"],
            attestation_ref=attestation_ref, verifier_kind=self.verifier_kind,
            field_verified=True, scope_digest=scope_digest,
            rationale=att["rationale"], evidence_refs=list(att["evidence_refs"]),
            issued_at=issued, expires_at=expires, reviewed_at=now)
        with ledger_lock(self.truth, busy="N9_HUMAN_GATE_LEDGER_BUSY"):
            rows = self.truth.query(_KIND, request_id=request_id)
            if len(rows) > 1:
                raise ContractError("N9_HUMAN_MULTIPLE_DECISIONS_FORBIDDEN")
            if rows:
                old = rows[0]
                if not hmac.compare_digest(old.get("signature", ""),
                                           self.authority._sign(_signed_payload(old))):
                    raise ContractError("N9_HUMAN_DECISION_SIGNATURE_CHANGED")
                # A stale approval cannot be extended by replay; new consent
                # requires new full frozen N8/DSH evidence and a new request.
                if any(old.get(k) != v for k, v in expected_row.items()
                       if k != "reviewed_at"):
                    raise ContractError("N9_HUMAN_DECISION_IMMUTABLE")
            else:
                self.truth.append_atomic(_EVENT, dict(
                    expected_row, signature=self.authority._sign(expected_row),
                    artifact_version=1))
        return dict(
            status="HOLD",
            reason=("N9_FRESH_REPRODUCTION_EXECUTION_NOT_YET_PROVEN"
                    if decision == "APPROVED" else "N9_HUMAN_REPRODUCTION_REJECTED"),
            request_id=request_id,
            decision_id=expected_row["decision_id"],
            human_decision=decision,
            original_attempt_id=request["original_attempt_id"],
            defect_confirmed=False, reproduction_completed=False,
            field_verified=False, bank_final=False)

    def assert_fresh_approved(self, *, request_id):
        request, contract = self._audited_request(request_id)
        row = self._one(_KIND, request_id=request_id)
        if (row["decision"] != "APPROVED"
                or row["side_effects_disposition"] != "SAFE_TO_REPRODUCE"
                or row["scope_digest"] != request_scope_digest(request, contract)
                or row["mission_id"] != request["mission_id"]
                or row["original_attempt_id"] != request["original_attempt_id"]
                or int(time.time()) >= row["expires_at"]
                or not hmac.compare_digest(row.get("signature", ""),
                                           self.authority._sign(_signed_payload(row)))):
            raise ContractError("N9_HUMAN_FRESH_APPROVAL_REQUIRED")
        return row


install_overlay()
