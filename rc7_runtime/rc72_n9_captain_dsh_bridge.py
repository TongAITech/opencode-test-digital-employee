"""C07/C04: approved Captain -> existing Fresh N9 Worker -> real DSH process.

An explicit Host-enabled professional launcher is the only positive route.
No legacy Worker allocation, no N7 business capability, no second R1 TaskLease,
no synthetic Defect/RCA/PASS. All process I/O takes place outside the R1 lock.
The first durable reservation prevents unattended replay after a crash.
"""
from __future__ import annotations

import hmac
import re
import time
import uuid

from rc6_runtime import contracts, truth as registry
from rc6_runtime.agent_runtime import (
    AgentRuntimeError, WorkerAssignment, WorkerInvocation,
)
from .models import ContractError
from .rc72_ledger_lock import ledger_lock

_KIND = "rc72_n9_captain_dsh_invocation"
_EVENT = "RC72_N9_CAPTAIN_DSH_INVOCATION_RESERVED"
_ALLOWED_READ_TOOLS = frozenset((
    "api_read_only", "read_only_diagnostic", "read_only_cat",
    "read_only_db_query", "read_only_codegraph", "read_only_log_query",
    "read_only_git_diff", "read_only_mcp_resource",
))


def install_overlay():
    def validate(payload):
        row = dict(payload)
        for field in (
            "binding_id", "release_id", "source_commit", "mission_id",
            "preparation_id", "diagnosis_id", "workitem_id", "team_id",
            "captain_lease_id", "captain_session_id", "worker_id",
            "lifecycle_session_id", "assignment_id", "runtime_lease_id",
            "runtime_lease_signature", "scope", "signature",
        ):
            contracts._require_str(row, field)
        if (row.get("purpose") != "N9_CAPTAIN_SIGNED_READONLY_DSH_INVOCATION"
                or row.get("state") != "RESERVED_NO_AUTOMATIC_REPLAY"
                or type(row.get("captain_generation")) is not int
                or row["captain_generation"] < 1
                or type(row.get("reserved_at")) is not int
                or row["reserved_at"] < 0
                or not isinstance(row.get("allowed_tools"), list)
                or not row["allowed_tools"]
                or len(set(row["allowed_tools"])) != len(row["allowed_tools"])
                or not set(row["allowed_tools"]).issubset(_ALLOWED_READ_TOOLS)
                or any(key in row for key in (
                    "defect_confirmed", "product_defect", "n9_pass", "bank_final",
                    "captain_token", "worker_secret", "signing_key"))):
            raise contracts.DomainValidationError("N9_CAPTAIN_DSH_SCOPE_OR_VERDICT_FORBIDDEN")
        row["artifact_type"] = _KIND
        row["artifact_version"] = contracts._artifact_version(row)
        return row
    contracts.VALIDATORS[_KIND] = validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, "binding_id")
    registry.IDENTITY_FIELDS[_KIND] = "binding_id"
    registry.BUCKETS[_KIND] = "rc72_n9_captain_dsh_invocations"


def _signed_fields(row):
    return {key: value for key, value in row.items()
            if key not in {"signature", "artifact_type", "artifact_version"}}


