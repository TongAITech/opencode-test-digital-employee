"""RC7.1 production execution profiles.

RC6's historical defaults encoded an older layer taxonomy (L5 E2E, L6 k6,
L7 ZAP). RC7.1 keeps the RC6 source/baseline intact and installs an additive
runtime overlay when the RC7 package is imported, matching the existing RC7.1
reality-gate installation pattern.

The profile selects the minimum runtime capability needed to execute the layer;
LayerExecutionEvidenceGate independently verifies the stronger semantic proof.
"""

from __future__ import annotations

from typing import Dict

import rc6_runtime.execution as rc6_execution
from rc6_runtime.execution import LayerExecutionProfile


RC7_1_EXECUTION_PROFILES: Dict[str, LayerExecutionProfile] = {
    "L1": LayerExecutionProfile("L1", "L1_EXECUTE", ("maven", "junit"), "CODE_UNIT"),
    "L2": LayerExecutionProfile("L2", "L2_EXECUTE", ("database",), "DB_COMPONENT"),
    "L3": LayerExecutionProfile("L3", "L3_EXECUTE", ("api-runtime",), "API_SERVICE"),
    "L4": LayerExecutionProfile("L4", "L4_EXECUTE", ("browser-skill",), "UI_BROWSER"),
    "L5": LayerExecutionProfile("L5", "L5_EXECUTE", ("api-runtime",), "API_CONTRACT"),
    "L6": LayerExecutionProfile("L6", "L6_EXECUTE", ("capability-runtime",), "CAPABILITY_EXECUTION"),
    "L7": LayerExecutionProfile("L7", "L7_EXECUTE", ("e2e-orchestrator",), "CROSS_LAYER_E2E"),
}


def install_rc7_1_execution_profiles() -> None:
    """Install RC7.1 defaults before RC7 execution services are imported.

    The mutation is process-local and happens only when ``rc7_runtime`` is
    imported. The RC6 source remains unchanged, while all RC7-created
    ``ExecutionRuntime`` instances use the RC7.1 taxonomy consistently.
    """
    rc6_execution.DEFAULT_EXECUTION_PROFILES.clear()
    rc6_execution.DEFAULT_EXECUTION_PROFILES.update(RC7_1_EXECUTION_PROFILES)
