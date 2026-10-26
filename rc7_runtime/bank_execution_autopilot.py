"""RC7.1 runtime-owned EXECUTION stage for BANK Mission Autopilot.

One invocation handles exactly the Case owned by the current canonical EXECUTION
or EXECUTION/REPAIR task. Multi-case progress is governed by CASE_FANOUT_CONTRACT.
No capability is assumed READY: tool admission comes only from field/runtime
capability evidence. Current-Attempt CAT hardening is delegated to the bank
execution service; missing CAT readiness blocks diagnosis rather than execution.

For a new Case-fanout Mission, business execution is forbidden until the whole
accepted-case denominator has real field preparation, canonical N5 artifacts,
and an independent Director ACCEPT. A later per-Case repair may refresh its own
preparation, but it may never bypass that current-run N5 terminal truth.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional, Tuple

from rc6_runtime.execution import ExecutionProfileRegistry
from rc6_runtime.preparation import PreparedAttempt

from .authority import RC7AuthorityRuntime
from .bank_attempt_cat_execution import BankAttemptCatRuntimeExecutionService
from .bank_preparation_batch_gate import BankPreparationBatchGate, BankPreparationBatchGateError
from .case_fanout_conformance import AcceptedCaseInventoryReader
from .case_runtime import CasePreparationService
from .case_script_bundle_resolver import CaseScriptExecutionBundleResolver
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .execution_capability import ExecutionCapabilityBrokerFactory, ExecutionCapabilityEvidenceError
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
        self.capability_snapshot = (
            Path(capability_snapshot).expanduser().resolve() if capability_snapshot else None
        )
        self.inventory = AcceptedCaseInventoryReader()
        self.bundle_resolver = CaseScriptExecutionBundleResolver(
            evidence_root=str(self.evidence_root / "script-runtime"),
            validation_timeout_seconds=min(max(30, timeout_seconds), 300),
        )
        self.execution = BankAttemptCatRuntimeExecutionService(
            evidence_root=str(self.evidence_root / "formal-execution"),
            state_root=str(self.state_root),
            timeout_seconds=timeout_seconds,
        )
        self.oracle = DeterministicOracleRuntime()
        self.profiles = ExecutionProfileRegistry(RC7_1_EXECUTION_PROFILES)
        self.preparation_factory = CasePreparationService
        self.n5_preparation = BankPreparationBatchGate(
            state_root=str(self.state_root),
            evidence_root=str(self.evidence_root / "autonomous-node-closure"),
            target_id=self.target_id,
            max_freshness_seconds=min(max(30, timeout_seconds), 300),
        )

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

    @staticmethod
    def _prepared(raw: dict) -> PreparedAttempt:
        try:
            return PreparedAttempt(
                status=str(raw["status"]),
                attempt_id=str(raw["attempt_id"]),
                tc_id=str(raw["tc_id"]),
                case_version=int(raw["case_version"]),
                target_id=str(raw["target_id"]),
                precondition_evidence=tuple(raw.get("precondition_evidence") or ()),
                initial_state_bindings=dict(raw.get("initial_state_bindings") or {}),
                input_data_bindings=dict(raw.get("input_data_bindings") or {}),
                binding_evidence=tuple(raw.get("binding_evidence") or ()),
                cleanup_policy=dict(raw.get("cleanup_policy") or {}),
                oracle_snapshot=dict(raw.get("oracle_snapshot") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BankExecutionAutopilotError("PREPARED_ATTEMPT_PAYLOAD_INVALID") from exc

    def _capability_broker(self, required_tools: Tuple[str, ...]):
        if self.capability_snapshot is None:
            raise ExecutionCapabilityEvidenceError("EXECUTION_CAPABILITY_SNAPSHOT_REQUIRED")
        factory = ExecutionCapabilityBrokerFactory(self.capability_snapshot)
        requested = list(required_tools)
        # CAT is loaded only when the field snapshot already carries real
        # discovery/executable/registration/probe/target-readiness evidence.
        # If absent, execution can still run; a CAT-required failure later
        # remains BLOCKED/EVIDENCE_GAP instead of being self-qualified here.
        if "cat" in factory.tools and "cat" not in requested:
            requested.append("cat")
        return factory.build(
            target_id=self.target_id,
            required_tools=tuple(requested),
        )

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
            WorkerOutput(
                task_id=task.task_id,
                worker_ref=worker_ref,
                artifacts=(artifact,),
                evidence=(evidence,),
            )
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

    def _prepare(
        self,
        preparation: CasePreparationService,
        *,
        control: ClosedLoopControlPlane,
        task: Task,
        worker_id: str,
        tc_id: str,
        bundle,
        batch: bool,
    ) -> dict:
        attempt_id = _stable_id(
            "ATT-N5-BATCH" if batch else "ATT-CASE",
            control.mission_id,
            task.task_id,
            tc_id,
            str(bundle.spec.case_version),
            self.target_id,
        )
        result = preparation.prepare(
            mission_id=control.mission_id,
            task_id=task.task_id,
            worker_id=worker_id,
            case=bundle.frozen_case,
            attempt_id=attempt_id,
            target_id=self.target_id,
        )
        if result.get("status") == "PREPARED":
            preparation.require_prepared(
                mission_id=control.mission_id,
                task_id=task.task_id,
                prepared_attempt=dict(result["prepared_attempt"]),
            )
        return result

    def _block_preparation_result(
        self,
        control: ClosedLoopControlPlane,
        task: Task,
        *,
        worker_id: str,
        tc_id: str,
        prepared_result: dict,
    ) -> None:
        human = prepared_result.get("status") == "HUMAN_GATE_REQUIRED"
        self._block(
            control,
            task,
            worker_ref=worker_id,
            tc_id=tc_id,
            status=str(prepared_result.get("status") or "BLOCKED_PREPARATION"),
            reason=str(
                prepared_result.get("reason")
                or prepared_result.get("field_required_capability")
                or "preparation blocked"
            ),
            human_required=human,
            details=dict(prepared_result),
            already_leased=True,
        )

    def run(self, control: ClosedLoopControlPlane, task: Task) -> None:
        if task.node != "EXECUTION":
            raise BankExecutionAutopilotError("EXECUTION_TASK_REQUIRED")
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
        preparation = self.preparation_factory(control.truth, self.state_root)
        current_result = None

        try:
            n5_accepted = self.n5_preparation.accepted(control)
        except BankPreparationBatchGateError as exc:
            self._block(
                control,
                task,
                worker_ref=active.runtime_worker_id,
                tc_id=tc_id,
                status="N5_BATCH_GATE_BLOCKED",
                reason=str(exc),
                already_leased=True,
            )
            return

        if not n5_accepted:
            inventory = self.inventory.load(control.truth, control.mission_id)
            batch_cases = []
            batch_results = []
            for batch_tc_id in inventory.tc_ids:
                batch_bundle = (
                    bundle
                    if batch_tc_id == tc_id
                    else self.bundle_resolver.resolve(
                        control.truth,
                        mission_id=control.mission_id,
                        tc_id=batch_tc_id,
                        cwd=str(self.package_root),
                        env=None,
                    )
                )
                prepared_result = self._prepare(
                    preparation,
                    control=control,
                    task=task,
                    worker_id=active.runtime_worker_id,
                    tc_id=batch_tc_id,
                    bundle=batch_bundle,
                    batch=True,
                )
                if prepared_result.get("status") != "PREPARED":
                    self._block_preparation_result(
                        control,
                        task,
                        worker_id=active.runtime_worker_id,
                        tc_id=batch_tc_id,
                        prepared_result=dict(prepared_result),
                    )
                    return
                batch_cases.append(batch_bundle.frozen_case)
                batch_results.append(dict(prepared_result))
                if batch_tc_id == tc_id:
                    current_result = dict(prepared_result)
            if current_result is None:
                self._block(
                    control,
                    task,
                    worker_ref=active.runtime_worker_id,
                    tc_id=tc_id,
                    status="N5_BATCH_GATE_BLOCKED",
                    reason="N5_CURRENT_CASE_NOT_IN_ACCEPTED_DENOMINATOR",
                    already_leased=True,
                )
                return
            try:
                self.n5_preparation.close_batch(
                    control,
                    execution_task_id=task.task_id,
                    worker_id=active.runtime_worker_id,
                    cases=batch_cases,
                    prepared_results=batch_results,
                )
            except BankPreparationBatchGateError as exc:
                self._block(
                    control,
                    task,
                    worker_ref=active.runtime_worker_id,
                    tc_id=tc_id,
                    status="N5_BATCH_GATE_BLOCKED",
                    reason=str(exc),
                    already_leased=True,
                )
                return
        else:
            current_result = self._prepare(
                preparation,
                control=control,
                task=task,
                worker_id=active.runtime_worker_id,
                tc_id=tc_id,
                bundle=bundle,
                batch=False,
            )
            if current_result.get("status") != "PREPARED":
                self._block_preparation_result(
                    control,
                    task,
                    worker_id=active.runtime_worker_id,
                    tc_id=tc_id,
                    prepared_result=dict(current_result),
                )
                return

        # Hard main-chain gate: business execution is reached only after the
        # whole current-run N5 denominator has an independent Director terminal.
        try:
            if not self.n5_preparation.accepted(control):
                raise BankPreparationBatchGateError("BANK_N5_DIRECTOR_TERMINAL_REQUIRED")
        except BankPreparationBatchGateError as exc:
            self._block(
                control,
                task,
                worker_ref=active.runtime_worker_id,
                tc_id=tc_id,
                status="N5_BATCH_GATE_BLOCKED",
                reason=str(exc),
                already_leased=True,
            )
            return

        prepared = self._prepared(dict(current_result["prepared_attempt"]))
        self.execution.execute_active_task(
            control,
            task.task_id,
            bundle=bundle,
            prepared=prepared,
            active=active,
            authority=self.authority,
            tool_broker=broker,
            oracle_evaluator=self.oracle,
            cwd=str(self.package_root),
            env=None,
        )
