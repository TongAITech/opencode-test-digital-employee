"""Owned native Mission composition. Construction alone executes no workers.

Host bindings provide scoped launchers and the execution adapter, never node
callbacks, evidence labels, or a replacement driver. Bank admission remains a
separate prerequisite and every native service retains its own evidence gate.
"""
from dataclasses import dataclass
from pathlib import Path
import re

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from .models import ContractError
from .execution_environment import ExecutionEnvironmentAdapter
from .rc72_authority import RC72AuthorityRuntime
from .rc72_bank_pip_mirror import NativeBankPipMirrorService
from .rc72_native_n1_launcher import NativeN1ReadDshLauncher
from .rc72_n1_strict_pipeline import N1StrictPipelineService
from .dsh_requirement_evaluator import DshRequirementEvaluator
from .dsh_code_evaluator import DshCodeEvaluator
from .rc72_n3_pipeline import N3PipelineService
from .rc72_n4_pipeline import N4PipelineService
from .rc72_n4_parent_guard import N4ParentScopedDesignEvaluator
from .rc72_n5_pipeline import N5PipelineService
from .rc72_n7_execution_preparation import ExecutionPreparationService
from .rc72_formal_runner import FormalN7RunnerAdapter
from .rc72_n7_pipeline import N7PipelineService
from .rc72_n9_accepted_scope import AcceptedScopeN9Service
from .rc72_expected_scope_input import ExpectedScopeInputService
from .rc72_libra_measurement import NativeLibraMeasurementService
from .rc72_native_coverage_intake import NativeCoverageGapIntakeService
from .rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService
from .rc72_n10_control import NativeN10ControlService
from .rc72_release_driver import ReleaseBatchDriver


ROLES = ('reality', 'requirement', 'requirement_review', 'source',
         'source_review', 'code', 'code_review', 'design', 'design_review',
         'data', 'data_verify')


@dataclass(frozen=True)
class MissionWorkerBinding:
    launcher: DshHeadlessWorkerLauncher
    tools: tuple


@dataclass(frozen=True)
class MissionHostBindings:
    """Approved host capabilities; no stage/evaluation/completion callbacks."""
    workers: dict
    bank_pip_mirror: NativeBankPipMirrorService
    execution_authority: RC72AuthorityRuntime
    execution_environment: ExecutionEnvironmentAdapter
    tool_registry: dict
    execution_env: object = None


