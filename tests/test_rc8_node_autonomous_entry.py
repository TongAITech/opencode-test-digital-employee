from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import pytest
from rc8_node.__main__ import (_AUTONOMOUS_STAGES, _N1_N10_REQUIRED_STAGES, _autonomous_readiness, _build_dispatcher, _env_flag, main)
from rc8_node.code_analysis_worker import CodeAnalysisWorker
from rc8_node.code_sufficiency_worker import CodeSufficiencyWorker
from rc8_node.design_sufficiency_worker import DesignSufficiencyWorker
from rc8_node.risk_test_model_worker import RiskTestModelWorker
from rc8_node.test_design_worker import TestDesignWorker
from rc8_runtime import NodeIdentity

class FakeCenter: pass

def _args(tmp_path: Path) -> Namespace:
    return Namespace(dsh_patch="bank-dsh-patch", dsh_bin="dsh", dsh_cwd="", dsh_timeout=300,
        codegraph_command="codegraph query --json", work_dir=str(tmp_path / "work"), state_dir=str(tmp_path / "state"),
        center="http://127.0.0.1:4098", http_timeout=30, lease_ttl=60, claim_interval=1.0)

def _identity() -> NodeIdentity:
    return NodeIdentity(node_id="NODE-AUTO", operator_ref="test", os_family="linux", architecture="x86_64", shell="bash", registered_at=1)

def test_autonomous_entry_registers_only_currently_implemented_stage_workers(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(_args(tmp_path), _identity(), FakeCenter())
    assert dispatcher.supported_stages == tuple(sorted(_AUTONOMOUS_STAGES))
    assert set(dispatcher.workers) == {"SCOPE_INTAKE", "REQUIREMENT_ANALYSIS", "REQUIREMENT_SUFFICIENCY", "CODE_ANALYSIS", "CODE_SUFFICIENCY", "RISK_TEST_MODEL", "TEST_DESIGN", "DESIGN_SUFFICIENCY", "APPLICABLE_LAYER_EXECUTION"}
    assert isinstance(dispatcher.workers["CODE_ANALYSIS"], CodeAnalysisWorker)
    assert isinstance(dispatcher.workers["CODE_SUFFICIENCY"], CodeSufficiencyWorker)
    assert isinstance(dispatcher.workers["RISK_TEST_MODEL"], RiskTestModelWorker)
    assert isinstance(dispatcher.workers["TEST_DESIGN"], TestDesignWorker)
    assert isinstance(dispatcher.workers["DESIGN_SUFFICIENCY"], DesignSufficiencyWorker)
    assert dispatcher.ttl_seconds == 60
    assert dispatcher.idle_sleep_seconds == 1.0

def test_single_node_n1_n10_readiness_fails_closed_until_all_stage_workers_exist() -> None:
    ready, missing = _autonomous_readiness()
    assert ready is False
    assert missing == tuple(stage for stage in _N1_N10_REQUIRED_STAGES if stage not in _AUTONOMOUS_STAGES)
    assert "CODE_ANALYSIS" not in missing
    assert "CODE_SUFFICIENCY" not in missing
    assert "RISK_TEST_MODEL" not in missing
    assert "TEST_DESIGN" not in missing
    assert "DESIGN_SUFFICIENCY" not in missing
    assert {"PRECONDITION_DATA_PREP", "EXECUTABLE_SPEC", "FAILURE_COVERAGE_EVALUATION", "MISSION_SUFFICIENCY", "REPORT_RELEASE"}.issubset(set(missing))

def test_autonomous_entry_keeps_later_unimplemented_stages_closed(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(_args(tmp_path), _identity(), FakeCenter())
    forbidden = {"EXECUTABLE_SPEC", "PRECONDITION_DATA_PREP", "FAILURE_COVERAGE_EVALUATION", "MISSION_SUFFICIENCY", "REPORT_RELEASE"}
    assert forbidden.isdisjoint(dispatcher.supported_stages)
    assert "RISK_TEST_MODEL" in dispatcher.supported_stages
    assert "TEST_DESIGN" in dispatcher.supported_stages
    assert "DESIGN_SUFFICIENCY" in dispatcher.supported_stages
    assert "CODE_ANALYSIS" in dispatcher.supported_stages
    assert "CODE_SUFFICIENCY" in dispatcher.supported_stages
    assert "APPLICABLE_LAYER_EXECUTION" in dispatcher.supported_stages

def test_autonomous_cli_requires_dsh_patch_before_any_runtime_registration() -> None:
    with pytest.raises(SystemExit) as captured:
        main(["--node-id", "NODE", "--operator", "operator", "--autonomous", "--once"])
    assert captured.value.code == 2

def test_env_flag_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("RC8_NODE_AUTONOMOUS", "1"); assert _env_flag("RC8_NODE_AUTONOMOUS") is True
    monkeypatch.setenv("RC8_NODE_AUTONOMOUS", "false"); assert _env_flag("RC8_NODE_AUTONOMOUS") is False
