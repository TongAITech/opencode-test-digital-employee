"""RC7 autonomous testing control-plane runtime.

RC7 is an additive refactor over the proven RC6 capability surface. The package
owns durable control-plane semantics while existing RC6 testing capabilities
remain reusable through the RC7 closed-loop adapters.
"""

# RC7.1 field fix: install the current-run JUnit evidence gate before any RC7
# execution module imports the RC6 compatibility JUnit adapter.
from .junit_reality import (
    RealityCheckedJUnitRunnerAdapter,
    install_rc7_1_junit_reality_gate,
)

install_rc7_1_junit_reality_gate()

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
from .mission_graph import MissionTaskGraph, MissionTaskGraphCompiler
from .final_report import FinalReportError, RC7FinalReportBuilder
from .dsh_worker_bridge import (
    DEFAULT_NODE_POLICIES,
    DshNodePolicy,
    DshTaskRunResult,
    DshTaskWorkerBridge,
    DshWorkerBridgeError,
)
from .candidate_payload import CandidatePayload, CandidatePayloadError, CandidatePayloadReader
from .dsh_requirement_evaluator import (
    DshRequirementEvaluation,
    DshRequirementEvaluator,
    DshRequirementEvaluatorError,
)
from .dsh_code_evaluator import DshCodeEvaluation, DshCodeEvaluator, DshCodeEvaluatorError
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

__all__ = [
    "RealityCheckedJUnitRunnerAdapter",
    "install_rc7_1_junit_reality_gate",
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
]
