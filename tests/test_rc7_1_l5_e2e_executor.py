from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from rc7_release.e2e_executor import E2EExecutorError, execute_e2e_journey


TARGET = "target-bank-l5"


def _write_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "e2e_helper.py"
    helper.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "mode = sys.argv[1]\n"
        "target = sys.argv[2]\n"
        "systems = ['cfg-admin', 'cfg-data'] if mode != 'same-system' else ['cfg-admin', 'cfg-admin']\n"
        "receipt = {\n"
        "  'journey_id': 'J-L5-001',\n"
        "  'target_id': target,\n"
        "  'hops': [\n"
        "    {'system_id': systems[0], 'tool_id': 'browser-skill', 'status': 'SUCCESS', 'invocation_ref': 'browser-skill://bank/hop1', 'result_sha256': 'a'*64},\n"
        "    {'system_id': systems[1], 'tool_id': 'api-runtime', 'status': 'SUCCESS', 'invocation_ref': ('fixture://hop2' if mode == 'fixture' else 'api-runtime://bank/hop2'), 'result_sha256': 'b'*64}\n"
        "  ],\n"
        "  'final_oracle': {\n"
        "    'oracle_id': 'ORACLE-L5-001',\n"
        "    'passed': mode != 'oracle-fail',\n"
        "    'expected': {'status': 'PUBLISHED'},\n"
        "    'actual': {'status': 'PUBLISHED'},\n"
        "    'evidence_ref': 'db://bank/final-state',\n"
        "    'evidence_sha256': 'c'*64\n"
        "  }\n"
        "}\n"
        "print(json.dumps(receipt, sort_keys=True))\n",
        encoding="utf-8",
    )
    return helper


def _configure(monkeypatch, helper: Path, mode: str = "success", target: str = TARGET) -> None:
    monkeypatch.setenv("PFC_WORKSPACE", str(helper.parent))
    monkeypatch.setenv("PFC_E2E_TARGET_ID", target)
    monkeypatch.setenv("PFC_E2E_CLIENT_BIN", sys.executable)
    monkeypatch.setenv("PFC_E2E_CLIENT_ARGS_JSON", json.dumps([str(helper), mode, target]))


def _journey():
    return {
        "journey_id": "J-L5-001",
        "steps": [
            {"system": "cfg-admin", "action": "publish"},
            {"system": "cfg-data", "action": "verify"},
        ],
        "oracle": {"expected": {"status": "PUBLISHED"}},
    }


def test_l5_executes_real_process_and_accepts_only_cross_system_receipt(tmp_path: Path, monkeypatch) -> None:
    helper = _write_helper(tmp_path)
    _configure(monkeypatch, helper)

    result = execute_e2e_journey(journey=_journey(), target_id=TARGET, timeout_seconds=10)

    assert result["tool"] == "e2e-orchestrator"
    assert result["target_id"] == TARGET
    assert result["shell"] is False
    assert result["request_transport"] == "STDIN_JSON"
    assert result["receipt_transport"] == "STDOUT_JSON"
    assert result["journey_receipt"]["hop_count"] == 2
    assert result["journey_receipt"]["system_ids"] == ["cfg-admin", "cfg-data"]
    assert result["journey_receipt"]["final_oracle"]["passed"] is True
    assert result["invocation_ref"].startswith("e2e-orchestrator://%s/" % TARGET)


def test_l5_rejects_same_system_hops(tmp_path: Path, monkeypatch) -> None:
    helper = _write_helper(tmp_path)
    _configure(monkeypatch, helper, mode="same-system")

    with pytest.raises(E2EExecutorError, match="E2E_REQUIRES_DISTINCT_SYSTEMS"):
        execute_e2e_journey(journey=_journey(), target_id=TARGET, timeout_seconds=10)


def test_l5_rejects_failed_final_oracle(tmp_path: Path, monkeypatch) -> None:
    helper = _write_helper(tmp_path)
    _configure(monkeypatch, helper, mode="oracle-fail")

    with pytest.raises(E2EExecutorError, match="E2E_FINAL_ORACLE_NOT_PASS"):
        execute_e2e_journey(journey=_journey(), target_id=TARGET, timeout_seconds=10)


def test_l5_rejects_fixture_hop_receipt(tmp_path: Path, monkeypatch) -> None:
    helper = _write_helper(tmp_path)
    _configure(monkeypatch, helper, mode="fixture")

    with pytest.raises(E2EExecutorError, match="E2E_FIXTURE_REFERENCE_FORBIDDEN"):
        execute_e2e_journey(journey=_journey(), target_id=TARGET, timeout_seconds=10)


def test_l5_rejects_target_mismatch_before_process(tmp_path: Path, monkeypatch) -> None:
    helper = _write_helper(tmp_path)
    _configure(monkeypatch, helper, target="different-target")

    with pytest.raises(E2EExecutorError, match="E2E_TARGET_MISMATCH"):
        execute_e2e_journey(journey=_journey(), target_id=TARGET, timeout_seconds=10)
