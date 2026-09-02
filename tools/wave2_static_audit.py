from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

BASELINE = "725457e5b475019072ac936fd55756c995ddf69a"
PROTECTED_PREFIXES = (
    "workspace-template/ai-test/runtime/aitest_runtime/autonomous_orchestration.py",
    "workspace-template/ai-test/runtime/aitest_runtime/g2_1/",
    "workspace-template/ai-test/runtime/aitest_runtime/r2_5/",
    "workspace-template/ai-test/runtime/aitest_runtime/r2_6/",
    "workspace-template/ai-test/runtime/aitest_runtime/durable_core",
)


def run(root: Path, *args: str) -> str:
    return subprocess.run(args, cwd=root, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="WAVE2_STATIC_AUDIT_RESULT.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    changed = [line for line in run(root, "git", "diff", "--name-only", f"{BASELINE}..HEAD").splitlines() if line]
    tracked = [line for line in run(root, "git", "ls-files").splitlines() if line]
    g3g4 = [path for path in tracked if "/aitest_runtime/g3/" in path or "/aitest_runtime/g4/" in path]
    source = "\n".join((root / path).read_text(encoding="utf-8", errors="replace") for path in g3g4 if (root / path).is_file())
    checks = {
        "protected_g2_g2_1_r2_5_r2_6_unchanged": not any(any(path == prefix or path.startswith(prefix) for prefix in PROTECTED_PREFIXES) for path in changed),
        "no_codegraph_binary_tracked": not any(path.lower().endswith((".exe", ".dll", ".zip", ".tar", ".gz")) and "codegraph" in path.lower() for path in tracked),
        "runtime_lock_tracks_codegraph": '"provider": "codegraph-ai/CodeGraph"' in (root / "runtime-lock.json").read_text(encoding="utf-8"),
        "git_change_truth_present": "GitChangeTruthProvider" in source,
        "provider_neutral_broker_present": "ChangeIntelligenceBroker" in source,
        "codegraph_real_seam_present": "CodeGraphProvider" in source and "CodeGraphProviderResolver" in source,
        "codegraph_unavailable_is_explicit": "CODEGRAPH_UNAVAILABLE" in source,
        "missing_symbol_obligation_present": "MISSING_SYMBOL_MAPPING" in source,
        "g4_governed_execution_binding_present": "GovernedExecutionBinding" in source and "G4_EXECUTION_BINDING_REQUIRED" in source,
        "bank_actual_coverage_authority_preserved": "BANK_INCREMENTAL_COVERAGE_PLATFORM" in source and "BANK_EFFECTIVE_INCREMENTAL" in source,
        "per_app_target_version_binding_present": "affected_application_target_versions" in source,
        "background_auto_resume_present": "auto_resume_human_gates" in source,
        "terminal_transition_guard_present": "G4_GOAL_TRANSITION_FORBIDDEN" in source and "TERMINAL_GOAL_STATUSES" in source,
        "typed_evidence_redaction_present": "TYPED_INGRESS_REDACTION_V1" in source,
        "no_legacy_aitest_db_in_g3_g4_product_source": "aitest.db" not in source,
        "g5_defect_boundary_preserved": "G4_G5_DEFECT_TRUTH_BOUNDARY" in source and "g5_defect_truth" in source,
        "g4_does_not_author_cases": "g4_case_authoring" in source and "FORBIDDEN" in source,
        "root_package_manifest_unique": [path for path in tracked if "/" not in path and "MANIFEST" in path.upper() and path.endswith(".json")] == ["PACKAGE_MANIFEST.json"],
    }
    failed = [key for key, value in checks.items() if not value]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "passed": sum(checks.values()),
        "total": len(checks),
        "failed": failed,
        "checks": checks,
        "baseline": BASELINE,
        "head": run(root, "git", "rev-parse", "HEAD").strip(),
        "changed_files": changed,
    }
    (root / args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
