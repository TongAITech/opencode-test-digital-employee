from __future__ import annotations

import ast
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME))

from aitest_runtime import product_entry
from aitest_runtime.r3_6.contracts import (
    DEFECT_ASSESSMENT_OUTCOMES,
    EVIDENCE_SUFFICIENCY,
    FALSE_POSITIVE_STATES,
    REPRODUCIBILITY_STATES,
)

FORBIDDEN_IMPORTS = {"aitest_runtime.defects", "aitest_runtime.defects.py"}
FORBIDDEN_MUTATION_ATTRS = {
    "record_fix_link", "request_fix_detection", "record_fix_detection_assessment",
    "create_session", "rotate_session", "close_session",
}
REQUIRED_FAILURE_CODES = {
    "G5_DIRECT_EXECUTION_FORBIDDEN",
    "G5_CONFIRMATION_UNSUPPORTED",
    "G5_LEGACY_DEFECT_TRUTH_FORBIDDEN",
    "G5_SENSITIVE_EVIDENCE_REJECTED",
    "G5_G6_HOLD",
}


def invoke(fn):
    try:
        return fn(), None
    except Exception as exc:
        return None, exc


def text_code(value) -> str:
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("error_code") or value.get("code") or value.get("reason") or value.get("message") or "")
    return str(value or "")


def g5_files() -> list[Path]:
    root = RUNTIME / "aitest_runtime" / "g5"
    return sorted(path for path in root.glob("*.py") if path.is_file()) if root.is_dir() else []


def static_audit(paths: list[Path]) -> dict[str, bool]:
    imported: set[str] = set()
    attrs: set[str] = set()
    source = ""
    parse_ok = True
    for path in paths:
        body = path.read_text(encoding="utf-8")
        source += "\n" + body
        try:
            tree = ast.parse(body, filename=str(path))
        except SyntaxError:
            parse_ok = False
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
            elif isinstance(node, ast.Attribute):
                attrs.add(node.attr)
    return {
        "g5_source_present": bool(paths),
        "g5_python_parses": bool(paths) and parse_ok,
        "legacy_defect_module_not_imported": bool(paths) and not any(name in FORBIDDEN_IMPORTS or name.startswith("aitest_runtime.defects") for name in imported),
        "fix_and_session_mutation_attrs_absent": bool(paths) and not (attrs & FORBIDDEN_MUTATION_ATTRS),
        "legacy_auto_confirm_not_reused": bool(paths) and "AUTO_CONFIRMED" not in source,
        "required_failure_codes_present": bool(paths) and REQUIRED_FAILURE_CODES.issubset(set(code for code in REQUIRED_FAILURE_CODES if code in source)),
        "no_second_store_files": bool(paths) and not any(path.suffix.lower() in {".db", ".sqlite", ".json"} for path in (RUNTIME / "aitest_runtime" / "g5").glob("*")),
    }


def non_confirmed(result, exc) -> bool:
    if exc is not None:
        return True
    if not isinstance(result, dict):
        return False
    text = json.dumps(result, sort_keys=True, default=str)
    return "CONFIRMED_DEFECT" not in text or result.get("status") in {"FAIL", "BLOCKED", "HOLD", "INCONCLUSIVE", "REJECTED"}


