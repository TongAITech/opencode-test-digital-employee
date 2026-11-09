"""WB-A03 E-group DESIGN-ONLY adversarial protocol oracle.

This module is a deliberately isolated, in-memory model for W0 contract
counterexamples. It is NOT an HTTP router, an authorization provider,
an R1 command processor, durable idempotency, SSE transport or a QA result.
Real implementations are gated on WB-B06 and independent F qualification.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


class ContractRejection(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractRejection(code)


def authorized_mission(
    principal_id: str,
    allowed_projects: Mapping[str, Sequence[str]],
    requested_project: str,
    mission_id: str,
    mission_owners: Mapping[str, Tuple[str, str]],
    requested_batch: str,
) -> Tuple[str, str]:
    """Authenticate/authorize project BEFORE resolving a mission (no enumeration)."""
    _require(bool(principal_id), "UNAUTHENTICATED")
    _require(requested_project in allowed_projects.get(principal_id, ()), "FORBIDDEN")
    owner = mission_owners.get(mission_id)
    _require(owner is not None, "RESOURCE_NOT_FOUND")
    _require(owner[0] == requested_project, "FORBIDDEN")
    _require(owner[1] == requested_batch, "ILLEGAL_ASSOCIATION")
    return owner


_ALLOWED_ACTIONS = frozenset({"pause", "resume", "retry_failed", "request_human_gate"})
_CLIENT_FIELDS = frozenset({
    "command_id", "idempotency_key", "expected_state_revision",
    "scope_ref", "action", "reason",
})


class InMemoryCommandOracle:
    """Illustrates command rejection and idempotency; cannot persist or mutate R1."""

    def __init__(self, allowed_projects: Mapping[str, Sequence[str]],
                 mission_owners: Mapping[str, Tuple[str, str]]) -> None:
        self.allowed_projects = allowed_projects
        self.mission_owners = mission_owners
        self._seen: Dict[Tuple[str, str, str, str], Tuple[str, str]] = {}

    def submit(self, trusted_principal: str, project: str, mission: str,
               batch: str, request: Mapping[str, Any],
               authoritative_revision: int) -> Dict[str, str]:
        authorized_mission(trusted_principal, self.allowed_projects,
                           project, mission, self.mission_owners, batch)
        _require(isinstance(request, Mapping), "VALIDATION_ERROR")
        _require(set(request) == _CLIENT_FIELDS, "UNTRUSTED_CLIENT_FIELDS")
        for key in ("command_id", "idempotency_key", "reason"):
            _require(isinstance(request[key], str) and bool(request[key].strip()),
                     "VALIDATION_ERROR")
        _require(request["action"] in _ALLOWED_ACTIONS, "FORBIDDEN_ACTION")
        _require(request["scope_ref"] == {
            "project_id": project, "batch_id": batch, "mission_id": mission
        }, "ILLEGAL_ASSOCIATION")
        _require(isinstance(request["expected_state_revision"], int)
                 and not isinstance(request["expected_state_revision"], bool),
                 "VALIDATION_ERROR")
        payload = json.dumps(request, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        key = (trusted_principal, project, mission, request["idempotency_key"])
        existing = self._seen.get(key)
        if existing:
            _require(existing[0] == payload, "IDEMPOTENCY_CONFLICT")
            return {"outcome": "accepted", "command_ref": existing[1],
                    "idempotency": "replay"}
        _require(request["expected_state_revision"] == authoritative_revision,
                 "STATE_REVISION_CONFLICT")
        # NO real command is dispatched and NO R1 mutation is performed.
        command_ref = "fixture:" + hashlib.sha256(
            "|".join(key).encode("utf-8")).hexdigest()[:20]
        self._seen[key] = (payload, command_ref)
        return {"outcome": "accepted", "command_ref": command_ref,
                "idempotency": "first_seen"}


_REQUIRED_EVENTS = frozenset({
    "event_id", "project_id", "batch_id", "type", "revision",
    "truth_revision", "source_ref", "timestamp",
})


class BatchReplayOracle:
    """In-memory sequential event replay contract, not an SSE broker."""

    def __init__(self, project: str, batch: str, access_scope_revision: int,
                 snapshot_watermark: int) -> None:
        _require(isinstance(snapshot_watermark, int) and snapshot_watermark >= 0,
                 "INVALID_WATERMARK")
        self.project = project
        self.batch = batch
        self.access_scope_revision = access_scope_revision
        self.revision = snapshot_watermark
        self._events: Dict[str, str] = {}

    def accept(self, event: Mapping[str, Any], project: str, batch: str,
               access_scope_revision: int) -> str:
        _require((project, batch) == (self.project, self.batch),
                 "CURSOR_SCOPE_MISMATCH")
        _require(access_scope_revision == self.access_scope_revision,
                 "ACCESS_SCOPE_REVOKED")
        _require(isinstance(event, Mapping)
                 and _REQUIRED_EVENTS.issubset(event), "MALFORMED_EVENT")
        _require((event["project_id"], event["batch_id"]) ==
                 (self.project, self.batch), "CROSS_BATCH_EVENT")
        try:
            ts = datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractRejection("INVALID_TIMESTAMP") from exc
        _require(ts.tzinfo is not None and ts.utcoffset() is not None,
                 "TIMEZONE_REQUIRED")
        _require(type(event["revision"]) is int and event["revision"] > 0
                 and type(event["truth_revision"]) is int
                 and event["truth_revision"] >= 0, "INVALID_REVISION")
        _require(all(isinstance(event[k], str) and bool(event[k])
                     for k in ("event_id", "type", "source_ref")), "MALFORMED_EVENT")
        encoded = json.dumps(dict(event), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        event_id = event["event_id"]
        if event_id in self._events:
            _require(self._events[event_id] == encoded, "EVENT_ID_MUTATED")
            return "duplicate_ignored"
        _require(event["revision"] == self.revision + 1, "EVENT_WATERMARK_GAP")
        self.revision += 1
        self._events[event_id] = encoded
        return "accepted"


def verified_sha256(content: Optional[bytes], expected_hash: Optional[str]) -> bool:
    """An R1 Evidence record's optional content_hash is never verification itself."""
    if not isinstance(content, bytes) or not isinstance(expected_hash, str):
        return False
    if not expected_hash.startswith("sha256:"):
        return False
    digest = expected_hash[len("sha256:"):]
    if len(digest) != 64 or any(c not in "0123456789abcdef"
                               for c in digest):
        return False
    return hmac.compare_digest(hashlib.sha256(content).hexdigest(), digest)