def create_mission_driver(truth, *, release_id, source_commit, workers,
                          bank_pip_mirror, execution_authority,
                          execution_environment, tool_registry, evidence_root,
                          execution_env=None):
    """Compose all implemented native routes against one ledger/source/release.

    Missing roles fail before constructing pipelines or touching the ledger.
    This is composition, not Field qualification or a terminal PASS decision.
    """
    if not isinstance(source_commit, str) or not re.fullmatch('[0-9a-f]{40}', source_commit):
        raise ContractError('MISSION_FACTORY_EXACT_SOURCE_REQUIRED')
    if not isinstance(release_id, str) or not release_id.strip():
        raise ContractError('MISSION_FACTORY_RELEASE_REQUIRED')
    if not isinstance(workers, dict) or set(workers) != set(ROLES):
        raise ContractError('MISSION_FACTORY_EXACT_ROLES_REQUIRED')
    bindings = dict(workers)
    roots = set()
    launchers = set()
    for role in ROLES:
        binding = bindings[role]
        if not isinstance(binding, MissionWorkerBinding):
            raise ContractError('MISSION_FACTORY_TYPED_WORKER_REQUIRED')
        worker = binding.launcher
        if (not isinstance(worker, DshHeadlessWorkerLauncher) or worker.truth is not truth
                or worker.release_id != release_id or not isinstance(worker.authority, RC72AuthorityRuntime)):
            raise ContractError('MISSION_FACTORY_WORKER_SCOPE_MISMATCH')
        if (not isinstance(binding.tools, tuple) or not binding.tools
                or any(not isinstance(t, str) or not t.strip() or '*' in t for t in binding.tools)
                or len(set(binding.tools)) != len(binding.tools)):
            raise ContractError('MISSION_FACTORY_EXACT_TOOLS_REQUIRED')
        root = worker.state_root.resolve()
        if id(worker) in launchers or any(root == old or root in old.parents or old in root.parents for old in roots):
            raise ContractError('MISSION_FACTORY_PRIVATE_ROLE_ROOT_REQUIRED')
        roots.add(root)
        launchers.add(id(worker))
    if not isinstance(bindings['reality'].launcher, NativeN1ReadDshLauncher):
        raise ContractError('MISSION_FACTORY_NATIVE_INPUT_READ_REQUIRED')
    if any(set(bindings[role].tools) != {'git', 'codegraph'} for role in ('code', 'code_review')):
        raise ContractError('MISSION_FACTORY_REQUIRED_CODE_TOOLS_CHANGED')
    if (not isinstance(bank_pip_mirror, NativeBankPipMirrorService)
            or bank_pip_mirror.truth is not truth or bank_pip_mirror.release_id != release_id
            or bank_pip_mirror.source_commit != source_commit):
        raise ContractError('MISSION_FACTORY_NATIVE_MIRROR_SCOPE_MISMATCH')
    if not isinstance(execution_authority, RC72AuthorityRuntime):
        raise ContractError('MISSION_FACTORY_NATIVE_EXECUTION_AUTHORITY_REQUIRED')
    if not isinstance(execution_environment, ExecutionEnvironmentAdapter):
        raise ContractError('MISSION_FACTORY_EXECUTION_ENVIRONMENT_REQUIRED')
    if (not isinstance(tool_registry, dict) or not tool_registry
            or any(not isinstance(family, str) or not family or not isinstance(tools, (list, tuple))
                   or not tools or any(not isinstance(t, str) or not t.strip() or '*' in t for t in tools)
                   or len(set(tools)) != len(tools)
                   for family, tools in tool_registry.items())):
        raise ContractError('MISSION_FACTORY_EXACT_EXECUTION_TOOLS_REQUIRED')

    def launcher(role):
        return bindings[role].launcher

    def tools(role):
        return bindings[role].tools

    root = Path(evidence_root).resolve()
    expected = ExpectedScopeInputService(N1StrictPipelineService(truth, source_commit=source_commit,
        launcher=launcher('reality'), allowed_tools=tools('reality')))
    n3 = N3PipelineService(truth, source_commit=source_commit,
        source_launcher=launcher('source'), source_tools=tools('source'),
        source_reviewer=launcher('source_review'), source_review_tools=tools('source_review'),
        code_launcher=launcher('code'), code_tools=tools('code'),
        code_evaluator=DshCodeEvaluator(launcher('code_review'), reviewer_allowed_tools=tools('code_review')))
    n4 = N4PipelineService(truth, source_commit=source_commit, launcher=launcher('design'),
        allowed_tools=tools('design'), evaluator=N4ParentScopedDesignEvaluator(
            launcher('design_review'), reviewer_allowed_tools=tools('design_review')))
    n5 = N5PipelineService(truth, source_commit=source_commit, launcher=launcher('data'),
        allowed_tools=tools('data'), verifier=launcher('data_verify'), verification_tools=tools('data_verify'))
    preparation = ExecutionPreparationService(truth, release_id=release_id, source_commit=source_commit,
        authority=execution_authority, tool_registry={k: tuple(v) for k, v in tool_registry.items()})
    n7 = N7PipelineService(preparation, runner=FormalN7RunnerAdapter(preparation,
        evidence_root=root/'runner', execution_env=execution_env, environment_adapter=execution_environment),
        capture_root=root/'execution-captures')
    n9 = AcceptedScopeN9Service(n7)
    measurement = NativeLibraMeasurementService(expected, n9, capture_root=root/'coverage-captures')
    intake = NativeCoverageGapIntakeService(measurement)
    diagnosis = NativeCoveragePathDiagnosisService(intake, evidence_root=root/'coverage-diagnosis')
    n10 = NativeN10ControlService(expected, n9, measurement, intake, diagnosis)
    return ReleaseBatchDriver(truth, source_commit=source_commit,
        n1_launcher=launcher('reality'), n1_tools=tools('reality'),
        n2_launcher=launcher('requirement'), n2_tools=tools('requirement'),
        n2_evaluator=DshRequirementEvaluator(launcher('requirement_review'), allowed_tools=tools('requirement_review')),
        n3_pipeline=n3, n4_pipeline=n4, n5_pipeline=n5, n7_pipeline=n7,
        n9_pipeline=n9, expected_scope=expected, n10_pipeline=n10, bank_pip_mirror=bank_pip_mirror)
