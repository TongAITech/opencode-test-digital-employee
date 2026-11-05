"""C07 approved DSH AgentTeams Host -> canonical R1 Captain cold re-entry.

The external *trusted* DSH Host MUST observe the real active Captain session
and issue a short-lived, host-signed receipt. A file, mission config, prompt,
or an unverified session string can never initialize or replace a Captain.

This component is read-only. It binds the exact existing R1 Captain generation
into A's native MissionFactory/N7 scheduler; it does not mint a session, lease,
Worker PASS, Field result, or DSH process. New Captain bootstrap and actual
provider-side liveness belong to the trusted AgentTeams Host.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import re
import time
from typing import Mapping, Sequence

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.control_plane import TaskScheduler
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_captain_dispatch_fencing import (
    CaptainDispatchFencer, install_captain_dispatch_overlay,
)
from rc7_runtime.rc72_captain_scheduling import CaptainFencedWorkItemScheduler
from rc7_runtime.rc72_mission_factory import MissionCaptainBinding
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService

_PURPOSE = "DSH_AGENTTEAMS_CAPTAIN_SESSION_OBSERVATION_V1"
_MAX_OBSERVATION_AGE = 30
_CLOCK_SKEW = 5


def _now():
    return int(time.time())


@dataclass(frozen=True)
class ObservedDshCaptain:
    """An approved Host observation, NOT a config-supplied session claim.

    signature is created with the *separate* Host controller authority after
    observing a real DSH session. Signatures are validated here, while the
    Host remains responsible for actual DSH provider liveness/authorization.
    """
    release_id: str
    source_commit: str
    release_batch_id: str
    mission_id: str
    team_id: str
    captain_session_id: str
    captain_lease_id: str
    captain_generation: int
    dsh_session_ref: str
    observed_at: int
    state: str
    signature: str

    def signed_fields(self):
        return dict(
            purpose=_PURPOSE,
            release_id=self.release_id,
            source_commit=self.source_commit,
            release_batch_id=self.release_batch_id,
            mission_id=self.mission_id,
            team_id=self.team_id,
            captain_session_id=self.captain_session_id,
            captain_lease_id=self.captain_lease_id,
            captain_generation=self.captain_generation,
            dsh_session_ref=self.dsh_session_ref,
            observed_at=self.observed_at,
            state=self.state,
        )


def reenter_host_captain(
    truth, *, release_id, source_commit, release_batch_id,
    observed, host_authority, role_profiles, approved_capabilities,
):
    """Return the *real* MissionFactory Captain binding for an existing lease.

    The approved Host module, not JSON capability config, provides the observed
    receipt and its isolated signer. This deliberately does not acquire a
    first lease or create a successor; explicit Host+R1 handoff runs separately.
    The formal ReleaseBatchDriver will re-assert R1 ownership at dispatch.
    """
    install_captain_dispatch_overlay()
    if not isinstance(truth, TruthRuntime):
        raise ContractError("C07_HOST_CANONICAL_R1_REQUIRED")
    if (not isinstance(release_id, str) or not release_id.strip()
            or not isinstance(source_commit, str)
            or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
            or not isinstance(release_batch_id, str)
            or not release_batch_id.strip()):
        raise ContractError("C07_HOST_RELEASE_SCOPE_REQUIRED")
    if type(observed) is not ObservedDshCaptain:
        raise ContractError("C07_HOST_SIGNED_OBSERVATION_REQUIRED")
    if type(host_authority) is not RC72AuthorityRuntime:
        raise ContractError("C07_HOST_ISOLATED_AUTHORITY_REQUIRED")
    if (not isinstance(observed.signature, str) or not observed.signature
            or not hmac.compare_digest(
                observed.signature, host_authority._sign(observed.signed_fields()))):
        raise ContractError("C07_HOST_OBSERVATION_SIGNATURE_INVALID")

    if (observed.release_id != release_id
            or observed.source_commit != source_commit
            or observed.release_batch_id != release_batch_id
            or observed.state != "ACTIVE"
            or not isinstance(observed.dsh_session_ref, str)
            or not observed.dsh_session_ref.startswith("dsh://")
            or any(not isinstance(x, str) or not x.strip() for x in (
                observed.mission_id, observed.team_id,
                observed.captain_session_id, observed.captain_lease_id
            ))):
        raise ContractError("C07_HOST_OBSERVED_SESSION_SCOPE_CHANGED")
    now = _now()
    if (type(observed.observed_at) is not int
            or observed.observed_at > now + _CLOCK_SKEW
            or now - observed.observed_at > _MAX_OBSERVATION_AGE):
        raise ContractError("C07_HOST_SESSION_OBSERVATION_STALE")
    if (type(observed.captain_generation) is not int
            or observed.captain_generation < 1):
        raise ContractError("C07_HOST_GENERATION_REQUIRED")

    batches = truth.query("rc72_release_batch", release_batch_id=release_batch_id)
    if (len(batches) != 1 or batches[0]["release_id"] != release_id
            or batches[0]["mission_id"] != observed.mission_id):
        raise ContractError("C07_HOST_BATCH_MISSION_SCOPE_MISMATCH")

    leases = truth.query("rc72_captain_dispatch_lease", mission_id=observed.mission_id)
    if not leases:
        raise ContractError("C07_HOST_EXISTING_CAPTAIN_LEASE_REQUIRED")
    # A duplicate latest generation means contested control-plane custody.
    generation = max(x["generation"] for x in leases)
    current = [x for x in leases if x["generation"] == generation]
    if len(current) != 1:
        raise ContractError("C07_HOST_CAPTAIN_GENERATION_NOT_UNIQUE")
    lease = current[0]
    if (lease["release_id"] != release_id
            or lease["mission_id"] != observed.mission_id
            or lease["team_id"] != observed.team_id
            or lease["captain_session_id"] != observed.captain_session_id
            or lease["lease_id"] != observed.captain_lease_id
            or lease["generation"] != observed.captain_generation
            or lease["state"] != "ACTIVE"
            or now >= lease["expires_at"]
            or now < lease["issued_at"]):
        # Re-entry checks are intentionally read-only even when expired. The
        # product driver performs the authoritative atomic owner check later.
        raise ContractError("C07_HOST_ACTIVE_CAPTAIN_GENERATION_REQUIRED")

    if (not isinstance(approved_capabilities, (list, tuple, set, frozenset))
            or not approved_capabilities
            or any(not isinstance(x, str) or not x.strip()
                   for x in approved_capabilities)):
        raise ContractError("C07_HOST_APPROVED_CAPABILITIES_REQUIRED")
    allowed = frozenset(approved_capabilities)
    if not isinstance(role_profiles, Mapping) or not role_profiles:
        raise ContractError("C07_HOST_EXACT_ROLE_PROFILES_REQUIRED")
    for role, caps in role_profiles.items():
        if (not isinstance(role, str) or not role.strip()
                or not isinstance(caps, (tuple, list, set, frozenset))
                or not caps or not set(caps).issubset(allowed)):
            raise ContractError("C07_HOST_ROLE_OUTSIDE_APPROVED_CAPABILITIES")
    fencer = CaptainDispatchFencer(truth, release_id=release_id)
    governed = CaptainFencedWorkItemScheduler(
        truth=truth, release_id=release_id, fencer=fencer,
        lifecycle=WorkerLifecycleService(truth, release_id=release_id),
        scheduler=TaskScheduler(truth, release_id=release_id),
        role_profiles=role_profiles,
    )
    return MissionCaptainBinding(
        governed, observed.captain_session_id,
        observed.captain_lease_id, observed.team_id)
