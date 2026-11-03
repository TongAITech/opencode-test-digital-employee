"""C07 additive Captain-fenced Fresh Worker admission into the existing TaskScheduler.

This is a real scheduling boundary (not an Agent prompt). It uses the canonical
TaskScheduler, WorkerLifecycleService and R1, and does *not* mint tool authority,
spawn DSH or execute business I/O. Session A integrates it at product entry.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Mapping, Sequence

from .control_plane import TaskScheduler
from .models import ContractError, TaskStatus
from .rc72_captain_dispatch_fencing import CaptainDispatchFencer
from .rc72_ledger_lock import ledger_lock
from .rc72_worker_lifecycle import WorkerLifecycleService


class CaptainSchedulingError(ContractError):
    pass


@dataclass(frozen=True)
class GovernedFreshDispatch:
    mission_id: str
    workitem_id: str
    etu_id: str
    role: str
    worker_id: str
    session_id: str
    captain_generation: int
    captain_lease_id: str
    state: str


class CaptainFencedWorkItemScheduler:
    """Admission on a single canonical R1/OS ledger, with role-profile enforcement.

    This API creates a fresh, durable WorkerSession and leases a real rc7_task.
    TaskLease/CapabilityLease issuance and observed DSH session binding are the
    explicit *next* runtime step; a leased WorkItem is not an executed Attempt.

    Caller supplies TRUSTED role_profiles at construction time; Captain cannot
    invent capabilities at dispatch. No Captain secret is placed in Worker input.
    """

    def __init__(self, *, truth, release_id: str, fencer: CaptainDispatchFencer,
                 lifecycle: WorkerLifecycleService, scheduler: TaskScheduler,
                 role_profiles: Mapping[str, Sequence[str]]):
        if (fencer.truth is not truth or lifecycle.truth is not truth
                or scheduler.truth is not truth or fencer.release_id != release_id
                or lifecycle.release_id != release_id or scheduler.release_id != release_id):
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_CANONICAL_RUNTIME_MISMATCH")
        if not isinstance(role_profiles, Mapping) or not role_profiles:
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_ROLE_PROFILES_REQUIRED")
        validated = {}
        for role, capabilities in role_profiles.items():
            if not isinstance(role, str) or not role.strip() or not isinstance(capabilities, (list, tuple, set, frozenset)):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_ROLE_PROFILE_INVALID")
            if not capabilities or any(not isinstance(x, str) or not x.strip() for x in capabilities):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_EMPTY_ROLE_CAPABILITY")
            values = frozenset(capabilities)
            if any(x.lower() in {"*", "all", "full_access", "field_full_access", "admin"}
                   or "*" in x for x in values):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_FULL_ACCESS_FORBIDDEN")
            validated[role] = values
        self.truth, self.fencer = truth, fencer
        self.lifecycle, self.scheduler = lifecycle, scheduler
        self.release_id, self.role_profiles = release_id, validated

    def dispatch_etu(self, *, mission_id: str, team_id: str,
                     captain_session_id: str, captain_lease_id: str,
                     role: str, etu_id: str, workitem_id: str,
                     canonical_refs: Mapping[str, object]) -> GovernedFreshDispatch:
        """Claim READY WorkItem for a new worker while fenced against rival Captains.

        Under lock, a previously allocated worker session is an orphan warning,
        not a reason to create a second worker and potentially replay I/O.
        """
        with ledger_lock(self.truth):
            self.fencer._batch(mission_id)
            owner = self.fencer._owner(
                mission_id, captain_lease_id, captain_session_id,
                int(time.time()))
            if owner["team_id"] != team_id:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_TEAM_MISMATCH")
            capabilities = self.role_profiles.get(role)
            if capabilities is None:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_UNREGISTERED_ROLE")
            task_rows = self.truth.query("rc7_task", task_id=workitem_id)
            if len(task_rows) != 1 or task_rows[0].get("mission_id") != mission_id:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_WORKITEM_MISMATCH")
            row = task_rows[0]
            if row["state"] != TaskStatus.READY.value:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_WORKITEM_NOT_READY")
            task = self.scheduler._task_from_row(row)
            if not set(task.required_capabilities).issubset(capabilities):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_CAPABILITY_GAP")
            if not self.scheduler._inputs_valid(task.input_artifact_refs):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_INPUTS_NOT_VERIFIED")
            etus = self.truth.query("rc72_etu", etu_id=etu_id)
            batch = self.fencer._batch(mission_id)
            if (len(etus) != 1 or etus[0]["mission_id"] != mission_id
                    or etus[0]["release_batch_id"] != batch["release_batch_id"]):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_ETU_MISMATCH")
            existing = [s for s in self.truth.query("rc72_worker_session", mission_id=mission_id)
                        if s.get("workitem_id") == workitem_id]
            if existing:
                # CLOSED also requires a signed new Attempt/retry decision. No
                # silent restoration from a lost Session or partial dispatch.
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_PRIOR_SESSION_RECOVERY_REQUIRED")
            if not isinstance(canonical_refs, Mapping):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_CANONICAL_REFS_REQUIRED")
            # Assign first: if process crashes before Task lease the orphan
            # session blocks unattended re-admission (fail-closed).
            fresh = self.lifecycle.assign_fresh_worker(
                mission_id=mission_id, team_id=team_id, role=role,
                etu_id=etu_id, workitem_id=workitem_id,
                canonical_refs=canonical_refs)
            leased = self.scheduler.lease_task(
                mission_id, workitem_id, worker_ref=fresh.worker_id,
                capabilities=capabilities)
            if leased is None or leased.lease_owner != fresh.worker_id:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_PARTIAL_DISPATCH_RECONCILIATION_REQUIRED")
            return GovernedFreshDispatch(
                mission_id=mission_id, workitem_id=workitem_id,
                etu_id=etu_id, role=role, worker_id=fresh.worker_id,
                session_id=fresh.session_id, captain_generation=owner["generation"],
                captain_lease_id=owner["lease_id"], state="LEASED_AWAITING_SIGNED_AUTHORITY_AND_DSH")
