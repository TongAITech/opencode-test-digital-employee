"""C07/C04: Captain-fenced real DSH WorkerInvocation for N9 cause candidates.

A Captain-owned N9 task already has a fresh R1 WorkerSession and Task lease.
The inherited DSH launcher.assign() would create a *different* worker and an
unfenced second lease, so it must not be used. This bridge adopts that exact
lifecycle worker into a tool-limited, signed runtime TaskLease and dispatches
one actual DSH process with durable intent. An unknown side effect is never
replayed after restart. The resulting candidate is NOT a product-defect verdict,
a reproduction, a fixed defect, an N9 Gate or a bank PASS.
"""
from __future__ import annotations

from dataclasses import asdict
import hmac
import time
import uuid

from rc6_runtime import contracts, truth as registry
from rc6_runtime.authority import AuthorityError, TaskLease, WorkerIdentity
from rc6_runtime.agent_runtime import (
    AgentRuntimeError, DshHeadlessWorkerLauncher, WorkerAssignment, WorkerInvocation,
)
from .models import ContractError
from .rc72_authority import RC72AuthorityRuntime
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash

_KIND = "rc72_n9_captain_worker_invocation"
_EVENT = "RC72_N9_CAPTAIN_WORKER_INVOCATION_ADMITTED"
_READONLY_TOOLS = frozenset({
    "api_read_only", "read_only_diagnostic", "read_only_cat",
    "read_only_db_query", "read_only_codegraph", "read_only_log_query",
    "read_only_git_diff", "read_only_mcp_resource",
})


def _now():
    return int(time.time())


def install_overlay():
    def validate(payload):
        row = dict(payload)
        for field in (
            "invocation_id", "release_id", "mission_id", "team_id",
            "captain_lease_id", "captain_session_id", "admission_id",
            "workitem_id", "worker_id", "session_id", "attempt_id",
            "assignment_id", "scope", "state", "signature",
        ):
            contracts._require_str(row, field)
        if row["state"] != "SIGNED_DSH_INTENT_NO_REPLAY":
            raise contracts.DomainValidationError("N9_CAPTAIN_INVOCATION_UNVERIFIED_RESULT")
        if not isinstance(row.get("captain_generation"), int) or isinstance(
                row.get("captain_generation"), bool) or row["captain_generation"] < 1:
            raise contracts.DomainValidationError("N9_CAPTAIN_INVOCATION_GENERATION_INVALID")
        if not isinstance(row.get("identity"), dict) or not isinstance(row.get("lease"), dict):
            raise contracts.DomainValidationError("N9_CAPTAIN_SIGNED_TASK_LEASE_REQUIRED")
        if any(k in row for k in (
            "product_defect", "reproduced", "execution_pass", "n9_pass",
            "field_verified", "bank_final", "captain_token", "signing_key",
        )):
            raise contracts.DomainValidationError("N9_CAPTAIN_PREMATURE_VERDICT_OR_SECRET")
        row["artifact_type"] = _KIND
        row["artifact_version"] = contracts._artifact_version(row)
        return row
    contracts.VALIDATORS[_KIND] = validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, "invocation_id")
    registry.IDENTITY_FIELDS[_KIND] = "invocation_id"
    registry.BUCKETS[_KIND] = "rc72_n9_captain_worker_invocations"


