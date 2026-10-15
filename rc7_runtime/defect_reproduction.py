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
    def __init__(self, *, evidence_root: str, timeout_seconds: int = 300) -> None:
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
    ) -> DefectReproductionResult:
        task = control.scheduler.task(task_id)
        if task.node != "EXECUTION" or task.task_type != "DEFECT_REPRODUCTION":
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_EXECUTION_TASK_REQUIRED")
        if task.state != TaskStatus.READY:
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_TASK_NOT_READY")
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
        if gap_row.get("category") != "PRODUCT_DEFECT" or gap_row.get("target_node") != "DEFECT":
            raise RuntimeExecutionError("DEFECT_REPRODUCTION_REQUIRES_PRODUCT_DEFECT_GAP")

        DeterministicOracleRuntime.validate_contract(prepared.oracle_snapshot)
        runtime = ExecutionRuntime(
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=DeterministicOracleRuntime(),
        )
        profile = runtime.profiles.get(bundle.spec.layer)
        identity = authority.issue_identity(
            profile.role,
            "EXECUTION",
            profile.layer,
            0,
            "defect-reproduction-" + uuid.uuid4().hex,
        )
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

        leased = control.lease_next(
            worker_ref=identity.worker_id,
            capabilities=("test_execution",),
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
