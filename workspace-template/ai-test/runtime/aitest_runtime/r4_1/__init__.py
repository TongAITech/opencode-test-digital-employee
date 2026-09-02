"""R4.1 Quality Version and Test Campaign durable foundation."""

from .contracts import *
from .errors import R41Error
from .extension import r4_1_extension
from .service import R41ApplicationService, R41OperationResult, compose_r4_1_runtime

__all__ = [
    "R41ApplicationService", "R41Error", "R41OperationResult", "compose_r4_1_runtime", "r4_1_extension",
    "Freshness", "Availability", "FieldValidationState", "QualityVersionLifecycle", "CampaignKind",
    "TestCampaignLifecycle", "TypedReference", "QualityVersion", "TestCampaign", "CampaignSelectionRevision",
    "R41State", "CREATE_QUALITY_VERSION", "CREATE_TEST_CAMPAIGN", "RECORD_CAMPAIGN_SELECTION_REVISION",
    "QUALITY_VERSION_CREATED", "TEST_CAMPAIGN_CREATED", "CAMPAIGN_SELECTION_REVISION_RECORDED",
    "COMMAND_TYPES", "EVENT_TYPES", "EXTENSION_ID", "EXTENSION_VERSION",
    "quality_version_digest", "campaign_digest", "selection_revision_digest", "input_payload",
]