class NativeN9CaptainSignedDshBridge:
    """Opt-in, native Host-owned execution of an already admitted N9 WorkItem."""

    def __init__(self, service):
        self.service = service
        self.pipeline = service.pipeline
        self.truth = service.truth
        self.launcher = service.launcher
        self.scheduler = self.pipeline.captain_scheduler
        if (self.scheduler is None or self.scheduler.truth is not self.truth
                or self.launcher.truth is not self.truth
                or type(self.launcher.authority) is not RC72AuthorityRuntime
                or self.scheduler.role_profiles.get("N9_QUALIFY") != frozenset(("defect_analysis",))
                or not set(service.allowed_tools).issubset(_READONLY_TOOLS)):
            raise ContractError("N9_CAPTAIN_SIGNED_READONLY_DSH_HOST_REQUIRED")
        install_overlay()

    def _one(self, kind, **filters):
        return self.service._one(kind, **filters)

    def _owner_locked(self, mission_id):
        row = self.scheduler.fencer._owner(
            mission_id, self.pipeline.captain_lease_id,
            self.pipeline.captain_session_id, _now())
        if row["team_id"] != self.pipeline.team_id:
            raise ContractError("N9_CAPTAIN_DSH_TEAM_NOT_OWNER")
        return row

    def _signed_intent(self, intent):
        body = {k: v for k, v in intent.items()
                if k not in ("signature", "artifact_type")}
        if not hmac.compare_digest(
                intent.get("signature", ""), self.launcher.authority._sign(body)):
            raise ContractError("N9_CAPTAIN_DSH_INTENT_SIGNATURE_CHANGED")
        return intent

    def _verify_intent(self, intent, admission, task, owner):
        self._signed_intent(intent)
        if (intent["mission_id"] != task["mission_id"]
                or intent["workitem_id"] != task["task_id"]
                or intent["worker_id"] != task["lease_owner"]
                or intent["worker_id"] != admission["worker_id"]
                or intent["session_id"] != admission["session_id"]
                or intent["team_id"] != admission["team_id"]
                or intent["admission_id"] != admission["admission_id"]
                or intent["captain_lease_id"] != owner["lease_id"]
                or intent["captain_session_id"] != owner["captain_session_id"]
                or intent["captain_generation"] != owner["generation"]
                or intent["scope"] != "task:" + task["task_id"]
                or intent["attempt_id"] != self.service._attempt_id(task["task_id"])
                or intent["state"] != "SIGNED_DSH_INTENT_NO_REPLAY"):
            raise ContractError("N9_CAPTAIN_DSH_INTENT_R1_SCOPE_CHANGED")
        identity = intent["identity"]
        lease = intent["lease"]
        if (identity.get("worker_id") != admission["worker_id"]
                or identity.get("session_id") != admission["session_id"]
                or identity.get("role") != "N9_QUALIFY"
                or identity.get("generation") != owner["generation"]
                or lease.get("worker_id") != admission["worker_id"]
                or lease.get("lease_id") != intent.get("lease_id")
                or lease.get("scope_ref") != intent["scope"]
                or set(lease.get("allowed_tools", ())) != set(self.service.allowed_tools)
                or lease.get("allowed_artifact_types")
                or not lease.get("signature")):
            raise ContractError("N9_CAPTAIN_DSH_SIGNED_LEASE_SCOPE_CHANGED")
        # Independently authenticate the embedded TaskLease's HMAC, not
        # merely the surrounding R1 dispatch-intent signature. Historical
        # authentication is allowed after expiry but cannot restore runtime
        # authority or grant another process invocation.
        try:
            self.launcher.authority.validate_historical_lease(
                WorkerIdentity(**identity), TaskLease(**lease))
        except (AuthorityError, TypeError, ValueError):
            raise ContractError("N9_CAPTAIN_DSH_SIGNED_LEASE_SIGNATURE_INVALID") from None
        return intent

    def _result(self, scope):
        return dict(status="HOLD",
            reason="N9_CAUSAL_REVIEW_AND_REAL_REPRODUCTION_REQUIRED",
            qualification_workitem_id=scope["qualification_workitem_id"],
            diagnosis_id=scope["diagnosis_id"],
            original_attempt_id=scope["original_attempt_id"],
            defect_confirmed=False, reproduction_completed=False,
            field_verified=False, bank_final=False)

    def _returned(self, scope, task, intent, events):
        returned = [e for e in events if e.get("event_name") == "HANDOFF_RETURNED"]
        if len(returned) > 1:
            raise ContractError("N9_CAPTAIN_DSH_DUPLICATE_HANDOFF")
        if not returned:
            return None
        event = returned[0]
        if (event.get("assignment_id") != intent["assignment_id"]
                or event.get("lease_id") != intent["lease_id"]
                or event.get("worker_instance_id") != intent["worker_id"]
                or event.get("parent_worker_id") != intent["captain_session_id"]
                or event.get("attempt_id") != intent["attempt_id"]):
            raise ContractError("N9_CAPTAIN_DSH_HANDOFF_NOT_SIGNED_WORKER")
        # Fresh DSH session must not belong to an unrelated earlier worker,
        # including an old process after the Python controller restarted.
        if any(e.get("dsh_session_id") == event.get("dsh_session_id")
               and e.get("assignment_id") != event.get("assignment_id")
               for e in self.truth.query("agent_runtime_event", mission_id=task["mission_id"])
               if e.get("event_name") == "HANDOFF_RETURNED"):
            raise ContractError("N9_CAPTAIN_DSH_SESSION_REUSED")
        return self.service._expected(scope, task, event)

    def analyze(self, *, preparation_id, diagnosis_id, admitted):
        p = self._one("rc72_n7_execution_preparation", preparation_id=preparation_id)
        wid = admitted["qualification_workitem_id"]
        task = self._one("rc7_task", task_id=wid)
        if (task["mission_id"] != p["mission_id"]
                or task["node"] != "DEFECT"
                or task["task_type"] != "N9_DISCREPANCY_QUALIFICATION"
                or task["required_capabilities"] != ["defect_analysis"]
                or len(task["gap_refs"]) != 1):
            raise ContractError("N9_CAPTAIN_DSH_NOT_PROFESSIONAL_WORKITEM")
        scope = dict(
            qualification_workitem_id=wid, preparation_id=preparation_id,
            diagnosis_id=diagnosis_id, original_attempt_id=p["attempt_id"],
            gap_id=task["gap_refs"][0])
        result = self._result(scope)
        assignment = None
        prompt = None

        with ledger_lock(self.truth, busy="N9_CAPTAIN_DSH_LEDGER_BUSY"):
            owner = self._owner_locked(p["mission_id"])
            admission = self._one("rc72_captain_etu_admission",
                                  admission_id=admitted["qualification_admission_id"])
            session = self._one("rc72_worker_session", session_id=admission["session_id"])
            if (admission["workitem_id"] != wid
                    or admission["captain_lease_id"] != owner["lease_id"]
                    or admission["captain_generation"] != owner["generation"]
                    or admission["worker_id"] != admitted["worker_id"]
                    or admission["session_id"] != admitted["session_id"]
                    or session["worker_id"] != task["lease_owner"]
                    or session["workitem_id"] != wid
                    or session["state"] != "ACTIVE"
                    or session["role"] != "N9_QUALIFY"):
                raise ContractError("N9_CAPTAIN_DSH_ADMISSION_SESSION_CHANGED")
            intents = self.truth.query(_KIND, workitem_id=wid)
            if len(intents) > 1:
                raise ContractError("N9_CAPTAIN_DSH_DUPLICATE_SIGNED_INTENT")
            events = self.truth.query("agent_runtime_event", mission_id=task["mission_id"],
                                      scope="task:" + wid)
            if intents:
                intent = self._verify_intent(intents[0], admission, task, owner)
                expected = self._returned(scope, task, intent, events)
                if expected is None:
                    return dict(result, reason="N9_DSH_INTERRUPTED_NO_REPLAY")
                receipts = self.truth.query("rc72_n9_professional_dsh_analysis",
                                            qualification_workitem_id=wid)
                if len(receipts) > 1:
                    raise ContractError("N9_CAPTAIN_DSH_DUPLICATE_ANALYSIS_RECEIPT")
                if not receipts:
                    # A process can return its signed HANDOFF and persist raw
                    # tool bytes, then crash before N9 candidate certification.
                    # Recover by *reading and authenticating existing R1 only*;
                    # never invoke the same DSH worker/tool a second time.
                    if (session.get("runtime_worker_id") != intent["worker_id"]
                            or session.get("runtime_assignment_id") != intent["assignment_id"]
                            or session.get("task_lease_ref") != intent["lease_id"]
                            or session.get("dsh_session_id") not in
                               (None, [e for e in events if
                                e.get("event_name") == "HANDOFF_RETURNED"][0]["dsh_session_id"])):
                        raise ContractError("N9_CAPTAIN_DSH_RECOVERY_SESSION_CHANGED")
                    self.truth.append_atomic(
                        "RC72_N9_PROFESSIONAL_DSH_ANALYSIS_UPSERTED",
                        dict(expected,
                             signature=self.pipeline.preparation.authority._sign(expected),
                             artifact_version=1))
                    if session.get("dsh_session_id") is None:
                        returned = [e for e in events
                                    if e.get("event_name") == "HANDOFF_RETURNED"][0]
                        self.scheduler.lifecycle._update_session(
                            session, dsh_session_id=returned["dsh_session_id"])
                    return dict(result, analysis_id=expected["analysis_id"],
                                cause_candidate_only=True)
                receipt = self.service._receipt(receipts[0])
                if any(receipt.get(k) != v for k,v in expected.items()):
                    raise ContractError("N9_CAPTAIN_DSH_RECEIPT_LINEAGE_CHANGED")
                return dict(result, analysis_id=receipt["analysis_id"],
                            cause_candidate_only=True)
            if events or task["state"] != "LEASED":
                return dict(result, reason="N9_DSH_INTERRUPTED_NO_REPLAY")
            if (session.get("runtime_worker_id") or session.get("runtime_assignment_id")
                    or session.get("dsh_session_id") or session.get("task_lease_ref")):
                raise ContractError("N9_CAPTAIN_DSH_ORPHAN_RUNTIME_BINDING")

            # An already-expiring Captain cannot authorize a longer DSH
            # subprocess. Require a genuine Host heartbeat before reserving
            # a Worker or any external tool effect; fail closed without R1 IO.
            remaining = owner["expires_at"] - _now()
            if remaining <= self.launcher.timeout_seconds + 5:
                return dict(result, reason="N9_CAPTAIN_DSH_CAPTAIN_TTL_INSUFFICIENT")
            identity = self.launcher.authority.adopt_identity(
                worker_id=admission["worker_id"], role="N9_QUALIFY",
                phase="MISSION_NODE_EXECUTION", layer=None,
                generation=owner["generation"], session_id=session["session_id"])
            scope_ref = "task:" + wid
            lease = self.launcher.authority.issue_lease(
                identity.worker_id, scope_ref, (), self.service.allowed_tools,
                ttl_seconds=min(self.launcher.timeout_seconds + 30, remaining - 1))
            assignment_id = "N9CAPASSIGN-" + uuid.uuid4().hex
            attempt_id = self.service._attempt_id(wid)
            invocation_id = "N9CAPINV-" + _hash([wid, diagnosis_id])[:24]
            intent = dict(
                invocation_id=invocation_id, artifact_version=1,
                release_id=self.pipeline.release_id,
                mission_id=task["mission_id"], team_id=owner["team_id"],
                captain_lease_id=owner["lease_id"],
                captain_session_id=owner["captain_session_id"],
                captain_generation=owner["generation"],
                admission_id=admission["admission_id"], workitem_id=wid,
                worker_id=identity.worker_id, session_id=session["session_id"],
                attempt_id=attempt_id, assignment_id=assignment_id,
                lease_id=lease.lease_id, scope=scope_ref,
                identity=asdict(identity), lease=asdict(lease),
                state="SIGNED_DSH_INTENT_NO_REPLAY")
            self.truth.append_atomic(_EVENT, dict(
                intent, signature=self.launcher.authority._sign(intent)))
            # No *new* N9 worker or Task lease is allocated here. The original
            # Captain Session -> WorkItem -> ToolLease is preserved in R1.
            assignment = WorkerAssignment(
                identity=identity, lease=lease,
                worker_instance_id=identity.worker_id,
                agent_id="n9-captain-independent-diagnostic",
                mission_id=task["mission_id"], attempt_id=attempt_id,
                assignment_id=assignment_id,
                parent_worker_id=owner["captain_session_id"],
                scope=scope_ref, input_refs=tuple(task["input_artifact_refs"]),
                allowed_artifact_types=(), allowed_tools=self.service.allowed_tools)
            pending = WorkerInvocation(
                worker_instance_id=identity.worker_id,
                agent_id=assignment.agent_id, mission_id=task["mission_id"],
                attempt_id=attempt_id, assignment_id=assignment_id,
                lease_id="PENDING",
                parent_worker_id=owner["captain_session_id"],
                scope=scope_ref, input_refs=list(assignment.input_refs))
            self.launcher._emit("WORKER_ASSIGN_REQUESTED", pending)
            pending.lease_id = lease.lease_id
            self.launcher._emit("WORKER_ADMITTED", pending)
            self.scheduler.scheduler.start(wid, worker_ref=identity.worker_id)
            self.scheduler.lifecycle._update_session(
                session, runtime_worker_id=identity.worker_id,
                runtime_assignment_id=assignment_id, task_lease_ref=lease.lease_id,
                runtime_attempt_id=attempt_id)
            prompt = self.service._prompt(scope, task)

        try:
            self.launcher.execute(assignment, prompt)
        except AgentRuntimeError:
            # Crash may have followed a real tool call. Hold for manual
            # reconciliation; never dispatch a second DSH process.
            return dict(result, reason="N9_DSH_UNKNOWN_PROCESS_NO_REPLAY")

        # Re-audit the original signed N7/N8 evidence *outside* the ledger
        # lock (the intake holds that OS lock itself, non-reentrant on Windows).
        qualified = self.service.intake.queue_reproduction(
            preparation_id=preparation_id, diagnosis_id=diagnosis_id)
        if (qualified.get("qualification_workitem_id") != wid
                or qualified.get("gap_id") != scope["gap_id"]
                or qualified.get("original_attempt_id") != scope["original_attempt_id"]):
            raise ContractError("N9_CAPTAIN_DSH_ACCEPTED_SCOPE_CHANGED")

        with ledger_lock(self.truth, busy="N9_CAPTAIN_DSH_LEDGER_BUSY"):
            owner = self._owner_locked(p["mission_id"])
            task = self._one("rc7_task", task_id=wid)
            admission = self._one("rc72_captain_etu_admission",
                                  admission_id=admitted["qualification_admission_id"])
            intent = self._verify_intent(
                self._one(_KIND, workitem_id=wid), admission, task, owner)
            events = self.truth.query("agent_runtime_event", mission_id=task["mission_id"],
                                      scope="task:" + wid)
            expected = self._returned(scope, task, intent, events)
            if expected is None:
                return dict(result, reason="N9_DSH_INTERRUPTED_NO_REPLAY")
            receipts = self.truth.query("rc72_n9_professional_dsh_analysis",
                                        qualification_workitem_id=wid)
            if receipts:
                if len(receipts) != 1:
                    raise ContractError("N9_CAPTAIN_DSH_DUPLICATE_ANALYSIS_RECEIPT")
                receipt = self.service._receipt(receipts[0])
                if any(receipt.get(k) != v for k,v in expected.items()):
                    raise ContractError("N9_CAPTAIN_DSH_RECEIPT_LINEAGE_CHANGED")
            else:
                self.truth.append_atomic(
                    "RC72_N9_PROFESSIONAL_DSH_ANALYSIS_UPSERTED",
                    dict(expected,
                         signature=self.pipeline.preparation.authority._sign(expected),
                         artifact_version=1))
            session = self._one("rc72_worker_session", session_id=admission["session_id"])
            if (session["runtime_worker_id"] != intent["worker_id"]
                    or session["runtime_assignment_id"] != intent["assignment_id"]
                    or session["task_lease_ref"] != intent["lease_id"]):
                raise ContractError("N9_CAPTAIN_DSH_RUNTIME_SESSION_CHANGED")
            if session.get("dsh_session_id") not in (None, events[-1].get("dsh_session_id")):
                raise ContractError("N9_CAPTAIN_DSH_SESSION_ALREADY_BOUND")
            signed_handoff = [e for e in events if e.get("event_name") == "HANDOFF_RETURNED"][0]
            self.scheduler.lifecycle._update_session(
                session, dsh_session_id=signed_handoff["dsh_session_id"])
            return dict(result, analysis_id=expected["analysis_id"],
                        cause_candidate_only=True)


install_overlay()
