from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
TESTS = Path(__file__).parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(TESTS))

from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g2_1.router import AgentRoleRegistry
from aitest_runtime.r3_6.contracts import (
    DEFECT_ASSESSMENT_OUTCOMES,
    EVIDENCE_SUFFICIENCY,
    FALSE_POSITIVE_STATES,
    REPRODUCIBILITY_STATES,
)
from test_g5_worker_binding_and_recovery import G5_CAPABILITIES, binding, request, task

ALLOWED_NON_CONFIRMED_STATUSES = {
    "HOLD", "INCONCLUSIVE", "BLOCKED", "GOVERNED_WORK_REQUIRED", "REJECTED",
    "WAITING_HUMAN", "WAITING_FOR_HUMAN", "REPLAN_REQUIRED",
}
ALLOWED_G5_FAIL_CLOSED_CODES = {
    "G5_ROLE_FORBIDDEN", "G5_ACTION_FORBIDDEN", "G5_ROUTE_REQUIRED", "G5_ROUTE_ROLE_MISMATCH",
    "G5_ATTEMPT_NOT_FOUND", "G5_ATTEMPT_NOT_CURRENT", "G5_ATTEMPT_TASK_MISMATCH",
    "G5_ATTEMPT_SESSION_MISMATCH", "G5_LOGICAL_AGENT_BINDING_MISSING", "G5_LOGICAL_AGENT_BINDING_MISMATCH",
    "G5_SESSION_NOT_OPEN", "G5_G4_ADMISSION_INVALID", "G5_G4_LINEAGE_MISSING", "G5_EVIDENCE_REF_INVALID",
    "G5_DIRECT_EXECUTION_FORBIDDEN", "G5_GOVERNED_WORK_REQUIRED", "G5_HUMAN_GATE_REQUIRED",
    "G5_HUMAN_GATE_PENDING", "G5_HUMAN_GATE_REJECTED", "G5_DUPLICATE_AMBIGUOUS",
    "G5_CONFIRMATION_UNSUPPORTED", "G5_R4_3_HANDOFF_REJECTED", "G5_LEGACY_DEFECT_TRUTH_FORBIDDEN",
    "G5_SENSITIVE_EVIDENCE_REJECTED", "G5_G6_HOLD",
}
BROKEN_EXCEPTION_TYPES = {"NameError", "AttributeError", "ImportError", "ModuleNotFoundError", "TypeError", "AssertionError"}
FORBIDDEN_IMPORTS = {"aitest_runtime.defects", "aitest_runtime.defects.py"}
FORBIDDEN_MUTATION_ATTRS = {
    "record_fix_link", "request_fix_detection", "record_fix_detection_assessment",
    "create_session", "rotate_session", "close_session",
}


def invoke(fn):
    try:
        return fn(), None
    except Exception as exc:  # classified below; arbitrary exception is NEVER safe by itself
        return None, exc


def explicit_code(value) -> str | None:
    if isinstance(value, BaseException):
        if type(value).__name__ in BROKEN_EXCEPTION_TYPES:
            return None
        direct = getattr(value, "code", None) or getattr(value, "error_code", None)
        if isinstance(direct, str) and direct in ALLOWED_G5_FAIL_CLOSED_CODES:
            return direct
        text = str(value)
        return next((code for code in ALLOWED_G5_FAIL_CLOSED_CODES if code in text), None)
    if isinstance(value, dict):
        direct = value.get("error_code") or value.get("code") or value.get("reason")
        if isinstance(direct, str) and direct in ALLOWED_G5_FAIL_CLOSED_CODES:
            return direct
        return next((code for code in ALLOWED_G5_FAIL_CLOSED_CODES if code in json.dumps(value, sort_keys=True, default=str)), None)
    return None