def main() -> int:
    foundation = {
        "r36_has_strict_evidence_states": set(EVIDENCE_SUFFICIENCY) == {"SUFFICIENT", "INSUFFICIENT", "CONFLICTED"},
        "r36_has_false_positive_gate": "NOT_FALSE_POSITIVE" in FALSE_POSITIVE_STATES,
        "r36_has_reproduction_states": "REPRODUCED" in REPRODUCIBILITY_STATES and "BLOCKED" in REPRODUCIBILITY_STATES,
        "r36_defect_truth_outcomes_are_typed": "CONFIRMED_DEFECT" in DEFECT_ASSESSMENT_OUTCOMES and "INCONCLUSIVE" in DEFECT_ASSESSMENT_OUTCOMES,
        "legacy_file_may_exist_but_is_not_authority": (RUNTIME / "aitest_runtime" / "defects.py").is_file(),
    }

    paths = g5_files()
    contract = static_audit(paths)
    command = getattr(product_entry, "g5_command", None)
    contract.update({
        "single_500_not_confirmed": False,
        "error_string_only_not_confirmed": False,
        "llm_confidence_only_not_confirmed": False,
        "static_code_suspicion_only_not_confirmed": False,
        "direct_provider_action_rejected": False,
        "raw_secret_injection_rejected": False,
        "g6_mutation_rejected": False,
    })

    if callable(command):
        with tempfile.TemporaryDirectory(prefix="g5-adversarial-") as td:
            old_root = os.environ.get("AITEST_WORKSPACE_ROOT")
            old_db = os.environ.get("AITEST_RUNTIME_SPINE_DB")
            os.environ["AITEST_WORKSPACE_ROOT"] = td
            os.environ["AITEST_RUNTIME_SPINE_DB"] = str(Path(td) / "runtime-spine.db")
            try:
                probes = {
                    "single_500_not_confirmed": {"candidate_signal": "HTTP 500", "http_status": 500},
                    "error_string_only_not_confirmed": {"candidate_signal": "NullPointerException at CreditLimitService"},
                    "llm_confidence_only_not_confirmed": {"candidate_signal": "model suspicion", "llm_confidence": 0.99},
                    "static_code_suspicion_only_not_confirmed": {"candidate_signal": "static code comparison suggests <= bug", "static_code_judgment": True},
                }
                for name, extra in probes.items():
                    value, exc = invoke(lambda extra=extra: command("DEFECT_HUNTER", "assess_defect_truth", {
                        "mission_id": "missing-mission", "task_id": "missing-task", "attempt_id": "missing-attempt", "session_id": "missing-session", **extra,
                    }))
                    contract[name] = non_confirmed(value, exc)

                direct, direct_exc = invoke(lambda: command("DEFECT_HUNTER", "execute_api", {"mission_id": "m", "task_id": "t", "attempt_id": "a", "session_id": "s"}))
                contract["direct_provider_action_rejected"] = any(code in text_code(direct_exc or direct) for code in ("G5_ACTION_FORBIDDEN", "G5_DIRECT_EXECUTION_FORBIDDEN"))

                secret, secret_exc = invoke(lambda: command("DEFECT_HUNTER", "record_anomaly", {
                    "mission_id": "m", "task_id": "t", "attempt_id": "a", "session_id": "s", "password": "never-persist", "token": "secret",
                }))
                contract["raw_secret_injection_rejected"] = secret_exc is not None or any(code in text_code(secret) for code in ("G5_SENSITIVE_EVIDENCE_REJECTED", "G5_ROUTE_REQUIRED", "G5_G4_ADMISSION_INVALID"))

                g6, g6_exc = invoke(lambda: command("DEFECT_HUNTER", "record_fix_link", {"mission_id": "m", "task_id": "t", "attempt_id": "a", "session_id": "s"}))
                contract["g6_mutation_rejected"] = any(code in text_code(g6_exc or g6) for code in ("G5_ACTION_FORBIDDEN", "G5_G6_HOLD"))
            finally:
                if old_root is None: os.environ.pop("AITEST_WORKSPACE_ROOT", None)
                else: os.environ["AITEST_WORKSPACE_ROOT"] = old_root
                if old_db is None: os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
                else: os.environ["AITEST_RUNTIME_SPINE_DB"] = old_db

    fixture_ok = all(foundation.values())
    missing = [name for name, value in contract.items() if not value]
    status = "PASS" if fixture_ok and not missing else "FAIL"
    truthful_red = fixture_ok and status == "FAIL" and bool(missing)
    out = {
        "suite": "test_g5_adversarial_defect_truth",
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
