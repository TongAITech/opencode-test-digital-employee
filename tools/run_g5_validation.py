from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

FROZEN_G1_G4_RUNNER_PATH = "tools/run_wave2_validation.py"
FROZEN_G1_G4_RUNNER_BLOB = "b006cecb48673a5b8735dda9e1b645ebafe7f1fc"

SUITES = (
    "test_g5_product_path.py",
    "test_g5_worker_binding_and_recovery.py",
    "test_g5_adversarial_defect_truth.py",
    "test_g5_human_gate_and_duplicate_correlation.py",
    "test_g5_same_mission_e2e.py",
    "test_g5_opencode_surface.py",
)
RUNTIME_ORACLE_SUITES = {
    "test_g5_adversarial_defect_truth.py",
    "test_g5_human_gate_and_duplicate_correlation.py",
    "test_g5_same_mission_e2e.py",
}
LATER_WAVE_SUITES = {
    "test_g5_adversarial_defect_truth.py",
    "test_g5_human_gate_and_duplicate_correlation.py",
    "test_g5_same_mission_e2e.py",
    "test_g5_opencode_surface.py",
}
PRODUCT_SEAM_CHECKS = {
    "g5_command_callable",
    "g5_cli_registered",
    "director_status_is_r1_truth",
    "cli_status_is_json_r1_truth",
    "invalid_role_fails_with_g5_role_forbidden",
    "invalid_action_fails_closed",
}
WORKER_BINDING_CHECKS = {
    "defect_hunter_task_dispatches",
    "current_binding_accepted",
    "wrong_task_rejected",
    "wrong_attempt_rejected",
    "wrong_session_rejected",
    "logical_agent_binding_missing_rejected",
    "logical_agent_binding_mismatch_rejected",
    "route_role_mismatch_rejected",
    "current_session_not_open_rejected",
    "stale_predecessor_rejected_after_rotation",
    "successor_binding_accepted_after_rotation",
    "root_logical_agent_binding_survives_rotation",
    "restart_work_context_uses_durable_truth",
}
PROGRAMMING_FAILURE_MARKERS = (
    "Traceback (most recent call last):",
    "SyntaxError:",
    "ImportError:",
    "ModuleNotFoundError:",
    "NameError:",
    "UnboundLocalError:",
    "AttributeError:",
    "StopIteration:",
    "KeyError:",
    "IndexError:",
    "ValueError:",
    "TypeError:",
    "AssertionError:",
    "FileNotFoundError:",
    "RuntimeError:",
)


def git_blob_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    body = path.read_bytes()
    header = f"blob {len(body)}\0".encode("utf-8")
    return hashlib.sha1(header + body).hexdigest()


