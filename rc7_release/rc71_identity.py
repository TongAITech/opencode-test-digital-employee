from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from rc7_release.final_manifest_refresh import refresh


SCHEMA = "pfc.aitest.rc7.1.release-identity.v1"
PRODUCT_VERSION = "RC7.1"
# Green engineering baseline immediately before the RC7.1 Bank Field Reality
# isolation slice.  The exact package source is still recorded separately in
# source_commit and must match the GitHub Actions HEAD that produced the ZIP.
BASELINE_COMMIT = "ef7052e42485d060c1dc7e0ec9517c59df4e2ae5"
BUILD_STATUS = "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"

REQUIRED_HARDENING_FILES = (
    "rc7_runtime/bank_field_reality.py",
    "rc7_release/real_mission_qualification_strict.py",
    "packaging/rc7/QUALIFY-FINAL.sh",
    "packaging/rc7/QUALIFY-BANK-FINAL.sh",
)


def validate_hardening_payload(package_root: str) -> Dict[str, object]:
    root = Path(package_root).expanduser().resolve()
    missing: List[str] = [
        rel for rel in REQUIRED_HARDENING_FILES if not (root / rel).is_file()
    ]
    return {
        "status": "PASS" if not missing else "HOLD",
        "required_files": list(REQUIRED_HARDENING_FILES),
        "missing_files": missing,
        "bank_field_reality": "NOT_VERIFIED",
    }


def identity(source_commit: str) -> Dict[str, object]:
    return {
        "schema": SCHEMA,
        "product": "PFC-AITest",
        "version": PRODUCT_VERSION,
        "release_line": "RC7_FIELD_FIX",
        "baseline_rc7_commit": BASELINE_COMMIT,
        "source_commit": str(source_commit).strip(),
        "build_status": BUILD_STATUS,
        "canonical_runtime_truth": "runtime-state/r1/event-stream.jsonl",
        "fixes": [
            "NONBLOCKING_DSH_BOOTSTRAP",
            "RC7_STARTUP_PHASE_TRACE",
            "NON_DESTRUCTIVE_RECOVERY_PROFILE",
            "DSH_WORKER_TIMEOUT_DIAGNOSTIC_AND_PROMPT_REDACTION",
            "JUNIT_CURRENT_RUN_XML_REALITY_GATE",
            "MAVEN_DEPENDENCY_BLOCKED_NOT_PASS",
            "BANK_FIELD_REALITY_FAIL_CLOSED_PROVENANCE_GATE",
            "ENGINEERING_FIXTURE_ISOLATED_FROM_BANK_FIELD_REALITY",
            "TURNKEY_SECOND_START_IDEMPOTENCE_GATE",
        ],
        "hardening_contract": {
            "required_files": list(REQUIRED_HARDENING_FILES),
            "engineering_fixture_bank_field_authority": False,
            "bank_field_reality": "NOT_VERIFIED",
            "bank_field_requires_positive_runtime_provenance": True,
            "second_start_idempotence_required": True,
        },
        "bank_field_required": [
            "REAL_BANK_MODEL_AND_PROVIDER",
            "REAL_4A_AND_BROWSER_E2E",
            "REAL_BLOAN_L4_L5_L7_EXECUTION",
            "APPROVED_REAL_L6_PROVIDER_PATH",
            "REAL_CAT_DB_AND_NETWORK_PERMISSIONS",
        ],
        "claims": {
            "rc8_architecture_backported": False,
            "dsh_internal_model_loader_rewritten": False,
            "bank_final": False,
        },
    }


def write_identity(package_root: str, source_commit: str) -> Path:
    root = Path(package_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    hardening = validate_hardening_payload(str(root))
    if hardening.get("status") != "PASS":
        raise RuntimeError(
            "RC71_HARDENING_PAYLOAD_MISSING:%s"
            % ",".join(hardening.get("missing_files", []))
        )

    path = root / "RC7.1-RELEASE.json"
    path.write_text(
        json.dumps(identity(source_commit), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    refreshed = refresh(root)
    if refreshed.get("status") != "PASS":
        raise RuntimeError("RC71_IDENTITY_MANIFEST_REFRESH_FAILED")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    path = write_identity(args.package_root, args.source_commit)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
