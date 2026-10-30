"""RC7.2 authority extensions for adopting governed worker identities.

RC7.2 MissionNode scheduling creates a durable worker identity before the real
DSH process exists.  The inherited AuthorityRuntime only issues random worker
identities, so directly calling its normal assignment path would create a
second worker identity for the same WorkItem.  This additive runtime lets a
previously governed RC7.2 worker identity be adopted fail-closed.

Adoption is authority state, not evidence that DSH started.  A real DSH session
must still be observed separately before MissionNode Attempt truth is admitted.
"""
from __future__ import annotations

from typing import Iterable, Optional

from rc6_runtime.authority import AuthorityError, AuthorityRuntime, TaskLease, WorkerIdentity


REALITY_RECON_WORKER = "REALITY_RECON_WORKER"


class RC72AuthorityRuntime(AuthorityRuntime):
    """AuthorityRuntime with explicit adoption for already-governed RC7.2 workers."""

    _ROLE_ARTIFACTS = {
        role: set(artifacts) for role, artifacts in AuthorityRuntime._ROLE_ARTIFACTS.items()
    }
    # Reality Recon may invoke leased tools and return a candidate handoff, but it
    # cannot directly author canonical business artifacts. NodeDelivery admission
    # remains an RC7.2 control-plane responsibility.
    _ROLE_ARTIFACTS[REALITY_RECON_WORKER] = set()

    def adopt_identity(
        self,
        *,
        worker_id: str,
        role: str,
        phase: str,
        layer: Optional[str],
        generation: int,
        session_id: str,
    ) -> WorkerIdentity:
        for name, value in (
            ("worker_id", worker_id),
            ("role", role),
            ("phase", phase),
            ("session_id", session_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise AuthorityError("INVALID_%s" % name.upper())
        if role not in self._ROLE_ARTIFACTS:
            raise AuthorityError("UNKNOWN_ROLE")
        if layer is not None and (not isinstance(layer, str) or not layer.strip()):
            raise AuthorityError("INVALID_LAYER")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise AuthorityError("INVALID_GENERATION")

        identity = WorkerIdentity(
            worker_id=worker_id.strip(),
            role=role.strip(),
            phase=phase.strip(),
            layer=layer.strip() if isinstance(layer, str) else None,
            generation=generation,
            session_id=session_id.strip(),
        )
        existing = self._identities.get(identity.worker_id)
        if existing is not None:
            if existing != identity:
                raise AuthorityError("WORKER_IDENTITY_CONFLICT")
            return existing
        self._identities[identity.worker_id] = identity
        return identity

    def validate_identity(
        self,
        worker_id: str,
        *,
        role: Optional[str] = None,
        phase: Optional[str] = None,
        layer: Optional[str] = None,
        generation: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> WorkerIdentity:
        identity = self._require_identity(worker_id)
        expectations = {
            "role": role,
            "phase": phase,
            "layer": layer,
            "generation": generation,
            "session_id": session_id,
        }
        for field, expected in expectations.items():
            if expected is not None and getattr(identity, field) != expected:
                raise AuthorityError("WORKER_IDENTITY_%s_MISMATCH" % field.upper())
        return identity

    def validate_lease(
        self,
        worker_id: str,
        lease_id: str,
        *,
        scope_ref: Optional[str] = None,
        allowed_artifact_types: Optional[Iterable[str]] = None,
        allowed_tools: Optional[Iterable[str]] = None,
        now: Optional[int] = None,
    ) -> TaskLease:
        identity = self._require_identity(worker_id)
        lease = self._require_lease(lease_id)
        self._validate_lease(identity, lease, now)
        if scope_ref is not None and lease.scope_ref != scope_ref:
            raise AuthorityError("LEASE_SCOPE_MISMATCH")
        if allowed_artifact_types is not None:
            expected = tuple(sorted(set(allowed_artifact_types)))
            if lease.allowed_artifact_types != expected:
                raise AuthorityError("LEASE_ARTIFACT_SCOPE_MISMATCH")
        if allowed_tools is not None:
            expected = tuple(sorted(set(allowed_tools)))
            if lease.allowed_tools != expected:
                raise AuthorityError("LEASE_TOOL_SCOPE_MISMATCH")
        return lease
