"""RC6 governed testing runtime."""

from .authority import AuthorityError, AuthorityRuntime, WorkerIdentity, TaskLease
from .budget import ContextBudget, ProviderBudget, BudgetDecision
from .contracts import DomainValidationError, validate_artifact, validate_test_case
from .mission import MissionRuntime, MissionState, ResumeEnvelope
from .reality import BankRealityRegistry, RealityError
from .stages import StageMachine, StageViolation
from .target import TargetIdentity, TargetIdentityBuilder, TargetIdentityError
from .truth import (
    EventValidationError,
    JsonlEventStore,
    PersistenceReceipt,
    Projection,
    ProjectionIntegrityError,
    TruthRuntime,
)

__all__ = [
    "AuthorityError", "AuthorityRuntime", "WorkerIdentity", "TaskLease",
    "ContextBudget", "ProviderBudget", "BudgetDecision",
    "DomainValidationError", "validate_artifact", "validate_test_case",
    "MissionRuntime", "MissionState", "ResumeEnvelope",
    "BankRealityRegistry", "RealityError",
    "StageMachine", "StageViolation",
    "TargetIdentity", "TargetIdentityBuilder", "TargetIdentityError",
    "EventValidationError", "JsonlEventStore", "PersistenceReceipt",
    "Projection", "ProjectionIntegrityError", "TruthRuntime",
]
