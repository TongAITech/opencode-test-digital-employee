"""C04 approved actual reproduction: new canonical WorkItem/Worker/Attempt and evidence.

The original N8 VALID_TEST_FAILURE is a discrepancy, NOT a PRODUCT_DEFECT.
Only a verified, fresh bank HumanGate for the exact signed N9 request admits
one new real RC7 execution. The inherited subprocess/Oracle/evidence runner
does the work. An R1 intent is durable BEFORE scheduling/business I/O; cold
reentry must audit, never launch the operation twice. Reproduced != RCA/Defect.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path

from rc6_runtime import contracts, truth as registry
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.preparation import PreparedAttempt
from .authority import RC7AuthorityRuntime
from .closed_loop_control import ClosedLoopControlPlane
from .defect_reproduction import DefectReproductionExecutionService
from .models import ContractError, Task, TaskStatus
from .rc72_ledger_lock import ledger_lock
from .rc72_canonical_design import CanonicalDesignService
from .rc72_n6_completion import _digest as n6_contract_digest
from .rc72_n7_execution_admission import _hash
from .rc72_n9_reproduction_human_gate import N9ReproductionHumanGateService
from .runtime_execution import VerifiedScriptExecutionBundle

_KIND = "rc72_n9_approved_reproduction_execution"
_EVENT = "RC72_N9_APPROVED_REPRODUCTION_EXECUTION_UPSERTED"
_PURPOSE = "C04_INDEPENDENT_APPROVED_ACTUAL_REPRODUCTION"
_STATES = {"IN_FLIGHT_NO_REPLAY", "EXECUTED_WITH_DURABLE_EVIDENCE"}
_CONTROL_KEYS = ("record_id", "request_id", "human_decision_id",
                 "release_id", "source_commit", "release_batch_id", "mission_id",
                 "original_attempt_id", "original_case_id", "original_contract_id",
                 "original_gap_id", "reproduction_workitem_id",
                 "reproduction_attempt_id", "contract_sha256",
                 "oracle_sha256", "script_sha256")


def _unsigned(row):
    return {k: v for k, v in row.items()
            if k not in ("signature", "artifact_type", "artifact_version")}


def install_overlay():
    def validate(payload):
        row = dict(payload)
        for key in _CONTROL_KEYS + ("signature",):
            contracts._require_str(row, key)
        if (row.get("purpose") != _PURPOSE or row.get("state") not in _STATES
                or not isinstance(row.get("approved_at"), int)
                or row.get("reproduction_attempt_id") == row.get("original_attempt_id")
                or any(k in row for k in (
                    "product_defect", "rca_approved", "fix_verified",
                    "regression_pass", "n9_pass", "bank_final", "field_verified"))):
            raise contracts.DomainValidationError("N9_REPRO_EXECUTION_PREMATURE_CLAIM_FORBIDDEN")
        if row["state"] == "EXECUTED_WITH_DURABLE_EVIDENCE":
            for key in ("evaluation_id", "execution_artifact_id", "worker_id",
                        "task_state", "execution_status", "conclusive"):
                if key not in row:
                    raise contracts.DomainValidationError("N9_REPRO_ACTUAL_RECORD_REQUIRED")
            if (row["task_state"] != "PASS"
                    or not isinstance(row.get("evidence_ids"), list)
                    or not row["evidence_ids"]
                    or type(row["conclusive"]) is not bool
                    or type(row.get("reproduced")) not in (bool, type(None))):
                raise contracts.DomainValidationError("N9_REPRO_ACTUAL_EVIDENCE_REQUIRED")
        row["artifact_type"] = _KIND
        row["artifact_version"] = contracts._artifact_version(row)
        return row
    contracts.VALIDATORS[_KIND] = validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, "record_id")
    registry.IDENTITY_FIELDS[_KIND] = "record_id"
    registry.BUCKETS[_KIND] = "rc72_n9_approved_reproduction_executions"


class N9ApprovedReproductionExecutionService:
    def __init__(self, human_gate, *, evidence_root, captain_scheduler=None,
                 captain_session_id=None, captain_lease_id=None, team_id=None,
                 timeout_seconds=300):
        if not isinstance(human_gate, N9ReproductionHumanGateService):
            raise ContractError("N9_REPRO_CANONICAL_HUMAN_GATE_REQUIRED")
        self.gate = human_gate
        self.truth, self.release_id, self.source_commit = (
            human_gate.truth, human_gate.release_id, human_gate.source_commit)
        self.authority = human_gate.authority
        self.evidence_root = Path(evidence_root).resolve()
        self.timeout_seconds = timeout_seconds
        self.captain_scheduler = captain_scheduler
        self.captain_session_id = captain_session_id
        self.captain_lease_id = captain_lease_id
        self.team_id = team_id
        if any(value is not None for value in (
                captain_scheduler, captain_session_id, captain_lease_id, team_id)):
            from .rc72_captain_scheduling import CaptainFencedWorkItemScheduler
            if (not isinstance(captain_scheduler, CaptainFencedWorkItemScheduler)
                    or captain_scheduler.truth is not self.truth
                    or captain_scheduler.release_id != self.release_id
                    or any(not isinstance(x, str) or not x for x in (
                        captain_session_id, captain_lease_id, team_id))):
                raise ContractError("N9_REPRO_CAPTAIN_BOUND_COMPONENTS_REQUIRED")
        install_overlay()

    def _one(self, kind, **scope):
        rows = self.truth.query(kind, **scope)
        if len(rows) != 1:
            raise ContractError("N9_REPRO_CANONICAL_R1_NOT_UNIQUE:" + kind)
        return rows[0]

    def _scope(self, request_id, bundle, prepared):
        approval = self.gate.assert_fresh_approved(request_id=request_id)
        request = self._one(
            "rc72_n9_reproduction_authorization_request", request_id=request_id)
        contract = self._one(
            "rc72_n6_executable_contract",
            contract_id=request["original_contract_id"])
        original = self._one("rc72_n7_execution_preparation",
                             preparation_id=request["preparation_id"])
        frozen_cases = CanonicalDesignService(
            self.truth, release_id=self.release_id,
            source_commit=self.source_commit).load(
                release_batch_id=request["release_batch_id"]).cases
        cases = [item for item in frozen_cases
                 if item["tc_id"] == request["original_case_id"]]
        if len(cases) != 1:
            raise ContractError("N9_REPRO_ORIGINAL_N4_CASE_NOT_UNIQUE")
        canonical = cases[0]
        etu = self._one("rc72_etu", etu_id=request["original_etu_id"])
        original_task = self._one("rc7_task",
                                  task_id=request["original_workitem_id"])
        gap = self._one("rc7_gap", gap_id=request["original_gap_id"])
        if (request["release_id"] != self.release_id
                or request["source_commit"] != self.source_commit
                or contract["contract_sha256"] != n6_contract_digest(contract)
                or original["attempt_id"] != request["original_attempt_id"]
                or original["case_id"] != request["original_case_id"]
                or original_task["mission_id"] != request["mission_id"]
                or original_task["input_artifact_refs"] != request["approved_case_artifact_refs"]
                or gap["category"] != "VALID_TEST_FAILURE"
                or gap["target_node"] != "N9_DEFECT"
                or not isinstance(bundle, VerifiedScriptExecutionBundle)
                or not isinstance(prepared, PreparedAttempt)
                or prepared.status != "PREPARED"
                or prepared.attempt_id == request["original_attempt_id"]
                or self.truth.query("execution_attempt", attempt_id=prepared.attempt_id)
                or prepared.tc_id != request["original_case_id"]
                or bundle.spec.tc_id != request["original_case_id"]
                or prepared.case_version != bundle.spec.case_version
                or bundle.spec.layer != etu["test_level"]
                or bundle.frozen_case.get("tc_id") != request["original_case_id"]
                or bundle.frozen_case.get("status") != "FROZEN"
                or bundle.frozen_case.get("release_id") != self.release_id
                or bundle.frozen_case.get("oracle", {}).get("checks") != contract["oracles"]
                or prepared.oracle_snapshot.get("checks") != contract["oracles"]
                or bundle.frozen_case.get("steps") != contract["steps"]
                or any(bundle.frozen_case.get(name) != canonical.get(name)
                       for name in (
                           "requirement_id", "sst_id", "obligation_id",
                           "preconditions", "steps", "expected_results",
                           "evidence_requirements"))
                or bundle.frozen_case.get("test_level") != canonical.get("test_level")):
            raise ContractError("N9_REPRO_NEW_ATTEMPT_FROZEN_ORACLE_OR_CASE_REQUIRED")
        source_ref = bundle.script.source_ref
        if (not isinstance(source_ref, str)
                or not source_ref.startswith("file://")
                or not isinstance(bundle.source_sha256, str)
                or len(bundle.source_sha256) != 64
                or not bundle.validation.ready):
            raise ContractError("N9_REPRO_APPROVED_SCRIPT_BYTES_REQUIRED")
        source_file = Path(source_ref[len("file://"):])
        if (not source_file.is_file() or source_file.is_symlink()
                or hashlib.sha256(source_file.read_bytes()).hexdigest()
                   != bundle.source_sha256):
            raise ContractError("N9_REPRO_APPROVED_SCRIPT_HASH_CHANGED")
        return request, approval, contract, original_task

    @staticmethod
    def _task_id(request_id):
        return "N9REPROTASK-" + _hash(["C04", request_id])[:24]

    def _record_id(self, request_id):
        return "N9REPROEXEC-" + _hash([self.release_id, request_id])[:24]

    def execute(self, *, request_id, bundle, prepared, authority, tool_broker,
                cwd, env=None, target_base_url=None):
        """Run one REAL subprocess from the verified frozen Case.

        All external resource preparation is supplied by the trusted Host.
        No tool call is simulated by this service, and no new Attempt can be
        inferred from a DSH candidate, a HumanGate flag, or an R1 plan alone.
        """
        request, approval, contract, original_task = self._scope(
            request_id, bundle, prepared)
        if (not isinstance(authority, RC7AuthorityRuntime)
                or not isinstance(tool_broker, ToolCapabilityBroker)):
            from .rc72_authority import RC72AuthorityRuntime
            if (not isinstance(authority, RC72AuthorityRuntime)
                    or not isinstance(tool_broker, ToolCapabilityBroker)):
                raise ContractError("N9_REPRO_TRUSTED_EXECUTION_BROKER_REQUIRED")
        leases = self.truth.query("rc72_captain_dispatch_lease",
                                  mission_id=request["mission_id"])
        if leases and self.captain_scheduler is None:
            raise ContractError("N9_REPRO_CAPTAIN_FENCED_HOST_REQUIRED")
        if not leases and self.captain_scheduler is not None:
            raise ContractError("N9_REPRO_CAPTAIN_R1_LEASE_REQUIRED")
        if leases:
            from .rc72_authority import RC72AuthorityRuntime
            if not isinstance(authority, RC72AuthorityRuntime):
                raise ContractError("N9_REPRO_GOVERNED_AUTHORITY_REQUIRED")
            owner = self.captain_scheduler.fencer.assert_owner(
                mission_id=request["mission_id"],
                lease_id=self.captain_lease_id,
                captain_session_id=self.captain_session_id)
            if owner["team_id"] != self.team_id:
                raise ContractError("N9_REPRO_CAPTAIN_TEAM_SCOPE_CHANGED")

        task_id = self._task_id(request_id)
        expected = dict(
            mission_id=request["mission_id"], node="EXECUTION",
            task_type="DEFECT_REPRODUCTION",
            gap_refs=[request["original_gap_id"]],
            input_artifact_refs=list(request["approved_case_artifact_refs"]),
            required_capabilities=list(original_task["required_capabilities"]))
        control = ClosedLoopControlPlane(
            self.truth, self.release_id, request["mission_id"])
        intent = dict(
            record_id=self._record_id(request_id), request_id=request_id,
            human_decision_id=approval["decision_id"],
            release_id=self.release_id, source_commit=self.source_commit,
            release_batch_id=request["release_batch_id"],
            mission_id=request["mission_id"],
            original_attempt_id=request["original_attempt_id"],
            original_case_id=request["original_case_id"],
            original_contract_id=request["original_contract_id"],
            original_gap_id=request["original_gap_id"],
            reproduction_workitem_id=task_id,
            reproduction_attempt_id=prepared.attempt_id,
            contract_sha256=contract["contract_sha256"],
            oracle_sha256=_hash(contract["oracles"]),
            script_sha256=bundle.source_sha256,
            approved_at=int(time.time()), purpose=_PURPOSE,
            state="IN_FLIGHT_NO_REPLAY")
        # Before recording ANY execution intent, refuse a reused prepared
        # Attempt or an already pending/finished attempt for the same Case.
        with ledger_lock(self.truth, busy="N9_REPRO_DISPATCH_LEDGER_BUSY"):
            if self.truth.query(_KIND, request_id=request_id):
                raise ContractError("N9_REPRO_ALREADY_ATTEMPTED_NO_BUSINESS_REPLAY")
            if self.truth.query("rc7_task", task_id=task_id):
                raise ContractError("N9_REPRO_UNRECONCILED_TASK_NO_REPLAY")
            control.register_task(Task(
                task_id=task_id, mission_id=request["mission_id"],
                node="EXECUTION", task_type="DEFECT_REPRODUCTION",
                objective="Independently reproduce signed N8 discrepancy for " +
                          request["original_case_id"],
                input_artifact_refs=expected["input_artifact_refs"],
                gap_refs=expected["gap_refs"],
                required_capabilities=expected["required_capabilities"],
                acceptance_criteria=[
                    "New independent Attempt distinct from original N7 failure",
                    "One real scoped business execution with frozen N6 Oracle",
                    "Durable evidence and independent conclusive reproduction classification",
                    "No PRODUCT_DEFECT, RCA or regression PASS inferred from execution"], priority=0))
            task = self._one("rc7_task", task_id=task_id)
            if any(task.get(k) != v for k, v in expected.items()):
                raise ContractError("N9_REPRO_ACTUAL_TASK_SCOPE_CHANGED")
            self.truth.append_atomic(
                _EVENT, dict(intent,
                             signature=self.authority._sign(intent),
                             artifact_version=1))
        # Intent is now durable: if the process dies at ANY later point, a
        # cold restarted coordinator must NOT execute it again.
        governed = None
        if leases:
            governed = self.captain_scheduler.dispatch_etu(
                mission_id=request["mission_id"], team_id=self.team_id,
                captain_session_id=self.captain_session_id,
                captain_lease_id=self.captain_lease_id,
                role=bundle.spec.layer + "_EXECUTE",
                etu_id=request["original_etu_id"], workitem_id=task_id,
                canonical_refs=dict(
                    etu_refs=[request["original_etu_id"]],
                    executable_contract_refs=[request["original_contract_id"]],
                    data_refs=[x["data_ref"] for x in contract["data_refs"]]))
        executor = DefectReproductionExecutionService(
            evidence_root=str(self.evidence_root),
            timeout_seconds=self.timeout_seconds,
            approved_n9_human_gate=self.gate)
        result = executor.execute_task(
            control, task_id,
            source_product_gap_id=request["original_gap_id"],
            approved_n9_request_id=request_id,
            governed_dispatch=governed,
            governed_fencer=(self.captain_scheduler.fencer if governed else None),
            bundle=bundle, prepared=prepared, authority=authority,
            tool_broker=tool_broker, cwd=cwd, env=env,
            target_base_url=target_base_url)
        durable = dict(intent,
            state="EXECUTED_WITH_DURABLE_EVIDENCE",
            evaluation_id=result.evaluation_id,
            execution_artifact_id=result.record_artifact_id,
            evidence_ids=list(result.evidence_ids),
            worker_id=result.runtime_worker_id,
            task_state=result.task_state,
            execution_status=result.execution_record.status,
            conclusive=result.conclusive,
            reproduced=result.reproduced)
        with ledger_lock(self.truth, busy="N9_REPRO_RECEIPT_LEDGER_BUSY"):
            row = self._one(_KIND, record_id=intent["record_id"])
            if (row["state"] != "IN_FLIGHT_NO_REPLAY"
                    or not hmac.compare_digest(row["signature"],
                                               self.authority._sign(_unsigned(row)))):
                raise ContractError("N9_REPRO_EXECUTION_INTENT_CHANGED")
            evaluation = self._one("rc7_evaluation",
                                   evaluation_id=result.evaluation_id)
            artifact = self._one("rc7_artifact",
                                 artifact_id=result.record_artifact_id)
            if (evaluation["mission_id"] != request["mission_id"]
                    or artifact["mission_id"] != request["mission_id"]
                    or result.record_artifact_id not in evaluation["artifact_refs"]
                    or not result.evidence_ids
                    or any(len(self.truth.query(
                        "rc7_evidence", evidence_id=eid)) != 1
                        for eid in result.evidence_ids)):
                raise ContractError("N9_REPRO_RESULT_R1_EVIDENCE_MISSING")
            self.truth.append_atomic(_EVENT, dict(
                durable, signature=self.authority._sign(durable),
                artifact_version=2))
        return dict(
            status="HOLD",
            reason=("N9_INDEPENDENT_REPRODUCTION_EVIDENCE_REQUIRES_RCA"
                    if result.conclusive else "N9_REPRODUCTION_INCONCLUSIVE_REPAIR_REQUIRED"),
            reproduction_record_id=intent["record_id"],
            request_id=request_id,
            original_attempt_id=request["original_attempt_id"],
            fresh_attempt_id=prepared.attempt_id,
            workitem_id=task_id, worker_id=result.runtime_worker_id,
            execution_artifact_id=result.record_artifact_id,
            evaluation_id=result.evaluation_id,
            evidence_ids=list(result.evidence_ids),
            reproduced=result.reproduced,
            conclusive=result.conclusive,
            defect_confirmed=False, rca_completed=False,
            regression_verified=False, field_verified=False, bank_final=False)

    def audit(self, *, request_id):
        """Return recorded proof only. Never restart an IN_FLIGHT operation."""
        row = self._one(_KIND, request_id=request_id)
        if not hmac.compare_digest(row.get("signature", ""),
                                   self.authority._sign(_unsigned(row))):
            raise ContractError("N9_REPRO_RECORD_SIGNATURE_CHANGED")
        if row["state"] == "IN_FLIGHT_NO_REPLAY":
            return dict(status="HOLD", reason="N9_REPRO_UNKNOWN_EFFECT_NO_REPLAY",
                        request_id=request_id, field_verified=False, bank_final=False)
        evaluation = self._one("rc7_evaluation", evaluation_id=row["evaluation_id"])
        artifact = self._one("rc7_artifact", artifact_id=row["execution_artifact_id"])
        task = self._one("rc7_task", task_id=row["reproduction_workitem_id"])
        if (task["state"] != "PASS"
                or evaluation["mission_id"] != row["mission_id"]
                or artifact["mission_id"] != row["mission_id"]
                or artifact["artifact_id"] not in evaluation["artifact_refs"]
                or task["evaluation_id"] != row["evaluation_id"]
                or any(len(self.truth.query("rc7_evidence", evidence_id=eid)) != 1
                       for eid in row["evidence_ids"])):
            raise ContractError("N9_REPRO_DURABLE_EXECUTION_PROOF_CHANGED")
        return dict(status="HOLD",
                    reason=("N9_INDEPENDENT_REPRODUCTION_EVIDENCE_REQUIRES_RCA"
                            if row["conclusive"] else
                            "N9_REPRODUCTION_INCONCLUSIVE_REPAIR_REQUIRED"),
                    request_id=request_id,
                    record_id=row["record_id"],
                    fresh_attempt_id=row["reproduction_attempt_id"],
                    execution_artifact_id=row["execution_artifact_id"],
                    evaluation_id=row["evaluation_id"],
                    reproduced=row["reproduced"],
                    conclusive=row["conclusive"],
                    defect_confirmed=False, rca_completed=False,
                    regression_verified=False, field_verified=False, bank_final=False)


install_overlay()
