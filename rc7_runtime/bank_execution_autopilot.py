"""RC7.1 runtime-owned EXECUTION stage for BANK Mission Autopilot.

One invocation handles exactly the Case owned by the current canonical EXECUTION
or EXECUTION/REPAIR task. Multi-case progress is governed by CASE_FANOUT_CONTRACT.
No capability is assumed READY: tool admission comes only from field/runtime
capability evidence. Current-Attempt CAT hardening is delegated to the bank
execution service; missing CAT readiness blocks diagnosis rather than execution.

RC7.1 N5 hardening: field CasePreparationService output is never passed directly
to a business runner. Every Case must first be adopted into the canonical
PREPARED_ATTEMPT contract and pass the governed N5 per-Case gate. BANK recovery
uses an N8-aware N5 selector so immutable predecessor history can coexist with a
single, explicitly authorized successor Attempt.

RC7.1 N8 hardening: a governed EXECUTION/REPAIR task is retry authorization
work, not a second business execution. Real execution failures are captured into
durable N8 recovery orders before the Mission may continue. A reactivated source
execution consumes a durable N8 successor authorization into a fresh PreparedAttempt
instead of replaying the predecessor Attempt identity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Optional, Tuple

from rc6_runtime.execution import ExecutionProfileRegistry

from .authority import RC7AuthorityRuntime
from .bank_attempt_cat_execution import BankAttemptCatRuntimeExecutionService
from .bank_autonomous_preparation_closure import BankAutonomousPreparationClosureError
from .bank_n5_recovery_closure import BankN5RecoveryAwarePreparationClosureCoordinator
from .bank_n8_recovery import BankN8RecoveryCoordinator, BankN8RecoveryError
from .bank_n8_successor import BankN8SuccessorCoordinator, BankN8SuccessorError
from .candidate_payload import CandidatePayloadReader
from .case_fanout_conformance import AcceptedCaseInventoryReader
from .case_runtime import CasePreparationService
from .case_script_bundle_resolver import CaseScriptExecutionBundleResolver
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .execution_capability import (
    ExecutionCapabilityBrokerFactory,
    ExecutionCapabilityEvidenceError,
)
from .execution_fanout_conformance import check_execution_barrier
from .execution_profiles import RC7_1_EXECUTION_PROFILES
from .models import Artifact, Evaluation, EvaluationResult, Evidence, Gap, GapSeverity, Task
from .oracle_runtime import DeterministicOracleRuntime


class BankExecutionAutopilotError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


class BankExecutionAutopilot:
    def __init__(
        self,
        *,
        authority: RC7AuthorityRuntime,
        state_root: str,
        evidence_root: str,
        package_root: str,
        target_id: str,
        capability_snapshot: Optional[str],
        timeout_seconds: int = 300,
    ) -> None:
        self.authority = authority
        self.state_root = Path(state_root).expanduser().resolve()
        self.evidence_root = Path(evidence_root).expanduser().resolve()
        self.package_root = Path(package_root).expanduser().resolve()
        self.target_id = str(target_id or "").strip()
        if not self.target_id:
            raise BankExecutionAutopilotError("EXECUTION_TARGET_REQUIRED")
        self.capability_snapshot = Path(capability_snapshot).expanduser().resolve() if capability_snapshot else None
        self.inventory = AcceptedCaseInventoryReader()
        self.candidate_reader = CandidatePayloadReader()
        self.bundle_resolver = CaseScriptExecutionBundleResolver(
            evidence_root=str(self.evidence_root / "script-runtime"),
            validation_timeout_seconds=min(max(30, timeout_seconds), 300),
        )
        self.execution = BankAttemptCatRuntimeExecutionService(
            evidence_root=str(self.evidence_root / "formal-execution"),
            state_root=str(self.state_root),
            timeout_seconds=timeout_seconds,
        )
        self.preparation_closure = BankN5RecoveryAwarePreparationClosureCoordinator(
            state_root=str(self.state_root),
            evidence_root=str(self.evidence_root / "autonomous-n5"),
            target_id=self.target_id,
            max_freshness_seconds=min(max(30, timeout_seconds), 300),
        )
        self.n8_recovery = BankN8RecoveryCoordinator(
            evidence_root=str(self.evidence_root / "n8")
        )
        self.n8_successor = BankN8SuccessorCoordinator(state_root=str(self.state_root))
        self.oracle = DeterministicOracleRuntime()
        self.profiles = ExecutionProfileRegistry(RC7_1_EXECUTION_PROFILES)

    def _case_for_task(self, control: ClosedLoopControlPlane, task: Task) -> str:
        inventory = self.inventory.load(control.truth, control.mission_id)
        accepted = set(inventory.tc_ids)
        if task.task_type == "REPAIR" and task.gap_refs:
            matches = set()
            for gap_id in task.gap_refs:
                rows = control.truth.query("rc7_gap", gap_id=gap_id)
                if len(rows) != 1:
                    continue
                for ref in rows[0].get("subject_refs") or []:
                    if isinstance(ref, str) and ref in accepted:
                        matches.add(ref)
            if len(matches) == 1:
                return next(iter(matches))
            if len(matches) > 1:
                raise BankExecutionAutopilotError(
                    "EXECUTION_REPAIR_CASE_NOT_UNIQUE:%s" % ",".join(sorted(matches))
                )
        barrier = check_execution_barrier(control.truth, control.mission_id)
        if not barrier.missing_tc_ids:
            raise BankExecutionAutopilotError("EXECUTION_FANOUT_ALREADY_COMPLETE")
        return barrier.missing_tc_ids[0]

    def _accepted_frozen_cases(self, control: ClosedLoopControlPlane) -> Tuple[Mapping[str, object], ...]:
        inventory = self.inventory.load(control.truth, control.mission_id)
        candidate = self.candidate_reader.load(
            control.truth,
            inventory.design_artifact_id,
            expected_mission_id=control.mission_id,
            expected_task_id=inventory.design_task_id,
        )
        raw_cases = candidate.semantic_payload.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise BankExecutionAutopilotError("EXECUTION_ACCEPTED_CASE_DENOMINATOR_REQUIRED")
        cases = []
        ids = []
        for raw in raw_cases:
            if not isinstance(raw, dict):
                raise BankExecutionAutopilotError("EXECUTION_ACCEPTED_CASE_OBJECT_REQUIRED")
            tc_id = str(raw.get("tc_id") or "").strip()
            if not tc_id:
                raise BankExecutionAutopilotError("EXECUTION_ACCEPTED_CASE_TC_ID_REQUIRED")
            ids.append(tc_id)
            cases.append(dict(raw))
        if tuple(ids) != inventory.tc_ids:
            raise BankExecutionAutopilotError("EXECUTION_ACCEPTED_CASE_DENOMINATOR_DRIFT")
        return tuple(cases)

    @staticmethod
    def _autonomous_run_id(control: ClosedLoopControlPlane) -> str:
        run_ids = set()
        for row in control.truth.query("rc7_control_event", mission_id=control.mission_id):
            data = row.get("data")
            if not isinstance(data, dict) or data.get("node_id") not in {"N2", "N3", "N4"}:
                continue
            run_id = str(data.get("run_id") or "").strip()
            if run_id:
                run_ids.add(run_id)
        if len(run_ids) != 1:
            raise BankExecutionAutopilotError(
                "EXECUTION_N5_AUTONOMOUS_RUN_ID_NOT_UNIQUE:%d" % len(run_ids)
            )
        return next(iter(run_ids))

    def _capability_broker(self, required_tools: Tuple[str, ...]):
        if self.capability_snapshot is None:
            raise ExecutionCapabilityEvidenceError("EXECUTION_CAPABILITY_SNAPSHOT_REQUIRED")
        factory = ExecutionCapabilityBrokerFactory(self.capability_snapshot)
        requested = list(required_tools)
        if "cat" in factory.tools and "cat" not in requested:
            requested.append("cat")
        return factory.build(target_id=self.target_id, required_tools=tuple(requested))

    def _block(
        self,
        control: ClosedLoopControlPlane,
        task: Task,
        *,
        worker_ref: str,
        tc_id: str,
        status: str,
        reason: str,
        human_required: bool = False,
        details: Optional[dict] = None,
        already_leased: bool = False,
    ) -> None:
        if not already_leased:
            leased = control.lease_next(worker_ref=worker_ref, capabilities=("test_execution",))
            if leased is None or leased.task_id != task.task_id:
                raise BankExecutionAutopilotError("EXECUTION_BLOCKER_LEASE_MISMATCH")
        control.start(task.task_id, worker_ref=worker_ref)
        payload = {
            "schema": "pfc.aitest.rc7.1.execution-blocker.v1",
            "mission_id": control.mission_id,
            "task_id": task.task_id,
            "tc_id": tc_id,
            "status": status,
            "reason": reason,
            "details": details or {},
        }
        folder = self.evidence_root / "execution-blockers" / control.mission_id
        folder.mkdir(parents=True, exist_ok=True)
        evidence_id = _stable_id("EVD-EXEC-BLOCK", control.mission_id, task.task_id, tc_id, status, reason)
        path = folder / (evidence_id + ".json")
        body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if path.exists() and path.read_bytes() != body:
            raise BankExecutionAutopilotError("EXECUTION_BLOCKER_IMMUTABILITY_CONFLICT")
        if not path.exists():
            path.write_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        evidence = Evidence(
            evidence_id=evidence_id,
            mission_id=control.mission_id,
            kind="RUNTIME_EXECUTION_BLOCKER",
            source_ref="runtime://bank-execution-autopilot",
            content_ref="file://" + str(path),
            subject_refs=[task.task_id, tc_id, status],
            content_hash="sha256:" + digest,
        )
        artifact = Artifact(
            artifact_id=_stable_id("ART-EXEC-BLOCK", control.mission_id, task.task_id, tc_id, status),
            mission_id=control.mission_id,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id=task.task_id,
            content_ref="file://" + str(path),
            parent_refs=[],
            evidence_refs=[evidence_id],
            content_hash="sha256:" + digest,
        )
        control.submit_worker_output(
            WorkerOutput(task_id=task.task_id, worker_ref=worker_ref, artifacts=(artifact,), evidence=(evidence,))
        )
        gap = Gap(
            gap_id=_stable_id("GAP-EXEC-BLOCK", control.mission_id, task.task_id, tc_id, status, reason),
            mission_id=control.mission_id,
            source_node="EXECUTION",
            category=("HUMAN_GATE_REQUIRED" if human_required else "EXECUTION_BLOCKED"),
            severity=GapSeverity.BLOCKER,
            target_node=("HUMAN_GATE" if human_required else "RUNTIME"),
            description=reason,
            subject_refs=[task.task_id, tc_id],
            evidence_refs=[evidence_id],
            acceptance_criteria=["resolve the runtime/preparation blocker with real field evidence and resume the same Mission"],
        )
        evaluation = Evaluation(
            evaluation_id=_stable_id("EVAL-EXEC-BLOCK", control.mission_id, task.task_id, tc_id, status, reason),
            mission_id=control.mission_id,
            node="EXECUTION",
            artifact_refs=[artifact.artifact_id],
            result=(EvaluationResult.HUMAN_REQUIRED if human_required else EvaluationResult.BLOCKED),
            evaluator_ref="rc7.1-runtime-execution-blocker",
            dimensions={"tc_id": tc_id, "status": status, "reason": reason, "test_result": "BLOCKED"},
            gap_refs=[gap.gap_id],
            evidence_refs=[evidence_id],
        )
        control.accept_evaluation(task.task_id, evaluation=evaluation, gaps=(gap,))

    def run(self, control: ClosedLoopControlPlane, task: Task) -> None:
        if task.node != "EXECUTION":
            raise BankExecutionAutopilotError("EXECUTION_TASK_REQUIRED")
        if task.task_type == "REPAIR":
            try:
                self.n8_recovery.handle_execution_repair(control, task)
            except BankN8RecoveryError as exc:
                raise BankExecutionAutopilotError("EXECUTION_N8_DIRECT_REPAIR_FAILED:%s" % exc) from exc
            return
        tc_id = self._case_for_task(control, task)
        bundle = self.bundle_resolver.resolve(
            control.truth,
            mission_id=control.mission_id,
            tc_id=tc_id,
            cwd=str(self.package_root),
            env=None,
        )
        profile = self.profiles.get(bundle.spec.layer)
        blocker_worker = "rc7.1-execution-blocker"
        try:
            broker = self._capability_broker(tuple(profile.required_tools))
        except ExecutionCapabilityEvidenceError as exc:
            self._block(
                control,
                task,
                worker_ref=blocker_worker,
                tc_id=tc_id,
                status="FIELD_REQUIRED",
                reason=str(exc),
            )
            return
        active = self.execution.activate_task(
            control,
            task.task_id,
            bundle=bundle,
            target_id=self.target_id,
            authority=self.authority,
            tool_broker=broker,
        )
        preparation = CasePreparationService(control.truth, self.state_root)
        try:
            prepared_result = self.n8_successor.materialize_direct_successor(
                control,
                source_task_id=task.task_id,
                worker_id=active.runtime_worker_id,
                tc_id=tc_id,
                target_id=self.target_id,
            )
        except BankN8SuccessorError as exc:
            self._block(
                control,
                task,
                worker_ref=active.runtime_worker_id,
                tc_id=tc_id,
                status="BLOCKED_RECOVERY",
                reason="EXECUTION_N8_SUCCESSOR_FAIL_CLOSED:%s" % exc,
                details={"n8_successor_gate": "FAIL_CLOSED"},
                already_leased=True,
            )
            return
        if prepared_result is None:
            attempt_id = _stable_id(
                "ATT-CASE",
                control.mission_id,
                task.task_id,
                tc_id,
                str(bundle.spec.case_version),
                self.target_id,
            )
            prepared_result = preparation.prepare(
                mission_id=control.mission_id,
                task_id=task.task_id,
                worker_id=active.runtime_worker_id,
                case=bundle.frozen_case,
                attempt_id=attempt_id,
                target_id=self.target_id,
            )
        if prepared_result.get("status") != "PREPARED":
            human = prepared_result.get("status") == "HUMAN_GATE_REQUIRED"
            self._block(
                control,
                task,
                worker_ref=active.runtime_worker_id,
                tc_id=tc_id,
                status=str(prepared_result.get("status") or "BLOCKED_PREPARATION"),
                reason=str(prepared_result.get("reason") or prepared_result.get("field_required_capability") or "preparation blocked"),
                human_required=human,
                details=dict(prepared_result),
                already_leased=True,
            )
            return
        try:
            n5 = self.preparation_closure.adopt_case_and_gate(
                control,
                run_id=self._autonomous_run_id(control),
                execution_task_id=task.task_id,
                case=bundle.frozen_case,
                prepared_result=prepared_result,
                accepted_cases=self._accepted_frozen_cases(control),
            )
        except (BankAutonomousPreparationClosureError, BankExecutionAutopilotError) as exc:
            self._block(
                control,
                task,
                worker_ref=active.runtime_worker_id,
                tc_id=tc_id,
                status="BLOCKED_PREPARATION",
                reason="EXECUTION_N5_FAIL_CLOSED:%s" % exc,
                details={"n5_gate": "FAIL_CLOSED"},
                already_leased=True,
            )
            return
        result = self.execution.execute_active_task(
            control,
            task.task_id,
            bundle=bundle,
            prepared=n5.prepared,
            active=active,
            authority=self.authority,
            tool_broker=broker,
            oracle_evaluator=self.oracle,
            cwd=str(self.package_root),
            env=None,
        )
        try:
            self.n8_recovery.capture_after_execution(
                control,
                source_task_id=task.task_id,
                result=result,
            )
        except BankN8RecoveryError as exc:
            raise BankExecutionAutopilotError("EXECUTION_N8_CAPTURE_FAILED:%s" % exc) from exc