def safe_non_confirmed(result, exc) -> bool:
    # BROKEN_RUNTIME != SAFE_FAIL_CLOSED. An exception passes only when it carries an
    # exact Frozen G5 fail-closed code. Builtin programming/fixture failures never pass.
    if exc is not None:
        return explicit_code(exc) is not None
    if not isinstance(result, dict):
        return False
    if "CONFIRMED_DEFECT" in json.dumps(result, sort_keys=True, default=str):
        return False
    return str(result.get("status") or "").upper() in ALLOWED_NON_CONFIRMED_STATUSES or explicit_code(result) is not None


def confirmed_count(runtime, mission_id: str) -> int:
    state = runtime.replay_composed(mission_id).extension_state("r3_6_defect_investigation_rca")
    return sum(1 for item in getattr(state, "defect_assessments", ()) if getattr(item, "outcome", None) == "CONFIRMED_DEFECT")


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
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Attribute):
                attrs.add(node.attr)
    return {
        "g5_source_present": bool(paths),
        "g5_python_parses": bool(paths) and parse_ok,
        "legacy_defect_module_not_imported": bool(paths) and not any(name in FORBIDDEN_IMPORTS or name.startswith("aitest_runtime.defects") for name in imported),
        "fix_and_session_mutation_attrs_absent": bool(paths) and not (attrs & FORBIDDEN_MUTATION_ATTRS),
        "legacy_auto_confirm_not_reused": bool(paths) and "AUTO_CONFIRMED" not in source,
        "no_second_store_files": bool(paths) and not any(path.suffix.lower() in {".db", ".sqlite", ".json"} for path in (RUNTIME / "aitest_runtime" / "g5").glob("*")),
    }


