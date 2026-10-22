from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from rc8_node.__main__ import _AUTONOMOUS_STAGES, _build_dispatcher, _env_flag, main
from rc8_runtime import NodeIdentity


class FakeCenter:
    pass


def _args(tmp_path: Path) -> Namespace:
    return Namespace(
        dsh_patch="bank-dsh-patch",
        dsh_bin="dsh",
        dsh_cwd="",
        dsh_timeout=300,
        work_dir=str(tmp_path / "work"),
        state_dir=str(tmp_path / "state"),
        center="http://127.0.0.1:4098",
        http_timeout=30,
        lease_ttl=60,
        claim_interval=1.0,
    )


def _identity() -> NodeIdentity:
    return NodeIdentity(
        node_id="NODE-AUTO",
        operator_ref="test",
        os_family="linux",
        architecture="x86_64",
        shell="bash",
        registered_at=1,
    )


def test_autonomous_entry_registers_only_currently_implemented_stage_workers(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(_args(tmp_path), _identity(), FakeCenter())
    assert dispatcher.supported_stages == tuple(sorted(_AUTONOMOUS_STAGES))
    assert set(dispatcher.workers) == {
        "SCOPE_INTAKE",
        "REQUIREMENT_ANALYSIS",
        "REQUIREMENT_SUFFICIENCY",
    }
    assert dispatcher.ttl_seconds == 60
    assert dispatcher.idle_sleep_seconds == 1.0


def test_autonomous_entry_does_not_register_unimplemented_code_or_design_stages(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(_args(tmp_path), _identity(), FakeCenter())
    forbidden = {
        "CODE_ANALYSIS",
        "CODE_SUFFICIENCY",
        "RISK_TEST_MODEL",
        "TEST_DESIGN",
        "DESIGN_SUFFICIENCY",
        "EXECUTABLE_SPEC",
        "PRECONDITION_DATA_PREP",
        "APPLICABLE_LAYER_EXECUTION",
        "FAILURE_COVERAGE_EVALUATION",
        "MISSION_SUFFICIENCY",
        "REPORT_RELEASE",
    }
    assert forbidden.isdisjoint(dispatcher.supported_stages)


def test_autonomous_cli_requires_dsh_patch_before_any_runtime_registration() -> None:
    with pytest.raises(SystemExit) as captured:
        main([
            "--node-id", "NODE",
            "--operator", "operator",
            "--autonomous",
            "--once",
        ])
    assert captured.value.code == 2


def test_env_flag_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("RC8_NODE_AUTONOMOUS", "1")
    assert _env_flag("RC8_NODE_AUTONOMOUS") is True
    monkeypatch.setenv("RC8_NODE_AUTONOMOUS", "false")
    assert _env_flag("RC8_NODE_AUTONOMOUS") is False
