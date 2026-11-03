"""RC7.2 authority extensions for adopting governed worker identities.

RC7.2 MissionNode scheduling creates a durable worker identity before the real
DSH process exists. The inherited AuthorityRuntime only issues random worker
identities, so directly calling its normal assignment path would create a
second worker identity for the same WorkItem. This additive runtime lets a
previously governed RC7.2 worker identity be adopted fail-closed.

Adoption is authority state, not evidence that DSH started. A real DSH session
must still be observed separately before MissionNode Attempt truth is admitted.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from typing import Iterable, Optional

from rc6_runtime.authority import AuthorityError, AuthorityRuntime, TaskLease, WorkerIdentity
from .authority import RC7AuthorityRuntime


REALITY_RECON_WORKER = "REALITY_RECON_WORKER"
REQUIREMENT_ANALYSIS_WORKER = "REQUIREMENT_ANALYSIS_WORKER"
SOURCE_TARGET_DISCOVERY_WORKER = "SOURCE_TARGET_DISCOVERY_WORKER"
SOURCE_TARGET_REVIEWER = "SOURCE_TARGET_REVIEWER"
CODE_ANALYSIS_WORKER = "CODE_ANALYSIS_WORKER"
TEST_DESIGN_WORKER = "TEST_DESIGN_WORKER"
DATA_PREPARER = "DATA_PREPARER"
DATA_VERIFIER = "DATA_VERIFIER"


class RC72AuthorityRuntime(AuthorityRuntime):
    """AuthorityRuntime with explicit adoption for already-governed RC7.2 workers."""

    _ROLE_ARTIFACTS = {
        role: set(artifacts) for role, artifacts in AuthorityRuntime._ROLE_ARTIFACTS.items()
    }
    _ROLE_ARTIFACTS[REALITY_RECON_WORKER] = set()
    _ROLE_ARTIFACTS[REQUIREMENT_ANALYSIS_WORKER] = set()
    _ROLE_ARTIFACTS[SOURCE_TARGET_DISCOVERY_WORKER] = set()
    _ROLE_ARTIFACTS[SOURCE_TARGET_REVIEWER] = set()
    _ROLE_ARTIFACTS[CODE_ANALYSIS_WORKER] = set()
    _ROLE_ARTIFACTS[TEST_DESIGN_WORKER] = set()
    # Reuse the inherited independent design reviewer candidate permissions;
    # this does not grant canonical Case, obligation, Evaluation or Gate writes.
    _ROLE_ARTIFACTS["RC7_TEST_DESIGN_REVIEWER"] = set(
        RC7AuthorityRuntime._ROLE_ARTIFACTS["RC7_TEST_DESIGN_REVIEWER"])
    # N5 data workers are execution identities only. They may call tools
    # explicitly granted by their task-scoped lease, but cannot write canonical
    # professional artifacts directly. DataRef/binding/lease truth is admitted
    # only by downstream evidence-backed finalization services.
    _ROLE_ARTIFACTS[DATA_PREPARER] = set()
    # The independent verifier is deliberately no more privileged than the
    # producer. It can observe through leased tools but cannot self-register a
    # verified DataRef, binding, lease, node PASS, or downstream release.
    _ROLE_ARTIFACTS[DATA_VERIFIER] = set()
    _ROLE_ARTIFACTS["RC72_COVERAGE_AUDITOR"] = set()

    def worker_process_environment(self, *, identity, lease, worker_instance_id, mission_id, scope, explicit, home):
        """Project a live native worker's environment, never the Captain's home."""
        from rc6_runtime.process_environment import scoped_process_environment
        if (worker_instance_id != identity.worker_id or self._require_identity(identity.worker_id) != identity
                or self._require_lease(lease.lease_id) != lease or lease.scope_ref != scope):
            raise AuthorityError('WORKER_PROCESS_IDENTITY_OR_SCOPE_MISMATCH')
        self._validate_lease(identity, lease, None)
        if int(time.time()) < lease.issued_at:
            raise AuthorityError('WORKER_PROCESS_LEASE_NOT_ISSUED')
        values = dict(explicit)
        if any(not isinstance(key, str) or not isinstance(value, str) or '\0' in value for key, value in values.items()):
            raise AuthorityError('WORKER_PROCESS_ENVIRONMENT_INVALID')
        if any(not isinstance(key, str) or any(word in key.upper() for word in
               ('CAPTAIN', 'COORDINATOR', 'SIGNING_KEY', 'AUTHORITY_KEY', 'RUNTIME_HMAC_KEY')) for key in values):
            raise AuthorityError('WORKER_PROCESS_CONTROL_CREDENTIAL_FORBIDDEN')
        # Windows environment names are case-insensitive. Canonicalize the
        # protected projection before validation so aliases cannot bypass it.
        protected = {'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'DSH_HOME',
                     'XDG_CONFIG_HOME', 'PFC_RC7_DSH_SESSION_MODE', 'PFC_RC7_DSH_ALLOWED_TOOLS',
                     'PFC_RC7_MCP_MISSION_ID', 'PFC_RC7_MCP_WORKER_ID', 'PFC_RC7_MCP_LEASE_ID',
                     'PFC_RC7_MCP_SCOPE_REF', 'PFC_RC7_MCP_TASK_ID'}
        normalized = {}
        for key, value in values.items():
            name = key.upper() if key.upper() in protected else key
            if name in normalized and normalized[name] != value:
                raise AuthorityError('WORKER_PROCESS_AMBIGUOUS_ENVIRONMENT')
            normalized[name] = value
        values = normalized
        binding = {'PFC_RC7_MCP_MISSION_ID': mission_id, 'PFC_RC7_MCP_WORKER_ID': identity.worker_id,
                   'PFC_RC7_MCP_LEASE_ID': lease.lease_id, 'PFC_RC7_MCP_SCOPE_REF': scope}
        if scope.startswith('task:'):
            binding['PFC_RC7_MCP_TASK_ID'] = scope[len('task:'):].split('/attempt:', 1)[0]
        if any(key in values and values[key] != value for key, value in binding.items()):
            raise AuthorityError('WORKER_PROCESS_CALLER_PROJECTION_MISMATCH')
        if values.get('PFC_RC7_DSH_SESSION_MODE', 'LEASE_BOUND_WORKER') != 'LEASE_BOUND_WORKER':
            raise AuthorityError('WORKER_PROCESS_INTERACTIVE_CONTROL_FORBIDDEN')
        if 'PFC_RC7_DSH_ALLOWED_TOOLS' in values:
            try:
                projected = json.loads(values['PFC_RC7_DSH_ALLOWED_TOOLS'])
            except ValueError:
                raise AuthorityError('WORKER_PROCESS_TOOL_PROJECTION_INVALID') from None
            if (not isinstance(projected, list) or any(not isinstance(tool, str) for tool in projected)
                    or len(set(projected)) != len(projected) or set(projected) != set(lease.allowed_tools)):
                raise AuthorityError('WORKER_PROCESS_TOOL_PROJECTION_MISMATCH')
        identifier = hashlib.sha256(json.dumps([identity.worker_id, identity.session_id, lease.lease_id, scope],
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:32]
        private = Path(home).resolve() / identifier
        expected = dict(HOME=private, USERPROFILE=private, APPDATA=private/'AppData'/'Roaming',
                        LOCALAPPDATA=private/'AppData'/'Local')
        for key, value in values.items():
            upper = key.upper()
            if upper in expected and Path(value).expanduser().resolve() != expected[upper]:
                raise AuthorityError('WORKER_PROCESS_PRIVATE_HOME_REQUIRED')
            if upper in {'DSH_HOME', 'XDG_CONFIG_HOME'}:
                try:
                    Path(value).expanduser().resolve().relative_to(private)
                except ValueError:
                    raise AuthorityError('WORKER_PROCESS_PRIVATE_PROFILE_REQUIRED') from None
        environment = scoped_process_environment(values, home=private)
        environment['PFC_RC7_DSH_SESSION_MODE'] = 'LEASE_BOUND_WORKER'
        environment.setdefault('DSH_HOME', str(private/'.dsh'))
        environment.setdefault('XDG_CONFIG_HOME', str(private/'.config'))
        return environment

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

    def get_identity(self, worker_id):
        return self._require_identity(worker_id)

    def get_lease(self, lease_id):
        return self._require_lease(lease_id)

    def revoke_lease(self, lease_id):
        self._require_lease(lease_id)
        self.revoke_worker_lease(lease_id)

    def is_lease_revoked(self, lease_id):
        return lease_id in getattr(self, '_revoked_lease_ids', set())

    def revoke_worker_lease(self, lease_id: str):
        revoked = getattr(self, "_revoked_lease_ids", None)
        if revoked is None:
            self._revoked_lease_ids = revoked = set()
        revoked.add(lease_id)
        self._leases.pop(lease_id, None)

    def _validate_lease(self, identity, lease, now):
        if lease.lease_id in getattr(self, "_revoked_lease_ids", set()):
            raise AuthorityError("LEASE_REVOKED")
        verified = super()._validate_lease(identity, lease, now)
        # Legacy RC6 permits use at exactly expires_at. RC7.2 signed worker
        # authority has an exclusive TTL end: [issued_at, expires_at).
        # Preserve parent signature verification before the boundary check.
        current = int(time.time()) if now is None else int(now)
        if current >= lease.expires_at:
            raise AuthorityError("LEASE_EXPIRED")
        return verified

    def validate_historical_lease(self, identity, lease):
        """Authenticate past observations only; never restore revoked authority."""
        return super()._validate_lease(identity, lease, lease.issued_at)

    def restore_renewed_worker_lease(self, identity, original, renewed):
        """Restore an authenticated same-scope temporal amendment, never scope."""
        from dataclasses import asdict
        self.validate_historical_lease(identity, original)
        left, right = asdict(original), asdict(renewed)
        for key in ('expires_at', 'signature'):
            left.pop(key)
            right.pop(key)
        if left != right or renewed.expires_at < original.expires_at:
            raise AuthorityError('LEASE_RENEWAL_SCOPE_CHANGED')
        self._validate_lease(identity, renewed, None)
        current = self._leases.get(renewed.lease_id)
        if current is not None:
            observed = asdict(current)
            for key in ('expires_at', 'signature'):
                observed.pop(key)
            if observed != left or current.expires_at > renewed.expires_at:
                raise AuthorityError('LEASE_RENEWAL_REGRESSION')
        self.adopt_identity(**asdict(identity))
        self._leases[renewed.lease_id] = renewed
        return renewed

    def restore_signed_worker_lease(self, identity, lease, *, expected_scope: str):
        """Restore audit metadata only after verifying the original HMAC and TTL."""
        from dataclasses import asdict
        if lease.scope_ref != expected_scope:
            raise AuthorityError("LEASE_SCOPE_MISMATCH")
        if identity.role not in self._ROLE_ARTIFACTS or not set(lease.allowed_artifact_types).issubset(self._ROLE_ARTIFACTS[identity.role]):
            raise AuthorityError("LEASE_ARTIFACT_SCOPE_EXCEEDS_ROLE")
        if any("*" in tool for tool in lease.allowed_tools):
            raise AuthorityError("WILDCARD_TOOL_FORBIDDEN")
        self._validate_lease(identity, lease, None)
        current = self._leases.get(lease.lease_id)
        if current is not None and current != lease:
            raise AuthorityError("LEASE_RESTORE_CONFLICT")
        self.adopt_identity(**asdict(identity))
        self._leases[lease.lease_id] = lease
        return lease

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
