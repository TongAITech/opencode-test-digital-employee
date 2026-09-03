from __future__ import annotations

import argparse
import hashlib
import json
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


def run_suite(test_dir: Path, filename: str, mode: str) -> dict[str, Any]:
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
    if mode == "red":
        accepted = (
            proc.returncode != 0
            and isinstance(parsed, dict)
            and parsed.get("status") == "FAIL"
            and parsed.get("fixture_ok") is True
            and parsed.get("truthful_red") is True
            and parsed.get("red_kind") == "MISSING_G5_INTEGRATION"
            and bool(parsed.get("missing_contract_checks"))
        )
    else:
        accepted = (
            proc.returncode == 0
            and isinstance(parsed, dict)
            and parsed.get("status") == "PASS"
            and parsed.get("fixture_ok") is True
            and not parsed.get("missing_contract_checks")
        )
    return {
        "file": filename,
        "mode": mode,
        "returncode": proc.returncode,
        "duration_sec": duration,
        "accepted": accepted,
        "parsed": parsed,
        "output_tail": proc.stdout[-6000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonical additive G5 EC0-EC7 validation runner")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--mode", choices=("red", "green"), default="red")
    parser.add_argument("--output", default=None, help="optional JSON output path; omitted means stdout only")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    test_dir = root / "workspace-template" / ".pfc-internal-field-validation" / "tests"
    frozen_runner = root / FROZEN_G1_G4_RUNNER_PATH
    frozen_blob = git_blob_sha(frozen_runner)
    frozen_runner_unchanged = frozen_blob == FROZEN_G1_G4_RUNNER_BLOB

    suites = [run_suite(test_dir, filename, args.mode) for filename in SUITES]
    all_suites_accepted = all(item["accepted"] for item in suites)
    status = "PASS" if frozen_runner_unchanged and all_suites_accepted else "FAIL"

    result = {
        "status": status,
        "mode": args.mode,
        "truth_source": "CONSTRUCTION_VALIDATION_EVIDENCE",
        "suite_count": len(suites),
        "all_g5_suites_accepted": all_suites_accepted,
        "ec0_truthful_red_frozen": args.mode == "red" and status == "PASS",
        "g5_green": args.mode == "green" and status == "PASS",
        "frozen_g1_g4_regression_runner": {
            "path": FROZEN_G1_G4_RUNNER_PATH,
            "expected_blob": FROZEN_G1_G4_RUNNER_BLOB,
            "observed_blob": frozen_blob,
            "unchanged": frozen_runner_unchanged,
            "authority": "G1_G4_REGRESSION_ONLY",
            "executed_by_this_runner": False,
            "note": "Its historical g5_defect_truth=HOLD field is metadata only and is not G5 gate truth.",
        },
        "suites": suites,
    }

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = root / output
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