class GovernedN9DshInvocation:
    """One real DSH invocation with the *same* Captain-fenced R1 Worker ID."""

    def __init__(self, analyst):
        self.analyst = analyst
        self.pipeline = analyst.pipeline
        self.truth = analyst.truth
        self.scheduler = analyst.pipeline.captain_scheduler
        self.launcher = analyst.launcher
        install_overlay()

    def _one(self, kind, **filters):
        return self.analyst._one(kind, **filters)

    def _result(self, scope, admitted):
        return dict(
            admitted, status="HOLD",
            reason="N9_CAUSAL_REVIEW_AND_REAL_REPRODUCTION_REQUIRED",
            diagnosis_id=scope["diagnosis_id"],
            original_attempt_id=scope["original_attempt_id"],
            defect_confirmed=False, reproduction_completed=False,
            field_verified=False, bank_final=False,
        )

    def _binding(self, wid):
        rows = self.truth.query(_KIND, workitem_id=wid)
        if len(rows) > 1:
            raise ContractError("N9_CAPTAIN_DSH_DUPLICATE_BINDINGS")
        if not rows:
            return None
        row = rows[0]
        signer = self.pipeline.preparation.authority
        if not hmac.compare_digest(row["signature"], signer._sign(_signed_fields(row))):
            raise ContractError("N9_CAPTAIN_DSH_SIGNED_BINDING_CHANGED")
        return row

    def _scope(self, preparation_id, diagnosis_id):
        return dict(self.analyst.intake.queue_reproduction(
            preparation_id=preparation_id, diagnosis_id=diagnosis_id),
            preparation_id=preparation_id, diagnosis_id=diagnosis_id)

    def _validate_governance(self, scope, admitted, task):
        wid = scope["qualification_workitem_id"]
        admission = self._one("rc72_captain_etu_admission",
                              admission_id=admitted["qualification_admission_id"])
        session = self._one("rc72_worker_session",
                            session_id=admitted["session_id"])
        owner = self.scheduler.fencer._owner(
            task["mission_id"], self.pipeline.captain_lease_id,
            self.pipeline.captain_session_id, int(time.time()))
        if (owner["mission_id"] != task["mission_id"]
                or owner["team_id"] != self.pipeline.team_id
                or admission["team_id"] != owner["team_id"]
                or admission["captain_lease_id"] != owner["lease_id"]
                or admission["captain_session_id"] != owner["captain_session_id"]
                or admission["captain_generation"] != owner["generation"]
                or admission["role"] != "N9_QUALIFY"
                or admission["mission_id"] != task["mission_id"]
                or admission["workitem_id"] != wid
                or admission["worker_id"] != task["lease_owner"]
                or admission["session_id"] != session["session_id"]
                or task["node"] != "DEFECT"
                or task["task_type"] != "N9_DISCREPANCY_QUALIFICATION"
                or task["required_capabilities"] != ["defect_analysis"]
                or task["gap_refs"] != [scope["gap_id"]]
                or task["state"] not in ("LEASED", "RUNNING")
                or session["state"] != "ACTIVE"
                or session["worker_id"] != admission["worker_id"]
                or session["mission_id"] != task["mission_id"]
                or session["team_id"] != owner["team_id"]
                or session["workitem_id"] != wid
                or session["role"] != "N9_QUALIFY"
                or session["purpose"] != "EXECUTION"
                or self.scheduler.role_profiles.get("N9_QUALIFY") != frozenset(("defect_analysis",))):
            raise ContractError("N9_CAPTAIN_DSH_CANONICAL_SCOPE_CHANGED")
        batch = self._one("rc72_release_batch", mission_id=task["mission_id"])
        if (session["release_batch_id"] != batch["release_batch_id"]
                or batch["release_id"] != self.pipeline.release_id):
            raise ContractError("N9_CAPTAIN_DSH_BATCH_CHANGED")
        return owner, admission, session

    def _validate_returned(self, scope, task, returned, binding, admission, session):
        if (returned.get("worker_instance_id") != binding["worker_id"]
                or returned.get("worker_instance_id") != admission["worker_id"]
                or returned.get("assignment_id") != binding["assignment_id"]
                or returned.get("lease_id") != binding["runtime_lease_id"]
                or returned.get("scope") != binding["scope"]
                or returned.get("attempt_id") != self.analyst._attempt_id(task["task_id"])
                or returned.get("dsh_session_id") in (
                    None, session["session_id"], self.pipeline.captain_session_id)
                or binding["lifecycle_session_id"] != session["session_id"]
                or binding["captain_lease_id"] != admission["captain_lease_id"]
                or binding["captain_generation"] != admission["captain_generation"]
                or binding["captain_session_id"] != admission["captain_session_id"]
                or binding["team_id"] != admission["team_id"]
                or binding["preparation_id"] != scope["preparation_id"]
                or binding["diagnosis_id"] != scope["diagnosis_id"]
                or binding["source_commit"] != self.pipeline.source_commit
                or binding["allowed_tools"] != sorted(self.analyst.allowed_tools)):
            raise ContractError("N9_CAPTAIN_DSH_HANDOFF_NOT_OWNED_BY_CAPTAIN")
        return self.analyst._expected(scope, task, returned)

    def analyze(self, *, preparation_id, diagnosis_id, admitted):
        if (not self.analyst.allowed_tools
                or not set(self.analyst.allowed_tools).issubset(_ALLOWED_READ_TOOLS)):
            raise ContractError("N9_CAPTAIN_DSH_READONLY_TOOLS_REQUIRED")
        scope = self._scope(preparation_id, diagnosis_id)
        wid = scope["qualification_workitem_id"]
        if (admitted.get("qualification_workitem_id") != wid
                or admitted.get("worker_id") is None
                or admitted.get("session_id") is None):
            raise ContractError("N9_CAPTAIN_DSH_QUALIFICATION_ADMISSION_CHANGED")
        result = self._result(scope, admitted)
        assignment = None
        # No nested N8 evidence audit or external subprocess while holding R1 lock.
        with ledger_lock(self.truth, busy="N9_CAPTAIN_DSH_LEDGER_BUSY"):
            task = self._one("rc7_task", task_id=wid)
            owner, admission, session = self._validate_governance(scope, admitted, task)
            binding = self._binding(wid)
            events = self.truth.query("agent_runtime_event",
                                      mission_id=task["mission_id"], scope="task:" + wid)
            returned = [x for x in events if x.get("event_name") == "HANDOFF_RETURNED"]
            if len(returned) > 1:
                raise ContractError("N9_CAPTAIN_DSH_MULTIPLE_HANDOFFS")
            if not binding and events:
                raise ContractError("N9_CAPTAIN_DSH_UNBOUND_RUNTIME_EVENTS")
            if binding and (binding["worker_id"] != admission["worker_id"]
                            or binding["lifecycle_session_id"] != session["session_id"]):
                raise ContractError("N9_CAPTAIN_DSH_BINDING_SCOPE_CHANGED")
            if binding and not returned:
                return dict(result, reason="N9_DSH_INTERRUPTED_NO_REPLAY")
            if not binding:
                if task["state"] != "LEASED":
                    raise ContractError("N9_CAPTAIN_DSH_TASK_NOT_LEASED")
                # A real DSH process may run only while its Captain lease will
                # still be valid at the entire configured process timeout.
                remaining = owner["expires_at"] - int(time.time())
                if remaining <= self.launcher.timeout_seconds + 5:
                    return dict(result, reason="N9_CAPTAIN_DSH_CAPTAIN_TTL_INSUFFICIENT")
                identity = self.launcher.authority.adopt_identity(
                    worker_id=admission["worker_id"], role="N9_QUALIFY",
                    phase="MISSION_NODE_EXECUTION", layer=None,
                    generation=owner["generation"], session_id=session["session_id"])
                lease = self.launcher.authority.issue_lease(
                    identity.worker_id, "task:" + wid, (), self.analyst.allowed_tools,
                    ttl_seconds=min(remaining - 1, self.launcher.timeout_seconds + 30))
                assignment = WorkerAssignment(
                    identity=identity, lease=lease,
                    worker_instance_id=identity.worker_id,
                    agent_id="n9-captain-governed-independent-analyst",
                    mission_id=task["mission_id"],
                    attempt_id=self.analyst._attempt_id(wid),
                    assignment_id="assign-" + uuid.uuid4().hex,
                    parent_worker_id=self.launcher.coordinator_instance_id,
                    scope="task:" + wid,
                    input_refs=tuple(task["input_artifact_refs"]),
                    allowed_artifact_types=(),
                    allowed_tools=tuple(self.analyst.allowed_tools))
                row = dict(
                    binding_id="CAPN9DSH-" + uuid.uuid4().hex,
                    purpose="N9_CAPTAIN_SIGNED_READONLY_DSH_INVOCATION",
                    state="RESERVED_NO_AUTOMATIC_REPLAY",
                    release_id=self.pipeline.release_id,
                    source_commit=self.pipeline.source_commit,
                    mission_id=task["mission_id"],
                    preparation_id=preparation_id,
                    diagnosis_id=diagnosis_id, workitem_id=wid,
                    team_id=owner["team_id"],
                    captain_lease_id=owner["lease_id"],
                    captain_session_id=owner["captain_session_id"],
                    captain_generation=owner["generation"],
                    worker_id=identity.worker_id,
                    lifecycle_session_id=session["session_id"],
                    assignment_id=assignment.assignment_id,
                    runtime_lease_id=lease.lease_id,
                    runtime_lease_signature=lease.signature,
                    scope=assignment.scope,
                    allowed_tools=sorted(self.analyst.allowed_tools),
                    reserved_at=int(time.time()))
                self.truth.append_atomic(_EVENT, dict(
                    row, signature=self.pipeline.preparation.authority._sign(row),
                    artifact_version=1))
                # Durable reservation is written BEFORE any possible process I/O.
                # Crash between here and runtime start is conservatively NO REPLAY.
                pending = WorkerInvocation(
                    worker_instance_id=assignment.worker_instance_id,
                    agent_id=assignment.agent_id,
                    mission_id=assignment.mission_id,
                    attempt_id=assignment.attempt_id,
                    assignment_id=assignment.assignment_id,
                    lease_id=assignment.lease.lease_id,
                    parent_worker_id=assignment.parent_worker_id,
                    scope=assignment.scope, input_refs=list(assignment.input_refs))
                self.launcher._emit("WORKER_ASSIGN_REQUESTED", pending)
                self.launcher._emit("WORKER_ADMITTED", pending)
                self.scheduler.scheduler.start(wid, worker_ref=identity.worker_id)
            elif returned:
                # A completed, original signed handoff can be reconciled after
                # a cold restart, but never trigger a second DSH process.
                pass

        if assignment is not None:
            try:
                self.launcher.execute(assignment, self.analyst._prompt(scope, task))
            except AgentRuntimeError:
                return dict(result, reason="N9_DSH_UNKNOWN_PROCESS_NO_REPLAY")
        # Revalidate the frozen N8 claim without the global lock.
        fresh_scope = self._scope(preparation_id, diagnosis_id)
        with ledger_lock(self.truth, busy="N9_CAPTAIN_DSH_LEDGER_BUSY"):
            if fresh_scope != scope:
                raise ContractError("N9_CAPTAIN_DSH_PROVENANCE_CHANGED_DURING_WORKER")
            task = self._one("rc7_task", task_id=wid)
            owner, admission, session = self._validate_governance(scope, admitted, task)
            binding = self._binding(wid)
            events = self.truth.query("agent_runtime_event",
                                      mission_id=task["mission_id"], scope="task:" + wid)
            returned = [x for x in events if x.get("event_name") == "HANDOFF_RETURNED"]
            if len(returned) != 1:
                if not returned:
                    return dict(result, reason="N9_DSH_INTERRUPTED_NO_REPLAY")
                raise ContractError("N9_CAPTAIN_DSH_MULTIPLE_HANDOFFS")
            expected = self._validate_returned(
                scope, task, returned[0], binding, admission, session)
            from .rc72_n9_professional_dsh import _KIND as ANALYSIS_KIND, _EVENT as ANALYSIS_EVENT
            receipts = self.truth.query(ANALYSIS_KIND, qualification_workitem_id=wid)
            if len(receipts) > 1:
                raise ContractError("N9_CAPTAIN_DSH_MULTIPLE_ANALYSES")
            if receipts:
                verified = self.analyst._receipt(receipts[0])
                if any(verified.get(key) != value for key, value in expected.items()):
                    raise ContractError("N9_CAPTAIN_DSH_SIGNED_ANALYSIS_CHANGED")
                return dict(result, analysis_id=verified["analysis_id"],
                            cause_candidate_only=True)
            signed = dict(expected, signature=self.pipeline.preparation.authority._sign(expected),
                          artifact_version=1)
            self.truth.append_atomic(ANALYSIS_EVENT, signed)
            # Lifecycle observation is produced only after the actual DSH
            # handoff + strict tool/raw-bytes verification, not at reservation.
            self.scheduler.lifecycle._update_session(
                session, runtime_worker_id=binding["worker_id"],
                runtime_assignment_id=binding["assignment_id"],
                runtime_attempt_id=self.analyst._attempt_id(wid),
                task_lease_ref=binding["runtime_lease_id"],
                dsh_session_id=returned[0]["dsh_session_id"])
            return dict(result, analysis_id=expected["analysis_id"],
                        cause_candidate_only=True)


install_overlay()
