from types import SimpleNamespace

import pytest

import rc7_runtime.autonomous_execution_service as service_module
from rc7_runtime.autonomous_execution_service import (
    AutonomousClosedLoopExecutionService,
    AutonomousExecutionServiceError,
)


def _control():
    return SimpleNamespace(truth=object(), mission_id="MISSION-BANK-FANOUT")


def test_case_fanout_mission_rejects_legacy_runtime_preparation(monkeypatch):
    monkeypatch.setattr(service_module, "case_fanout_contract_enabled", lambda truth, mission_id: True)

    with pytest.raises(
        AutonomousExecutionServiceError,
        match="BANK_CASE_FANOUT_REQUIRES_FIELD_CASE_RUNTIME:CASE_PREPARED_ATTEMPT",
    ):
        AutonomousClosedLoopExecutionService._reject_legacy_preparation_for_case_fanout(_control())


def test_legacy_mission_keeps_compatibility_preparation_surface(monkeypatch):
    monkeypatch.setattr(service_module, "case_fanout_contract_enabled", lambda truth, mission_id: False)
    AutonomousClosedLoopExecutionService._reject_legacy_preparation_for_case_fanout(_control())
