"""Opt-in R4.8 closed-loop coordination extension."""

from .authority_ports import R48AuthorityPort
from .composition import compose_r4_8_closed_loop_runtime, validate_r4_8_composition
from .contracts import *
from .errors import R48ContractError, R48Error, R48ErrorCode
from .extension import r4_8_extension
from .service import R48ApplicationService


__all__ = (
    "R48ApplicationService",
    "R48CompositionSpec",
    "R48CompositionValidationResult",
    "R48AuthorityBinding",
    "R48AuthorityKind",
    "R48BindingSource",
    "R48AuthorityOutcome",
    "R48ProcessingOutcome",
    "R48StageDisposition",
    "R48OperationKind",
    "R48ReentryKind",
    "R48CycleRegistrationInput",
    "R48CapabilityObservationInput",
    "R48AuthorityOperationInput",
    "R48AuthorityReceiptInput",
    "R48ReentryInput",
    "R48WaitingInput",
    "R48CycleCloseInput",
    "R48ReconciliationInput",
    "R48AuthorityResult",
    "R48AuthorityProcessingResult",
    "R48CyclePolicySnapshot",
    "R48CycleContext",
    "R48CoordinationStep",
    "R48AuthorityOperation",
    "R48AuthorityReceipt",
    "R48ReentryRecord",
    "R48CycleState",
    "R48State",
    "R48Phase",
    "R48CoordinationStatus",
    "R48OperationStatus",
    "R48ErrorCode",
    "R48ContractError",
    "validate_r4_8_composition",
    "compose_r4_8_closed_loop_runtime",
    "r4_8_extension",
)