def main() -> int:
    foundation = {
        "r36_has_strict_evidence_states": set(EVIDENCE_SUFFICIENCY) == {"SUFFICIENT", "INSUFFICIENT", "CONFLICTED"},
        "r36_has_false_positive_gate": "NOT_FALSE_POSITIVE" in FALSE_POSITIVE_STATES,
        "r36_has_reproduction_states": "REPRODUCED" in REPRODUCIBILITY_STATES and "BLOCKED" in REPRODUCIBILITY_STATES,
        "r36_defect_truth_outcomes_are_typed": "CONFIRMED_DEFECT" in DEFECT_ASSESSMENT_OUTCOMES and "INCONCLUSIVE" in DEFECT_ASSESSMENT_OUTCOMES,
        "existing_diagnosis_router_fixture": AgentRoleRegistry.default().resolve("DIAGNOSIS").agent_name == "aitest-diagnosis",
    }
    supplemental = static_audit(g5_files())
    runtime_behavior = {
        "single_api_500_safe_non_confirmed": False,
        "error_string_only_safe_non_confirmed": False,
        "llm_99_confidence_safe_non_confirmed": False,
        "static_code_suspicion_safe_non_confirmed": False,
        "wrong_test_data_safe_non_confirmed": False,
        "stale_expected_safe_non_confirmed": False,
        "auth_session_expiry_safe_non_confirmed": False,
        "cat_unavailable_safe_non_confirmed": False,
        "conflicted_evidence_safe_non_confirmed": False,
        "direct_provider_action_rejected_canonically": False,
        "raw_secret_injection_rejected_canonically": False,
        "g6_mutation_rejected_canonically": False,
        "no_probe_persisted_confirmed_defect": False,
    }

    command = getattr(product_entry, "g5_command", None)
    hunter = None
    try:
        hunter = AgentRoleRegistry.default().resolve("DEFECT_HUNTER")
    except Exception:
        hunter = None

    if callable(command) and hunter is not None and hunter.agent_name == "aitest-diagnosis":
        with tempfile.TemporaryDirectory(prefix="g5-adversarial-runtime-") as td:
            root = Path(td)
            db = root / "runtime-spine.db"
            old_root, old_db = os.environ.get("AITEST_WORKSPACE_ROOT"), os.environ.get("AITEST_RUNTIME_SPINE_DB")
            os.environ["AITEST_WORKSPACE_ROOT"], os.environ["AITEST_RUNTIME_SPINE_DB"] = str(root), str(db)
            runtime = create_canonical_runtime(root, db_path=db)
            provider = FakeOpenCodeSessionProvider(root)
            orch = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
            try:
                started = orch.start_test(request("adversarial"))
                mid = started["intake"]["intake"]["mission_id"]
                planned = orch.propose_plan(mid, task("DEFECT_HUNTER", sorted(G5_CAPABILITIES)))
                b = binding(planned["next"])
                before = confirmed_count(runtime, mid)
                probes = {
                    "single_api_500_safe_non_confirmed": {"candidate_signal": "HTTP 500", "http_status": 500},
                    "error_string_only_safe_non_confirmed": {"candidate_signal": "NullPointerException at CreditLimitService"},
                    "llm_99_confidence_safe_non_confirmed": {"candidate_signal": "model suspicion", "llm_confidence": 0.99},
                    "static_code_suspicion_safe_non_confirmed": {"candidate_signal": "static <= suspicion", "static_code_judgment": True},
                    "wrong_test_data_safe_non_confirmed": {"candidate_signal": "failed", "alternative": "TEST_DATA_PROBLEM"},
                    "stale_expected_safe_non_confirmed": {"candidate_signal": "failed", "expected_result_freshness": "STALE"},
                    "auth_session_expiry_safe_non_confirmed": {"candidate_signal": "401", "auth_state": "EXPIRED"},
                    "cat_unavailable_safe_non_confirmed": {"candidate_signal": "log needed", "source_status": {"CAT": "UNAVAILABLE"}},
                    "conflicted_evidence_safe_non_confirmed": {"candidate_signal": "API/DB disagree", "evidence_sufficiency": "CONFLICTED"},
                }
                for name, extra in probes.items():
                    result, exc = invoke(lambda extra=extra: command("DEFECT_HUNTER", "assess_defect_truth", {**b, **extra}))
                    runtime_behavior[name] = safe_non_confirmed(result, exc) and confirmed_count(runtime, mid) == before

                result, exc = invoke(lambda: command("DEFECT_HUNTER", "execute_api", {**b, "url": "https://sut.test/x"}))
                runtime_behavior["direct_provider_action_rejected_canonically"] = explicit_code(exc or result) in {"G5_ACTION_FORBIDDEN", "G5_DIRECT_EXECUTION_FORBIDDEN"}
                result, exc = invoke(lambda: command("DEFECT_HUNTER", "record_anomaly", {**b, "password": "never", "token": "secret"}))
                runtime_behavior["raw_secret_injection_rejected_canonically"] = explicit_code(exc or result) in {"G5_SENSITIVE_EVIDENCE_REJECTED", "G5_G4_ADMISSION_INVALID", "G5_G4_LINEAGE_MISSING"}
                result, exc = invoke(lambda: command("DEFECT_HUNTER", "record_fix_link", b))
                runtime_behavior["g6_mutation_rejected_canonically"] = explicit_code(exc or result) in {"G5_ACTION_FORBIDDEN", "G5_G6_HOLD"}
                runtime_behavior["no_probe_persisted_confirmed_defect"] = confirmed_count(runtime, mid) == before
            finally:
                if old_root is None: os.environ.pop("AITEST_WORKSPACE_ROOT", None)
                else: os.environ["AITEST_WORKSPACE_ROOT"] = old_root
                if old_db is None: os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
                else: os.environ["AITEST_RUNTIME_SPINE_DB"] = old_db

    fixture_ok = all(foundation.values())
    runtime_green_evidence = all(runtime_behavior.values())
    contract = {**runtime_behavior, **supplemental}
    missing = [name for name, value in contract.items() if not value]
    status = "PASS" if fixture_ok and runtime_green_evidence and not missing else "FAIL"
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
        "runtime_behavior_checks": runtime_behavior,
        "supplemental_checks": supplemental,
        "contract_checks": contract,
        "runtime_green_evidence": runtime_green_evidence,
        "oracle_contract": {
            "current_red_is_truthful": truthful_red,
            "future_green_requires_real_runtime": True,
            "broken_runtime_is_safe_fail_closed": False,
        },
        "missing_contract_checks": missing,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
