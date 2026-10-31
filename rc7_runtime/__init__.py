"""RC7 autonomous testing control-plane runtime.

RC7 is an additive refactor over the proven RC6 capability surface. The package
owns durable control-plane semantics while existing RC6 testing capabilities
remain reusable through the RC7 closed-loop adapters.
"""

# RC7.1 field fixes must be installed before the compatibility execution/worker
# modules below import their RC6 surfaces.
from .junit_reality import (
    RealityCheckedJUnitRunnerAdapter,
    install_rc7_1_junit_reality_gate,
)
from .worker_launch_reality import install_rc7_1_worker_timeout_diagnostics
from .model_resilience import (
    PersistentSlidingWindowGovernor,
    classify_failure,
    install_rc7_1_model_resilience,
)

install_rc7_1_junit_reality_gate()
install_rc7_1_worker_timeout_diagnostics()
install_rc7_1_model_resilience()

from .models import (
    Artifact,
    ArtifactStatus,
    Evaluation,
    EvaluationResult,
    EventRecord,
    Evidence,
    Gap,
    GapSeverity,
    GapStatus,
    Mission,
    MissionStatus,
    Task,
    TaskStatus,
)
from .state_machine import (
    ConvergenceInput,
    ConvergenceDecision,
    decide_convergence,
    invalidate_artifact,
    transition_gap,
    transition_mission,
    transition_task,
)
from .closed_loop_control import ClosedLoopControlError, ClosedLoopControlPlane
from .rc72_economy_control_plane import (
    RC72EconomyClosedLoopControlPlane,
    install_rc72_economy_control_plane_default,
)

install_rc72_economy_control_plane_default()
ClosedLoopControlPlane = RC72EconomyClosedLoopControlPlane

from .mission_graph import MissionTaskGraph, MissionTaskGraphCompiler
from .final_report import FinalReportError, RC7FinalReportBuilder
from .dsh_worker_bridge import (
    DEFAULT_NODE_POLICIES,
    DshNodePolicy,
    DshTaskRunResult,
    DshTaskWorkerBridge,
    DshWorkerBridgeError,
)
from .dsh_worker_contract_v2 import install_rc7_1_worker_output_contracts

install_rc7_1_worker_output_contracts()

from .candidate_payload import CandidatePayload, CandidatePayloadError, CandidatePayloadReader
from .dsh_requirement_evaluator import (
    DshRequirementEvaluation,
    DshRequirementEvaluator,
    DshRequirementEvaluatorError,
)
from .dsh_code_evaluator import DshCodeEvaluation, DshCodeEvaluator, DshCodeEvaluatorError
from .rc72_n3_code_analysis_gate_contract import (
    install_rc72_n3_code_analysis_gate_contract,
)

# RC7.2 N3 raw candidates keep their replayable V1 envelope but are promoted
# into the canonical schema required by the real deterministic Code gate.  This
# must be installed package-wide so source handoff/promotion/review cannot drift
# into mutually incompatible schemas depending on import order.
install_rc72_n3_code_analysis_gate_contract()

from .rc72_n3_completion import N3CompletionError, N3DeliveryGateService
from .rc72_n3_completion_r1_replay import install_rc72_n3_completion_r1_replay

# Canonical DSH tool Evidence stores the immutable outer R1 event identity.
# Aggregate N3 verification must replay that raw event instead of confusing it
# with the projected agent_runtime_event payload id.
install_rc72_n3_completion_r1_replay()

from .dsh_test_design_evaluator import (
    DshTestDesignEvaluation,
    DshTestDesignEvaluatorError,
)
from .dsh_test_design_oracle_evaluator import (
    DshExecutionReadyTestDesignEvaluator as DshTestDesignEvaluator,
)
from .dsh_proof import DshProofError, DshR1ProofReader, DshToolCallProof, code_tool_category
from .oracle_runtime import DeterministicOracleError, DeterministicOracleRuntime
from .execution_diagnosis import (
    DiagnosisClosure,
    ExecutionDiagnosisCoordinator,
    ExecutionTrustFacts,
)
from .attempt_lineage import LineageAwareAttemptHistory
from .lineage_diagnosis import LineageAwareExecutionDiagnosisCoordinator
from .execution_recovery import (
    ExecutionRecoveryPlanner,
    RecoveryPlanningError,
    RecoveryWorkPlan,
)
from .execution_recovery_control import (
    DirectRetryAuthorization,
    ExecutionRecoveryController,
    RecoveryControlError,
)
from .execution_autonomous_loop import (
    AutonomousExecutionLoop,
    AutonomousExecutionLoopError,
    AutonomousExecutionLoopResult,
)
from .preparation_control import (
    RuntimePreparationError,
    RuntimePreparationService,
    RuntimePreparedAttempt,
)
from .autonomous_execution_service import (
    AutonomousClosedLoopExecutionService,
    AutonomousExecutionServiceError,
    PreparedAutonomousExecutionResult,
)
from .rc72_domain import (
    AutonomousMissionNode,
    BackEdge,
    BackEdgeState,
    ETUState,
    ExecutionTaskUnit,
    MissionNodeRecord,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
    ObligationStatus,
    RC72_CANONICAL_NODE_ORDER,
    ReleaseBatch,
    TestObligation,
)
from .rc72_linkage import (
    NodeTransition,
    NodeTransitionKind,
    WorkItemAttemptBinding,
    WorkItemAttemptState,
)
from .rc72_repository import CanonicalRC72Repository, RC72LineageError
from .rc72_truth import append_rc72_entity, install_rc72_truth_overlay
from .rc72_schedule_semantics import (
    CanonicalScheduleDescriptorResolver,
    WorkScheduleSemanticsService,
)

