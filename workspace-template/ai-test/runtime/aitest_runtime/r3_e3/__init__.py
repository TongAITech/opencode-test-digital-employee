"""R3.E3 controlled Browser runtime integration seam."""

from .contracts import (
    BrowserActionReceipt,
    BrowserActionRequest,
    BrowserContextObservation,
    CapabilityReport,
    EnvironmentBinding,
    LeaseHandoffReceipt,
    RuntimeBootstrapReceipt,
    R3E3Error,
    RuntimeStateObservation,
)
from aitest_runtime.r3_e2.ports import ContextReuseReceipt

from .runtime import BrowserRuntimeEntrypoint, ControlledBrowserRuntime, setupBrowserRuntime
from .human_gate import R26HumanGateBridge
from .vertical_slice import VerticalSliceGateResult, evaluate_vertical_slice_gate

__all__ = [
    "BrowserActionReceipt",
    "BrowserActionRequest",
    "BrowserContextObservation",
    "CapabilityReport",
    "ContextReuseReceipt",
    "BrowserRuntimeEntrypoint",
    "ControlledBrowserRuntime",
    "EnvironmentBinding",
    "LeaseHandoffReceipt",
    "R3E3Error",
    "R26HumanGateBridge",
    "RuntimeBootstrapReceipt",
    "RuntimeStateObservation",
    "VerticalSliceGateResult",
    "evaluate_vertical_slice_gate",
    "setupBrowserRuntime",
]
