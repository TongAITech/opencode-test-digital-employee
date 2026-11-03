"""Single-owner Captain dispatch fencing on canonical RC7.2 R1.

This is an additive control-plane guard for WorkerLifecycleService. It does not
replace AgentTeams, issue worker credentials, perform business I/O, or mutate
the global R1 schema. A crashed/expired Captain must not silently reclaim
dispatch authority; a verified R1 handoff is required.
"""
from __future__ import annotations

import time
import uuid

from rc6_runtime import contracts
from rc6_runtime import truth as registry
from .models import ContractError
from .rc72_ledger_lock import ledger_lock

_KIND = "rc72_captain_dispatch_lease"
_EVENT = "RC72_CAPTAIN_DISPATCH_LEASE_UPSERTED"
_STATES = {"ACTIVE", "QUIESCED", "EXPIRED", "SUPERSEDED"}


def _now():
    return int(time.time())


def _validate(payload):
    row = dict(payload)
    for field in ("lease_id", "release_id", "mission_id", "team_id",
                  "captain_session_id", "state"):
        contracts._require_str(row, field)
    if row["state"] not in _STATES:
        raise contracts.DomainValidationError("CAPTAIN_DISPATCH_STATE_INVALID")
    for field in ("generation", "issued_at", "expires_at"):
        value = row.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise contracts.DomainValidationError("CAPTAIN_DISPATCH_%s_INVALID" % field.upper())
    if row["generation"] < 1 or row["expires_at"] <= row["issued_at"]:
        raise contracts.DomainValidationError("CAPTAIN_DISPATCH_WINDOW_INVALID")
    if row["state"] == "QUIESCED" and not isinstance(row.get("quiesced_at"), int):
        raise contracts.DomainValidationError("CAPTAIN_QUIESCE_TIMESTAMP_REQUIRED")
    if row["state"] == "SUPERSEDED" and not row.get("superseded_by"):
        raise contracts.DomainValidationError("CAPTAIN_SUCCESSOR_REQUIRED")
    for forbidden in ("captain_token", "secret", "worker_token", "case_pass", "bank_final"):
        if forbidden in row:
            raise contracts.DomainValidationError("CAPTAIN_DISPATCH_SECRET_OR_PREMATURE_CLAIM")
    row["artifact_type"] = _KIND
    row["artifact_version"] = contracts._artifact_version(row)
    return row


def install_captain_dispatch_overlay():
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, "lease_id")
    registry.IDENTITY_FIELDS[_KIND] = "lease_id"
    registry.BUCKETS[_KIND] = "rc72_captain_dispatch_leases"


