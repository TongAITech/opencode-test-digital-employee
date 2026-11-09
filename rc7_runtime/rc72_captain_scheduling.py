"""C07 additive Captain-fenced Fresh Worker admission into the existing TaskScheduler.

This is a real scheduling boundary (not an Agent prompt). It uses the canonical
TaskScheduler, WorkerLifecycleService and R1, and does *not* mint tool authority,
spawn DSH or execute business I/O. Session A integrates it at product entry.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
import uuid
from typing import Mapping, Sequence

from rc6_runtime import contracts, truth as registry
from .truth_overlay import install_rc7_truth_overlay
from .control_plane import TaskScheduler
from .models import ContractError, TaskStatus
from .rc72_captain_dispatch_fencing import CaptainDispatchFencer
from .rc72_agentteams_capacity import TeamCapacityPolicy
from .rc72_ledger_lock import ledger_lock
from .rc72_worker_lifecycle import WorkerLifecycleService


class CaptainSchedulingError(ContractError):
    pass


_ADMISSION_KIND = "rc72_captain_etu_admission"
_ADMISSION_EVENT = "RC72_CAPTAIN_ETU_ADMITTED"
_ADMITTED = "LEASED_AWAITING_SIGNED_AUTHORITY_AND_DSH"


def _validate_admission(payload):
    out = dict(payload)
    for key in ("admission_id", "release_id", "mission_id", "team_id",
                "captain_lease_id", "captain_session_id", "etu_id", "workitem_id",
                "role", "worker_id", "session_id", "state"):
        contracts._require_str(out, key)
    generation = out.get("captain_generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise contracts.DomainValidationError("CAPTAIN_ADMISSION_GENERATION_INVALID")
    if out["state"] != _ADMITTED:
        raise contracts.DomainValidationError("CAPTAIN_ADMISSION_CANNOT_CLAIM_EXECUTION")
    if any(key in out for key in (
            "captain_token", "signing_key", "full_access", "raw_result",
            "execution_pass", "field_verified", "bank_final")):
        raise contracts.DomainValidationError("CAPTAIN_ADMISSION_SECRET_OR_RESULT_FORBIDDEN")
    out["artifact_type"] = _ADMISSION_KIND
    out["artifact_version"] = contracts._artifact_version(out)
    return out


def install_captain_etu_admission_overlay():
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_ADMISSION_KIND] = _validate_admission
    registry.EVENT_TYPES[_ADMISSION_EVENT] = (_ADMISSION_KIND, "admission_id")
    registry.BUCKETS[_ADMISSION_KIND] = "rc72_captain_etu_admissions"
    registry.IDENTITY_FIELDS[_ADMISSION_KIND] = "admission_id"


@dataclass(frozen=True)
class GovernedFreshDispatch:
    admission_id: str
    mission_id: str
    team_id: str
    workitem_id: str
    etu_id: str
    role: str
    worker_id: str
    session_id: str
    captain_generation: int
    captain_lease_id: str
    captain_session_id: str
    state: str


@dataclass(frozen=True)
class GovernedReadyBatch:
    """R1 admitted workers and durable READY workitems left queued."""
    admitted: tuple
    queued_workitem_ids: tuple


class CaptainFencedWorkItemScheduler:
    """Admission on a single canonical R1/OS ledger, with role-profile enforcement.

    This API creates a fresh, durable WorkerSession and leases a real rc7_task.
    TaskLease/CapabilityLease issuance and observed DSH session binding are the
    explicit *next* runtime step; a leased WorkItem is not an executed Attempt.

    Caller supplies TRUSTED role_profiles at construction time; Captain cannot
    invent capabilities at dispatch. No Captain secret is placed in Worker input.
    """

    _ETU_EXECUTOR_ROLES = frozenset(
        {"test-executor", "performance-executor", "security-executor"}
        | {"L%d_EXECUTE" % level for level in range(1, 8)})

    def __init__(self, *, truth, release_id: str, fencer: CaptainDispatchFencer,
                 lifecycle: WorkerLifecycleService, scheduler: TaskScheduler,
                 role_profiles: Mapping[str, Sequence[str]],
                 capacity_policy: TeamCapacityPolicy = None):
        install_captain_etu_admission_overlay()
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
            if any(x.lower().replace("-", "_").replace(" ", "_")
                   in {"*", "all", "full_access", "field_full_access", "admin", "captain"}
                   or "*" in x for x in values):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_FULL_ACCESS_FORBIDDEN")
            validated[role] = values
        self.truth, self.fencer = truth, fencer
        self.lifecycle, self.scheduler = lifecycle, scheduler
        self.release_id, self.role_profiles = release_id, validated
        if capacity_policy is not None and type(capacity_policy) is not TeamCapacityPolicy:
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_CAPACITY_POLICY_INVALID")
        self.capacity_policy = capacity_policy if capacity_policy is not None else TeamCapacityPolicy()

    def dispatch_ready_batch(self, *, mission_id: str, team_id: str,
                             captain_session_id: str, captain_lease_id: str,
                             workitems: Sequence[Mapping]) -> GovernedReadyBatch:
        """Fair bounded admission in the canonical TaskScheduler READY order.

        This is a *real* task admission method, not a simulated Agent spawn.
        Each admission rechecks Captain fencing, source/ETU planning, TaskLease
        and active slot atomically inside dispatch_etu's ledger lock. Requests
        must be frozen and approved by the N7 planner; the Captain cannot pass
        inferred role, ETU or mutable tool permissions from model prose.
        READY tasks not admitted remain durable and can be picked up again on
        the next Mission tick after a WorkerSession is safely closed.
        """
        if (not isinstance(workitems, (list, tuple)) or not workitems
                or len(workitems) > self.capacity_policy.team_member_capacity):
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_BATCH_SIZE_INVALID")
        indexed = {}
        expected = {"workitem_id", "etu_id", "role", "canonical_refs"}
        for item in workitems:
            if (not isinstance(item, Mapping) or set(item) != expected
                    or any(not isinstance(item[key], str) or not item[key].strip()
                           for key in ("workitem_id", "etu_id", "role"))
                    or not isinstance(item["canonical_refs"], Mapping)):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_BATCH_ITEM_INVALID")
            name = item["workitem_id"]
            if name in indexed:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_BATCH_DUPLICATE_WORKITEM")
            indexed[name] = item
        ready = self.scheduler.ready_tasks(mission_id)
        order = [item.task_id for item in ready if item.task_id in indexed]
        if len(order) != len(indexed):
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_BATCH_WORKITEM_NOT_READY")
        admitted = []
        for index, workitem_id in enumerate(order):
            item = indexed[workitem_id]
            try:
                result = self.dispatch_etu(
                    mission_id=mission_id, team_id=team_id,
                    captain_session_id=captain_session_id,
                    captain_lease_id=captain_lease_id,
                    role=item["role"], etu_id=item["etu_id"],
                    workitem_id=workitem_id,
                    canonical_refs=item["canonical_refs"])
            except CaptainSchedulingError as exc:
                if str(exc) == "CAPTAIN_SCHEDULER_ACTIVE_CAPACITY_REACHED":
                    return GovernedReadyBatch(tuple(admitted), tuple(order[index:]))
                raise
            admitted.append(result)
        return GovernedReadyBatch(tuple(admitted), ())

    def _assert_active_team_capacity(self, team_id):
        """Capacity is reserved for ACTIVE R1 WorkerSessions, not roster size.

        Under the same R1 ledger lock as worker assignment, even a crashed
        pre-TaskLease session consumes capacity until governed checkpoint/
        closure. No forced reclamation, invented idle worker or task replay.
        """
        sessions = self.truth.query("rc72_worker_session")
        active = [s for s in sessions
                  if s.get("team_id") == team_id and s.get("state") == "ACTIVE"]
        if len({s.get("session_id") for s in active}) != len(active):
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_TEAM_SESSION_DUPLICATE")
        if len(active) >= self.capacity_policy.max_active_workers:
            raise CaptainSchedulingError(
                "CAPTAIN_SCHEDULER_ACTIVE_CAPACITY_REACHED")
        # This gate does not prove observed DSH model concurrency or that
        # the plugin has actually created all 32 member identities.

    def _assert_n7_planning_lineage(self, *, mission_id, batch, task, etu):
        """Enforce exact canonical N7 Case -> ETU -> WorkItem mapping.

        A matching Mission ID is *not* proof that a Case belongs to an ETU.
        N7's production planner emits authoritative items; never guess this
        relationship from a WorkItem objective or a string similarity.
        """
        if task.task_type != "RC72_CASE_EXECUTION":
            return
        # The actual N7 planning overlay may be imported after this adapter.
        from .rc72_n7_execution_planning import install_rc72_n7_execution_planning_overlay

        install_rc72_n7_execution_planning_overlay()
        plans = self.truth.query("rc72_n7_execution_plan", mission_id=mission_id)
        matches = [(plan, item) for plan in plans for item in plan.get("items", ())
                   if item.get("workitem_id") == task.task_id]
        if len(matches) != 1:
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_N7_PLAN_ITEM_NOT_UNIQUE")
        plan, item = matches[0]
        if (plan.get("release_id") != self.release_id
                or plan.get("release_batch_id") != batch["release_batch_id"]
                or plan.get("status") != "PLANNED"
                or plan.get("snapshot_id") != etu.get("planning_snapshot_ref")
                or item.get("etu_id") != etu["etu_id"]
                or item.get("case_id") not in etu.get("case_ids", ())
                or item.get("input_artifact_refs") != task.input_artifact_refs):
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_N7_CANONICAL_LINEAGE_MISMATCH")
        snapshot = self.truth.query("rc72_decomposition_snapshot",
                                    snapshot_id=plan["snapshot_id"])
        if (len(snapshot) != 1 or snapshot[0].get("mission_id") != mission_id
                or etu["etu_id"] not in snapshot[0].get("etu_ids", ())):
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_N7_SNAPSHOT_NOT_VERIFIED")

    @staticmethod
    def _single_prelease_chain(sessions):
        """Follow parent ids, never timestamp/order, and reject broken history.

        All non-terminal sessions must be checkpointed as proven pre-TaskLease
        orphans. A terminal may be ACTIVE only for explicit reconciliation;
        unattended dispatch requires the terminal to be safely CLOSED.
        """
        if not sessions:
            return None
        indexed = {row["session_id"]: row for row in sessions}
        if len(indexed) != len(sessions):
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_RECOVERY_CHAIN_NOT_UNIQUE")
        parents = {row.get("parent_session_id") for row in sessions
                   if row.get("parent_session_id")}
        terminals = [row for row in sessions if row["session_id"] not in parents]
        if len(terminals) != 1:
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_RECOVERY_CHAIN_NOT_LINEAR")
        terminal = terminals[0]
        seen = set()
        current = terminal
        while current is not None:
            identity = current["session_id"]
            if identity in seen:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_RECOVERY_CHAIN_CYCLE")
            seen.add(identity)
            if current is not terminal or current["state"] == "CLOSED":
                if (current.get("state") != "CLOSED"
                        or current.get("close_reason") != "ORPHAN_BEFORE_WORKITEM_LEASE_VERIFIED"
                        or not current.get("checkpoint_id")):
                    raise CaptainSchedulingError("CAPTAIN_SCHEDULER_RECOVERY_CHAIN_NOT_PROVEN")
            if any(current.get(key) != terminal.get(key) for key in
                   ("mission_id", "workitem_id", "etu_id", "team_id", "role")):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_RECOVERY_CHAIN_SCOPE_DRIFT")
            parent = current.get("parent_session_id")
            if parent and parent not in indexed:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_RECOVERY_CHAIN_PARENT_MISSING")
            current = indexed[parent] if parent else None
        if len(seen) != len(sessions):
            raise CaptainSchedulingError("CAPTAIN_SCHEDULER_RECOVERY_CHAIN_DISCONNECTED")
        return terminal

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
            if role not in self._ETU_EXECUTOR_ROLES:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_ROLE_CANNOT_EXECUTE_ETU")
            task_rows = self.truth.query("rc7_task", task_id=workitem_id)
            if len(task_rows) != 1 or task_rows[0].get("mission_id") != mission_id:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_WORKITEM_MISMATCH")
            row = task_rows[0]
            if row["state"] != TaskStatus.READY.value:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_WORKITEM_NOT_READY")
            task = self.scheduler._task_from_row(row)
            for dependency_id in task.dependency_task_ids:
                dependency = self.truth.query("rc7_task", task_id=dependency_id)
                if (len(dependency) != 1
                        or dependency[0].get("mission_id") != mission_id
                        or dependency[0].get("state") != TaskStatus.PASS.value):
                    raise CaptainSchedulingError("CAPTAIN_SCHEDULER_DEPENDENCY_NOT_PASS")
            if not set(task.required_capabilities).issubset(capabilities):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_CAPABILITY_GAP")
            if not self.scheduler._inputs_valid(task.input_artifact_refs):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_INPUTS_NOT_VERIFIED")
            for ref in task.input_artifact_refs:
                artifacts = self.truth.query("rc7_artifact", artifact_id=ref)
                if artifacts and (len(artifacts) != 1
                                  or artifacts[0].get("mission_id") != mission_id):
                    raise CaptainSchedulingError("CAPTAIN_SCHEDULER_INPUT_MISSION_MISMATCH")
            etus = self.truth.query("rc72_etu", etu_id=etu_id)
            batch = self.fencer._batch(mission_id)
            if (len(etus) != 1 or etus[0]["mission_id"] != mission_id
                    or etus[0]["release_batch_id"] != batch["release_batch_id"]):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_ETU_MISMATCH")
            if etus[0].get("state") in {
                    "PASS", "BLOCKED", "NEEDS_REVISION", "SPLIT_REQUIRED",
                    "MERGED", "STALE"}:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_ETU_NOT_EXECUTABLE")
            if not set(etus[0].get("required_capabilities") or ()).issubset(capabilities):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_ETU_CAPABILITY_GAP")
            if (task.task_type == "RC72_CASE_EXECUTION"
                    and role != etus[0]["test_level"] + "_EXECUTE"):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_N7_ROLE_SCOPE_MISMATCH")
            self._assert_n7_planning_lineage(
                mission_id=mission_id, batch=batch, task=task, etu=etus[0])
            existing = [s for s in self.truth.query("rc72_worker_session", mission_id=mission_id)
                        if s.get("workitem_id") == workitem_id]
            terminal = self._single_prelease_chain(existing)
            if terminal and (terminal.get("team_id") != team_id
                             or terminal.get("etu_id") != etu_id
                             or terminal.get("role") != role):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_RECOVERY_SCOPE_DRIFT")
            if terminal and terminal["state"] != "CLOSED":
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_PRIOR_SESSION_RECOVERY_REQUIRED")
            self._assert_active_team_capacity(team_id)
            if not isinstance(canonical_refs, Mapping):
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_CANONICAL_REFS_REQUIRED")
            # Assign first: if process crashes before Task lease the orphan
            # session blocks unattended re-admission (fail-closed).
            fresh = self.lifecycle.assign_fresh_worker(
                mission_id=mission_id, team_id=team_id, role=role,
                etu_id=etu_id, workitem_id=workitem_id,
                canonical_refs=canonical_refs,
                parent_session_id=terminal["session_id"] if terminal else None)
            leased = self.scheduler.lease_task(
                mission_id, workitem_id, worker_ref=fresh.worker_id,
                capabilities=capabilities)
            if leased is None or leased.lease_owner != fresh.worker_id:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_PARTIAL_DISPATCH_RECONCILIATION_REQUIRED")
            admission_id = "CAPAD-" + uuid.uuid4().hex
            self.truth.append_atomic(_ADMISSION_EVENT, dict(
                admission_id=admission_id, release_id=self.release_id,
                mission_id=mission_id, team_id=team_id,
                captain_lease_id=owner["lease_id"],
                captain_session_id=owner["captain_session_id"],
                captain_generation=owner["generation"], etu_id=etu_id,
                workitem_id=workitem_id, role=role,
                worker_id=fresh.worker_id, session_id=fresh.session_id,
                state=_ADMITTED, artifact_version=1))
            return GovernedFreshDispatch(
                admission_id=admission_id,
                mission_id=mission_id, team_id=team_id, workitem_id=workitem_id,
                etu_id=etu_id, role=role, worker_id=fresh.worker_id,
                session_id=fresh.session_id, captain_generation=owner["generation"],
                captain_lease_id=owner["lease_id"],
                captain_session_id=owner["captain_session_id"],
                state=_ADMITTED)


    @staticmethod
    def _contains_worker_identity(value, worker_id):
        """Search *raw* event payloads, even before all overlays are imported."""
        if isinstance(value, str):
            return value == worker_id
        if isinstance(value, dict):
            return any(CaptainFencedWorkItemScheduler._contains_worker_identity(
                item, worker_id) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(CaptainFencedWorkItemScheduler._contains_worker_identity(
                item, worker_id) for item in value)
        return False

    def recover_unleased_orphan(self, *, mission_id: str, team_id: str,
                                captain_session_id: str, captain_lease_id: str,
                                workitem_id: str, session_id: str):
        """Proof-bound reconciliation of admission crash *before* any Task lease.

        Only a session with no signed authority, no DSH identity, no resources,
        no Attempts and no observed external side effects can be closed by a
        Captain and safely replaced by a new Fresh Worker. UNKNOWN stays blocked.
        """
        from rc6_runtime import truth as registry

        with ledger_lock(self.truth):
            self.fencer._batch(mission_id)
            owner = self.fencer._owner(
                mission_id, captain_lease_id, captain_session_id, int(time.time()))
            if owner["team_id"] != team_id:
                raise CaptainSchedulingError("CAPTAIN_SCHEDULER_TEAM_MISMATCH")
            tasks = self.truth.query("rc7_task", task_id=workitem_id)
            if (len(tasks) != 1 or tasks[0].get("mission_id") != mission_id
                    or tasks[0].get("state") != TaskStatus.READY.value
                    or tasks[0].get("lease_owner")):
                raise CaptainSchedulingError("ORPHAN_RECOVERY_WORKITEM_ALREADY_DISPATCHED")
            sessions = [row for row in self.truth.query("rc72_worker_session", mission_id=mission_id)
                        if row.get("workitem_id") == workitem_id]
            session = self._single_prelease_chain(sessions)
            if session is None or session["session_id"] != session_id:
                raise CaptainSchedulingError("ORPHAN_RECOVERY_SESSION_NOT_UNIQUE")
            if session.get("state") != "ACTIVE" or session.get("team_id") != team_id:
                raise CaptainSchedulingError("ORPHAN_RECOVERY_SESSION_NOT_ACTIVE")
            if any(session.get(key) for key in (
                    "runtime_worker_id", "runtime_assignment_id", "task_lease_ref",
                    "runtime_attempt_id", "dsh_session_id", "binding_id")):
                raise CaptainSchedulingError("ORPHAN_RECOVERY_AUTHORITY_OR_DSH_OBSERVED")
            worker_id = session["worker_id"]
            # R1 raw history, not just currently installed projections, is the
            # authoritative fail-closed proof. A previous external invocation
            # could have written an event whose overlay was not imported in
            # this cold interpreter. Exactly ONE initial session event must
            # reference this new Worker; any additional reference is unknown
            # provenance and categorically blocks unattended re-admission.
            # A connector may record only the Session ID and omit Worker ID.
            # Both unique identities must be absent from every other event.
            references = [event for event in self.truth.store.iter_raw()
                          if (self._contains_worker_identity(event.get("payload"), worker_id)
                              or self._contains_worker_identity(event.get("payload"), session_id))]
            if (len(references) != 1
                    or references[0].get("event_type") != "RC72_WORKER_SESSION_UPSERTED"
                    or references[0].get("entity_id") != session_id
                    or references[0].get("entity_version") != 1):
                raise CaptainSchedulingError("ORPHAN_RECOVERY_R1_PROVENANCE_UNKNOWN")
            for artifact_type in (
                    "rc72_workitem_attempt_binding", "execution_attempt",
                    "rc72_data_lease", "rc72_browser_lease", "rc72_capability_lease",
                    "rc72_native_tool_call", "rc72_n7_http_call",
                    "rc72_n7_tool_dispatch", "rc72_execution_process_heartbeat",
                    "rc72_n7_formal_runner_receipt"):
                if artifact_type not in registry.BUCKETS:
                    continue
                # A matching worker in ANY state or Mission blocks automatic
                # recovery. An expired resource does not prove side-effect safety.
                if self.truth.query(artifact_type, worker_id=worker_id):
                    raise CaptainSchedulingError("ORPHAN_RECOVERY_RESOURCE_OR_EFFECT_OBSERVED")
            if "rc7_evidence" in registry.BUCKETS:
                for evidence in self.truth.query("rc7_evidence", mission_id=mission_id):
                    if (worker_id in evidence.get("subject_refs", ())
                            or evidence.get("source_ref") == worker_id):
                        raise CaptainSchedulingError("ORPHAN_RECOVERY_EVIDENCE_OBSERVED")
            checkpoint = self.lifecycle.checkpoint_and_close(
                session_id, reason="ORPHAN_BEFORE_WORKITEM_LEASE_VERIFIED")
            return checkpoint


install_captain_etu_admission_overlay()
