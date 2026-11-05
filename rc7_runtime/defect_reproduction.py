"""Governed defect reproduction execution without duplicate defect emission.

A defect reproduction is real Execution work, but its objective is different
from ordinary product testing: determine whether the already-qualified product
mismatch reproduces. Therefore a trusted Oracle FAIL means the reproduction
Task PASSes with reproduced=True; it must not emit a second PRODUCT_DEFECT Gap.

Inconclusive/blocked reproduction remains repairable and is routed back to the
Defect qualification loop as DEFECT_QUALIFICATION_INCOMPLETE.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple

from rc6_runtime.automation import JUnitRunnerAdapter, PytestRunnerAdapter
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.execution import ExecutionRecord, ExecutionRuntime
from rc6_runtime.preparation import PreparedAttempt

from .authority import RC7AuthorityRuntime
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .controlled_api_execution_strict import StrictControlledApiRunnerAdapter
from .models import Evaluation, EvaluationResult, Gap, GapSeverity, TaskStatus
from .oracle_runtime import DeterministicOracleRuntime
from .runtime_execution import RuntimeExecutionError, VerifiedScriptExecutionBundle, _EvidenceBackedProcessHarness
from .runtime_execution_control import ClosedLoopRuntimeExecutionService


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class DefectReproductionResult:
    execution_record: ExecutionRecord
    record_artifact_id: str
    evidence_ids: Tuple[str, ...]
    evaluation_id: str
    task_state: str
    reproduced: Optional[bool]
    conclusive: bool
    runtime_worker_id: str
    runtime_lease_id: str


class DefectReproductionExecutionService:
    def __init__(self, *, evidence_root: str, timeout_seconds: int = 300,
                 approved_n9_human_gate=None) -> None:
        # Legacy PRODUCT_DEFECT reproduction remains unchanged. The RC7.2
        # VALID_TEST_FAILURE exception requires a typed, independently signed
        # N8/N9 + bank HumanGate; it is never a free-form product claim.
        if approved_n9_human_gate is not None:
            from .rc72_n9_reproduction_human_gate import N9ReproductionHumanGateService
            if not isinstance(approved_n9_human_gate, N9ReproductionHumanGateService):
                raise RuntimeExecutionError("N9_REPRO_TRUSTED_HUMAN_GATE_REQUIRED")
        self.approved_n9_human_gate = approved_n9_human_gate
        self.evidence_root = Path(evidence_root).resolve()
        self.timeout_seconds = int(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def execute_task(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        *,
        source_product_gap_id: str,
        bundle: VerifiedScriptExecutionBundle,
        prepared: PreparedAttempt,
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
        target_base_url: Optional[str] = None,
        approved_n9_request_id: Optional[str] = None,
        governed_dispatch=None,
        governed_fencer=None,
    ) -> DefectReproductionResult:
        task = control.scheduler.task(task_id)
        if task.node != "EXECUTION" or task.task_type != "DEFECT_REPRODUCTION":
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_EXECUTION_TASK_REQUIRED")
        if governed_dispatch is None:
            if task.state != TaskStatus.READY:
                raise RuntimeExecutionError("DEFECT_REPRODUCTION_TASK_NOT_READY")
        elif task.state != TaskStatus.LEASED:
            raise RuntimeExecutionError("N9_REPRO_GOVERNED_WORKITEM_NOT_LEASED")
        if prepared.status != "PREPARED":
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_PREPARED_ATTEMPT_REQUIRED")
        if prepared.tc_id != bundle.spec.tc_id or prepared.case_version != bundle.spec.case_version:
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_CASE_MISMATCH")
        if not isinstance(source_product_gap_id, str) or not source_product_gap_id:
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_SOURCE_GAP_REQUIRED")
        product_gap = control.truth.query("rc7_gap", gap_id=source_product_gap_id)
        if len(product_gap) != 1:
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_SOURCE_GAP_NOT_UNIQUE")
        gap_row = product_gap[0]
        if gap_row.get("mission_id") != control.mission_id:
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_SOURCE_GAP_MISSION_MISMATCH")
        if approved_n9_request_id is None:
            if governed_dispatch is not None:
                raise RuntimeExecutionError("N9_REPRO_GOVERNED_DISPATCH_REQUIRES_APPROVAL")
            if gap_row.get("category") != "PRODUCT_DEFECT" or gap_row.get("target_node") != "DEFECT":
                raise RuntimeExecutionError("DEFECT_REPRODUCTION_REQUIRES_PRODUCT_DEFECT_GAP")
        else:
            gate = self.approved_n9_human_gate
            if gate is None or control.truth is not gate.truth:
                raise RuntimeExecutionError("N9_REPRO_TRUSTED_CANONICAL_HUMAN_GATE_REQUIRED")
            gate.assert_fresh_approved(request_id=approved_n9_request_id)
            matches = control.truth.query(
                "rc72_n9_reproduction_authorization_request",
                request_id=approved_n9_request_id)
            if len(matches) != 1:
                raise RuntimeExecutionError("N9_REPRO_ORIGINAL_REQUEST_REQUIRED")
            request = matches[0]
            contracts = control.truth.query(
                "rc72_n6_executable_contract",
                contract_id=request["original_contract_id"])
            if len(contracts) != 1:
                raise RuntimeExecutionError("N9_REPRO_ORIGINAL_N6_CONTRACT_REQUIRED")
            contract = contracts[0]
            # An original N8 discrepancy is not a product Defect. Only one
            # exactly approved Case+Oracle+Attempt can enter a NEW reproduction.
            if (gap_row.get("category") != "VALID_TEST_FAILURE"
                    or gap_row.get("target_node") != "N9_DEFECT"
                    or request["original_gap_id"] != source_product_gap_id
                    or request["mission_id"] != control.mission_id
                    or request["release_id"] != control.release_id
                    or task.gap_refs != [source_product_gap_id]
                    or task.input_artifact_refs != request["approved_case_artifact_refs"]
                    or prepared.attempt_id == request["original_attempt_id"]
                    or prepared.tc_id != request["original_case_id"]
                    or bundle.spec.tc_id != request["original_case_id"]
                    or bundle.frozen_case.get("tc_id") != request["original_case_id"]
                    or bundle.frozen_case.get("status") != "FROZEN"
                    or bundle.frozen_case.get("release_id") != request["release_id"]
                    or bundle.frozen_case.get("oracle", {}).get("checks") != contract["oracles"]
                    or prepared.oracle_snapshot.get("checks") != contract["oracles"]
                    or (contract.get("preconditions")
                        and not prepared.precondition_evidence)
                    or (contract.get("data_refs")
                        and not prepared.binding_evidence)):
                raise RuntimeExecutionError("N9_REPRO_FRESH_FROZEN_CASE_OR_ORACLE_SCOPE_REQUIRED")

        if approved_n9_request_id is not None:
            from .rc72_captain_scheduling import GovernedFreshDispatch
            from .rc72_captain_dispatch_fencing import CaptainDispatchFencer
            from .rc72_authority import RC72AuthorityRuntime
            captain_leases = control.truth.query(
                "rc72_captain_dispatch_lease", mission_id=control.mission_id)
            if captain_leases:
                if (not isinstance(governed_dispatch, GovernedFreshDispatch)
                        or not isinstance(governed_fencer, CaptainDispatchFencer)
                        or governed_fencer.truth is not control.truth
                        or not isinstance(authority, RC72AuthorityRuntime)):
                    raise RuntimeExecutionError("N9_REPRO_CAPTAIN_OWNED_DISPATCH_REQUIRED")
                owner = governed_fencer.assert_owner(
                    mission_id=control.mission_id,
                    lease_id=governed_dispatch.captain_lease_id,
                    captain_session_id=governed_dispatch.captain_session_id)
                admission = control.truth.query(
                    "rc72_captain_etu_admission",
                    admission_id=governed_dispatch.admission_id)
                if (len(admission) != 1
                        or admission[0]["worker_id"] != governed_dispatch.worker_id
                        or admission[0]["session_id"] != governed_dispatch.session_id
                        or admission[0]["workitem_id"] != task_id
                        or admission[0]["etu_id"] != request["original_etu_id"]
                        or admission[0]["captain_lease_id"] != owner["lease_id"]
                        or admission[0]["captain_generation"] != owner["generation"]
                        or owner["team_id"] != governed_dispatch.team_id
                        or governed_dispatch.mission_id != control.mission_id
                        or governed_dispatch.role != bundle.spec.layer + "_EXECUTE"
                        or task.lease_owner != governed_dispatch.worker_id):
                    raise RuntimeExecutionError("N9_REPRO_CAPTAIN_FRESH_WORKER_SCOPE_CHANGED")
            elif governed_dispatch is not None:
                raise RuntimeExecutionError("N9_REPRO_GOVERNED_DISPATCH_WITHOUT_CAPTAIN")
        DeterministicOracleRuntime.validate_contract(prepared.oracle_snapshot)
        runtime = ExecutionRuntime(
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=DeterministicOracleRuntime(),
        )
        profile = runtime.profiles.get(bundle.spec.layer)
        if governed_dispatch is not None:
            identity = authority.adopt_identity(
                worker_id=governed_dispatch.worker_id,
                role=profile.role, phase="EXECUTION",
                layer=profile.layer, generation=0,
                session_id=governed_dispatch.session_id)
        else:
            identity = authority.issue_identity(
                profile.role, "EXECUTION", profile.layer,
                0, "defect-reproduction-" + uuid.uuid4().hex)

        lease = authority.issue_lease(
            identity.worker_id,
            "case:%s@%s" % (bundle.spec.tc_id, bundle.spec.case_version),
            ExecutionRuntime.REQUIRED_ARTIFACTS,
            profile.required_tools,
            ttl_seconds=max(self.timeout_seconds + 120, 300),
        )
        for tool_id in profile.required_tools:
            try:
                tool_broker.bind_worker(tool_id, identity.worker_id, visible=True, permitted=True)
            except Exception as exc:
                raise RuntimeExecutionError(
                    "DEFECT_REPRODUCTION_TOOL_BIND_FAILED:%s:%s" % (tool_id, exc)
                ) from exc
        admission = tool_broker.admit(identity.worker_id, profile.required_tools, prepared.target_id)
        if not admission.ready:
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_TOOL_ADMISSION_BLOCKED:%s" % admission.blocked)

        # The C04 route leases EXACTLY the newly approved reproduction Task:
        # lease_next could accidentally take a ready sibling or stale repair.
        if governed_dispatch is not None:
            leased = control.scheduler.task(task_id)
            if (leased.lease_owner != identity.worker_id
                    or leased.state != TaskStatus.LEASED):
                raise RuntimeExecutionError("N9_REPRO_CAPTAIN_TASK_LEASE_CHANGED")
            # A handoff between allocation and process start must not regain
            # the old Captain's business authority.
            governed_fencer.assert_owner(
                mission_id=control.mission_id,
                lease_id=governed_dispatch.captain_lease_id,
                captain_session_id=governed_dispatch.captain_session_id)
        elif approved_n9_request_id is None:
            leased = control.lease_next(
                worker_ref=identity.worker_id,
                capabilities=("test_execution",),
            )
        else:
            leased = control.scheduler.lease_task(
                control.mission_id, task_id,
                worker_ref=identity.worker_id,
                capabilities=task.required_capabilities,
            )
        if leased is None or leased.task_id != task_id:
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_SCHEDULER_LEASE_MISMATCH")
        control.start(task_id, worker_ref=identity.worker_id)

        if bundle.spec.runner_type == "PYTEST":
            delegate = PytestRunnerAdapter(timeout_seconds=self.timeout_seconds)
        elif bundle.spec.runner_type == "JUNIT":
            delegate = JUnitRunnerAdapter(timeout_seconds=self.timeout_seconds)
        else:
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_RUNNER_NOT_IMPLEMENTED:%s" % bundle.spec.runner_type)
        delegate.harness = _EvidenceBackedProcessHarness(
            evidence_root=str(self.evidence_root),
            timeout_seconds=self.timeout_seconds,
        )
        runner = delegate
        if bundle.spec.layer == "L3":
            if not isinstance(target_base_url, str) or not target_base_url.strip():
                raise RuntimeExecutionError("DEFECT_REPRODUCTION_L3_TARGET_BASE_URL_REQUIRED")
            runner = StrictControlledApiRunnerAdapter(
                delegate=delegate,
                target_base_url=target_base_url.strip(),
                evidence_root=str(self.evidence_root),
                attempt_id=prepared.attempt_id,
                proxy_timeout_seconds=min(self.timeout_seconds, 60),
            )

        raw_record = runtime.execute_with_runner(
            case=bundle.frozen_case,
            executable_spec=bundle.spec,
            script=bundle.script,
            validation=bundle.validation,
            prepared=prepared,
            worker_id=identity.worker_id,
            lease_id=lease.lease_id,
            runner=runner,
            cwd=cwd,
            env=env,
        )
        helper = ClosedLoopRuntimeExecutionService(
            evidence_root=str(self.evidence_root),
            timeout_seconds=self.timeout_seconds,
        )
        record, artifact, record_evidence, evidence = helper._persistable_output(
            control,
            task_id=task_id,
            bundle=bundle,
            raw_record=raw_record,
        )
        output_evidence = tuple(evidence) + (record_evidence,)
        control.submit_worker_output(
            WorkerOutput(
                task_id=task_id,
                worker_ref=identity.worker_id,
                artifacts=(artifact,),
                evidence=output_evidence,
            )
        )

        reproduced: Optional[bool]
        conclusive: bool
        if record.status == "FAIL" and record.integrity_passed and record.assertion_passed is False:
            reproduced = True
            conclusive = True
        elif record.status == "PASS" and record.integrity_passed and record.assertion_passed is True:
            reproduced = False
            conclusive = True
        else:
            reproduced = None
            conclusive = False

        evidence_ids = tuple(item.evidence_id for item in evidence) + (record_evidence.evidence_id,)
        gaps = ()
        result = EvaluationResult.PASS
        if not conclusive:
            result = EvaluationResult.REPAIR_REQUIRED
            gap = Gap(
                gap_id=_stable_id(
                    "GAP-DEFECT-REPRO",
                    control.mission_id,
                    source_product_gap_id,
                    prepared.attempt_id,
                ),
                mission_id=control.mission_id,
                source_node="EXECUTION",
                category="DEFECT_QUALIFICATION_INCOMPLETE",
                severity=GapSeverity.HIGH,
                target_node="DEFECT",
                description="defect reproduction did not reach a trustworthy business conclusion",
                subject_refs=[source_product_gap_id, prepared.attempt_id, prepared.tc_id],
                evidence_refs=list(evidence_ids),
                acceptance_criteria=["repeat the original product mismatch with trusted runtime evidence"],
            )
            gaps = (gap,)

        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-DEFECT-REPRO",
                control.mission_id,
                source_product_gap_id,
                prepared.attempt_id,
                str(reproduced),
                result.value,
            ),
            mission_id=control.mission_id,
            node="EXECUTION",
            artifact_refs=[artifact.artifact_id],
            result=result,
            evaluator_ref="rc7-defect-reproduction-runtime-gate",
            dimensions={
                "purpose": "DEFECT_REPRODUCTION",
                "source_product_gap_id": source_product_gap_id,
                "approved_n9_request_id": approved_n9_request_id,
                "attempt_id": prepared.attempt_id,
                "execution_status": record.status,
                "integrity_passed": record.integrity_passed,
                "assertion_passed": record.assertion_passed,
                "reproduced": reproduced,
                "conclusive": conclusive,
            },
            gap_refs=[item.gap_id for item in gaps],
            evidence_refs=list(evidence_ids),
        )
        accepted = control.accept_evaluation(task_id, evaluation=evaluation, gaps=gaps)
        return DefectReproductionResult(
            execution_record=record,
            record_artifact_id=artifact.artifact_id,
            evidence_ids=evidence_ids,
            evaluation_id=evaluation.evaluation_id,
            task_state=accepted.state.value,
            reproduced=reproduced,
            conclusive=conclusive,
            runtime_worker_id=identity.worker_id,
            runtime_lease_id=lease.lease_id,
        )
