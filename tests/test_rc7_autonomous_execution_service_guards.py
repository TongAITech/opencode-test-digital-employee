from __future__ import annotations

from types import SimpleNamespace

import pytest

from rc7_runtime.autonomous_execution_service import (
    AutonomousClosedLoopExecutionService,
    AutonomousExecutionServiceError,
)


def _bundle(layer):
    return SimpleNamespace(spec=SimpleNamespace(layer=layer))


def test_generic_execution_rejects_l3_before_any_runtime_side_effect(tmp_path):
    service = AutonomousClosedLoopExecutionService(evidence_root=str(tmp_path))
    with pytest.raises(AutonomousExecutionServiceError, match="L3_REQUIRES_CONTROLLED_EXECUTION"):
        service.execute_generic(
            None,
            "TASK-L3",
            bundle=_bundle("L3"),
            prepared=None,
            authority=None,
            tool_broker=None,
            oracle_evaluator=None,
            cwd=str(tmp_path),
        )


def test_controlled_l3_entry_rejects_non_l3_before_any_runtime_side_effect(tmp_path):
    service = AutonomousClosedLoopExecutionService(evidence_root=str(tmp_path))
    with pytest.raises(AutonomousExecutionServiceError, match="CONTROLLED_L3_EXECUTION_REQUIRES_L3_SPEC"):
        service.execute_l3(
            None,
            "TASK-L2",
            bundle=_bundle("L2"),
            prepared=None,
            authority=None,
            tool_broker=None,
            target_base_url="http://127.0.0.1:1",
            cwd=str(tmp_path),
        )
