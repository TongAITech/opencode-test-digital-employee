from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from rc7_release.zap_executor import ZapExecutorError, execute_zap_scan


TARGET = "target-bank-l7"
TARGET_URL = "https://bank.example/cfg-admin"


def _write_zap_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "zap_helper.py"
    helper.write_text(
        "import json, os, pathlib, sys\n"
        "mode = sys.argv[1]\n"
        "args = sys.argv[2:]\n"
        "if '-cmd' not in args or '-autorun' not in args:\n"
        "    print('bad zap command', file=sys.stderr); sys.exit(21)\n"
        "plan = pathlib.Path(args[args.index('-autorun') + 1])\n"
        "if not plan.is_file():\n"
        "    print('plan missing', file=sys.stderr); sys.exit(22)\n"
        "report = pathlib.Path(os.environ['PFC_ZAP_REPORT_PATH'])\n"
        "if mode == 'no-report':\n"
        "    print('scan ended without report'); sys.exit(0)\n"
        "site = 'https://other.example/' if mode == 'wrong-target' else os.environ['PFC_ZAP_TARGET_URL']\n"
        "alerts = []\n"
        "if mode == 'finding':\n"
        "    alerts = [{'pluginid': '10020', 'alertRef': '10020', 'alert': 'X-Frame-Options Header Not Set', 'riskcode': '2', 'confidence': '2', 'instances': [{'uri': site}]}]\n"
        "payload = {'@version': 'controlled-zap-protocol', 'site': [{'@name': site, 'alerts': alerts}]}\n"
        "report.parent.mkdir(parents=True, exist_ok=True)\n"
        "report.write_text(json.dumps(payload), encoding='utf-8')\n"
        "print('zap helper completed')\n",
        encoding="utf-8",
    )
    return helper


def _write_plan(tmp_path: Path) -> Path:
    plan = tmp_path / "zap-plan.yaml"
    plan.write_text("env:\n  contexts: []\njobs: []\n", encoding="utf-8")
    return plan


def _configure(monkeypatch, tmp_path: Path, helper: Path, mode: str = "success", target: str = TARGET) -> Path:
    report = tmp_path / "zap-report.json"
    monkeypatch.setenv("PFC_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PFC_ZAP_TARGET_ID", target)
    monkeypatch.setenv("PFC_ZAP_TARGET_URL", TARGET_URL)
    monkeypatch.setenv("PFC_ZAP_BIN", sys.executable)
    monkeypatch.setenv("PFC_ZAP_ARGS_JSON", json.dumps([str(helper), mode]))
    monkeypatch.setenv("PFC_ZAP_REPORT_PATH", str(report))
    return report


def test_l7_executes_zap_cli_shape_and_accepts_valid_target_report(tmp_path: Path, monkeypatch) -> None:
    helper = _write_zap_helper(tmp_path)
    plan = _write_plan(tmp_path)
    _configure(monkeypatch, tmp_path, helper)

    result = execute_zap_scan(plan_path=str(plan), scan_id="security-baseline", target_id=TARGET, timeout_seconds=10)

    assert result["tool"] == "zap"
    assert result["implementation"] == "zap-automation-framework"
    assert result["target_id"] == TARGET
    assert result["target_origin"] == "https://bank.example"
    assert result["summary"]["matched_site_count"] == 1
    assert result["summary"]["finding_count"] == 0
    assert result["fresh_report_required"] is True
    assert result["shell"] is False
    assert result["invocation_ref"].startswith("zap://%s/security-baseline/" % TARGET)


def test_l7_findings_are_actual_not_executor_failure(tmp_path: Path, monkeypatch) -> None:
    helper = _write_zap_helper(tmp_path)
    plan = _write_plan(tmp_path)
    _configure(monkeypatch, tmp_path, helper, mode="finding")

    result = execute_zap_scan(plan_path=str(plan), scan_id="security-baseline", target_id=TARGET, timeout_seconds=10)

    assert result["summary"]["finding_count"] == 1
    assert result["summary"]["risk_counts"]["medium"] == 1
    assert result["summary"]["findings_are_product_security_actual_not_executor_failure"] is True


def test_l7_rejects_wrong_target_report_even_when_process_exits_zero(tmp_path: Path, monkeypatch) -> None:
    helper = _write_zap_helper(tmp_path)
    plan = _write_plan(tmp_path)
    _configure(monkeypatch, tmp_path, helper, mode="wrong-target")

    with pytest.raises(ZapExecutorError, match="ZAP_REPORT_TARGET_SITE_NOT_FOUND"):
        execute_zap_scan(plan_path=str(plan), scan_id="security-baseline", target_id=TARGET, timeout_seconds=10)


def test_l7_rejects_missing_fresh_report_and_does_not_reuse_stale_file(tmp_path: Path, monkeypatch) -> None:
    helper = _write_zap_helper(tmp_path)
    plan = _write_plan(tmp_path)
    report = _configure(monkeypatch, tmp_path, helper, mode="no-report")
    report.write_text(json.dumps({"site": [{"@name": TARGET_URL, "alerts": []}]}), encoding="utf-8")

    with pytest.raises(ZapExecutorError, match="ZAP_FRESH_REPORT_NOT_PRODUCED"):
        execute_zap_scan(plan_path=str(plan), scan_id="security-baseline", target_id=TARGET, timeout_seconds=10)
    assert not report.exists()


def test_l7_rejects_target_identity_mismatch_before_execution(tmp_path: Path, monkeypatch) -> None:
    helper = _write_zap_helper(tmp_path)
    plan = _write_plan(tmp_path)
    _configure(monkeypatch, tmp_path, helper, target="different-target")

    with pytest.raises(ZapExecutorError, match="ZAP_TARGET_MISMATCH"):
        execute_zap_scan(plan_path=str(plan), scan_id="security-baseline", target_id=TARGET, timeout_seconds=10)


def test_l7_rejects_plan_outside_workspace(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    helper = _write_zap_helper(workspace)
    outside = tmp_path / "outside-plan.yaml"
    outside.write_text("jobs: []\n", encoding="utf-8")
    _configure(monkeypatch, workspace, helper)

    with pytest.raises(ZapExecutorError, match="ZAP_PLAN_PATH_ESCAPE"):
        execute_zap_scan(plan_path=str(outside), scan_id="security-baseline", target_id=TARGET, timeout_seconds=10)
