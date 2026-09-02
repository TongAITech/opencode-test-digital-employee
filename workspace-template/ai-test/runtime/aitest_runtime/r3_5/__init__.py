"""R3.5 Page, Auth, Journey and Real E2E Intelligence extension.

This package is an additive seam over the frozen R1 Event Stream, R3.E1
Knowledge substrate, R3.E2 SUTAuthContext and R3.E3 controlled browser ports.
It does not own a second Event, Evidence, Mission, Session or Knowledge truth.
"""

from .contracts import (
    ARCHITECTURE_BASELINE_REF,
    BACKEND_SURFACES,
    BUILD_PAGE_GRAPH,
    CHECKPOINT_JOURNEY,
    COMMAND_TYPES,
    DEFINE_JOURNEY,
    EVENT_TYPES,
    EXECUTION_TYPES,
    EXTENSION_ID,
    EXTENSION_VERSION,
    EVIDENCE_CLASSES,
    FRONTEND_SURFACES,
    JOURNEY_RECORDED,
    PAGE_GRAPH_RECORDED,
    PAGE_GRAPH_STATUSES,
    PAGE_RECONCILIATION_STATES,
    RECORD_TRANSITION,
    RECORD_VERIFICATION,
    RUNTIME_EXECUTIONS,
    TRANSITION_RECORDED,
    VERIFICATION_RECORDED,
    BusinessJourney,
    CodeSymbolRef,
    JourneyCheckpoint,
    JourneyStep,
    JourneyTransition,
    JourneyVerification,
    PageGraph,
    PageNode,
    PageRuntimeReconciliation,
    R35State,
    SourceRef,
    UserActionBinding,
)
from .e2e import E2ELifecycle, LIFECYCLE_STAGES, classify_execution, classify_result, lifecycle_status, require_engineering_only
from .errors import R35Error
from .extension import r3_5_extension
from .journey import checkpoint_journey, define_journey, record_journey_transition, update_journey_lifecycle
from .knowledge import R3E1KnowledgeBridge
from .page_intelligence import PageGraphBuildRequest, PageGraphBuildResult, build_page_graph
from .reconciliation import reconcile_page_runtime, verify_sut_auth_context
from .service import R35ApplicationService, R35OperationResult, R3_5ApplicationService
from .workset import (
    WorkSetRequest,
    WorkSetResult,
    checkpoint_workset,
    retrieve_workset,
)


__all__ = [
    "ARCHITECTURE_BASELINE_REF", "BACKEND_SURFACES", "BUILD_PAGE_GRAPH", "CHECKPOINT_JOURNEY",
    "COMMAND_TYPES", "DEFINE_JOURNEY", "EVENT_TYPES", "EXECUTION_TYPES", "EXTENSION_ID",
    "EXTENSION_VERSION", "EVIDENCE_CLASSES", "FRONTEND_SURFACES", "JOURNEY_RECORDED",
    "PAGE_GRAPH_RECORDED", "PAGE_GRAPH_STATUSES", "PAGE_RECONCILIATION_STATES", "RECORD_TRANSITION", "RECORD_VERIFICATION",
    "RUNTIME_EXECUTIONS", "TRANSITION_RECORDED", "VERIFICATION_RECORDED", "BusinessJourney",
    "CodeSymbolRef", "E2ELifecycle", "JourneyCheckpoint", "JourneyStep", "JourneyTransition", "JourneyVerification",
    "PageGraph", "PageGraphBuildRequest", "PageGraphBuildResult", "PageNode", "PageRuntimeReconciliation",
    "R35ApplicationService", "R3_5ApplicationService", "R35Error", "R35OperationResult", "R35State",
    "R3E1KnowledgeBridge", "SourceRef", "UserActionBinding", "WorkSetRequest", "WorkSetResult",
    "build_page_graph", "checkpoint_journey", "checkpoint_workset", "classify_execution", "define_journey",
    "LIFECYCLE_STAGES", "lifecycle_status", "classify_result", "r3_5_extension", "reconcile_page_runtime", "record_journey_transition",
    "require_engineering_only", "retrieve_workset", "update_journey_lifecycle", "verify_sut_auth_context",
]
