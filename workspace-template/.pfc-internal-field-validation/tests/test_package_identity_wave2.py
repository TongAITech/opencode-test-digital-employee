from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
SCRIPT = REPO / "tools" / "source_identity.py"
spec = importlib.util.spec_from_file_location("source_identity", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def write_manifest(root: Path, identity: str, *, validation_status: str = "PASS") -> None:
    payload = {
        "schema_version": "aitest.git-native-package-manifest.v2",
        "source_truth": "GIT_COMMIT",
        "baseline_commit": "725457e5b475019072ac936fd55756c995ddf69a",
        "candidate_branch": "repair/g3-g4-wave2",
        "candidate_commit": "TEST-CANDIDATE",
        "source_identity_formula": mod.FORMULA,
        "source_content_identity": identity,
        "validation": {"status": validation_status},
    }
    (root / mod.MANIFEST).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    git(root, "add", mod.MANIFEST)


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="wave2-identity-") as td:
        root = Path(td)
        git(root, "init", "-q")
        (root / "src").mkdir()
        (root / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
        (root / "README.md").write_text("wave2\n", encoding="utf-8")
        git(root, "add", "src/a.py", "README.md")

        first = mod.compute(root)
        checks["identity_formula_is_single_git_tracked_formula"] = first["formula"] == mod.FORMULA and first["file_count"] == 2

        write_manifest(root, first["source_content_identity"])
        strict = mod.verify(root, strict=True)
        second = mod.compute(root)
        checks["canonical_package_manifest_is_excluded_from_identity"] = strict["status"] == "PASS" and second["source_content_identity"] == first["source_content_identity"]

        (root / "src" / "a.py").write_text("print(2)\n", encoding="utf-8")
        drift = mod.verify(root, strict=True)
        checks["strict_self_check_fails_on_source_drift"] = drift["status"] == "FAIL" and "SOURCE_CONTENT_IDENTITY_MISMATCH" in drift["errors"]

        (root / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
        pending = mod.compute(root)
        write_manifest(root, pending["source_content_identity"], validation_status="PENDING")
        pending_check = mod.verify(root, strict=True)
        checks["strict_self_check_rejects_pending_validation_truth"] = pending_check["status"] == "FAIL" and "VALIDATION_TRUTH_NOT_PASS" in pending_check["errors"]

        write_manifest(root, pending["source_content_identity"], validation_status="PASS")
        (root / "G4_FINAL_PACKAGE_MANIFEST.json").write_text("{}\n", encoding="utf-8")
        duplicate = mod.verify(root, strict=True)
        checks["historical_or_duplicate_root_manifest_fails_closed"] = duplicate["status"] == "FAIL" and any(error.startswith("MULTIPLE_OR_MISSING_CANONICAL_ROOT_MANIFESTS:") for error in duplicate["errors"])

        (root / "G4_FINAL_PACKAGE_MANIFEST.json").unlink()
        final = mod.verify(root, strict=True)
        checks["single_canonical_root_manifest_passes_strict_self_check"] = final["status"] == "PASS" and final["root_identity_files"] == [mod.MANIFEST]

    failed = [name for name, ok in checks.items() if not ok]
    result = {"status": "PASS" if not failed else "FAIL", "passed": sum(bool(v) for v in checks.values()), "total": len(checks), "failed": failed, "checks": checks}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
