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
from .rc72_code_tool_binding import canonical_code_tools
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
from .rc72_official_journey_execution import OfficialJourneyExecutionService
from .rc72_journey_n7_adapter import SignedN7OfficialBSKAdapter, SignedN7OfficialJourneyAdapter
from .rc72_journey_bsk import JourneyBSKAdapter
from .rc72_journey_playwright import JourneyPlaywrightAdapter
from .rc72_n8_product_recovery import NativeN8ProductRecoveryService
from .rc72_n9_professional_dsh import NativeN9ProfessionalDshAnalysisService
from .rc72_capability_broker import CapabilityBroker, CapabilityPolicyRule
from .rc72_n9_accepted_scope import AcceptedScopeN9Service
from .rc72_expected_scope_input import ExpectedScopeInputService
from .rc72_libra_measurement import NativeLibraMeasurementService
from .rc72_native_coverage_intake import NativeCoverageGapIntakeService
from .rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService
from .rc72_native_coverage_repair import NativeCoverageRepairService
from .rc72_native_coverage_rerun import NativeCoverageRerunService
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
class MissionCaptainBinding:
    """Scoped host-owned Captain lease; never an implicit Full Access grant.

    The runtime scheduler validates its persisted Captain generation and
    signed TaskLease at dispatch time. The factory only verifies ownership
    and binds it into the real formal N7 pipeline.
    """
    scheduler: object
    captain_session_id: str
    captain_lease_id: str
    team_id: str


@dataclass(frozen=True)
class MissionProfessionalDshBinding:
    """Separate host-owned, tool-limited N9 analyst; never an N7 retry worker."""
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
    captain_binding: object = None
    capability_policies: object = None
    official_bsk_execution: object = None
    official_playwright_execution: object = None
    professional_dsh_binding: object = None


