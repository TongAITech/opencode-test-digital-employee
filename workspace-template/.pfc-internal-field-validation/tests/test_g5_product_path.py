from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
TESTS = Path(__file__).parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(TESTS))

from aitest_runtime import product_entry
from aitest_runtime.canonical_runtime import canonical_extension_manifests
from aitest_runtime.r3_6.contracts import ARCHITECTURE_BASELINE_REF
from aitest_runtime.r3_6.service import R36ApplicationService
from aitest_runtime.r4_3.service import R43ApplicationService

REQUIRED_DIRECTOR_ACTIONS = {
    "status", "intake_observations", "investigation_status", "open_investigation",
    "request_human_review", "canonical_defects",
}
REQUIRED_WORKER_ACTIONS = {
    "status", "work_context", "record_anomaly", "create_candidate",
    "request_evidence_deepening", "record_evidence_assessment", "correlate_sources",
    "evaluate_reproducibility", "assess_false_positive", "assess_defect_truth",
    "record_rca", "record_checkpoint", "handoff_confirmed_defect",
}


def parse_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def invoke(fn):
    try:
        return fn(), None
    except Exception as exc:
        return None, exc


def error_code(value) -> str:
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("error_code") or value.get("code") or value.get("reason") or value.get("message") or "")
    return str(value or "")


def parser_has_g5() -> bool:
    parser = product_entry.parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return "g5" in action.choices
    return False


def g5_source() -> str:
    root = RUNTIME / "aitest_runtime" / "g5"
    if not root.is_dir():
        return ""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.glob("*.py")) if path.is_file())


def main() -> int:
    foundation = {
        "product_entry_importable": callable(product_entry.parser),
        "r36_service_available": callable(R36ApplicationService),
        "r43_service_available": callable(R43ApplicationService),
        "r36_historical_baseline_unchanged": ARCHITECTURE_BASELINE_REF == "v5",
        "no_g5_durable_extension_registered": all(
            "g5" not in str(getattr(manifest, "extension_id", "")).lower()
            for manifest in canonical_extension_manifests()
        ),
    }

    g5_module, g5_import_error = invoke(lambda: importlib.import_module("aitest_runtime.g5"))
    source = g5_source()
    command = getattr(product_entry, "g5_command", None)

    direct_status = {}
    direct_exc = None
    if callable(command):
        with tempfile.TemporaryDirectory(prefix="g5-product-status-") as td:
            old_root = os.environ.get("AITEST_WORKSPACE_ROOT")
            old_db = os.environ.get("AITEST_RUNTIME_SPINE_DB")
            os.environ["AITEST_WORKSPACE_ROOT"] = td
            os.environ["AITEST_RUNTIME_SPINE_DB"] = str(Path(td) / "runtime-spine.db")
            try:
                direct_status, direct_exc = invoke(lambda: command("DIRECTOR", "status", {}))
            finally:
                if old_root is None: os.environ.pop("AITEST_WORKSPACE_ROOT", None)
                else: os.environ["AITEST_WORKSPACE_ROOT"] = old_root
                if old_db is None: os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
                else: os.environ["AITEST_RUNTIME_SPINE_DB"] = old_db

    cli = {}
    cli_returncode = None
    if parser_has_g5():
        with tempfile.TemporaryDirectory(prefix="g5-product-cli-") as td:
            env = os.environ.copy()
            env["AITEST_WORKSPACE_ROOT"] = td
            env["AITEST_RUNTIME_SPINE_DB"] = str(Path(td) / "runtime-spine.db")
            env["PYTHONPATH"] = str(RUNTIME) + os.pathsep + env.get("PYTHONPATH", "")
            proc = subprocess.run(
                [sys.executable, "-m", "aitest_runtime.product_entry", "g5", "--role", "DIRECTOR", "--action", "status", "--payload", "{}"],
                cwd=str(WORKSPACE), env=env, text=True, capture_output=True, timeout=60,
            )
            cli_returncode = proc.returncode
            cli = parse_json(proc.stdout)

    invalid_role = invalid_role_exc = invalid_action = invalid_action_exc = None
    if callable(command):
        invalid_role, invalid_role_exc = invoke(lambda: command("EXECUTOR", "status", {}))
        invalid_action, invalid_action_exc = invoke(lambda: command("DIRECTOR", "execute_provider", {}))

    contract = {
        "g5_package_importable": g5_module is not None and g5_import_error is None,
        "g5_command_callable": callable(command),
        "g5_cli_registered": parser_has_g5(),
        "director_status_is_r1_truth": isinstance(direct_status, dict) and direct_exc is None and direct_status.get("truth_source") == "R1_EVENT_STREAM",
        "cli_status_is_json_r1_truth": cli_returncode == 0 and cli.get("truth_source") == "R1_EVENT_STREAM",
        "invalid_role_fails_with_g5_role_forbidden": "G5_ROLE_FORBIDDEN" in error_code(invalid_role_exc or invalid_role),
        "invalid_action_fails_closed": any(code in error_code(invalid_action_exc or invalid_action) for code in ("G5_ACTION_FORBIDDEN", "G5_DIRECT_EXECUTION_FORBIDDEN")),
        "director_action_registry_present": bool(source) and all(action in source for action in REQUIRED_DIRECTOR_ACTIONS),
        "worker_action_registry_present": bool(source) and all(action in source for action in REQUIRED_WORKER_ACTIONS),
        "r1_truth_contract_present": bool(source) and "R1_EVENT_STREAM" in source,
        "legacy_defect_module_not_imported": bool(source) and "aitest_runtime.defects" not in source and "AUTO_CONFIRMED" not in source,
    }

    fixture_ok = all(foundation.values())
    missing = [name for name, value in contract.items() if not value]
    status = "PASS" if fixture_ok and not missing else "FAIL"
    truthful_red = fixture_ok and status == "FAIL" and bool(missing)
    out = {
        "suite": "test_g5_product_path",
        "status": status,
        "passed": sum(bool(v) for v in {**foundation, **contract}.values()),
        "total": len(foundation) + len(contract),
        "fixture_ok": fixture_ok,
        "truthful_red": truthful_red,
        "red_kind": "MISSING_G5_INTEGRATION" if truthful_red else None,
        "foundation_checks": foundation,
        "contract_checks": contract,
        "missing_contract_checks": missing,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