def publication_oracle(nodegate: Mapping[str, Any], n10: Mapping[str, Any],
                       approval: Mapping[str, Any],
                       evidence_checks: Sequence[bool],
                       truth_available: bool = True) -> str:
    """Only an illustration of a fail-closed VIEW, NEVER a publish command."""
    if not truth_available:
        return "UNKNOWN"
    if nodegate.get("decision") != "PASS":
        return "HOLD"
    if n10.get("state") != "COMPLETED" or n10.get("convergence") != "CONVERGED":
        return "HOLD"
    if approval.get("decision") != "APPROVED" or not approval.get("reviewer_id"):
        return "HOLD"
    if not evidence_checks or not all(value is True for value in evidence_checks):
        return "HOLD"
    return "ELIGIBLE_TO_REQUEST_ONLY"


def evidence_defect_trace(attempt: Mapping[str, Any], evidence: Mapping[str, Any],
                          defect: Mapping[str, Any]) -> bool:
    """Never infer trace from similar names or version labels."""
    ids = ("mission_id", "attempt_id")
    if not all(attempt.get(k) and evidence.get(k) == attempt.get(k) for k in ids):
        return False
    if evidence.get("evidence_id") not in defect.get("evidence_refs", ()):
        return False
    if not all(attempt.get(k) == defect.get(k) for k in ("mission_id", "batch_id")):
        return False
    return bool(attempt.get("etu_id") and attempt.get("workitem_id")
                and attempt.get("case_id") and attempt.get("task_lease_ref")
                and evidence.get("hash_verified") is True)
