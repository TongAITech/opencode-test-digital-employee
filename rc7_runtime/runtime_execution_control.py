"""R1/control-plane integration for runtime-owned formal execution.

The same runtime-issued layer identity leases the RC7 EXECUTION Task, launches
the approved runner, persists process/result evidence and an
EXECUTION_CONCLUSION Artifact, then submits the independent ExecutionClosedLoop
Evaluation.  No model/worker can provide the authoritative execution status.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.automation import JUnitRunnerAdapter, PytestRunnerAdapter
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.diagnosis import DiagnosisResult, RecoveryDecision
from rc6_runtime.execution import ExecutionRecord, ExecutionRuntime
from rc6_runtime.preparation import PreparedAttempt

from .authority import RC7AuthorityRuntime
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .execution_diagnosis import ExecutionDiagnosisCoordinator, ExecutionTrustFacts
from .execution_loop import ExecutionClosedLoop, ExecutionLoopResult
from .models import Artifact, Evidence, TaskStatus
from .runtime_execution import (
    RuntimeExecutionError,
    VerifiedScriptExecutionBundle,
    _EvidenceBackedProcessHarness,
)


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class ClosedLoopExecutionResult:
    execution_record: ExecutionRecord
    record_artifact_id: str
    record_evidence_id: str
    evidence_ids: Tuple[str, ...]
    loop_result: ExecutionLoopResult
    task_state: str
    runtime_worker_id: str
    runtime_lease_id: str


class ClosedLoopRuntimeExecutionService:
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
        bundle: VerifiedScriptExecutionBundle,
        prepared: PreparedAttempt,
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        oracle_evaluator: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
        diagnosis: Optional[DiagnosisResult] = None,
        recovery: Optional[RecoveryDecision] = None,
        diagnosis_coordinator: Optional[ExecutionDiagnosisCoordinator] = None,
        diagnosis_trust: Optional[ExecutionTrustFacts] = None,
    ) -> ClosedLoopExecutionResult:
        task = control.scheduler.task(task_id)
        if task.node != "EXECUTION":
            raise RuntimeExecutionError("FORMAL_EXECUTION_TASK_NODE_MISMATCH")
        if task.state != TaskStatus.READY:
            raise RuntimeExecutionError("FORMAL_EXECUTION_TASK_NOT_READY")
        if prepared.tc_id != bundle.spec.tc_id or prepared.case_version != bundle.spec.case_version:
            raise RuntimeExecutionError("PREPARED_ATTEMPT_SCRIPT_CASE_MISMATCH")
        if prepared.status != "PREPARED":
            raise RuntimeExecutionError("FORMAL_EXECUTION_REQUIRES_PREPARED_ATTEMPT")

        runtime = ExecutionRuntime(
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=oracle_evaluator,
        )
        profile = runtime.profiles.get(bundle.spec.layer)
        identity = authority.issue_identity(
            profile.role,
            "EXECUTION",
            profile.layer,
            0,
            "runtime-execution-" + uuid.uuid4().hex,
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
                    "EXECUTION_TOOL_RUNTIME_BIND_FAILED:%s:%s" % (tool_id, exc)
                ) from exc
        admission = tool_broker.admit(identity.worker_id, profile.required_tools, prepared.target_id)
        if not admission.ready:
            raise RuntimeExecutionError("EXECUTION_TOOL_ADMISSION_NOT_READY:%s" % admission.blocked)

        leased = control.lease_next(
            worker_ref=identity.worker_id,
            capabilities=("test_execution",),
        )
        if leased is None or leased.task_id != task_id:
            raise RuntimeExecutionError("FORMAL_EXECUTION_SCHEDULER_LEASE_MISMATCH")
        control.start(task_id, worker_ref=identity.worker_id)

        if bundle.spec.runner_type == "PYTEST":
            runner = PytestRunnerAdapter(timeout_seconds=self.timeout_seconds)
        elif bundle.spec.runner_type == "JUNIT":
            runner = JUnitRunnerAdapter(timeout_seconds=self.timeout_seconds)
        else:
            raise RuntimeExecutionError("FORMAL_RUNNER_NOT_IMPLEMENTED:%s" % bundle.spec.runner_type)
        runner.harness = _EvidenceBackedProcessHarness(
            evidence_root=str(self.evidence_root),
            timeout_seconds=self.timeout_seconds,
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
        record, record_artifact, record_evidence, evidence = self._persistable_output(
            control,
            task_id=task_id,
            bundle=bundle,
            raw_record=raw_record,
        )

        diagnostic_evidence = None
        effective_diagnosis = diagnosis
        effective_recovery = recovery
        if effective_diagnosis is None and effective_recovery is None and str(record.status).upper() != "PASS":
            coordinator = diagnosis_coordinator or ExecutionDiagnosisCoordinator(
                authority=authority,
                tool_broker=tool_broker,
                evidence_root=str(self.evidence_root),
            )
            trust = diagnosis_trust or ExecutionTrustFacts(exception_type=record.reason)
            closure = coordinator.diagnose(
                record=record,
                bundle=bundle,
                prepared=prepared,
                trust=trust,
            )
            if closure.evidence_ref and closure.evidence_sha256:
                diagnostic_evidence = Evidence(
                    evidence_id=_stable_id(
                        "EVD-EXEC-DIAG",
                        control.mission_id,
                        record.attempt_id,
                        closure.evidence_sha256,
                    ),
                    mission_id=control.mission_id,
                    kind="RUNTIME_FAILURE_DIAGNOSIS",
                    source_ref="runtime://execution-diagnosis",
                    content_ref=closure.evidence_ref,
                    subject_refs=[task_id, record.attempt_id, record.tc_id],
                    content_hash="sha256:" + closure.evidence_sha256,
                )
            if closure.complete and closure.diagnosis is not None:
                effective_diagnosis = DiagnosisResult(
                    diagnosis_id=closure.diagnosis.diagnosis_id,
                    attempt_id=closure.diagnosis.attempt_id,
                    failure_class=closure.diagnosis.failure_class,
                    evidence_refs=tuple(
                        dict.fromkeys(
                            tuple(record.evidence_refs)
                            + ((diagnostic_evidence.evidence_id,) if diagnostic_evidence is not None else ())
                        )
                    ),
                    cat_required=closure.diagnosis.cat_required,
                    cat_queried=closure.diagnosis.cat_queried,
                    rationale=closure.diagnosis.rationale,
                    classifier_ref=closure.diagnosis.classifier_ref,
                    failure_signature=closure.diagnosis.failure_signature,
                    root_cause_candidate=closure.diagnosis.root_cause_candidate,
                )
                effective_recovery = closure.recovery

        output_evidence = tuple(evidence) + (record_evidence,)
        if diagnostic_evidence is not None:
            output_evidence = output_evidence + (diagnostic_evidence,)
        control.submit_worker_output(
            WorkerOutput(
                task_id=task_id,
                worker_ref=identity.worker_id,
                artifacts=(record_artifact,),
                evidence=output_evidence,
            )
        )
        loop_result = ExecutionClosedLoop().evaluate(
            mission_id=control.mission_id,
            artifact_ref=record_artifact.artifact_id,
            record=record,
            diagnosis=effective_diagnosis,
            recovery=effective_recovery,
            evaluator_ref="rc7-runtime-owned-execution-gate",
        )
        accepted = control.accept_evaluation(
            task_id,
            evaluation=loop_result.evaluation,
            gaps=loop_result.gaps,
        )
        evidence_ids = tuple(item.evidence_id for item in evidence) + (record_evidence.evidence_id,)
        if diagnostic_evidence is not None:
            evidence_ids = evidence_ids + (diagnostic_evidence.evidence_id,)
        return ClosedLoopExecutionResult(
            execution_record=record,
            record_artifact_id=record_artifact.artifact_id,
            record_evidence_id=record_evidence.evidence_id,
            evidence_ids=evidence_ids,
            loop_result=loop_result,
            task_state=accepted.state.value,
            runtime_worker_id=identity.worker_id,
            runtime_lease_id=lease.lease_id,
        )

    def _persistable_output(
        self,
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        bundle: VerifiedScriptExecutionBundle,
        raw_record: ExecutionRecord,
    ) -> Tuple[ExecutionRecord, Artifact, Evidence, Sequence[Evidence]]:
        evidence = []
        canonical_ids = []
        for raw_ref in raw_record.evidence_refs:
            if not isinstance(raw_ref, str) or not raw_ref:
                continue
            digest = ""
            if raw_ref.startswith("file://"):
                path = Path(raw_ref[len("file://"):])
                if path.is_file():
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
            evidence_id = _stable_id(
                "EVD-EXEC-RUNTIME",
                control.mission_id,
                raw_record.attempt_id,
                raw_ref,
                digest,
            )
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    mission_id=control.mission_id,
                    kind="RUNTIME_EXECUTION_EVIDENCE",
                    source_ref="runtime://formal-execution",
                    content_ref=raw_ref,
                    subject_refs=[task_id, raw_record.attempt_id, raw_record.tc_id],
                    content_hash=("sha256:" + digest) if digest else None,
                )
            )
            canonical_ids.append(evidence_id)

        record = ExecutionRecord(
            attempt_id=raw_record.attempt_id,
            tc_id=raw_record.tc_id,
            case_version=raw_record.case_version,
            target_id=raw_record.target_id,
            layer=raw_record.layer,
            worker_id=raw_record.worker_id,
            lease_id=raw_record.lease_id,
            status=raw_record.status,
            integrity_passed=raw_record.integrity_passed,
            actual_result=raw_record.actual_result,
            tool_call_refs=raw_record.tool_call_refs,
            evidence_refs=tuple(dict.fromkeys(canonical_ids)),
            assertion_ref=raw_record.assertion_ref,
            assertion_passed=raw_record.assertion_passed,
            reason=raw_record.reason,
        )
        folder = self.evidence_root / "execution-records" / control.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (raw_record.attempt_id + ".json")
        payload = {
            "record": asdict(record),
            "raw_evidence_refs": list(raw_record.evidence_refs),
            "upstream_script": {
                "mission_id": bundle.upstream_mission_id,
                "task_id": bundle.upstream_task_id,
                "evaluation_id": bundle.upstream_evaluation_id,
                "result_ref": bundle.upstream_result_ref,
                "spec_ref": bundle.spec_ref,
                "script_id": bundle.script.script_id,
                "script_source_ref": bundle.script.source_ref,
                "script_source_sha256": bundle.source_sha256,
                "validation_id": bundle.validation.validation_id,
            },
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
        path.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        record_evidence_id = _stable_id(
            "EVD-EXEC-RECORD", control.mission_id, raw_record.attempt_id, digest
        )
        record_evidence = Evidence(
            evidence_id=record_evidence_id,
            mission_id=control.mission_id,
            kind="RUNTIME_EXECUTION_RECORD",
            source_ref="runtime://formal-execution",
            content_ref="file://" + str(path),
            subject_refs=[task_id, raw_record.attempt_id, raw_record.tc_id],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=_stable_id("ART-EXEC", control.mission_id, raw_record.attempt_id, digest),
            mission_id=control.mission_id,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id=task_id,
            content_ref="file://" + str(path),
            parent_refs=[],
            evidence_refs=list(dict.fromkeys(canonical_ids + [record_evidence_id])),
            content_hash="sha256:" + digest,
        )
        return record, artifact, record_evidence, evidence
