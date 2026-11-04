"""N9 actual, limited DSH cause-analysis candidate from a proven N8 discrepancy.

This service only executes a credential-scoped professional analyst and retains
actual DSH process/tool/raw bytes in canonical R1. The candidate is NOT a
reproduction, product defect, RCA acceptance, regression or N9 PASS.
A crash/unknown process effect never authorizes another model/tool invocation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from rc6_runtime import contracts, truth as registry
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, AgentRuntimeError
from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError
from .rc72_authority import RC72AuthorityRuntime
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash
from .rc72_n9_professional_intake import NativeN9ProfessionalIntakeService

_KIND = "rc72_n9_professional_dsh_analysis"
_EVENT = "RC72_N9_PROFESSIONAL_DSH_ANALYSIS_UPSERTED"
_STATES = {"ANALYSIS_CANDIDATE_REVIEW_REQUIRED"}
_FINDINGS = {"INCONCLUSIVE", "POSSIBLE_PRODUCT_CAUSE",
             "POSSIBLE_TEST_ORACLE_PROBLEM", "POSSIBLE_ENVIRONMENT_CAUSE"}


def install_overlay():
    def validate(payload):
        row = dict(payload)
        for field in ("analysis_id", "release_id", "source_commit", "mission_id",
                      "preparation_id", "diagnosis_id", "qualification_workitem_id",
                      "original_attempt_id", "original_gap_id", "worker_id",
                      "assignment_id", "dsh_session_id", "raw_output_ref",
                      "raw_output_sha256", "candidate_sha256", "signature"):
            contracts._require_str(row, field)
        if row.get("state") not in _STATES or row.get("purpose") != "N9_INDEPENDENT_DSH_CAUSE_ANALYSIS":
            raise contracts.DomainValidationError("N9_DSH_UNACCEPTED_RECEIPT_FORBIDDEN")
        if not isinstance(row.get("candidate"), dict) or not isinstance(row.get("tool_calls"), list):
            raise contracts.DomainValidationError("N9_DSH_PROOF_REQUIRED")
        if any(key in row for key in (
                "defect_confirmed", "product_defect", "reproduced", "rca_approved",
                "regression_pass", "n9_pass", "field_verified", "bank_final")):
            raise contracts.DomainValidationError("N9_DSH_UNPROVEN_VERDICT_FORBIDDEN")
        row["artifact_type"] = _KIND
        row["artifact_version"] = contracts._artifact_version(row)
        return row
    contracts.VALIDATORS[_KIND] = validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, "analysis_id")
    registry.IDENTITY_FIELDS[_KIND] = "analysis_id"
    registry.BUCKETS[_KIND] = "rc72_n9_professional_dsh_analyses"


class NativeN9ProfessionalDshAnalysisService:
    """Execute exactly one scoped professional DSH attempt per frozen N8 gap."""

    def __init__(self, pipeline, *, launcher, allowed_tools):
        self.intake = NativeN9ProfessionalIntakeService(pipeline)
        self.pipeline, self.truth = pipeline, pipeline.truth
        self.release_id, self.source_commit = pipeline.release_id, pipeline.source_commit
        if (not isinstance(launcher, DshHeadlessWorkerLauncher)
                or launcher.truth is not self.truth
                or launcher.release_id != self.release_id
                or not isinstance(launcher.authority, RC72AuthorityRuntime)
                or launcher.authority is pipeline.preparation.authority
                or not isinstance(allowed_tools, tuple) or not allowed_tools
                or len(set(allowed_tools)) != len(allowed_tools)
                or any(not isinstance(tool, str) or not tool.strip() or '*' in tool for tool in allowed_tools)):
            raise ContractError("N9_DSH_INDEPENDENT_SCOPED_LAUNCHER_REQUIRED")
        self.launcher, self.allowed_tools = launcher, allowed_tools
        install_overlay()

    def _one(self, kind, **filters):
        items = self.truth.query(kind, **filters)
        if len(items) != 1:
            raise ContractError("N9_DSH_R1_NOT_UNIQUE:" + kind)
        return items[0]

    @staticmethod
    def _candidate(data, calls):
        expected = {"finding", "hypotheses", "reproduction_steps", "tool_evidence_refs"}
        if not isinstance(data, dict) or set(data) != expected or data.get("finding") not in _FINDINGS:
            raise ContractError("N9_DSH_ANALYST_STRICT_CANDIDATE_REQUIRED")
        for field in ("hypotheses", "reproduction_steps", "tool_evidence_refs"):
            values = data.get(field)
            if (not isinstance(values, list) or not values
                    or len(set(values)) != len(values)
                    or any(not isinstance(v, str) or not v.strip() for v in values)):
                raise ContractError("N9_DSH_ANALYST_STRICT_CANDIDATE_REQUIRED")
        observed = {x["call_ref"] for x in calls}
        if not set(data["tool_evidence_refs"]).issubset(observed):
            raise ContractError("N9_DSH_EVIDENCE_NOT_OBSERVED")
        return data

    def _raw(self, ref, mission_id, assignment_id):
        if not isinstance(ref, str) or not ref.startswith("file://"):
            raise ContractError("N9_DSH_NATIVE_RAW_FILE_REQUIRED")
        expected = (self.launcher.state_root / "worker-evidence" /
                    mission_id / (assignment_id + ".jsonl"))
        if expected.is_symlink() or not expected.is_file():
            raise ContractError("N9_DSH_NATIVE_RAW_FILE_REQUIRED")
        # The inherited RC6 DSH launcher currently emits file:// + the
        # resolved POSIX representation. Windows has a drive-bearing URI:
        # never slice file:// then accidentally turn C:/ into /C:/.
        # Trust only the *exact* private launcher output path, not an
        # arbitrary URI supplied by a worker or a remote file authority.
        expected = expected.resolve()
        valid_refs = {"file://" + expected.as_posix(), expected.as_uri()}
        if ref not in valid_refs:
            raise ContractError("N9_DSH_NATIVE_RAW_PATH_CHANGED")
        content = expected.read_bytes()
        if not content or len(content) > 8 * 1024 * 1024:
            raise ContractError("N9_DSH_NATIVE_RAW_SIZE_INVALID")
        digest = hashlib.sha256(content).hexdigest()
        try:
            events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(content.decode("utf-8")))
        except UnicodeError:
            raise ContractError("N9_DSH_NATIVE_RAW_ENCODING_INVALID") from None
        candidate = DshHeadlessWorkerLauncher._final_json(events)
        return digest, candidate

    def _expected(self, scope, task, returned):
        if (returned.get("event_name") != "HANDOFF_RETURNED"
                or returned.get("mission_id") != task["mission_id"]
                or returned.get("scope") != "task:" + scope["qualification_workitem_id"]
                or returned.get("result") != "PASS"
                or returned.get("exit_code") != 0
                or not isinstance(returned.get("tool_calls"), list)
                or not returned["tool_calls"]):
            raise ContractError("N9_DSH_SIGNED_RUNTIME_HANDOFF_REQUIRED")
        calls = returned["tool_calls"]
        if any(call.get("tool_name") not in self.allowed_tools
               or not isinstance(call.get("call_ref"), str) for call in calls):
            raise ContractError("N9_DSH_UNAUTHORIZED_TOOL_OBSERVED")
        raw = [r for r in returned.get("evidence_refs", [])
               if isinstance(r, str) and r.startswith("file://")]
        if len(raw) != 1:
            raise ContractError("N9_DSH_NATIVE_RAW_FILE_REQUIRED")
        digest, candidate = self._raw(raw[0], task["mission_id"], returned["assignment_id"])
        self._candidate(candidate, calls)
        original_attempt_id = scope["original_attempt_id"]
        failed = self._one("rc72_n7_execution_preparation", preparation_id=scope["preparation_id"])
        if (returned.get("worker_instance_id") == failed["worker_id"]
                or returned.get("dsh_session_id") is None
                or returned.get("attempt_id") != self._attempt_id(scope["qualification_workitem_id"])
                or returned.get("worker_instance_id") != task.get("lease_owner")
                or task["state"] != "RUNNING"):
            raise ContractError("N9_DSH_FRESH_WORKER_AND_TASK_LEASE_REQUIRED")
        return dict(
            analysis_id="N9DSH-" + _hash([task["task_id"],scope["diagnosis_id"]])[:24],
            purpose="N9_INDEPENDENT_DSH_CAUSE_ANALYSIS",state="ANALYSIS_CANDIDATE_REVIEW_REQUIRED",
            release_id=self.release_id,source_commit=self.source_commit,
            mission_id=task["mission_id"],preparation_id=scope["preparation_id"],
            diagnosis_id=scope["diagnosis_id"],qualification_workitem_id=task["task_id"],
            original_attempt_id=original_attempt_id,original_gap_id=scope["gap_id"],
            worker_id=returned["worker_instance_id"],
            assignment_id=returned["assignment_id"],
            dsh_session_id=returned["dsh_session_id"],
            raw_output_ref=raw[0],raw_output_sha256=digest,
            candidate=candidate,candidate_sha256=_hash(candidate),tool_calls=calls)

    @staticmethod
    def _attempt_id(task_id):
        return "N9ANALYST-" + _hash(task_id)[:24]

    def _prompt(self, scope, task):
        context = dict(
            mission_id=task["mission_id"],workitem_id=task["task_id"],
            original_attempt_id=scope["original_attempt_id"],
            diagnosis_id=scope["diagnosis_id"],gap_id=scope["gap_id"],
            approved_case_artifact_refs=list(task["input_artifact_refs"]),
            allowed_tools=list(self.allowed_tools))
        return (
            "You are an independent N9 defect-analysis worker. Invoke at least one "
            "actually authorized tool to examine the accepted N8 discrepancy. "
            "Do not execute a product write or reproduce the original business operation. "
            "Do not claim PRODUCT_DEFECT, accepted RCA, a fixed defect, N9 PASS or BANK_FINAL. "
            "Return ONLY one strict JSON object, keys: finding "
            "(INCONCLUSIVE/POSSIBLE_PRODUCT_CAUSE/POSSIBLE_TEST_ORACLE_PROBLEM/"
            "POSSIBLE_ENVIRONMENT_CAUSE), hypotheses (nonempty strings), "
            "reproduction_steps (nonempty strings, for separately authorized future attempt), "
            "tool_evidence_refs (real DSH tool call refs). Input="
            + json.dumps(context, sort_keys=True, ensure_ascii=False))

    def _receipt(self, row):
        signed = {k:v for k,v in row.items()
                  if k not in {"signature", "artifact_type", "artifact_version"}}
        if not hmac.compare_digest(row.get("signature",""),
                                   self.pipeline.preparation.authority._sign(signed)):
            raise ContractError("N9_DSH_RECEIPT_SIGNATURE_CHANGED")
        digest, parsed = self._raw(row["raw_output_ref"],row["mission_id"],row["assignment_id"])
        if digest != row["raw_output_sha256"] or _hash(parsed) != row["candidate_sha256"]:
            raise ContractError("N9_DSH_RAW_BYTES_CHANGED")
        self._candidate(parsed,row["tool_calls"])
        return row

    def analyze(self, *, preparation_id, diagnosis_id):
        """Reserve one professional Worker first; never hold R1 lock over DSH I/O.

        Reservation and task ownership are serialized by the shared R1 ledger.
        DSH process execution is outside that lock, so other RC7.2 workers can
        make progress. Its HANDOFF event or failed/started event prevents a
        new agent from replaying an unknown model/tool side effect.
        """
        assignment = None
        prompt = None
        # This performs the independent N8/process/Oracle audit. It owns its
        # own global R1 lock internally; never nest it inside our reservation
        # lock (Windows and Linux OS locks must fail BUSY on re-entry).
        # The intake result carries the admitted WorkItem, Attempt and Gap
        # but not its original preparation_id; bind that exact audited input
        # rather than assuming an absent key in the DSH handoff.
        scope=dict(self.intake.queue_reproduction(
            preparation_id=preparation_id, diagnosis_id=diagnosis_id),
            preparation_id=preparation_id)
        with ledger_lock(self.truth, busy="N9_DSH_PROFESSIONAL_LEDGER_BUSY"):
            wid=scope["qualification_workitem_id"]
            task=self._one("rc7_task",task_id=wid)
            assignment_scope="task:" + wid
            result=dict(status="HOLD",reason="N9_CAUSAL_REVIEW_AND_REAL_REPRODUCTION_REQUIRED",
                        qualification_workitem_id=wid,diagnosis_id=diagnosis_id,
                        original_attempt_id=scope["original_attempt_id"],
                        defect_confirmed=False,reproduction_completed=False,
                        field_verified=False,bank_final=False)
            receipts=self.truth.query(_KIND,qualification_workitem_id=wid)
            if len(receipts)>1:
                raise ContractError("N9_DSH_RECEIPT_NOT_UNIQUE")
            events=self.truth.query("agent_runtime_event",mission_id=task["mission_id"],
                                    scope=assignment_scope)
            returned=[event for event in events if event.get("event_name")=="HANDOFF_RETURNED"]
            if len(returned)>1:
                raise ContractError("N9_DSH_DUPLICATE_HANDOFF_REJECTED")
            if receipts:
                if len(returned)!=1:
                    raise ContractError("N9_DSH_RECEIPT_WITHOUT_REAL_HANDOFF")
                expected=self._expected(scope,task,returned[0])
                receipt=self._receipt(receipts[0])
                if any(receipt.get(k)!=v for k,v in expected.items()):
                    raise ContractError("N9_DSH_RECEIPT_LINEAGE_CHANGED")
                return dict(result,analysis_id=receipt["analysis_id"],
                            cause_candidate_only=True)
            if not events:
                if task["state"]!="READY":
                    return dict(result,reason="N9_DSH_TASK_NOT_READY")
                assignment=self.launcher.assign(
                    agent_id="n9-independent-professional-analyst",
                    role="FAILURE_DIAGNOSTIC",phase="MISSION_NODE_EXECUTION",
                    mission_id=task["mission_id"],attempt_id=self._attempt_id(wid),
                    scope=assignment_scope,input_refs=tuple(task["input_artifact_refs"]),
                    allowed_artifact_types=(),allowed_tools=self.allowed_tools)
                control=ClosedLoopControlPlane(self.truth,self.release_id,task["mission_id"])
                leased=control.scheduler.lease_task(
                    task["mission_id"],wid,worker_ref=assignment.worker_instance_id,
                    capabilities=("defect_analysis",))
                if leased is None:
                    return dict(result,reason="N9_DSH_GOVERNED_WORKITEM_NOT_LEASABLE")
                control.scheduler.start(wid,worker_ref=assignment.worker_instance_id)
                prompt=self._prompt(scope,task)
            elif not returned:
                # An assignment/start/failure event is a durable reservation,
                # even if the process crashed before its return event.
                return dict(result,reason="N9_DSH_INTERRUPTED_NO_REPLAY")

        if assignment is not None:
            try:
                self.launcher.execute(assignment,prompt)
            except AgentRuntimeError:
                # The child may have called a tool before the process failed.
                # Keep the exact R1 task fenced, never automatically relaunch.
                return dict(result,reason="N9_DSH_UNKNOWN_PROCESS_NO_REPLAY")

        # Full provenance re-audit must also occur *outside* the
        # reservation lock, because the independent failure evidence auditor
        # itself owns that lock and never accepts nested re-entry.
        fresh_scope=dict(self.intake.queue_reproduction(
            preparation_id=preparation_id, diagnosis_id=diagnosis_id),
            preparation_id=preparation_id)
        with ledger_lock(self.truth, busy="N9_DSH_PROFESSIONAL_LEDGER_BUSY"):
            if fresh_scope!=scope:
                raise ContractError("N9_DSH_ACCEPTED_SCOPE_CHANGED_DURING_WORKER")
            task=self._one("rc7_task",task_id=wid)
            events=self.truth.query("agent_runtime_event",mission_id=task["mission_id"],
                                    scope=assignment_scope)
            returned=[event for event in events if event.get("event_name")=="HANDOFF_RETURNED"]
            if len(returned)!=1:
                if not returned:
                    return dict(result,reason="N9_DSH_INTERRUPTED_NO_REPLAY")
                raise ContractError("N9_DSH_DUPLICATE_HANDOFF_REJECTED")
            expected=self._expected(scope,task,returned[0])
            receipts=self.truth.query(_KIND,qualification_workitem_id=wid)
            if len(receipts)>1:
                raise ContractError("N9_DSH_RECEIPT_NOT_UNIQUE")
            if receipts:
                receipt=self._receipt(receipts[0])
                if any(receipt.get(k)!=v for k,v in expected.items()):
                    raise ContractError("N9_DSH_RECEIPT_LINEAGE_CHANGED")
                return dict(result,analysis_id=receipt["analysis_id"],
                            cause_candidate_only=True)
            signed=dict(expected,signature=self.pipeline.preparation.authority._sign(expected),
                        artifact_version=1)
            self.truth.append_atomic(_EVENT,signed)
            return dict(result,analysis_id=expected["analysis_id"],
                        cause_candidate_only=True)


install_overlay()
