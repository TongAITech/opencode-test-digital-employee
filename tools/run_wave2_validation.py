from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ORIGINAL_267 = [
    ("g2_autonomous", "test_autonomous_orchestration.py", 15),
    ("g1_g2_1_launch_auth", "test_g1_g2_1_launch_auth_decoupling.py", 7),
    ("g1_g2_product_subprocess", "test_g1_g2_product_path_subprocess.py", 9),
    ("g2_1_background_subprocess", "test_g2_1_background_control_loop_subprocess.py", 5),
    ("g2_1_process_lifecycle", "test_g2_1_control_loop_process_lifecycle.py", 9),
    ("g2_1_router", "test_g2_1_session_router_control_loop.py", 27),
    ("g3_product", "test_g3_testing_intelligence_product_path.py", 50),
    ("portable_launcher", "test_portable_launcher_policy.py", 9),
    ("runtime_convergence", "test_runtime_convergence.py", 30),
    ("g2r_waiting_human", "test_g2_waiting_human_nonblocking_scheduler_repair.py", 9),
    ("g4_focused", "test_g4_repair_focused_integration.py", 7),
    ("g4_formal_52", "test_g4_formal_product_gate.py", 52),
    ("g4_same_mission_e2e", "test_g4_full_same_mission_product_e2e.py", 20),
    ("g4_opencode_surface", "test_g4_opencode_product_surface.py", 14),
    ("g4_capability_human_gate", "test_g4_capability_human_gate_product_path.py", 4),
]
POST_CLOSURE_22 = [("post_closure_adversarial", "test_g3_g4_post_closure_adversarial.py", 22)]
WAVE2 = [
    ("r2_1_change_intelligence_broker", "test_g3_change_intelligence_broker_wave2.py", 29),
    ("r2_2_governed_execution_binding", "test_g4_governed_execution_binding_wave2.py", 7),
    ("r2_3_coverage_identity", "test_g4_coverage_identity_wave2.py", 8),
    ("r2_4_background_auto_resume", "test_g4_background_auto_resume_wave2.py", 8),
    ("r2_5_goal_transition", "test_g4_goal_transition_wave2.py", 7),
    ("r2_6_sensitive_evidence", "test_g4_sensitive_evidence_wave2.py", 7),
    ("r2_7_package_identity", "test_package_identity_wave2.py", 6),
]


def parse_last_json(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and not text[index + end :].strip():
            candidates.append(value)
    return candidates[-1] if candidates else None


def reported_counts(parsed: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not isinstance(parsed, dict):
        return None, None
    passed = parsed.get("passed")
    total = parsed.get("total")
    checks = parsed.get("checks")
    if (passed is None or total is None) and isinstance(checks, dict):
        total = len(checks)
        passed = sum(bool(value) for value in checks.values())
    return (int(passed) if isinstance(passed, int) else None, int(total) if isinstance(total, int) else None)


def run_suite(test_dir: Path, name: str, filename: str, expected: int) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(test_dir / filename)],
        cwd=test_dir,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    duration = round(time.monotonic() - started, 3)
    parsed = parse_last_json(proc.stdout)
    passed, total = reported_counts(parsed)
    status = "PASS" if proc.returncode == 0 and passed == expected and total == expected else "FAIL"
    return {
        "name": name,
        "file": filename,
        "expected_checks": expected,
        "returncode": proc.returncode,
        "duration_sec": duration,
        "reported_passed": passed,
        "reported_total": total,
        "status": status,
        "parsed": parsed,
        "output_tail": proc.stdout[-6000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="WAVE2_VALIDATION_RESULT.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    test_dir = root / "workspace-template" / ".pfc-internal-field-validation" / "tests"
    groups = [
        ("original_267", ORIGINAL_267, 267),
        ("post_closure_22", POST_CLOSURE_22, 22),
        ("wave2_new", WAVE2, sum(item[2] for item in WAVE2)),
    ]
    suites: list[dict[str, Any]] = []
    group_results: dict[str, Any] = {}
    for group_name, definitions, expected_total in groups:
        group_suites = []
        for name, filename, expected in definitions:
            result = run_suite(test_dir, name, filename, expected)
            suites.append(result)
            group_suites.append(result)
        passed = sum(int(item["reported_passed"] or 0) for item in group_suites if item["status"] == "PASS")
        group_results[group_name] = {
            "expected": expected_total,
            "passed": passed,
            "status": "PASS" if passed == expected_total and all(item["status"] == "PASS" for item in group_suites) else "FAIL",
        }
    combined_expected = sum(group[2] for group in groups)
    combined_passed = sum(value["passed"] for value in group_results.values())
    same_e2e = next(item for item in suites if item["name"] == "g4_same_mission_e2e")
    result = {
        "status": "PASS" if combined_passed == combined_expected and all(value["status"] == "PASS" for value in group_results.values()) else "FAIL",
        "fresh": True,
        "groups": group_results,
        "combined": {"passed": combined_passed, "total": combined_expected},
        "same_mission_e2e": {"status": same_e2e["status"], "passed": same_e2e["reported_passed"], "total": same_e2e["reported_total"]},
        "suites": suites,
        "g5_defect_truth": "HOLD",
        "g6_closed_loop": "HOLD",
    }
    output = root / args.output
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
