from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
SCRIPT = REPO / "packaging" / "engineering_source_identity.py"
spec = importlib.util.spec_from_file_location("engineering_source_identity", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="identity-wave2-") as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src/a.py").write_text("print(1)\n", encoding="utf-8")
        (root / "README.md").write_text("x\n", encoding="utf-8")
        (root / "SOURCE_BASELINE_MANIFEST.json").write_text("{}\n", encoding="utf-8")
        manifest = mod.build_manifest(
            root,
            baseline_commit="725457e5b475019072ac936fd55756c995ddf69a",
            branch="repair/g3-g4-wave2",
            regression={"status": "PASS"},
        )
        mod.write_manifest(root, manifest)
        first = mod.self_check(root)
        checks["identity_formula_reproducible"] = (
            first["status"] == "PASS"
            and first["source_content_identity"] == manifest["source_content_identity"]
            and manifest["file_count"] == 2
        )
        before = manifest["source_content_identity"]
        (root / "src/a.py").write_text("print(2)\n", encoding="utf-8")
        try:
            mod.self_check(root)
            changed = False
        except ValueError as exc:
            changed = "SOURCE_CONTENT_IDENTITY_MISMATCH" in str(exc)
        checks["self_check_fails_on_source_drift"] = changed
        (root / "src/a.py").write_text("print(1)\n", encoding="utf-8")
        manifest = mod.build_manifest(
            root,
            baseline_commit="725457e5b475019072ac936fd55756c995ddf69a",
            branch="repair/g3-g4-wave2",
        )
        mod.write_manifest(root, manifest)
        (root / "PACKAGE_IDENTITY.json").write_text("{}\n", encoding="utf-8")
        try:
            mod.self_check(root)
            duplicate = False
        except ValueError as exc:
            duplicate = "MULTIPLE_OR_MISSING_CANONICAL_ROOT_IDENTITIES" in str(exc)
        checks["multiple_canonical_root_identities_fail_closed"] = duplicate
        (root / "PACKAGE_IDENTITY.json").unlink()
        (root / "G4_FINAL_PACKAGE_MANIFEST.json").write_text("{}\n", encoding="utf-8")
        try:
            mod.build_manifest(root, baseline_commit="x", branch="repair/g3-g4-wave2")
            historical = False
        except ValueError as exc:
            historical = "HISTORICAL_ROOT_IDENTITY_MUST_BE_MOVED" in str(exc)
        checks["historical_root_manifest_must_move"] = historical
        checks["source_baseline_manifest_is_metadata_not_identity_input"] = (
            "SOURCE_BASELINE_MANIFEST.json" in mod.EXCLUDED_IDENTITY_PATHS
            and before == first["source_content_identity"]
        )
    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
