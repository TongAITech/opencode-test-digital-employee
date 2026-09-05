from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
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
DIRECTOR_SURFACE_CHECKS = {
    "director_intake_observations_is_r1_read_only",
    "director_intake_reports_admitted_status",
    "director_investigation_status_is_durable_truth",
    "director_investigation_status_uses_latest_valid_checkpoint",
    "director_open_investigation_returns_governed_work",
    "director_open_investigation_does_not_create_plan",
    "director_open_investigation_does_not_create_task",
    "director_existing_hunter_task_reused_only_if_exact",
    "director_canonical_defects_reads_r43",
    "director_canonical_defects_is_same_mission_read_only",
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
EC3_PRECONFIRMATION_CHECKS = {
    "g4_fail_creates_durable_unexpected_observation",
    "g4_fail_remains_observation_only",
    "missing_g4_lineage_rejected",
    "wrong_g4_lineage_rejected",
    "g5_exact_admission_creates_r36_anomaly",
    "g5_originated_r36_lineage_v7",
    "r36_candidate_created",
    "candidate_hypothesis_and_alternatives_explicit",
    "existing_typed_refs_deepening_durable_ec3",
    "evidence_assessment_durable_ec3",
    "cross_source_correlation_durable_ec3",
    "reproducibility_durable_ec3",
    "false_positive_assessment_durable_ec3",
    "rca_durable_ec3",
    "checkpoint_durable_ec3",
}
EC3_SAFETY_CHECKS = {
    "single_api_500_safe_non_confirmed",
    "error_string_only_safe_non_confirmed",
    "llm_99_confidence_safe_non_confirmed",
    "static_code_suspicion_safe_non_confirmed",
}
CONFIRMATION_BARRIER_CHECKS = {
    "confirmation_action_blocked_before_ec5",
    "no_confirmed_defect_persisted_after_ec3",
    "no_r43_lifecycle_opened_after_ec3",
}
EC4_GOVERNED_EVIDENCE_CHECKS = {
    "new_evidence_gap_returns_governed_work_required",
    "governed_work_truth_is_r1",
    "governed_work_request_is_contract",
    "g5_does_not_execute_provider_directly",
    "g5_does_not_create_workgraph_task_directly",
    "g2_planner_scheduler_router_creates_governed_work",
    "g2_g4_governed_reproduction_creates_durable_evidence",
    "g5_resumes_from_durable_typed_refs",
    "bounded_deepening_is_raw_payload_free",
    "companion_governed_work_path",
}
EC4_RECOVERY_CHECKS = {
    "multiple_checkpoints_event_ordered",
    "checkpoint_workset_digest_cursor_revalidated",
    "historical_checkpoint_session_is_provenance_only",
    "session_rotation_occurs_for_recovery",
    "stale_predecessor_rejected_during_recovery",
    "successor_current_binding_accepted_during_recovery",
    "restart_reconstructs_investigation_from_durable_truth",
    "conversation_history_not_recovery_truth",
    "no_confirmed_defect_persisted_after_ec4",
    "no_r43_lifecycle_opened_after_ec4",
}
EC5_ADVERSARIAL_CHECKS = {
    "auth_session_expiry_safe_non_confirmed",
    "cat_unavailable_safe_non_confirmed",
    "conflicted_evidence_safe_non_confirmed",
    "direct_provider_action_rejected_canonically",
    "error_string_only_safe_non_confirmed",
    "g6_mutation_rejected_canonically",
    "llm_99_confidence_safe_non_confirmed",
    "no_probe_persisted_confirmed_defect",
    "raw_secret_injection_rejected_canonically",
    "single_api_500_safe_non_confirmed",
    "stale_expected_safe_non_confirmed",
    "static_code_suspicion_safe_non_confirmed",
    "wrong_test_data_safe_non_confirmed",
}
EC5_ATOMIC_CONFIRMATION_CHECKS = {
    "ordinary_needs_no_gate",
    "ordinary_autonomous_confirm",
    "no_gate_blocks_confirmation",
    "successor_binding_confirms",
}
EC5_HUMAN_GATE_CHECKS = {
    "no_gate_blocks_confirmation",
    "pending_gate_blocks_confirmation",
    "choice_gate_exact_frozen_shape",
    "confirm_without_continuation_blocks",
    "applied_continuation_is_allowing",
    "stale_binding_rejected_after_continuation",
    "successor_binding_confirms",
    "rejected_block_blocks",
    "plan_revision_more_evidence_blocks",
    "human_cannot_bypass_r36",
}
EC5_DUPLICATE_CHECKS = {
    "same_mission_typed_reuse_one_lifecycle",
    "ambiguous_requires_review",
    "cross_mission_merge_forbidden",
}
EC5_R43_HANDOFF_CHECKS = {
    "r43_real_service_called",
    "r43_exact_handoff_idempotent",
}
EC6_OPENCODE_CHECKS = {
    "g5_subprocess_helper_present",
    "g5_helper_calls_product_entry_g5",
    "g5_helper_uses_diagnosis_role",
    "g5_helper_requires_json",
    "g5_helper_requires_r1_truth",
    "diagnosis_calls_canonical_g5_helper",
    "diagnosis_no_longer_returns_pending_g5_hold",
    "diagnosis_exposes_frozen_worker_actions",
    "g5_helper_does_not_own_provider_or_session_lifecycle",
    "product_entry_registers_g5_cli",
    "agent_requires_governed_new_evidence_path",
    "agent_does_not_claim_direct_cat_db_api_ui_authority",
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
    return all_checks(parsed, PRODUCT_SEAM_CHECKS) and all_checks(
        parsed, DIRECTOR_SURFACE_CHECKS
    )


def worker_runtime_green(parsed: dict[str, Any]) -> bool:
    return all_checks(parsed, WORKER_BINDING_CHECKS)


def opencode_runtime_green(
    root: Path, parsed: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    canonical_substrate = "ISOLATED_TEMP_RUNTIME_SPINE"
    contract = parsed.get("contract_checks") or {}
    if not isinstance(contract, dict) or not all(bool(value) for value in contract.values()):
        return False, {
            "returncode": None,
            "parsed": None,
            "output_tail": "OPENCODE_SUITE_CONTRACT_CHECKS_INCOMPLETE",
            "canonical_substrate": canonical_substrate,
        }
    runtime = root / "workspace-template" / "ai-test" / "runtime"
    with tempfile.TemporaryDirectory(prefix="g5-opencode-runtime-") as temp:
        durable_root = Path(temp)
        runtime_spine_db = durable_root / "state" / "runtime-spine.db"
        runtime_spine_db.parent.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "AITEST_RUNTIME_SPINE_DB": str(runtime_spine_db),
            "AITEST_WORKSPACE_ROOT": str(root / "workspace-template"),
            "PYTHONPATH": str(runtime),
        }
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
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    result = parse_last_json(proc.stdout)
    probe = {
        "returncode": proc.returncode,
        "parsed": result,
        "output_tail": proc.stdout[-6000:],
        "canonical_substrate": canonical_substrate,
    }
    return (
        proc.returncode == 0
        and isinstance(result, dict)
        and result.get("status") == "PASS"
        and result.get("truth_source") == "R1_EVENT_STREAM"
        and result.get("next_required_action") is None,
        probe,
    )


def oracle_shape(
    root: Path, filename: str, parsed: dict[str, Any] | None
) -> tuple[bool, bool, bool, dict[str, Any] | None]:
    if not isinstance(parsed, dict):
        return False, False, False, None
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
        return future_runtime, current_truth, runtime_green, None
    if filename == "test_g5_product_path.py":
        return True, current_truth, product_runtime_green(parsed), None
    if filename == "test_g5_worker_binding_and_recovery.py":
        return True, current_truth, worker_runtime_green(parsed), None
    if filename == "test_g5_opencode_surface.py":
        runtime_green, probe = opencode_runtime_green(root, parsed)
        return True, current_truth, runtime_green, probe
    return False, current_truth, False, None


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
    future_runtime, current_truth, runtime_green, runtime_probe = oracle_shape(
        root, filename, parsed
    )
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
    result = {
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
    if runtime_probe is not None:
        result["opencode_runtime_probe"] = runtime_probe
    return result


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


def suite_is_green(suite: dict[str, Any]) -> bool:
    parsed = suite.get("parsed")
    return (
        suite.get("returncode") == 0
        and suite.get("programming_exception") is False
        and suite.get("future_green_requires_real_runtime") is True
        and suite.get("runtime_green_evidence") is True
        and isinstance(parsed, dict)
        and parsed.get("status") == "PASS"
        and parsed.get("fixture_ok") is True
        and not parsed.get("missing_contract_checks")
    )


def named_checks(parsed: dict[str, Any] | None, required: set[str]) -> bool:
    return required.issubset(checks(parsed))


def named_checks_green(parsed: dict[str, Any] | None, required: set[str]) -> bool:
    observed = checks(parsed)
    return required.issubset(observed) and all(observed.get(name) is True for name in required)


def progressive_oracle_conditions(
    suites: list[dict[str, Any]], frozen_runner_unchanged: bool
) -> dict[str, bool]:
    same_mission = suite_by_name(suites, "test_g5_same_mission_e2e.py").get("parsed")
    adversarial = suite_by_name(suites, "test_g5_adversarial_defect_truth.py").get("parsed")
    human = suite_by_name(suites, "test_g5_human_gate_and_duplicate_correlation.py").get("parsed")
    product = suite_by_name(suites, "test_g5_product_path.py").get("parsed")
    opencode = suite_by_name(suites, "test_g5_opencode_surface.py").get("parsed")
    same_foundation = (same_mission or {}).get("foundation_checks") or {}
    return {
        "frozen_g1_g4_runner_exact": frozen_runner_unchanged,
        "six_exact_g5_suites_present": len(suites) == 6 and {item["file"] for item in suites} == set(SUITES),
        "all_suites_structured_or_green": all(structured_or_green(suite) for suite in suites),
        "future_green_requires_runtime_behavior": all(
            suite.get("future_green_requires_real_runtime") is True for suite in suites
        ),
        "no_programming_exceptions": all(not suite["programming_exception"] for suite in suites),
        "ec3_preconfirmation_matrix_complete": (
            named_checks(same_mission, EC3_PRECONFIRMATION_CHECKS)
            and named_checks(adversarial, EC3_SAFETY_CHECKS)
            and same_foundation.get("r36_historical_baseline_v5_unchanged") is True
        ),
        "confirmation_barrier_matrix_complete": named_checks(
            same_mission, CONFIRMATION_BARRIER_CHECKS
        ),
        "ec4_governed_evidence_matrix_complete": named_checks(
            same_mission, EC4_GOVERNED_EVIDENCE_CHECKS
        ),
        "ec4_recovery_matrix_complete": named_checks(same_mission, EC4_RECOVERY_CHECKS),
        "ec5_adversarial_matrix_complete": named_checks(adversarial, EC5_ADVERSARIAL_CHECKS),
        "ec5_atomic_confirmation_matrix_complete": named_checks(
            human, EC5_ATOMIC_CONFIRMATION_CHECKS
        ),
        "ec5_human_gate_matrix_complete": named_checks(human, EC5_HUMAN_GATE_CHECKS),
        "ec5_duplicate_matrix_complete": named_checks(human, EC5_DUPLICATE_CHECKS),
        "ec5_r43_handoff_matrix_complete": named_checks(human, EC5_R43_HANDOFF_CHECKS),
        "director_surface_matrix_complete": named_checks(
            product, DIRECTOR_SURFACE_CHECKS
        ),
        "ec6_opencode_matrix_complete": named_checks(opencode, EC6_OPENCODE_CHECKS),
        "ec7_full_green_matrix_complete": all(
            isinstance(suite.get("parsed"), dict)
            and "fixture_ok" in suite["parsed"]
            and "missing_contract_checks" in suite["parsed"]
            for suite in suites
        ),
    }


def progressive_milestones(suites: list[dict[str, Any]]) -> dict[str, bool]:
    product = suite_by_name(suites, "test_g5_product_path.py")
    worker = suite_by_name(suites, "test_g5_worker_binding_and_recovery.py")
    adversarial = suite_by_name(suites, "test_g5_adversarial_defect_truth.py")
    human = suite_by_name(suites, "test_g5_human_gate_and_duplicate_correlation.py")
    same_mission = suite_by_name(suites, "test_g5_same_mission_e2e.py")
    opencode = suite_by_name(suites, "test_g5_opencode_surface.py")
    same_foundation = (same_mission.get("parsed") or {}).get("foundation_checks") or {}
    milestones = {
        "product_seam_green": all_checks(product.get("parsed"), PRODUCT_SEAM_CHECKS),
        "worker_binding_green": all_checks(worker.get("parsed"), WORKER_BINDING_CHECKS),
        "ec3_preconfirmation_green": (
            named_checks_green(same_mission.get("parsed"), EC3_PRECONFIRMATION_CHECKS)
            and named_checks_green(adversarial.get("parsed"), EC3_SAFETY_CHECKS)
            and same_foundation.get("r36_historical_baseline_v5_unchanged") is True
        ),
        "confirmation_barrier_green": named_checks_green(
            same_mission.get("parsed"), CONFIRMATION_BARRIER_CHECKS
        ),
        "ec4_governed_evidence_green": named_checks_green(
            same_mission.get("parsed"), EC4_GOVERNED_EVIDENCE_CHECKS
        ),
        "ec4_recovery_green": named_checks_green(
            same_mission.get("parsed"), EC4_RECOVERY_CHECKS
        ),
        "ec5_confirmation_policy_green": named_checks_green(
            adversarial.get("parsed"), EC5_ADVERSARIAL_CHECKS
        ),
        "ec5_atomic_confirmation_green": named_checks_green(
            human.get("parsed"), EC5_ATOMIC_CONFIRMATION_CHECKS
        ),
        "ec5_human_gate_green": named_checks_green(
            human.get("parsed"), EC5_HUMAN_GATE_CHECKS
        ),
        "ec5_duplicate_green": named_checks_green(human.get("parsed"), EC5_DUPLICATE_CHECKS),
        "ec5_r43_handoff_green": named_checks_green(
            human.get("parsed"), EC5_R43_HANDOFF_CHECKS
        ),
        "director_surface_green": named_checks_green(
            product.get("parsed"), DIRECTOR_SURFACE_CHECKS
        ),
        "opencode_surface_green": (
            named_checks_green(opencode.get("parsed"), EC6_OPENCODE_CHECKS)
            and opencode.get("runtime_green_evidence") is True
        ),
        "g5_full_green": all(suite_is_green(suite) for suite in suites),
    }
    milestones["ec5_green"] = all(
        milestones[name]
        for name in (
            "ec5_confirmation_policy_green",
            "ec5_atomic_confirmation_green",
            "ec5_human_gate_green",
            "ec5_duplicate_green",
            "ec5_r43_handoff_green",
        )
    )
    return milestones


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
        "product_stage_structured_or_green": structured_or_green(product),
        "worker_stage_structured_or_green": structured_or_green(worker),
        "all_progressive_stages_structured_or_green": all(
            structured_or_green(suite) for suite in suites
        ),
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
        "later_waves_structured_or_green": all(structured_or_green(suite) for suite in later),
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


def progressive_wave_verdict(
    wave: str,
    suites: list[dict[str, Any]],
    frozen_runner_unchanged: bool,
) -> tuple[bool, bool, dict[str, bool], dict[str, bool], list[str]]:
    oracle_conditions = progressive_oracle_conditions(suites, frozen_runner_unchanged)
    oracle_ready = all(oracle_conditions.values())
    milestones = progressive_milestones(suites)

    requirements = {
        "EC3": (
            "product_seam_green",
            "worker_binding_green",
            "ec3_preconfirmation_green",
            "confirmation_barrier_green",
        ),
        "EC4": (
            "product_seam_green",
            "worker_binding_green",
            "ec3_preconfirmation_green",
            "confirmation_barrier_green",
            "ec4_governed_evidence_green",
            "ec4_recovery_green",
        ),
        "EC5": (
            "product_seam_green",
            "worker_binding_green",
            "ec3_preconfirmation_green",
            "ec4_governed_evidence_green",
            "ec4_recovery_green",
            "ec5_confirmation_policy_green",
            "ec5_atomic_confirmation_green",
            "ec5_human_gate_green",
            "ec5_duplicate_green",
            "ec5_r43_handoff_green",
        ),
        "EC6": (
            "product_seam_green",
            "worker_binding_green",
            "ec3_preconfirmation_green",
            "ec4_governed_evidence_green",
            "ec4_recovery_green",
            "ec5_green",
            "director_surface_green",
            "opencode_surface_green",
        ),
        "EC7": ("g5_full_green",),
    }[wave]
    failures = [name for name in requirements if not milestones[name]]
    if not oracle_ready:
        failures.extend(
            f"oracle:{name}" for name, passed in oracle_conditions.items() if not passed
        )
    return oracle_ready and not failures, oracle_ready, oracle_conditions, milestones, failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Canonical additive G5 EC0-EC7 validation runner"
    )
    parser.add_argument("--root", default=".")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--mode", choices=("red", "green"))
    selection.add_argument("--wave", choices=("EC1", "EC2", "EC3", "EC4", "EC5", "EC6", "EC7"))
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
        "no_programming_exceptions": all(not suite["programming_exception"] for suite in suites),
        "frozen_g1_g4_runner_exact": frozen_runner_unchanged,
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
        oracle_ready = all(conditions.values())
        result.update(
            {
                "status": "PASS" if passed else "FAIL",
                "wave": "EC1",
                "wave_expectation_satisfied": passed,
                "wave_oracle_ready": oracle_ready,
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
                "later_waves_fail_closed": all(
                    structured_missing(suite)
                    for suite in suites
                    if suite["file"] in LATER_WAVE_SUITES
                ),
                "ec2_r2_5_missing_oracle_present": "logical_agent_binding_missing_rejected" in worker_checks,
                "ec2_r2_5_mismatch_oracle_present": "logical_agent_binding_mismatch_rejected" in worker_checks,
                "wave_oracle_ready": oracle_ready,
                "wave_conditions": conditions,
                "wave_failures": failures,
            }
        )
    elif args.wave in {"EC3", "EC4", "EC5", "EC6", "EC7"}:
        passed, oracle_ready, conditions, milestones, failures = progressive_wave_verdict(
            args.wave, suites, frozen_runner_unchanged
        )
        result.update(
            {
                "status": "PASS" if passed else "FAIL",
                "wave": args.wave,
                "wave_expectation_satisfied": passed,
                "wave_oracle_ready": oracle_ready,
                "wave_conditions": conditions,
                "wave_failures": failures,
                "later_waves_fail_closed": all(
                    structured_missing(suite) or suite_is_green(suite)
                    for suite in suites
                    if suite["file"] in LATER_WAVE_SUITES
                ),
                **milestones,
            }
        )
        if args.wave == "EC7":
            # EC7 uses the exact green-mode suite requirements even though wave
            # invocations retain the progressive runner execution mode.
            result["g5_green"] = milestones["g5_full_green"]
            result["all_g5_suites_accepted"] = milestones["g5_full_green"]
            result["ec7_g5_focused_gate"] = "PASS" if milestones["g5_full_green"] else "FAIL"

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output = output if output.is_absolute() else root / output
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
