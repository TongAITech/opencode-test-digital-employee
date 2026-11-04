"""Explicit B-authority Field proof bridge for native BrowserSkill Journey.

Unlike mutable adapter.field_verified, this opt-in adapter receives a scoped
proof only from an A/B-configured external bank attestation verifier. It
cannot produce Field proof itself. Real B/4A/BSK checks and signer
cryptography live outside C09; unsigned/self-declared evidence is rejected.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Mapping, Sequence, Tuple

from .models import ContractError
from .rc72_journey_bsk import JourneyBSKAdapter


def bsk_field_scope_digest(scope: Mapping[str, Any]) -> str:
    """Canonical identity of exactly one official or benchmark Attempt."""
    values = [
        "replay_id", "execution_id", "candidate_id", "official_asset_id",
        "mission_id", "release_batch_id", "requirement_id", "sst_id",
        "obligation_id", "case_id", "workitem_id", "attempt_id",
        "worker_id", "session_id", "browser_lease_id",
    ]
    material = {k: scope.get(k) for k in values}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class JourneyBSKCertifiedFieldAdapter(JourneyBSKAdapter):
    adapter_kind = "BROWSERSKILL_FIELD_ATTESTED"
    field_verified = False

    def __init__(
        self, *, field_attestation_verifier: Callable[
            [Mapping[str, Any]], Mapping[str, Any]],
        trusted_verifier_kinds: Sequence[str],
        **kwargs: Any,
    ) -> None:
        if not callable(field_attestation_verifier):
            raise ContractError("JOURNEY_BSK_FIELD_EXTERNAL_VERIFIER_REQUIRED")
        trusted = {s.strip() for s in trusted_verifier_kinds
                   if isinstance(s, str) and s.strip()}
        if not trusted:
            raise ContractError("JOURNEY_BSK_FIELD_TRUSTED_ISSUER_REQUIRED")
        super().__init__(**kwargs)
        self.field_authority = field_attestation_verifier
        self.trusted_verifier_kinds = trusted
        self._approved_run = None
        self._proof_expires_at = 0
        self._field_proof_ref = None

    def verify_field_scope(self, scope: Mapping[str, Any]) -> bool:
        if not isinstance(scope, Mapping):
            raise ContractError("JOURNEY_BSK_FIELD_SCOPE_REQUIRED")
        binding = self._guard(scope)
        proof = self.field_authority(dict(scope))
        if not isinstance(proof, Mapping):
            raise ContractError("JOURNEY_BSK_FIELD_AUTHORITY_NO_PROOF")
        now = int(time.time())
        run_id = scope.get("replay_id") or scope.get("execution_id")
        expected = {
            "scope_digest": bsk_field_scope_digest(scope),
            "bsk_session_id": binding["session"],
            "tab_id": binding["tab_id"],
            "browser_instance_id": binding["instance"]["browser_instance_id"],
            "auth_asset_ref": binding["instance"].get("auth_asset_ref"),
            "browser_lease_id": scope["browser_lease_id"],
            "attempt_id": scope["attempt_id"],
            "case_id": scope["case_id"],
        }
        if any(proof.get(key) != value for key, value in expected.items()):
            raise ContractError("JOURNEY_BSK_FIELD_PROOF_SCOPE_MISMATCH")
        if (proof.get("verifier_kind") not in self.trusted_verifier_kinds
                or proof.get("signature_verified") is not True
                or proof.get("field_verified") is not True
                or proof.get("attestation_kind") != "BANK_BSK_FIELD_SESSION"):
            raise ContractError("JOURNEY_BSK_FIELD_PROOF_NOT_TRUSTED")
        issued, expires = proof.get("issued_at"), proof.get("expires_at")
        if (type(issued) is not int or type(expires) is not int
                or issued > now or expires <= now or expires - issued > 3600):
            raise ContractError("JOURNEY_BSK_FIELD_PROOF_EXPIRED")
        evidence = proof.get("evidence_refs")
        ref = proof.get("attestation_ref")
        if (not isinstance(ref, str) or not ref.strip()
                or not isinstance(evidence, list) or not evidence
                or not all(isinstance(x, str) and x.strip() for x in evidence)):
            raise ContractError("JOURNEY_BSK_FIELD_PROOF_EVIDENCE_REQUIRED")
        self._approved_run = (run_id, scope["attempt_id"],
                              scope["browser_lease_id"])
        self._proof_expires_at = expires
        self._field_proof_ref = ref
        return True

    def execute_step(self, step: Mapping[str, Any],
                     context: Mapping[str, Any]):
        current = (
            context.get("replay_id") or context.get("execution_id"),
            context.get("attempt_id"), context.get("browser_lease_id"),
        )
        if (self._approved_run != current
                or int(time.time()) >= self._proof_expires_at):
            raise ContractError("JOURNEY_BSK_FIELD_SCOPE_NOT_ATTESTED")
        return super().execute_step(step, context)

    def close(self) -> None:
        super().close()
        self._approved_run = None
        self._proof_expires_at = 0
        self._field_proof_ref = None
