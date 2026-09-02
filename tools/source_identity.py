from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

FORMULA = "sha256(UTF-8 sorted `<file_sha256>  <path>` lines, exactly one final newline; tracked files from `git ls-files`; excludes PACKAGE_MANIFEST.json)"
MANIFEST = "PACKAGE_MANIFEST.json"


def tracked_files(root: Path) -> list[str]:
    proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
    values = [item.decode("utf-8") for item in proc.stdout.split(b"\0") if item]
    return sorted(path for path in values if path != MANIFEST)


def compute(root: Path) -> dict[str, Any]:
    rows: list[str] = []
    files: list[dict[str, Any]] = []
    for rel in tracked_files(root):
        path = root / rel
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {rel}")
        files.append({"path": rel, "sha256": digest, "size": path.stat().st_size})
    canonical = ("\n".join(rows) + "\n").encode("utf-8")
    return {
        "formula": FORMULA,
        "file_count": len(files),
        "source_content_identity": hashlib.sha256(canonical).hexdigest(),
        "files": files,
    }


def root_identity_files(root: Path) -> list[str]:
    names = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        upper = path.name.upper()
        if "MANIFEST" in upper and path.suffix.lower() == ".json":
            names.append(path.name)
    return sorted(names)


def verify(root: Path, *, strict: bool) -> dict[str, Any]:
    manifest_path = root / MANIFEST
    errors: list[str] = []
    if not manifest_path.exists():
        errors.append("PACKAGE_MANIFEST_MISSING")
        manifest: dict[str, Any] = {}
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roots = root_identity_files(root)
    if roots != [MANIFEST]:
        errors.append("MULTIPLE_OR_MISSING_CANONICAL_ROOT_MANIFESTS:" + ",".join(roots))
    actual = compute(root)
    if manifest.get("source_identity_formula") not in {None, FORMULA}:
        errors.append("SOURCE_IDENTITY_FORMULA_MISMATCH")
    expected = manifest.get("source_content_identity")
    if strict:
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append("SOURCE_CONTENT_IDENTITY_NOT_FINALIZED")
        elif expected != actual["source_content_identity"]:
            errors.append("SOURCE_CONTENT_IDENTITY_MISMATCH")
        if manifest.get("validation", {}).get("status") != "PASS":
            errors.append("VALIDATION_TRUTH_NOT_PASS")
    return {
        "status": "PASS" if not errors else "FAIL",
        "strict": strict,
        "errors": errors,
        "root_identity_files": roots,
        "actual": {key: actual[key] for key in ("formula", "file_count", "source_content_identity")},
        "manifest_source_content_identity": expected,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("compute", "verify"))
    parser.add_argument("--root", default=".")
    parser.add_argument("--output")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    result = compute(root) if args.command == "compute" else verify(root, strict=args.strict)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("status", "PASS") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