class CaptainDispatchFencer:
    """Fail-closed dispatch custody. Call assert_owner before every scheduling write.

    This guard can only protect codepaths that invoke it. Until the formal
    Mission driver is integrated with the fencer, C07 is NOT product-closed.
    """

    def __init__(self, truth, *, release_id):
        install_captain_dispatch_overlay()
        self.truth = truth
        self.release_id = release_id

    def _rows(self, mission_id):
        return sorted(self.truth.query(_KIND, mission_id=mission_id),
                      key=lambda row: (row["generation"], row["issued_at"]))

    def _save(self, payload):
        row = dict(payload)
        row.pop("artifact_type", None)
        self.truth.append_atomic(_EVENT, row)
        return self.truth.query(_KIND, lease_id=row["lease_id"])[0]

    def _replace(self, row, **changes):
        candidate = dict(row)
        candidate.pop("artifact_type", None)
        candidate.update(changes, artifact_version=row["artifact_version"] + 1)
        return self._save(candidate)

    def _batch(self, mission_id):
        rows = self.truth.query("rc72_release_batch", mission_id=mission_id)
        if len(rows) != 1 or rows[0]["release_id"] != self.release_id:
            raise ContractError("CAPTAIN_MISSION_NOT_CANONICAL")
        return rows[0]

    def _latest(self, mission_id):
        rows = self._rows(mission_id)
        return rows[-1] if rows else None

    def _owner(self, mission_id, lease_id, captain_session_id, now):
        lease = self._latest(mission_id)
        if (lease is None or lease["lease_id"] != lease_id
                or lease["captain_session_id"] != captain_session_id):
            raise ContractError("CAPTAIN_DISPATCH_FENCED")
        if lease["state"] != "ACTIVE":
            raise ContractError("CAPTAIN_DISPATCH_NOT_ACTIVE")
        if now > lease["expires_at"]:
            self._replace(lease, state="EXPIRED")
            raise ContractError("CAPTAIN_DISPATCH_LEASE_EXPIRED")
        return lease

    def acquire_initial(self, *, mission_id, team_id, captain_session_id,
                        ttl_seconds=300):
        if not all(isinstance(x, str) and x.strip() for x in
                   (mission_id, team_id, captain_session_id)):
            raise ContractError("CAPTAIN_DISPATCH_SCOPE_REQUIRED")
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds < 1:
            raise ContractError("CAPTAIN_DISPATCH_TTL_INVALID")
        with ledger_lock(self.truth):
            self._batch(mission_id)
            if self._latest(mission_id) is not None:
                raise ContractError("CAPTAIN_DISPATCH_EXISTING_OWNER_REQUIRES_HANDOFF")
            now = _now()
            return self._save(dict(
                lease_id="CAPF-" + uuid.uuid4().hex, release_id=self.release_id,
                mission_id=mission_id, team_id=team_id, captain_session_id=captain_session_id,
                generation=1, issued_at=now, expires_at=now + ttl_seconds,
                state="ACTIVE", artifact_version=1))

    def assert_owner(self, *, mission_id, lease_id, captain_session_id):
        with ledger_lock(self.truth):
            self._batch(mission_id)
            return self._owner(mission_id, lease_id, captain_session_id, _now())

    def heartbeat(self, *, mission_id, lease_id, captain_session_id, ttl_seconds=300):
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds < 1:
            raise ContractError("CAPTAIN_DISPATCH_TTL_INVALID")
        with ledger_lock(self.truth):
            owner = self._owner(mission_id, lease_id, captain_session_id, _now())
            return self._replace(owner, expires_at=max(owner["expires_at"], _now() + ttl_seconds))

    def prepare_handoff(self, *, mission_id, lease_id, captain_session_id,
                        lifecycle, team_id, current_node_refs,
                        latest_delivery_refs, latest_gate_refs, next_workitem_ids):
        """First quiesce dispatch durably; then persist existing lifecycle checkpoint.

        A crash between these steps blocks dispatch instead of risking two
        Captains. Recovery requires independent incident reconciliation.
        """
        with ledger_lock(self.truth):
            owner = self._owner(mission_id, lease_id, captain_session_id, _now())
            if owner["team_id"] != team_id:
                raise ContractError("CAPTAIN_HANDOFF_TEAM_MISMATCH")
            self._replace(owner, state="QUIESCED", quiesced_at=_now())
            checkpoint = lifecycle.create_captain_handoff(
                mission_id=mission_id, team_id=team_id,
                old_captain_session_id=captain_session_id,
                current_node_refs=list(current_node_refs),
                latest_delivery_refs=list(latest_delivery_refs),
                latest_gate_refs=list(latest_gate_refs),
                next_workitem_ids=list(next_workitem_ids))
            row = self._latest(mission_id)
            self._replace(row, checkpoint_id=checkpoint.checkpoint_id)
            return checkpoint

    def takeover(self, *, mission_id, team_id, checkpoint_id,
                 new_captain_session_id, lifecycle, ttl_seconds=300):
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds < 1:
            raise ContractError("CAPTAIN_DISPATCH_TTL_INVALID")
        with ledger_lock(self.truth):
            old = self._latest(mission_id)
            if (old is None or old["state"] != "QUIESCED"
                    or old.get("checkpoint_id") != checkpoint_id
                    or old["team_id"] != team_id
                    or old["captain_session_id"] == new_captain_session_id):
                raise ContractError("CAPTAIN_HANDOFF_CHECKPOINT_REQUIRED")
            checkpoints = self.truth.query("rc72_captain_handoff", checkpoint_id=checkpoint_id)
            if (len(checkpoints) != 1 or checkpoints[0].get("mission_id") != mission_id
                    or checkpoints[0].get("team_id") != team_id
                    or checkpoints[0].get("old_captain_session_id") != old["captain_session_id"]):
                raise ContractError("CAPTAIN_HANDOFF_R1_MISMATCH")
            self._batch(mission_id)
            readiness = lifecycle.takeover_captain(
                checkpoint_id=checkpoint_id,
                new_captain_session_id=new_captain_session_id,
                expected_mission_id=mission_id, expected_team_id=team_id)
            if not readiness.ready:
                raise ContractError("CAPTAIN_TAKEOVER_NOT_READY")
            now = _now()
            successor = dict(lease_id="CAPF-" + uuid.uuid4().hex, release_id=self.release_id,
                             mission_id=mission_id, team_id=team_id,
                             captain_session_id=new_captain_session_id,
                             generation=old["generation"] + 1, issued_at=now,
                             expires_at=now + ttl_seconds, state="ACTIVE",
                             parent_lease_id=old["lease_id"], checkpoint_id=checkpoint_id,
                             takeover_id=readiness.takeover_id, artifact_version=1)
            # Persist the old generation fence before granting the successor.
            self._replace(old, state="SUPERSEDED", superseded_by=successor["lease_id"])
            return self._save(successor)


install_captain_dispatch_overlay()
