from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .contracts import (
    BrowserContextRef,
    ContinuationProof,
    HumanGateReference,
    RuntimeVerificationReceipt,
    SUTAuthContextScope,
)


class HumanGatePort(Protocol):
    def open_external_action(self, *, mission_id: str, lineage_refs: Mapping[str, Any], browser_context_ref: BrowserContextRef) -> HumanGateReference:
        ...

    def read_decision(self, gate_ref: HumanGateReference) -> HumanGateReference:
        ...


class BrowserAuthContextPort(Protocol):
    def inspect_context(self, browser_context_ref: BrowserContextRef) -> BrowserContextRef:
        ...

    def inspect_lease(self, browser_context_ref: BrowserContextRef) -> str:
        ...

    def verify_authenticated_runtime(
        self,
        *,
        browser_context_ref: BrowserContextRef,
        requested_scope: SUTAuthContextScope,
        policy: Mapping[str, Any],
    ) -> RuntimeVerificationReceipt:
        ...

    def reuse_context(self, *, browser_context_ref: BrowserContextRef, requested_scope: SUTAuthContextScope) -> "ContextReuseReceipt":
        ...


class ContinuationPort(Protocol):
    def record_resume(self, *, mission_id: str, gate_ref: HumanGateReference, auth_context_id: str, browser_context_ref: BrowserContextRef) -> ContinuationProof:
        ...


@dataclass(frozen=True)
class ContextReuseReceipt:
    reused: bool
    browser_context_ref: BrowserContextRef
    scope_digest: str
    reuse_receipt_ref: str
    observed_at: str
    reason: str = "REUSED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "reused": self.reused,
            "browser_context_ref": self.browser_context_ref.to_dict(),
            "scope_digest": self.scope_digest,
            "reuse_receipt_ref": self.reuse_receipt_ref,
            "observed_at": self.observed_at,
            "reason": self.reason,
        }


def require_real_runtime_verification(
    receipt: RuntimeVerificationReceipt,
    *,
    scope: SUTAuthContextScope,
    expected_browser_context_ref: BrowserContextRef,
) -> None:
    if not receipt.real_runtime:
        raise ValueError("R3_E2_RUNTIME_VERIFICATION_REQUIRED: verifier did not provide real runtime evidence")
    if receipt.verifier_kind.upper() in {"MOCK", "FAKE", "NOT_CONFIGURED"}:
        raise ValueError("R3_E2_RUNTIME_VERIFICATION_REQUIRED: mock/fake/not-configured verifier is not runtime evidence")
    if receipt.scope_digest != scope.digest or receipt.source_ref.scope != scope:
        raise ValueError("R3_E2_SCOPE_MISMATCH: runtime verification scope does not match requested scope")
    if receipt.browser_context_ref != expected_browser_context_ref:
        raise ValueError("R3_E2_BROWSER_CONTEXT_MISMATCH: runtime verification used a different Browser context")
    if receipt.observed_lease_owner != expected_browser_context_ref.observed_lease_owner:
        raise ValueError("R3_E2_BROWSER_LEASE_MISMATCH: runtime verification lease differs from expected lease")
    if receipt.source_ref.source_kind != "RUNTIME_VERIFICATION":
        raise ValueError("R3_E2_PROVENANCE_INVALID: runtime verification source kind is not RUNTIME_VERIFICATION")