__all__ = [
    "RealityCheckedJUnitRunnerAdapter",
    "install_rc7_1_junit_reality_gate",
    "install_rc7_1_worker_timeout_diagnostics",
    "PersistentSlidingWindowGovernor",
    "classify_failure",
    "install_rc7_1_model_resilience",
    "install_rc7_1_worker_output_contracts",
    "install_rc72_n3_code_analysis_gate_contract",
    "install_rc72_n3_completion_r1_replay",
    "Artifact",
    "ArtifactStatus",
    "Evaluation",
    "EvaluationResult",
    "EventRecord",
    "Evidence",
    "Gap",
    "GapSeverity",
    "GapStatus",
    "Mission",
    "MissionStatus",
    "Task",
    "TaskStatus",
    "ConvergenceInput",
    "ConvergenceDecision",
    "decide_convergence",
    "invalidate_artifact",
    "transition_gap",
    "transition_mission",
    "transition_task",
    "ClosedLoopControlError",
    "ClosedLoopControlPlane",
    "RC72EconomyClosedLoopControlPlane",
    "install_rc72_economy_control_plane_default",
    "MissionTaskGraph",
    "MissionTaskGraphCompiler",
    "FinalReportError",
    "RC7FinalReportBuilder",
    "DEFAULT_NODE_POLICIES",
    "DshNodePolicy",
    "DshTaskRunResult",
    "DshTaskWorkerBridge",
    "DshWorkerBridgeError",
    "CandidatePayload",
    "CandidatePayloadError",
    "CandidatePayloadReader",
    "DshRequirementEvaluation",
    "DshRequirementEvaluator",
    "DshRequirementEvaluatorError",
    "DshCodeEvaluation",
    "DshCodeEvaluator",
    "DshCodeEvaluatorError",
    "N3CompletionError",
    "N3DeliveryGateService",
    "DshTestDesignEvaluation",
    "DshTestDesignEvaluator",
    "DshTestDesignEvaluatorError",
    "DshProofError",
    "DshR1ProofReader",
    "DshToolCallProof",
    "code_tool_category",
    "DeterministicOracleError",
    "DeterministicOracleRuntime",
    "DiagnosisClosure",
    "ExecutionDiagnosisCoordinator",
    "ExecutionTrustFacts",
    "LineageAwareAttemptHistory",
    "LineageAwareExecutionDiagnosisCoordinator",
    "ExecutionRecoveryPlanner",
    "RecoveryPlanningError",
    "RecoveryWorkPlan",
    "DirectRetryAuthorization",
    "ExecutionRecoveryController",
    "RecoveryControlError",
    "AutonomousExecutionLoop",
    "AutonomousExecutionLoopError",
    "AutonomousExecutionLoopResult",
    "RuntimePreparationError",
    "RuntimePreparationService",
    "RuntimePreparedAttempt",
    "AutonomousClosedLoopExecutionService",
    "AutonomousExecutionServiceError",
    "PreparedAutonomousExecutionResult",
    "AutonomousMissionNode",
    "MissionNodeState",
    "MissionNodeRecord",
    "NodeDelivery",
    "NodeGate",
    "NodeGateDecision",
    "ReleaseBatch",
    "TestObligation",
    "ObligationStatus",
    "ExecutionTaskUnit",
    "ETUState",
    "BackEdge",
    "BackEdgeState",
    "NodeTransition",
    "NodeTransitionKind",
    "WorkItemAttemptBinding",
    "WorkItemAttemptState",
    "RC72_CANONICAL_NODE_ORDER",
    "CanonicalRC72Repository",
    "RC72LineageError",
    "append_rc72_entity",
    "install_rc72_truth_overlay",
    "CanonicalScheduleDescriptorResolver",
    "WorkScheduleSemanticsService",
]
