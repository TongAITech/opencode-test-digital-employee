"""Strict RC7.2 N1 Reality completion with executable-runtime binding admission.

The legacy N1 delivery/gate service proves immutable DSH evidence and basic
reality facts.  This service adds the missing pre-admission boundary required by
N6: every executable runtime binding must already be explicit, verified,
runtime-owned, exact, and replayable from the same hash-anchored N1 candidate.

Invalid bindings are rejected *before* NodeDelivery/NodeGate creation, so N1
cannot PASS and N2 cannot become READY through this strict path.  A successful
base N1 PASS is immediately followed by canonical binding persistence.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_n1_completion import N1DeliveryGateService
from .rc72_n1_executable_binding import (
    N1ExecutableBindingError,
    N1ExecutableBindingService,
)


class N1StrictRealityGateError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N1StrictRealityGateError(
            "RC72_N1_STRICT_%s_REQUIRED" % name.upper()
        )
    return value.strip()


class N1StrictRealityGateService:
    """Fail-closed N1 completion path used before N2 may be released."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.base = N1DeliveryGateService(
            truth, source_commit=self.source_commit
        )
        self.bindings = N1ExecutableBindingService(
            truth, source_commit=self.source_commit
        )

    def _validated_binding_keys(self, release_batch_id: str) -> List[str]:
        attempt = self.base._attempt(release_batch_id)
        anchor = self.base._anchor(attempt)
        candidate, _content_ref, _raw_hash, _calls = self.base._raw_candidate(
            attempt, anchor
        )
        facts = candidate.get("facts")
        if not isinstance(facts, Mapping):
            raise N1StrictRealityGateError(
                "RC72_N1_STRICT_FACTS_REQUIRED"
            )
        raw_bindings = facts.get("executable_bindings")
        if not isinstance(raw_bindings, list) or not raw_bindings:
            raise N1StrictRealityGateError(
                "RC72_N1_STRICT_EXECUTABLE_BINDINGS_REQUIRED"
            )

        release_id = _required(attempt.get("release_id"), "release_id")
        mission_id = _required(attempt.get("mission_id"), "mission_id")
        batch_id = _required(
            attempt.get("release_batch_id"), "release_batch_id"
        )
        if batch_id != release_batch_id:
            raise N1StrictRealityGateError(
                "RC72_N1_STRICT_RELEASE_BATCH_MISMATCH"
            )

        keys: List[str] = []
        seen = set()
        for index, raw in enumerate(raw_bindings):
            if not isinstance(raw, Mapping):
                raise N1StrictRealityGateError(
                    "RC72_N1_STRICT_BINDING_%d_OBJECT_REQUIRED" % index
                )
            binding_key = _required(
                raw.get("binding_key"),
                "binding_%d_key" % index,
            )
            if binding_key in seen:
                raise N1StrictRealityGateError(
                    "RC72_N1_STRICT_BINDING_KEY_DUPLICATE:%s" % binding_key
                )
            seen.add(binding_key)
            try:
                self.bindings._normalize(
                    raw,
                    release_id=release_id,
                    mission_id=mission_id,
                    release_batch_id=batch_id,
                    binding_key=binding_key,
                )
            except N1ExecutableBindingError as exc:
                raise N1StrictRealityGateError(
                    "RC72_N1_STRICT_BINDING_INVALID:%s:%s"
                    % (binding_key, str(exc))
                ) from exc
            keys.append(binding_key)
        return keys

    def complete(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(
            release_batch_id, "release_batch_id"
        )
        binding_keys = self._validated_binding_keys(release_batch_id)

        # Only after all runtime bindings are proven may the inherited immutable
        # evidence -> Delivery -> independent Gate -> N2 forward path execute.
        result = self.base.complete(release_batch_id=release_batch_id)
        gate = result.get("gate") or {}
        if gate.get("decision") != "PASS":
            out = dict(result)
            out["executable_bindings"] = []
            return out

        canonical = []
        for binding_key in binding_keys:
            canonical.append(
                self.bindings.canonicalize(
                    release_batch_id=release_batch_id,
                    binding_key=binding_key,
                )
            )
        out = dict(result)
        out["executable_bindings"] = canonical
        out["binding_keys"] = list(binding_keys)
        return out


__all__ = [
    "N1StrictRealityGateError",
    "N1StrictRealityGateService",
]
