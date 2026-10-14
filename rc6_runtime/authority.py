from __future__ import annotations

import hmac
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, Optional, Set


class AuthorityError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerIdentity:
    worker_id: str
    role: str
    phase: str
    layer: Optional[str]
    generation: int
    session_id: str


@dataclass(frozen=True)
class TaskLease:
    lease_id: str
    worker_id: str
    phase: str
    layer: Optional[str]
    scope_ref: str
    allowed_artifact_types: tuple
    allowed_tools: tuple
    issued_at: int
    expires_at: int
    signature: str


class AuthorityRuntime:
    """Fail-closed worker authority.

    Identity and lease are runtime-issued. Prompt text cannot elevate privileges.
    """

    _ROLE_ARTIFACTS: Dict[str, Set[str]] = {
        "COORDINATOR": {"mission_checkpoint", "routing_decision", "gate_decision"},
        "REQUIREMENT_ANALYZER": {"requirement_analysis"},
        "REQUIREMENT_REVIEWER": {"requirement_review", "analysis_gap"},
        "CODE_ANALYZER": {"code_analysis"},
        "CODE_REVIEWER": {"code_review", "analysis_gap"},
        "L1_DESIGN": {"case_candidate_l1"},
        "L2_DESIGN": {"case_candidate_l2"},
        "L3_DESIGN": {"case_candidate_l3"},
        "L4_DESIGN": {"case_candidate_l4"},
        "L5_DESIGN": {"case_candidate_l5"},
        "L6_DESIGN": {"case_candidate_l6"},
        "L7_DESIGN": {"case_candidate_l7"},
        "L1_EXECUTE": {"execution_attempt", "assertion", "evidence", "coverage_observation"},
        "L2_EXECUTE": {"execution_attempt", "assertion", "evidence", "coverage_observation"},
        "L3_EXECUTE": {"execution_attempt", "assertion", "evidence", "coverage_observation"},
        "L4_EXECUTE": {"execution_attempt", "assertion", "evidence", "coverage_observation"},
        "L5_EXECUTE": {"execution_attempt", "assertion", "evidence", "coverage_observation"},
        "L6_EXECUTE": {"execution_attempt", "assertion", "evidence", "coverage_observation"},
        "L7_EXECUTE": {"execution_attempt", "assertion", "evidence", "coverage_observation"},
        "FAILURE_DIAGNOSTIC": {"failure_diagnosis", "recovery_decision", "evidence"},
    }

    def __init__(self, signing_key: bytes):
        if not signing_key or len(signing_key) < 16:
            raise ValueError("signing_key must be at least 16 bytes")
        self._key = signing_key
        self._identities: Dict[str, WorkerIdentity] = {}
        self._leases: Dict[str, TaskLease] = {}

    def issue_identity(self, role: str, phase: str, layer: Optional[str], generation: int, session_id: str) -> WorkerIdentity:
        if role not in self._ROLE_ARTIFACTS:
            raise AuthorityError("UNKNOWN_ROLE")
        if generation < 0:
            raise AuthorityError("INVALID_GENERATION")
        identity = WorkerIdentity(
            worker_id="wrk-" + uuid.uuid4().hex,
            role=role,
            phase=phase,
            layer=layer,
            generation=generation,
            session_id=session_id,
        )
        self._identities[identity.worker_id] = identity
        return identity

    def rotate_same_role(self, worker_id: str, successor_session_id: str) -> WorkerIdentity:
        current = self._require_identity(worker_id)
        return self.issue_identity(
            role=current.role,
            phase=current.phase,
            layer=current.layer,
            generation=current.generation + 1,
            session_id=successor_session_id,
        )

    def issue_lease(
        self,
        worker_id: str,
        scope_ref: str,
        allowed_artifact_types: Iterable[str],
        allowed_tools: Iterable[str],
        ttl_seconds: int = 1800,
    ) -> TaskLease:
        identity = self._require_identity(worker_id)
        artifacts = tuple(sorted(set(allowed_artifact_types)))
        tools = tuple(sorted(set(allowed_tools)))
        role_allowed = self._ROLE_ARTIFACTS[identity.role]
        if not set(artifacts).issubset(role_allowed):
            raise AuthorityError("LEASE_ARTIFACT_SCOPE_EXCEEDS_ROLE")
        now = int(time.time())
        raw = {
            "lease_id": "lease-" + uuid.uuid4().hex,
            "worker_id": worker_id,
            "phase": identity.phase,
            "layer": identity.layer,
            "scope_ref": scope_ref,
            "allowed_artifact_types": artifacts,
            "allowed_tools": tools,
            "issued_at": now,
            "expires_at": now + ttl_seconds,
        }
        signature = self._sign(raw)
        lease = TaskLease(signature=signature, **raw)
        self._leases[lease.lease_id] = lease
        return lease

    def authorize_artifact(self, worker_id: str, lease_id: str, artifact_type: str, now: Optional[int] = None) -> None:
        identity = self._require_identity(worker_id)
        lease = self._require_lease(lease_id)
        self._validate_lease(identity, lease, now)
        if artifact_type not in self._ROLE_ARTIFACTS[identity.role]:
            raise AuthorityError("ROLE_ARTIFACT_FORBIDDEN")
        if artifact_type not in lease.allowed_artifact_types:
            raise AuthorityError("LEASE_ARTIFACT_FORBIDDEN")
        if identity.role == "COORDINATOR" and artifact_type not in {"mission_checkpoint", "routing_decision", "gate_decision"}:
            raise AuthorityError("COORDINATOR_PROFESSIONAL_ACTION_FORBIDDEN")

    def authorize_tool(self, worker_id: str, lease_id: str, tool_name: str, now: Optional[int] = None) -> None:
        identity = self._require_identity(worker_id)
        lease = self._require_lease(lease_id)
        self._validate_lease(identity, lease, now)
        if tool_name not in lease.allowed_tools:
            raise AuthorityError("LEASE_TOOL_FORBIDDEN")

    def _validate_lease(self, identity: WorkerIdentity, lease: TaskLease, now: Optional[int]) -> None:
        if lease.worker_id != identity.worker_id:
            raise AuthorityError("LEASE_WORKER_MISMATCH")
        if lease.phase != identity.phase or lease.layer != identity.layer:
            raise AuthorityError("LEASE_IDENTITY_MISMATCH")
        payload = asdict(lease)
        signature = payload.pop("signature")
        if not hmac.compare_digest(signature, self._sign(payload)):
            raise AuthorityError("LEASE_SIGNATURE_INVALID")
        current = int(time.time()) if now is None else int(now)
        if current > lease.expires_at:
            raise AuthorityError("LEASE_EXPIRED")

    def _sign(self, payload: dict) -> str:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=list).encode("utf-8")
        return hmac.new(self._key, body, hashlib.sha256).hexdigest()

    def _require_identity(self, worker_id: str) -> WorkerIdentity:
        try:
            return self._identities[worker_id]
        except KeyError:
            raise AuthorityError("UNKNOWN_WORKER")

    def _require_lease(self, lease_id: str) -> TaskLease:
        try:
            return self._leases[lease_id]
        except KeyError:
            raise AuthorityError("UNKNOWN_LEASE")
