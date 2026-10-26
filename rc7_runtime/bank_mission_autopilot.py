"""RC7.1 production Mission Autopilot composition.

Durable BANK Mission bootstrap is driven from canonical R1 through Runtime-owned
Reality Recon, authorized DSH producer Workers, independent evaluators, per-Case
Script fan-out and Runtime-owned per-Case Execution. No stage treats model text
as PASS and no target/capability identity is guessed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .active_task_supervisor import MissionActiveTaskSupervisor
from .authority import RC7AuthorityRuntime
from .authorized_dsh_launcher import Rc7AuthorizedDshHeadlessWorkerLauncher
from .autonomous_n10_governed import GovernedAutonomousN10FinalizationService
from .autonomous_n10_node import AutonomousN10Error
from .bank_autonomous_node_closure import (
    BankAutonomousNodeClosureCoordinator,
    BankAutonomousNodeClosureError,
)
from .bank_dsh_tool_policy import FIELD_NODE_POLICIES
from .bank_execution_autopilot import BankExecutionAutopilot
from .bank_mission import start_or_resume
from .bank_mission_director import BankMissionDirectorGate, BankMissionDirectorGateError
from .bank_n7_execution_closure import (
    BankN7ExecutionClosureCoordinator,
    BankN7ExecutionClosureError,
)
from .bank_n8_dsh_bridge import BankN8AwareDshTaskWorkerBridge
from .bank_n8_owner_repair_evaluator import (
    BankN8OwnerRepairEvaluationError,
    BankN8OwnerRepairEvaluator,
)
from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .dsh_code_evaluator import DshCodeEvaluator
from .dsh_requirement_evaluator import DshRequirementEvaluator
from .dsh_test_design_oracle_evaluator import DshExecutionReadyTestDesignEvaluator
from .mission_autonomous_driver import MissionAutonomousDriver, MissionAutonomousDriverError
from .mission_stage_dispatch import MissionStageDispatcher
from .models import Task, TaskStatus
from .reality_recon import RuntimeRealityReconService
from .script_contract import AcceptedTestDesignScriptContractCompiler
from .script_fanout_evaluator import DshCaseFanoutScriptEvaluator


class BankMissionAutopilotError(RuntimeError):
    pass


@dataclass(frozen=True)
class BankMissionAutopilotConfig:
    r1_path: Path
    mission_id: str
    release_id: str
    goal: str
    run_id: str
    package_root: Path
    state_root: Path
    evidence_root: Path
    dsh_bin: Path
    patch_path: Path
    target_id: str
    source_revision: str
    repository_ref: str
    runtime_profile: str
    reality_evidence_refs: Tuple[str, ...]
    execution_capability_snapshot: Optional[Path]
    max_steps: int = 100
    timeout_seconds: int = 300


def _required_text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BankMissionAutopilotError(code)
    return value.strip()


def _runtime_owned_run_id(*, release_id: str, mission_id: str) -> str:
    """Return the stable Runtime-owned autonomous-run identity for a Mission.

    This is identity creation, not target/business guessing: release and Mission
    identities are already explicit durable inputs. The deterministic value lets
    process/session restarts rejoin the same N1-N10 run without requiring a
    human to invent an extra identifier.
    """
    release = _required_text(release_id, "AUTOPILOT_RELEASE_ID_REQUIRED")
    mission = _required_text(mission_id, "AUTOPILOT_MISSION_ID_REQUIRED")
    digest = hashlib.sha256((release + "\x1f" + mission).encode("utf-8")).hexdigest()[:24]
    return "RUN-RC71-" + digest


def _read_text(path: Path, code: str) -> str:
    if not path.is_file():
        raise BankMissionAutopilotError(code + ":" + str(path))
    value = path.read_text(encoding="utf-8", errors="replace").strip()
    return _required_text(value, code)


def _runtime_profile_from_file(package_root: Path) -> Tuple[str, Path]:
    path = package_root / "state" / "rc7-dsh-runtime-profile.json"
    if not path.is_file():
        raise BankMissionAutopilotError("AUTOPILOT_RUNTIME_PROFILE_EVIDENCE_REQUIRED:%s" % path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BankMissionAutopilotError("AUTOPILOT_RUNTIME_PROFILE_INVALID:%s" % path) from exc
    profile = payload.get("runtime_profile") if isinstance(payload, dict) else None
    return _required_text(profile, "AUTOPILOT_RUNTIME_PROFILE_REQUIRED"), path


def _authority_secret(state_root: Path) -> bytes:
    folder = state_root / "authority"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "rc7-authority.key"
    if path.is_file():
        raw = path.read_bytes()
        if len(raw) < 32:
            raise BankMissionAutopilotError("AUTOPILOT_AUTHORITY_SECRET_INVALID")
        return raw
    raw = secrets.token_bytes(48)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError:
        raw = path.read_bytes()
        if len(raw) < 32:
            raise BankMissionAutopilotError("AUTOPILOT_AUTHORITY_SECRET_INVALID")
        return raw
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return raw


def discover_config(
    *,
    r1_path: str,
    mission_id: str,
    release_id: str,
    goal: str,
    run_id: Optional[str] = None,
    package_root: Optional[str] = None,
    state_root: Optional[str] = None,
    evidence_root: Optional[str] = None,
    dsh_bin: Optional[str] = None,
    patch_path: Optional[str] = None,
    target_id: Optional[str] = None,
    source_revision: Optional[str] = None,
    repository_ref: Optional[str] = None,
    runtime_profile: Optional[str] = None,
    execution_capability_snapshot: Optional[str] = None,
    max_steps: int = 100,
    timeout_seconds: int = 300,
) -> BankMissionAutopilotConfig:
    r1 = Path(_required_text(r1_path, "AUTOPILOT_R1_REQUIRED")).expanduser().resolve()
    root = Path(package_root).expanduser().resolve() if package_root else r1.parent.parent.parent.resolve()
    state = Path(state_root).expanduser().resolve() if state_root else (root / "runtime-state").resolve()
    evidence = Path(evidence_root).expanduser().resolve() if evidence_root else (state / "evidence").resolve()
    state.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)

    mission = _required_text(mission_id, "AUTOPILOT_MISSION_ID_REQUIRED")
    release = _required_text(release_id, "AUTOPILOT_RELEASE_ID_REQUIRED")

    source_path = root / "SOURCE_COMMIT"
    source = source_revision or os.environ.get("PFC_RC7_SOURCE_REVISION")
    if not source:
        source = _read_text(source_path, "AUTOPILOT_SOURCE_REVISION_REQUIRED")
    source = _required_text(source, "AUTOPILOT_SOURCE_REVISION_REQUIRED")

    profile_path: Optional[Path] = None
    profile = runtime_profile or os.environ.get("PFC_RC7_DSH_PROFILE")
    if not profile:
        profile, profile_path = _runtime_profile_from_file(root)
    else:
        profile = _required_text(profile, "AUTOPILOT_RUNTIME_PROFILE_REQUIRED")
        candidate = root / "state" / "rc7-dsh-runtime-profile.json"
        if candidate.is_file():
            profile_path = candidate

    target = target_id or os.environ.get("PFC_RC7_TARGET_ID")
    target = _required_text(target, "AUTOPILOT_TARGET_ID_REQUIRED_NO_GUESSING")

    explicit_run_id = str(run_id or "").strip()
    environment_run_id = str(os.environ.get("PFC_RC7_AUTONOMOUS_RUN_ID") or "").strip()
    if explicit_run_id and environment_run_id and explicit_run_id != environment_run_id:
        raise BankMissionAutopilotError(
            "AUTOPILOT_RUN_ID_CLI_ENV_CONFLICT:%s:%s"
            % (explicit_run_id, environment_run_id)
        )
    autonomous_run_id = (
        explicit_run_id
        or environment_run_id
        or _runtime_owned_run_id(release_id=release, mission_id=mission)
    )

    binary_raw = dsh_bin or os.environ.get("PFC_RC7_DSH_BIN") or shutil.which("dsh")
    binary = Path(_required_text(binary_raw, "AUTOPILOT_DSH_BIN_REQUIRED")).expanduser().resolve()
    if not binary.exists():
        raise BankMissionAutopilotError("AUTOPILOT_DSH_BIN_NOT_FOUND:%s" % binary)

    patch_raw = patch_path or os.environ.get("PFC_RC7_DSH_PATCH") or str(root / "state" / "rc7-dsh.patch.yml")
    patch = Path(_required_text(patch_raw, "AUTOPILOT_DSH_PATCH_REQUIRED")).expanduser().resolve()
    if not patch.is_file():
        raise BankMissionAutopilotError("AUTOPILOT_DSH_PATCH_NOT_FOUND:%s" % patch)

    repo = repository_ref or os.environ.get("PFC_RC7_REPOSITORY_REF") or str(root)
    repo = _required_text(repo, "AUTOPILOT_REPOSITORY_REF_REQUIRED")

    capability_raw = execution_capability_snapshot or os.environ.get("PFC_RC7_EXECUTION_CAPABILITY_SNAPSHOT")
    if capability_raw:
        capability_path: Optional[Path] = Path(capability_raw).expanduser().resolve()
    else:
        candidate = root / "state" / "execution-capabilities.json"
        capability_path = candidate.resolve() if candidate.is_file() else None

    evidence_refs = []
    if source_path.is_file():
        evidence_refs.append("file://" + str(source_path))
    if profile_path is not None and profile_path.is_file():
        evidence_refs.append("file://" + str(profile_path))
    if patch.is_file():
        evidence_refs.append("file://" + str(patch))
    if not evidence_refs:
        raise BankMissionAutopilotError("AUTOPILOT_REALITY_EVIDENCE_REQUIRED")

    return BankMissionAutopilotConfig(
        r1_path=r1,
        mission_id=mission,
        release_id=release,
        goal=_required_text(goal, "AUTOPILOT_GOAL_REQUIRED"),
        run_id=autonomous_run_id,
        package_root=root,
        state_root=state,
        evidence_root=evidence,
        dsh_bin=binary,
        patch_path=patch,
        target_id=target,
        source_revision=source,
        repository_ref=repo,
        runtime_profile=profile,
        reality_evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        execution_capability_snapshot=capability_path,
        max_steps=max(1, int(max_steps)),
        timeout_seconds=max(1, int(timeout_seconds)),
    )


class BankMissionAutopilot:
    def __init__(self, config: BankMissionAutopilotConfig) -> None:
        self.config = config
        self.truth = TruthRuntime(config.r1_path)
        self.control = ClosedLoopControlPlane(self.truth, config.release_id, config.mission_id)
        self.authority = RC7AuthorityRuntime(_authority_secret(config.state_root))
        self.launcher = Rc7AuthorizedDshHeadlessWorkerLauncher(
            dsh_bin=str(config.dsh_bin),
            patch_path=str(config.patch_path),
            cwd=str(config.package_root),
            truth=self.truth,
            authority=self.authority,
            coordinator_instance_id="rc7.1-bank-autopilot",
            release_id=config.release_id,
            state_root=str(config.state_root),
            timeout_seconds=config.timeout_seconds,
        )
        self.bridge = BankN8AwareDshTaskWorkerBridge(
            self.control,
            self.launcher,
            node_policies=FIELD_NODE_POLICIES,
        )
        self.supervisor = MissionActiveTaskSupervisor(
            self.control,
            self.bridge,
            evidence_root=str(config.evidence_root / "supervisor"),
        )
        self.requirement_evaluator = DshRequirementEvaluator(self.launcher)
        self.code_evaluator = DshCodeEvaluator(self.launcher)
        self.test_design_evaluator = DshExecutionReadyTestDesignEvaluator(self.launcher)
        self.script_evaluator = DshCaseFanoutScriptEvaluator(evidence_root=str(config.evidence_root))
        self.n8_owner_repair_evaluator = BankN8OwnerRepairEvaluator()
        self.script_compiler = AcceptedTestDesignScriptContractCompiler()
        self.reality = RuntimeRealityReconService(evidence_root=str(config.evidence_root / "reality"))
        self.node_closure = BankAutonomousNodeClosureCoordinator(
            release_id=config.release_id,
            run_id=config.run_id,
            evidence_root=str(config.evidence_root / "autonomous-node-closure"),
        )
        self.n7 = BankN7ExecutionClosureCoordinator(
            target_id=config.target_id,
            evidence_root=str(config.evidence_root / "n7"),
        )
        self.n10 = GovernedAutonomousN10FinalizationService(
            evidence_root=str(config.evidence_root / "n10")
        )
        self.director_gate = BankMissionDirectorGate(
            self.truth,
            release_id=config.release_id,
            evidence_root=str(config.evidence_root / "n10"),
        )
        self.reader = CandidatePayloadReader()
        self.execution = BankExecutionAutopilot(
            authority=self.authority,
            state_root=str(config.state_root),
            evidence_root=str(config.evidence_root),
            package_root=str(config.package_root),
            target_id=config.target_id,
            capability_snapshot=(str(config.execution_capability_snapshot) if config.execution_capability_snapshot else None),
            timeout_seconds=config.timeout_seconds,
        )

    @staticmethod
    def _single_output_artifact(task: Task) -> str:
        refs = [ref for ref in task.output_artifact_refs if isinstance(ref, str) and ref]
        if len(refs) != 1:
            raise BankMissionAutopilotError("AUTOPILOT_SINGLE_OUTPUT_ARTIFACT_REQUIRED:%s:%d" % (task.task_id, len(refs)))
        return refs[0]

    def _reconcile_evaluated_node(self, task_id: str, node_id: str) -> None:
        current = self.control.scheduler.task(task_id)
        if current.state != TaskStatus.PASS:
            return
        try:
            self.node_closure.reconcile_passed_task(
                self.control,
                node_id=node_id,
                source_task_id=task_id,
            )
        except BankAutonomousNodeClosureError as exc:
            raise BankMissionAutopilotError(
                "AUTOPILOT_AUTONOMOUS_NODE_CLOSURE_FAILED:%s:%s"
                % (node_id, exc)
            ) from exc

    def _reconcile_script_node(self, task_id: str) -> None:
        current = self.control.scheduler.task(task_id)
        if current.state != TaskStatus.PASS:
            return
        try:
            self.node_closure.reconcile_script_task(
                self.control,
                source_task_id=task_id,
            )
        except BankAutonomousNodeClosureError as exc:
            raise BankMissionAutopilotError(
                "AUTOPILOT_AUTONOMOUS_NODE_CLOSURE_FAILED:N6:%s" % exc
            ) from exc

    def _requirement_eval(self, task: Task) -> None:
        self.requirement_evaluator.evaluate_and_apply(
            self.control,
            task.task_id,
            self._single_output_artifact(task),
        )
        self._reconcile_evaluated_node(task.task_id, "N2")

    def _code_eval(self, task: Task) -> None:
        self.code_evaluator.evaluate_and_apply(
            self.control,
            task.task_id,
            self._single_output_artifact(task),
            target_id=self.config.target_id,
        )
        self._reconcile_evaluated_node(task.task_id, "N3")

    def _test_design_eval(self, task: Task) -> None:
        self.test_design_evaluator.evaluate_and_apply(
            self.control,
            task.task_id,
            self._single_output_artifact(task),
        )
        self._reconcile_evaluated_node(task.task_id, "N4")

    def _script_eval(self, task: Task) -> None:
        artifact_id = self._single_output_artifact(task)
        candidate = self.reader.load(
            self.control.truth,
            artifact_id,
            expected_mission_id=self.control.mission_id,
            expected_task_id=task.task_id,
        )
        binding = candidate.semantic_payload.get("binding")
        if not isinstance(binding, dict):
            raise BankMissionAutopilotError("AUTOPILOT_SCRIPT_BINDING_REQUIRED")
        tc_id = _required_text(binding.get("tc_id"), "AUTOPILOT_SCRIPT_TC_ID_REQUIRED")
        design_refs = [
            ref for ref in task.input_artifact_refs
            if self.control.truth.query("rc7_artifact", artifact_id=ref)
            and self.control.truth.query("rc7_artifact", artifact_id=ref)[0].get("artifact_type_name") == "TEST_DESIGN_MODEL"
        ]
        if len(design_refs) != 1:
            raise BankMissionAutopilotError("AUTOPILOT_SCRIPT_DESIGN_ARTIFACT_NOT_UNIQUE")
        contract = self.script_compiler.compile(
            self.control.truth,
            mission_id=self.control.mission_id,
            design_artifact_id=design_refs[0],
            tc_id=tc_id,
        )
        self.script_evaluator.evaluate_and_apply(
            self.control,
            task.task_id,
            artifact_id,
            contract=contract,
            cwd=str(self.config.package_root),
            env=None,
        )
        self._reconcile_script_node(task.task_id)

    def _n8_owner_repair_eval(self, task: Task) -> None:
        try:
            self.n8_owner_repair_evaluator.evaluate_and_apply(
                self.control,
                task.task_id,
                self._single_output_artifact(task),
            )
        except BankN8OwnerRepairEvaluationError as exc:
            raise BankMissionAutopilotError(
                "AUTOPILOT_N8_OWNER_REPAIR_EVALUATION_FAILED:%s" % exc
            ) from exc

    def _runtime_handler(self, task: Task) -> None:
        if task.node == "REALITY_RECON":
            self.reality.reconcile(
                self.control,
                task.task_id,
                facts={
                    "release_id": self.config.release_id,
                    "source_revision": self.config.source_revision,
                    "repository_ref": self.config.repository_ref,
                    "runtime_profile": self.config.runtime_profile,
                },
                evidence_refs=self.config.reality_evidence_refs,
            )
            return
        if task.node == "EXECUTION":
            self.execution.run(self.control, task)
            return
        raise BankMissionAutopilotError("AUTOPILOT_RUNTIME_NODE_UNSUPPORTED:%s" % task.node)

    def _convergence(self) -> None:
        try:
            self.node_closure.reconcile_passed_nodes(self.control)
            self.n7.close_current_batch(
                self.control,
                run_id=self.config.run_id,
            )
            prepared = self.n10.prepare_ready(
                self.control,
                run_id=self.config.run_id,
            )
            self.director_gate.review_and_accept(self.control, prepared)
            self.n10.converge_after_director_accept(
                self.control,
                run_id=self.config.run_id,
            )
        except (
            BankAutonomousNodeClosureError,
            BankN7ExecutionClosureError,
            AutonomousN10Error,
            BankMissionDirectorGateError,
        ) as exc:
            raise BankMissionAutopilotError(
                "AUTOPILOT_GOVERNED_CONVERGENCE_FAILED:%s" % exc
            ) from exc

    def _final_report(self):
        try:
            return self.n10.generate_final_report(
                self.control,
                run_id=self.config.run_id,
            )
        except AutonomousN10Error as exc:
            raise BankMissionAutopilotError(
                "AUTOPILOT_GOVERNED_N10_FINAL_REPORT_FAILED:%s" % exc
            ) from exc

    def drive(self):
        dispatcher = MissionStageDispatcher(
            self.control,
            producer_runner=self.bridge.run_next,
            runtime_handlers={
                "REALITY_RECON": self._runtime_handler,
                "EXECUTION": self._runtime_handler,
            },
        )
        driver = MissionAutonomousDriver(
            self.control,
            dispatcher,
            output_evaluators={
                "RUNTIME:REPAIR": self._n8_owner_repair_eval,
                "CODE_ANALYSIS:REPAIR": self._n8_owner_repair_eval,
                "SCRIPT_READINESS:REPAIR": self._n8_owner_repair_eval,
                "REQUIREMENT_ANALYSIS": self._requirement_eval,
                "CODE_ANALYSIS": self._code_eval,
                "TEST_DESIGN": self._test_design_eval,
                "SCRIPT_READINESS": self._script_eval,
            },
            active_task_handler=self.supervisor.handle,
            convergence_handler=self._convergence,
            final_report_handler=self._final_report,
        )
        return driver.drive(max_steps=self.config.max_steps)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run RC7.1 BANK Mission Autopilot from canonical R1")
    parser.add_argument("--r1", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--package-root")
    parser.add_argument("--state-root")
    parser.add_argument("--evidence-root")
    parser.add_argument("--dsh-bin")
    parser.add_argument("--patch")
    parser.add_argument("--target-id")
    parser.add_argument("--source-revision")
    parser.add_argument("--repository-ref")
    parser.add_argument("--runtime-profile")
    parser.add_argument("--execution-capability-snapshot")
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    start_or_resume(r1_path=args.r1, mission_id=args.mission_id, release_id=args.release_id, goal=args.goal)
    config = discover_config(
        r1_path=args.r1,
        mission_id=args.mission_id,
        release_id=args.release_id,
        goal=args.goal,
        run_id=args.run_id,
        package_root=args.package_root,
        state_root=args.state_root,
        evidence_root=args.evidence_root,
        dsh_bin=args.dsh_bin,
        patch_path=args.patch,
        target_id=args.target_id,
        source_revision=args.source_revision,
        repository_ref=args.repository_ref,
        runtime_profile=args.runtime_profile,
        execution_capability_snapshot=args.execution_capability_snapshot,
        max_steps=args.max_steps,
        timeout_seconds=args.timeout_seconds,
    )
    try:
        autopilot = BankMissionAutopilot(config)
        result = autopilot.drive()
    except (BankMissionAutopilotError, MissionAutonomousDriverError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    mission = autopilot.control._mission()
    payload = {
        "status": result.status,
        "mission_id": result.mission_id,
        "run_id": config.run_id,
        "steps": result.step_count,
        "last_action": result.action,
        "task_id": result.task_id,
        "node": result.node,
        "reason": result.reason,
        "mission_state": mission.state.value,
        "sufficiency_state": mission.sufficiency_state,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if result.status in {"CONVERGED", "CLOSED", "WAITING", "HUMAN_REQUIRED", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
