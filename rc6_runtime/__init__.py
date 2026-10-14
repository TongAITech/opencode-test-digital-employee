"""RC6 governed testing runtime."""

from .authority import AuthorityError, AuthorityRuntime, TaskLease, WorkerIdentity
from .budget import BudgetDecision, ContextBudget, ProviderBudget
from .capability import CapabilityAdmission, ToolCallEvidence, ToolCapabilityBroker, ToolCapabilityError
from .contracts import DomainValidationError, validate_artifact, validate_test_case
from .coverage import (
    CaseFreezeGate,
    ClosureResult,
    CoverageContractError,
    CoverageSubject,
    CoverageSubjectRegistry,
    DeltaDesignPlanner,
    DeltaDesignRequest,
    DesignClosureEvaluator,
    OraclePolicy,
)
from .design import DesignContextBuilder, DesignRuntimeError, DesignTask, DesignTaskPlanner, LayerApplicabilityRouter, LayerDecision
from .diagnosis import (
    AttemptHistory,
    AttemptHistoryEntry,
    CATCorrelationResult,
    CATPolicy,
    CorrelationScope,
    DiagnosisContractError,
    DiagnosisResult,
    DiagnosisRuntime,
    FailureContext,
    RecoveryDecision as DiagnosisRecoveryDecision,
    RecoveryEngine,
    history_entry_from_execution,
)
from .execution import (
    DEFAULT_EXECUTION_PROFILES,
    ExecutionContractError,
    ExecutionIntegrityGate,
    ExecutionProfileRegistry,
    ExecutionRecord,
    ExecutionRuntime,
    LayerExecutionProfile,
    OracleAssertionResult,
    RealActionResult,
)
from .execution_coverage import (
    DEFAULT_LAYER_COVERAGE_PROFILES,
    CoverageDeltaRequest,
    CoverageObservation,
    CoverageObservationRuntime,
    EmpiricalClosureResult,
    EmpiricalCoverageEvaluator,
    EmpiricalCoverageGap,
    EmpiricalCoverageRegistry,
    EmpiricalCoverageSubject,
    ExecutionCoverageDeltaPlanner,
    ExecutionCoverageError,
    LayerCoverageProfile,
    LayerCoverageResult,
)
from .intelligence import CodeSufficiencyEvaluator, GateResult, IntelligenceContractError, RequirementSufficiencyEvaluator
from .mission import MissionRuntime, MissionState, ResumeEnvelope
from .preparation import (
    AttemptBindingStore,
    PreparationContractError,
    PreparationPlan,
    PreparedAttempt,
    PreparationRecoveryEngine,
    PreparationRuntime,
    PreparationSpecParser,
    RecoveryDecision,
)
from .presentation import (
    ADMIN_ENTITIES,
    CHINESE_LABELS,
    AdminHtmlRenderer,
    AdminReadModel,
    AllureRenderer,
    AllureResultsAdapter,
    MissionReportBuilder,
    PageResult,
    PresentationError,
    TruthReconciler,
)
from .reality import BankRealityRegistry, RealityError
from .stages import StageMachine, StageViolation
from .target import TargetIdentity, TargetIdentityBuilder, TargetIdentityError
from .truth import EventValidationError, JsonlEventStore, PersistenceReceipt, Projection, ProjectionIntegrityError, TruthRuntime

__all__ = [
    "AuthorityError", "AuthorityRuntime", "TaskLease", "WorkerIdentity",
    "BudgetDecision", "ContextBudget", "ProviderBudget",
    "CapabilityAdmission", "ToolCallEvidence", "ToolCapabilityBroker", "ToolCapabilityError",
    "DomainValidationError", "validate_artifact", "validate_test_case",
    "CaseFreezeGate", "ClosureResult", "CoverageContractError", "CoverageSubject", "CoverageSubjectRegistry",
    "DeltaDesignPlanner", "DeltaDesignRequest", "DesignClosureEvaluator", "OraclePolicy",
    "DesignContextBuilder", "DesignRuntimeError", "DesignTask", "DesignTaskPlanner", "LayerApplicabilityRouter", "LayerDecision",
    "AttemptHistory", "AttemptHistoryEntry", "CATCorrelationResult", "CATPolicy", "CorrelationScope",
    "DiagnosisContractError", "DiagnosisResult", "DiagnosisRuntime", "FailureContext", "DiagnosisRecoveryDecision",
    "RecoveryEngine", "history_entry_from_execution",
    "DEFAULT_EXECUTION_PROFILES", "ExecutionContractError", "ExecutionIntegrityGate", "ExecutionProfileRegistry",
    "ExecutionRecord", "ExecutionRuntime", "LayerExecutionProfile", "OracleAssertionResult", "RealActionResult",
    "DEFAULT_LAYER_COVERAGE_PROFILES", "CoverageDeltaRequest", "CoverageObservation", "CoverageObservationRuntime",
    "EmpiricalClosureResult", "EmpiricalCoverageEvaluator", "EmpiricalCoverageGap", "EmpiricalCoverageRegistry",
    "EmpiricalCoverageSubject", "ExecutionCoverageDeltaPlanner", "ExecutionCoverageError", "LayerCoverageProfile", "LayerCoverageResult",
    "CodeSufficiencyEvaluator", "GateResult", "IntelligenceContractError", "RequirementSufficiencyEvaluator",
    "MissionRuntime", "MissionState", "ResumeEnvelope",
    "AttemptBindingStore", "PreparationContractError", "PreparationPlan", "PreparedAttempt",
    "PreparationRecoveryEngine", "PreparationRuntime", "PreparationSpecParser", "RecoveryDecision",
    "ADMIN_ENTITIES", "CHINESE_LABELS", "AdminHtmlRenderer", "AdminReadModel", "AllureRenderer",
    "AllureResultsAdapter", "MissionReportBuilder", "PageResult", "PresentationError", "TruthReconciler",
    "BankRealityRegistry", "RealityError",
    "StageMachine", "StageViolation",
    "TargetIdentity", "TargetIdentityBuilder", "TargetIdentityError",
    "EventValidationError", "JsonlEventStore", "PersistenceReceipt", "Projection", "ProjectionIntegrityError", "TruthRuntime",
]