def create_mission_driver(truth, *, release_id, source_commit, workers,
                          bank_pip_mirror, execution_authority,
                          execution_environment, tool_registry, evidence_root,
                          execution_env=None, captain_binding=None, capability_policies=None,
                          official_bsk_execution=None, official_playwright_execution=None,
                          professional_dsh_binding=None):
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
    try:
        for role in ('code','code_review'):
            canonical_code_tools(bindings[role].tools,allow_legacy=False)
    except ValueError:
        raise ContractError('MISSION_FACTORY_REQUIRED_CODE_TOOLS_CHANGED')
    if (type(bank_pip_mirror) is not NativeBankPipMirrorService
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

    captain_kwargs = {}
    if captain_binding is not None:
        from .rc72_captain_scheduling import CaptainFencedWorkItemScheduler
        from .rc72_captain_dispatch_fencing import CaptainDispatchFencer
        if not isinstance(captain_binding, MissionCaptainBinding):
            raise ContractError('MISSION_FACTORY_TYPED_CAPTAIN_BINDING_REQUIRED')
        governed = captain_binding.scheduler
        if (not isinstance(governed, CaptainFencedWorkItemScheduler)
                or governed.truth is not truth or governed.release_id != release_id
                or not isinstance(governed.fencer, CaptainDispatchFencer)
                or governed.fencer.truth is not truth or governed.fencer.release_id != release_id
                or governed.lifecycle.truth is not truth or governed.lifecycle.release_id != release_id
                or governed.scheduler.truth is not truth or governed.scheduler.release_id != release_id):
            raise ContractError('MISSION_FACTORY_CAPTAIN_CANONICAL_RUNTIME_REQUIRED')
        if any(not isinstance(value, str) or not value.strip() for value in (
                captain_binding.captain_session_id,
                captain_binding.captain_lease_id, captain_binding.team_id)):
            raise ContractError('MISSION_FACTORY_CAPTAIN_SCOPE_REQUIRED')
        captain_kwargs = dict(captain_scheduler=governed,
                              captain_session_id=captain_binding.captain_session_id,
                              captain_lease_id=captain_binding.captain_lease_id,
                              team_id=captain_binding.team_id)

    # Policy is host-owned and must select an exact tool in the N7 registry.
    # Missing policy deliberately maps to the native Broker DENY outcome;
    # never infer administrative permission or a physical tool restoration.
    allowed_execution_tools = {t for group in tool_registry.values() for t in group}
    if (capability_policies is not None and
            (not isinstance(capability_policies, dict)
             or any(not isinstance(tool, str) or tool not in allowed_execution_tools
                    or not isinstance(rule, CapabilityPolicyRule)
                    for tool, rule in capability_policies.items()))):
        raise ContractError('MISSION_FACTORY_EXACT_CAPABILITY_POLICY_REQUIRED')

    # Do not infer a BrowserSkill session or full-access route from a name:
    # the host must bind a B-owned pool and real BSK adapter for this release.
    bsk_registered = 'journey_bsk' in allowed_execution_tools
    if bsk_registered != (official_bsk_execution is not None):
        raise ContractError('MISSION_FACTORY_BSK_APPROVED_TOOL_AND_EXECUTOR_REQUIRED')
    official_journey_adapters = {}
    if bsk_registered:
        if (not isinstance(official_bsk_execution, OfficialJourneyExecutionService)
                or official_bsk_execution.truth is not truth
                or official_bsk_execution.release_id != release_id
                or not isinstance(official_bsk_execution.adapter, JourneyBSKAdapter)
                or official_bsk_execution.adapter.pool is not official_bsk_execution.browser_pool
                or official_bsk_execution.browser_pool.truth is not truth
                or official_bsk_execution.browser_pool.release_id != release_id):
            raise ContractError('MISSION_FACTORY_BSK_NATIVE_HOST_OWNERSHIP_REQUIRED')
        official_journey_adapters['journey_bsk'] = SignedN7OfficialBSKAdapter(
            official_bsk_execution)

    # Playwright/CDP is an approved signed Journey, never the generic HTTP
    # runner. A registry name cannot invent a B-owned browser or 4A identity.
    playwright_registered = 'journey_playwright' in allowed_execution_tools
    if playwright_registered != (official_playwright_execution is not None):
        raise ContractError('MISSION_FACTORY_PLAYWRIGHT_APPROVED_TOOL_AND_EXECUTOR_REQUIRED')
    if playwright_registered:
        execution = official_playwright_execution
        if (type(execution) is not OfficialJourneyExecutionService
                or execution.truth is not truth
                or execution.release_id != release_id
                or type(execution.adapter) is not JourneyPlaywrightAdapter
                or execution.adapter.pool is not execution.browser_pool
                or execution.browser_pool.truth is not truth
                or execution.browser_pool.release_id != release_id
                or execution.adapter_kind != 'PLAYWRIGHT_CDP_LOCAL'
                or execution.trusted_field_adapter_kinds
                or execution.adapter.field_verified is not False):
            raise ContractError('MISSION_FACTORY_PLAYWRIGHT_NATIVE_HOST_OWNERSHIP_REQUIRED')
        official_journey_adapters['journey_playwright'] = SignedN7OfficialJourneyAdapter(
            execution)

    specialist = None
    if professional_dsh_binding is not None:
        if not isinstance(professional_dsh_binding, MissionProfessionalDshBinding):
            raise ContractError('MISSION_FACTORY_N9_TYPED_INDEPENDENT_BINDING_REQUIRED')
        analyst = professional_dsh_binding.launcher
        analyst_tools = professional_dsh_binding.tools
        if (not isinstance(analyst, DshHeadlessWorkerLauncher)
                or analyst.truth is not truth or analyst.release_id != release_id
                or not isinstance(analyst.authority, RC72AuthorityRuntime)
                or analyst.authority is execution_authority
                or id(analyst) in launchers
                or any(analyst.state_root.resolve() == old
                       or analyst.state_root.resolve() in old.parents
                       or old in analyst.state_root.resolve().parents
                       for old in roots)
                or not isinstance(analyst_tools, tuple) or not analyst_tools
                or len(set(analyst_tools)) != len(analyst_tools)
                or any(not isinstance(t, str) or not t.strip()
                       or '*' in t for t in analyst_tools)
                or set(analyst_tools) & allowed_execution_tools):
            raise ContractError('MISSION_FACTORY_N9_READONLY_ISOLATION_REQUIRED')

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
        capture_root=root/'execution-captures',
        official_journey_adapters=official_journey_adapters, **captain_kwargs)
    if professional_dsh_binding is not None:
        specialist = NativeN9ProfessionalDshAnalysisService(
            n7, launcher=professional_dsh_binding.launcher,
            allowed_tools=professional_dsh_binding.tools,
            captain_dsh_host_enabled=(captain_binding is not None))
    n8 = NativeN8ProductRecoveryService(n7, capability_broker=CapabilityBroker(
        truth, release_id=release_id, authority=execution_authority,
        policies=capability_policies or {}), professional_dsh=specialist)
    n9 = AcceptedScopeN9Service(n7)
    measurement = NativeLibraMeasurementService(expected, n9, capture_root=root/'coverage-captures')
    intake = NativeCoverageGapIntakeService(measurement)
    diagnosis = NativeCoveragePathDiagnosisService(intake, evidence_root=root/'coverage-diagnosis')
    # Production N10 must own the accepted repair -> fresh physical N7 ->
    # fresh Libra sequence; standalone component tests cannot substitute for
    # the ReleaseBatch product entry.  All three services share this R1 truth.
    repair = NativeCoverageRepairService(diagnosis)
    rerun = NativeCoverageRerunService(repair)
    n10 = NativeN10ControlService(expected, n9, measurement, intake, diagnosis,
        repair=repair, rerun=rerun)
    return ReleaseBatchDriver(truth, source_commit=source_commit,
        n1_launcher=launcher('reality'), n1_tools=tools('reality'),
        n2_launcher=launcher('requirement'), n2_tools=tools('requirement'),
        n2_evaluator=DshRequirementEvaluator(launcher('requirement_review'), allowed_tools=tools('requirement_review')),
        n3_pipeline=n3, n4_pipeline=n4, n5_pipeline=n5, n7_pipeline=n7,
        n8_pipeline=n8,
        n9_pipeline=n9, expected_scope=expected, n10_pipeline=n10, bank_pip_mirror=bank_pip_mirror)