def parse_last_json(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    values: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and not text[index + end :].strip():
            values.append(value)
    return values[-1] if values else None


def checks(parsed: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return {}
    value = parsed.get("runtime_behavior_checks") or parsed.get("contract_checks") or {}
    return value if isinstance(value, dict) else {}


def all_checks(parsed: dict[str, Any] | None, required: set[str]) -> bool:
    observed = checks(parsed)
    return all(observed.get(name) is True for name in required)


def product_runtime_green(parsed: dict[str, Any]) -> bool:
    return all_checks(parsed, PRODUCT_SEAM_CHECKS)


def worker_runtime_green(parsed: dict[str, Any]) -> bool:
    return all_checks(parsed, WORKER_BINDING_CHECKS)


def opencode_runtime_green(root: Path, parsed: dict[str, Any]) -> bool:
    contract = parsed.get("contract_checks") or {}
    if not isinstance(contract, dict) or not all(bool(value) for value in contract.values()):
        return False
    runtime = root / "workspace-template" / "ai-test" / "runtime"
    env = {**os.environ, "PYTHONPATH": str(runtime)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "aitest_runtime.product_entry",
            "g5",
            "--role",
            "DIAGNOSIS",
            "--action",
            "status",
            "--payload",
            "{}",
        ],
        cwd=str(root / "workspace-template"),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    result = parse_last_json(proc.stdout)
    return (
        proc.returncode == 0
        and isinstance(result, dict)
        and result.get("truth_source") == "R1_EVENT_STREAM"
    )


def oracle_shape(
    root: Path, filename: str, parsed: dict[str, Any] | None
) -> tuple[bool, bool, bool]:
    if not isinstance(parsed, dict):
        return False, False, False
    current_truth = (
        parsed.get("truthful_red") is True
        and parsed.get("red_kind") == "MISSING_G5_INTEGRATION"
    )
    if filename in RUNTIME_ORACLE_SUITES:
        contract = parsed.get("oracle_contract") or {}
        future_runtime = (
            isinstance(contract, dict)
            and contract.get("future_green_requires_real_runtime") is True
        )
        runtime_green = parsed.get("runtime_green_evidence") is True
        return future_runtime, current_truth, runtime_green
    if filename == "test_g5_product_path.py":
        return True, current_truth, product_runtime_green(parsed)
    if filename == "test_g5_worker_binding_and_recovery.py":
        return True, current_truth, worker_runtime_green(parsed)
    if filename == "test_g5_opencode_surface.py":
        return True, current_truth, opencode_runtime_green(root, parsed)
    return False, current_truth, False


def run_suite(root: Path, test_dir: Path, filename: str, mode: str) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(test_dir / filename)],
        cwd=str(test_dir),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    duration = round(time.monotonic() - started, 3)
    parsed = parse_last_json(proc.stdout)
    future_runtime, current_truth, runtime_green = oracle_shape(root, filename, parsed)
    programming_exception = any(
        marker in proc.stdout for marker in PROGRAMMING_FAILURE_MARKERS
    )
    if mode == "red":
        accepted = (
            proc.returncode != 0
            and isinstance(parsed, dict)
            and parsed.get("status") == "FAIL"
            and parsed.get("fixture_ok") is True
            and parsed.get("truthful_red") is True
            and parsed.get("red_kind") == "MISSING_G5_INTEGRATION"
            and bool(parsed.get("missing_contract_checks"))
            and future_runtime
            and current_truth
            and not runtime_green
            and not programming_exception
        )
    else:
        accepted = (
            proc.returncode == 0
            and isinstance(parsed, dict)
            and parsed.get("status") == "PASS"
            and parsed.get("fixture_ok") is True
            and not parsed.get("missing_contract_checks")
            and future_runtime
            and runtime_green
            and not programming_exception
        )
    return {
        "file": filename,
        "mode": mode,
        "returncode": proc.returncode,
        "duration_sec": duration,
        "accepted": accepted,
        "future_green_requires_real_runtime": future_runtime,
        "current_red_is_truthful": current_truth,
        "runtime_green_evidence": runtime_green,
        "programming_exception": programming_exception,
        "parsed": parsed,
        "output_tail": proc.stdout[-6000:],
    }


def suite_by_name(suites: list[dict[str, Any]], filename: str) -> dict[str, Any]:
    return next(item for item in suites if item["file"] == filename)


def structured_missing(suite: dict[str, Any]) -> bool:
    parsed = suite.get("parsed")
    return (
        suite.get("returncode") != 0
        and suite.get("programming_exception") is False
        and isinstance(parsed, dict)
        and parsed.get("status") == "FAIL"
        and parsed.get("fixture_ok") is True
        and parsed.get("truthful_red") is True
        and parsed.get("red_kind") == "MISSING_G5_INTEGRATION"
        and bool(parsed.get("missing_contract_checks"))
    )


def structured_or_green(suite: dict[str, Any]) -> bool:
    parsed = suite.get("parsed")
    if structured_missing(suite):
        return True
    return (
        suite.get("returncode") == 0
        and suite.get("programming_exception") is False
        and isinstance(parsed, dict)
        and parsed.get("status") == "PASS"
        and parsed.get("fixture_ok") is True
        and not parsed.get("missing_contract_checks")
    )


def ec1_verdict(
    suites: list[dict[str, Any]], frozen_runner_unchanged: bool
) -> tuple[bool, dict[str, bool], list[str]]:
    product = suite_by_name(suites, "test_g5_product_path.py")
    worker = suite_by_name(suites, "test_g5_worker_binding_and_recovery.py")
    adversarial = suite_by_name(suites, "test_g5_adversarial_defect_truth.py")
    product_parsed = product.get("parsed") or {}
    worker_parsed = worker.get("parsed") or {}
    adversarial_parsed = adversarial.get("parsed") or {}
    product_checks = product_parsed.get("contract_checks") or {}
    product_foundation = product_parsed.get("foundation_checks") or {}
    worker_checks = worker_parsed.get("contract_checks") or {}
    static_checks = adversarial_parsed.get("supplemental_checks") or {}

    conditions = {
        "frozen_g1_g4_runner_exact": frozen_runner_unchanged,
        "defect_hunter_role_registered": worker_checks.get("defect_hunter_role_registered") is True,
        "defect_hunter_agent_exact": worker_checks.get("defect_hunter_agent_exact") is True,
        "defect_hunter_capabilities_exact": worker_checks.get("defect_hunter_capabilities_exact") is True,
        "g5_package_importable": product_checks.get("g5_package_importable") is True,
        "g5_non_durable_contracts_present": product_checks.get("g5_non_durable_contracts_present") is True,
        "no_g5_durable_extension_registered": product_foundation.get("no_g5_durable_extension_registered") is True,
        "no_second_store_files": static_checks.get("no_second_store_files") is True,
        "no_session_owner": static_checks.get("fix_and_session_mutation_attrs_absent") is True,
        "g5_command_unavailable": product_checks.get("g5_command_callable") is False,
        "g5_cli_unavailable": product_checks.get("g5_cli_registered") is False,
        "worker_binding_unavailable": all(worker_checks.get(name) is False for name in WORKER_BINDING_CHECKS),
        "all_unavailable_stages_are_structured": all(structured_missing(suite) for suite in suites),
        "no_programming_exceptions": all(not suite["programming_exception"] for suite in suites),
    }
    failures = [name for name, passed in conditions.items() if not passed]
    return not failures, conditions, failures


def ec2_verdict(
    suites: list[dict[str, Any]], frozen_runner_unchanged: bool
) -> tuple[bool, bool, dict[str, bool], list[str]]:
    product = suite_by_name(suites, "test_g5_product_path.py")
    worker = suite_by_name(suites, "test_g5_worker_binding_and_recovery.py")
    later = [suite for suite in suites if suite["file"] in LATER_WAVE_SUITES]
    product_green = all_checks(product.get("parsed"), PRODUCT_SEAM_CHECKS)
    worker_green = all_checks(worker.get("parsed"), WORKER_BINDING_CHECKS)
    worker_checks = checks(worker.get("parsed"))
    conditions = {
        "frozen_g1_g4_runner_exact": frozen_runner_unchanged,
        "product_suite_structured": structured_or_green(product),
        "worker_suite_structured": structured_or_green(worker),
        "worker_binding_matrix_complete": WORKER_BINDING_CHECKS.issubset(worker_checks),
        "later_waves_fail_closed": all(structured_missing(suite) for suite in later),
        "no_programming_exceptions": all(not suite["programming_exception"] for suite in suites),
    }
    oracle_ready = all(conditions.values())
    wave_failures = []
    if not product_green:
        wave_failures.append("product_seam_green")
    if not worker_green:
        wave_failures.append("worker_binding_green")
    if not oracle_ready:
        wave_failures.extend(name for name, passed in conditions.items() if not passed)
    return oracle_ready and not wave_failures, oracle_ready, conditions, wave_failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Canonical additive G5 EC0-EC7 validation runner"
    )
    parser.add_argument("--root", default=".")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--mode", choices=("red", "green"))
    selection.add_argument("--wave", choices=("EC1", "EC2"))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    mode = args.mode or "red"
    root = Path(args.root).resolve()
    test_dir = root / "workspace-template" / ".pfc-internal-field-validation" / "tests"
    frozen_runner = root / FROZEN_G1_G4_RUNNER_PATH
    frozen_blob = git_blob_sha(frozen_runner)
    frozen_runner_unchanged = frozen_blob == FROZEN_G1_G4_RUNNER_BLOB
    suites = [run_suite(root, test_dir, filename, mode) for filename in SUITES]

    all_suites_accepted = all(suite["accepted"] for suite in suites)
    legacy_status = (
        "PASS"
        if frozen_runner_unchanged and len(suites) == 6 and all_suites_accepted
        else "FAIL"
    )
    result: dict[str, Any] = {
        "status": legacy_status,
        "mode": mode,
        "truth_source": "CONSTRUCTION_VALIDATION_EVIDENCE",
        "suite_count": len(suites),
        "all_g5_suites_accepted": all_suites_accepted,
        "ec0_truthful_red_frozen": mode == "red" and legacy_status == "PASS",
        "g5_green": mode == "green" and legacy_status == "PASS",
        "green_requires_runtime_behavior_in_every_suite": all(
            suite["future_green_requires_real_runtime"] for suite in suites
        ),
        "frozen_g1_g4_regression_runner": {
            "path": FROZEN_G1_G4_RUNNER_PATH,
            "expected_blob": FROZEN_G1_G4_RUNNER_BLOB,
            "observed_blob": frozen_blob,
            "unchanged": frozen_runner_unchanged,
            "authority": "G1_G4_REGRESSION_ONLY",
            "executed_by_this_runner": False,
            "note": "Historical g5_defect_truth=HOLD is metadata only and is not G5 gate truth.",
        },
        "suites": suites,
    }

    if args.wave == "EC1":
        passed, conditions, failures = ec1_verdict(suites, frozen_runner_unchanged)
        result.update(
            {
                "status": "PASS" if passed else "FAIL",
                "wave": "EC1",
                "wave_expectation_satisfied": passed,
                "wave_conditions": conditions,
                "wave_failures": failures,
            }
        )
    elif args.wave == "EC2":
        passed, oracle_ready, conditions, failures = ec2_verdict(
            suites, frozen_runner_unchanged
        )
        worker = suite_by_name(suites, "test_g5_worker_binding_and_recovery.py")
        worker_checks = checks(worker.get("parsed"))
        result.update(
            {
                "status": "PASS" if passed else "FAIL",
                "wave": "EC2",
                "wave_expectation_satisfied": passed,
                "product_seam_green": "product_seam_green" not in failures,
                "worker_binding_green": "worker_binding_green" not in failures,
                "later_waves_fail_closed": conditions["later_waves_fail_closed"],
                "ec2_r2_5_missing_oracle_present": "logical_agent_binding_missing_rejected" in worker_checks,
                "ec2_r2_5_mismatch_oracle_present": "logical_agent_binding_mismatch_rejected" in worker_checks,
                "wave_oracle_ready": oracle_ready,
                "wave_conditions": conditions,
                "wave_failures": failures,
            }
        )

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output = output if output.is_absolute() else root / output
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
