from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .contracts import BrowserContextRef, SUTAuthContextIdentity, SUTAuthContextScope
from .ports import BrowserAuthContextPort, ContinuationPort, HumanGatePort
from .service import R3E2ApplicationService


@dataclass(frozen=True)
class R3E2VerticalSliceResult:
    status: str
    evidence_mode: str
    checks: tuple[Mapping[str, Any], ...]
    closure_receipt: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evidence_mode": self.evidence_mode,
            "checks": [dict(item) for item in self.checks],
            "closure_receipt": dict(self.closure_receipt),
        }


def execute_vertical_slice(
    *,
    service: R3E2ApplicationService,
    mission_id: str,
    identity: SUTAuthContextIdentity,
    scope: SUTAuthContextScope,
    browser_context_ref: BrowserContextRef,
    lineage_refs: Mapping[str, Any],
    human_gate_port: HumanGatePort,
    browser_auth_port: BrowserAuthContextPort,
    continuation_port: ContinuationPort,
    observed_at: str,
    evidence_mode: str = "STRUCTURAL",
) -> R3E2VerticalSliceResult:
    checks: list[dict[str, Any]] = []

    def check(check_id: str, condition: bool, evidence: Mapping[str, Any]) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if condition else "GAP", "evidence": dict(evidence)})

    requested = service.request_auth_context(
        mission_id=mission_id,
        identity=identity,
        scope=scope,
        browser_context_ref=browser_context_ref,
        lineage_refs=lineage_refs,
        idempotency_key=f"vertical-request:{identity.key}",
    )
    check("VS-E2-01", requested.ok and requested.value.status == "AUTH_REQUIRED", {"status": requested.value.status if requested.value else None})
    if not requested.ok:
        return _result(evidence_mode, checks, {"failure": requested.to_dict()})

    gate = human_gate_port.open_external_action(mission_id=mission_id, lineage_refs=lineage_refs, browser_context_ref=browser_context_ref)
    linked = service.link_human_gate(mission_id=mission_id, context_id=identity.sut_auth_context_id, context_epoch=identity.context_epoch, gate_ref=gate, idempotency_key=f"vertical-gate:{identity.key}")
    check("VS-E2-02", linked.ok and gate.gate_kind == "EXTERNAL_ACTION" and gate.action_kind == "SUT_AUTHENTICATION_4A", {"gate_id": gate.gate_id, "gate_status": gate.status})
    if not linked.ok:
        return _result(evidence_mode, checks, {"failure": linked.to_dict()})

    decision = human_gate_port.read_decision(gate)
    armed = service.arm_runtime_verification(mission_id=mission_id, context_id=identity.sut_auth_context_id, context_epoch=identity.context_epoch, gate_ref=decision, observed_at=observed_at, human_gate_port=None, idempotency_key=f"vertical-arm:{identity.key}")
    check("VS-E2-03", armed.ok and decision.status == "APPROVED", {"gate_id": decision.gate_id, "decision_status": decision.status, "e2_status": armed.value.status if armed.value else None})
    if not armed.ok:
        return _result(evidence_mode, checks, {"failure": armed.to_dict()})

    receipt = browser_auth_port.verify_authenticated_runtime(browser_context_ref=browser_context_ref, requested_scope=scope, policy={"auth_method": "HUMAN_4A"})
    check("VS-E2-04", receipt.real_runtime and receipt.source_ref.source_kind == "RUNTIME_VERIFICATION", {"real_runtime": receipt.real_runtime, "verifier_kind": receipt.verifier_kind})
    verified = service.verify_runtime_auth(mission_id=mission_id, context_id=identity.sut_auth_context_id, context_epoch=identity.context_epoch, receipt=receipt, idempotency_key=f"vertical-verify:{identity.key}")
    check("VS-E2-05", verified.ok and verified.value.status == "AUTHENTICATED" and verified.value.validation_status == "VALID", {"status": verified.value.status if verified.value else None, "validation_status": verified.value.validation_status if verified.value else None, "verified_at": verified.value.verified_at if verified.value else None, "expires_at": verified.value.expires_at if verified.value else None})
    if not verified.ok:
        return _result(evidence_mode, checks, {"failure": verified.to_dict()})

    reuse_and_resume = service.authorize_resume(
        mission_id=mission_id,
        context_id=identity.sut_auth_context_id,
        context_epoch=identity.context_epoch,
        browser_auth_port=browser_auth_port,
        continuation_port=continuation_port,
        observed_at=observed_at,
        idempotency_key=f"vertical-resume:{identity.key}",
    )
    context = service.get_context(mission_id, identity.sut_auth_context_id, identity.context_epoch)
    check("VS-E2-06", context is not None and context.browser_context_ref == browser_context_ref, {"browser_context_reused": context is not None and context.browser_context_ref == browser_context_ref})
    check("VS-E2-07", reuse_and_resume.ok and reuse_and_resume.value.continuation_proof is not None and reuse_and_resume.value.continuation_proof.applied, {"resume_ok": reuse_and_resume.ok, "route": reuse_and_resume.value.continuation_proof.route if reuse_and_resume.value and reuse_and_resume.value.continuation_proof else None})
    check("VS-E2-08", bool(lineage_refs.get("case_step_ref")), {"case_step_ref": lineage_refs.get("case_step_ref")})

    receipt = {
        "mission_id": mission_id,
        "sut_auth_context_id": identity.sut_auth_context_id,
        "context_epoch": identity.context_epoch,
        "scope_digest": scope.digest,
        "browser_context_ref": browser_context_ref.to_dict(),
        "human_gate_id": gate.gate_id,
        "verification_id": receipt.verification_id,
        "verified_at": receipt.verified_at,
        "expires_at": receipt.expires_at,
        "continuation_proof": context.continuation_proof.to_dict() if context and context.continuation_proof else None,
        "original_case_step_ref": lineage_refs.get("case_step_ref"),
    }
    receipt["closure_digest"] = canonical_sha256(receipt)
    return _result(evidence_mode, checks, receipt)


def _result(evidence_mode: str, checks: list[dict[str, Any]], receipt: Mapping[str, Any]) -> R3E2VerticalSliceResult:
    all_pass = all(item["status"] == "PASS" for item in checks)
    real_mode = evidence_mode == "REAL_RUNTIME"
    status = "PASS" if all_pass and real_mode else "INCOMPLETE"
    final_receipt = dict(receipt)
    final_receipt["runtime_evidence_status"] = "REAL_RUNTIME" if real_mode and all_pass else "STRUCTURAL_ONLY_OR_GAP"
    return R3E2VerticalSliceResult(status, evidence_mode, tuple(checks), final_receipt)
