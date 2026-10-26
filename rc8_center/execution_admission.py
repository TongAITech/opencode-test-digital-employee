"""Deterministic Center admission gate for N7 case execution.

The gate runs before Center creates the N7 governance ATTEMPT_STARTED event.
It re-authorizes the exact current N4 frozen case, N5 PreparedAttempt and N6
ExecutableSpec.  Admission is not test execution and never creates PASS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from rc8_runtime.mission_graph import MissionStageType
from rc8_runtime.mission_nodes import MissionNodeAdoptionGraph, MissionNodeType, binding_for_stage

from .case_inventory import CenterFrozenCaseInventoryResolver, FrozenCaseInventoryError
from .executable_readiness import CenterExecutableReadinessService, ExecutableReadinessError
from .prepared_attempt import CenterPreparedAttemptService, PreparedAttemptError, PreparedAttemptState


class N7ExecutionAdmissionError(ValueError):
    pass


def _case_id_from_scope_refs(scope_refs: Sequence[str]) -> str:
    matches = []
    for ref in tuple(scope_refs or ()):
        if not isinstance(ref, str) or not ref.startswith("case:"):
            continue
        value = ref.split(":", 1)[1].strip()
        if value and value not in matches:
            matches.append(value)
    if len(matches) != 1:
        raise N7ExecutionAdmissionError("N7_CASE_SCOPE_REQUIRED")
    return matches[0]


@dataclass(frozen=True)
class N7ExecutionAdmission:
    test_run_id: str
    work_item_id: str
    case_id: str
    stage_instance_id: str
    mission_node_id: str
    prepared_attempt_id: str
    case_execution_attempt_id: str
    executable_spec_id: str
    frozen_case_ref: str
    case_inventory_ref: str
    case_inventory_fingerprint_ref: str


class CenterN7ExecutionAdmissionGate:
    """Fail-closed N7 start authorization over durable Center truth."""

    def __init__(
        self,
        *,
        governance_repository: object,
        case_inventory_resolver: CenterFrozenCaseInventoryResolver,
        prepared_attempts: CenterPreparedAttemptService,
        executable_readiness: CenterExecutableReadinessService,
    ) -> None:
        self.governance_repository = governance_repository
        self.case_inventory_resolver = case_inventory_resolver
        self.prepared_attempts = prepared_attempts
        self.executable_readiness = executable_readiness

    def authorize_start(self, *, work: object, stage_instance_id: Optional[str]) -> Optional[N7ExecutionAdmission]:
        if str(work.identity.stage) != MissionStageType.APPLICABLE_LAYER_EXECUTION.value:
            return None
        if not stage_instance_id:
            raise N7ExecutionAdmissionError("N7_STAGE_INSTANCE_REQUIRED")

        stage = self.governance_repository.get_stage(stage_instance_id)
        if stage is None:
            raise N7ExecutionAdmissionError("N7_STAGE_INSTANCE_REQUIRED")
        if stage.test_run_id != work.identity.test_run_id:
            raise N7ExecutionAdmissionError("N7_STAGE_TEST_RUN_MISMATCH")
        if stage.stage_type != MissionStageType.APPLICABLE_LAYER_EXECUTION.value:
            raise N7ExecutionAdmissionError("N7_STAGE_REQUIRED")

        binding = binding_for_stage(stage.stage_type)
        if binding.mission_node_type != MissionNodeType.N7_COVERAGE_DRIVEN_EXECUTION_CLOSURE:
            raise N7ExecutionAdmissionError("N7_MISSION_NODE_BINDING_REQUIRED")
        graph = MissionNodeAdoptionGraph(work.identity.test_run_id, stage.scope_version)
        mission_node = graph.node(binding.mission_node_type)

        case_id = _case_id_from_scope_refs(work.identity.scope_refs)
        try:
            inventory = self.case_inventory_resolver.resolve(
                test_run_id=work.identity.test_run_id,
                scope_version=stage.scope_version,
            )
        except FrozenCaseInventoryError as exc:
            raise N7ExecutionAdmissionError("N7_REQUIRES_CURRENT_N4_FROZEN_CASE:%s" % exc) from exc
        frozen_cases = [item for item in inventory.cases if item.case_id == case_id]
        if len(frozen_cases) != 1:
            raise N7ExecutionAdmissionError("N7_CASE_NOT_IN_FROZEN_INVENTORY")
        frozen_case = frozen_cases[0]
        required_inventory_refs = {
            frozen_case.case_revision_ref,
            inventory.artifact_ref,
            inventory.fingerprint_ref,
        }
        if not required_inventory_refs.issubset(set(work.identity.scope_refs)):
            raise N7ExecutionAdmissionError("N7_FROZEN_CASE_SCOPE_MISMATCH")

        prepared = self.prepared_attempts.current_for_case(
            test_run_id=work.identity.test_run_id,
            case_id=case_id,
        )
        if prepared is None:
            raise N7ExecutionAdmissionError("N7_REQUIRES_CURRENT_N5_PREPARED_ATTEMPT")
        if prepared.state != PreparedAttemptState.PREPARED:
            raise N7ExecutionAdmissionError("N7_REQUIRES_N5_PREPARED_STATE")
        expected_n5_node = graph.node(MissionNodeType.N5_TEST_DATA_PRECONDITIONS).mission_node_id
        if prepared.mission_node_id != expected_n5_node:
            raise N7ExecutionAdmissionError("N7_N5_SCOPE_VERSION_MISMATCH")
        try:
            self.prepared_attempts.require_current_for_execution(
                prepared_attempt_id=prepared.prepared_attempt_id,
                test_run_id=prepared.test_run_id,
                case_id=prepared.case_id,
                attempt_id=prepared.attempt_id,
            )
        except PreparedAttemptError as exc:
            raise N7ExecutionAdmissionError("N7_REQUIRES_CURRENT_N5_PREPARED_ATTEMPT:%s" % exc) from exc

        spec = self.executable_readiness.repository.current_for_attempt(
            work.identity.test_run_id,
            case_id,
            prepared.attempt_id,
        )
        if spec is None:
            raise N7ExecutionAdmissionError("N7_REQUIRES_CURRENT_N6_EXECUTABLE_SPEC")
        expected_n6_node = graph.node(MissionNodeType.N6_SCRIPT_BUILD_READINESS).mission_node_id
        if spec.mission_node_id != expected_n6_node:
            raise N7ExecutionAdmissionError("N7_N6_SCOPE_VERSION_MISMATCH")
        if spec.prepared_attempt_id != prepared.prepared_attempt_id:
            raise N7ExecutionAdmissionError("N7_N6_PREPARED_ATTEMPT_MISMATCH")
        if spec.frozen_case_ref != frozen_case.case_revision_ref:
            raise N7ExecutionAdmissionError("N7_N6_FROZEN_CASE_MISMATCH")
        try:
            current = self.executable_readiness.require_ready_for_execution(
                executable_spec_id=spec.executable_spec_id,
                prepared_attempt_id=prepared.prepared_attempt_id,
                test_run_id=work.identity.test_run_id,
                case_id=case_id,
                attempt_id=prepared.attempt_id,
            )
        except ExecutableReadinessError as exc:
            raise N7ExecutionAdmissionError("N7_REQUIRES_CURRENT_N6_READY:%s" % exc) from exc

        return N7ExecutionAdmission(
            test_run_id=work.identity.test_run_id,
            work_item_id=work.identity.work_item_id,
            case_id=case_id,
            stage_instance_id=stage_instance_id,
            mission_node_id=mission_node.mission_node_id,
            prepared_attempt_id=prepared.prepared_attempt_id,
            case_execution_attempt_id=prepared.attempt_id,
            executable_spec_id=current.executable_spec_id,
            frozen_case_ref=frozen_case.case_revision_ref,
            case_inventory_ref=inventory.artifact_ref,
            case_inventory_fingerprint_ref=inventory.fingerprint_ref,
        )
