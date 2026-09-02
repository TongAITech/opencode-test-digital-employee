from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "aitest.git-native-package-manifest.v1"
IDENTITY_FORMULA = "sha256(UTF-8 sorted `<file_sha256>  <path>` lines, exactly one final newline; excludes PACKAGE_MANIFEST.json and SOURCE_BASELINE_MANIFEST.json)"
EXCLUDED_IDENTITY_PATHS = frozenset({"PACKAGE_MANIFEST.json", "SOURCE_BASELINE_MANIFEST.json"})
CANONICAL_ROOT_IDENTITY_NAMES = frozenset({"PACKAGE_MANIFEST.json", "PACKAGE_IDENTITY.json"})
HISTORICAL_ROOT_PATTERNS = ("G3_", "G4_", "POST_CLOSURE_")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_record(root: Path, path: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    data = path.read_bytes()
    return {"path": rel, "sha256": sha256_bytes(data), "size": len(data)}


def source_records(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or rel in EXCLUDED_IDENTITY_PATHS:
            continue
        records.append(file_record(root, path))
    return records


def source_content_identity(records: list[dict[str, Any]]) -> str:
    lines = [f"{item['sha256']}  {item['path']}" for item in sorted(records, key=lambda x: x["path"])]
    return sha256_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def root_identity_files(root: Path) -> list[str]:
    found = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name in CANONICAL_ROOT_IDENTITY_NAMES or (
            name.endswith(".json")
            and any(name.startswith(prefix) and ("MANIFEST" in name or "IDENTITY" in name) for prefix in HISTORICAL_ROOT_PATTERNS)
        ):
            found.append(name)
    return sorted(found)


def build_manifest(root: Path, *, baseline_commit: str, branch: str, regression: dict[str, Any] | None = None) -> dict[str, Any]:
    root = root.resolve()
    records = source_records(root)
    identity = source_content_identity(records)
    historical = [name for name in root_identity_files(root) if name not in CANONICAL_ROOT_IDENTITY_NAMES]
    if historical:
        raise ValueError("HISTORICAL_ROOT_IDENTITY_MUST_BE_MOVED:" + ",".join(historical))
    return {
        "schema_version": SCHEMA,
        "source_truth": "GIT_COMMIT",
        "baseline_commit": baseline_commit,
        "candidate_branch": branch,
        "identity_formula": IDENTITY_FORMULA,
        "excluded_identity_paths": sorted(EXCLUDED_IDENTITY_PATHS),
        "file_count": len(records),
        "source_content_identity": identity,
        "files": records,
        "regression": dict(regression or {}),
        "canonical_root_identity": "PACKAGE_MANIFEST.json",
        "historical_manifest_policy": "docs/reviews/historical/",
    }


def write_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    target = root / "PACKAGE_MANIFEST.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return target


def self_check(root: Path) -> dict[str, Any]:
    root = root.resolve()
    canonical = [name for name in root_identity_files(root) if name in CANONICAL_ROOT_IDENTITY_NAMES]
    historical = [name for name in root_identity_files(root) if name not in CANONICAL_ROOT_IDENTITY_NAMES]
    if canonical != ["PACKAGE_MANIFEST.json"]:
        raise ValueError("MULTIPLE_OR_MISSING_CANONICAL_ROOT_IDENTITIES:" + ",".join(canonical))
    if historical:
        raise ValueError("HISTORICAL_ROOT_IDENTITY_MUST_BE_MOVED:" + ",".join(historical))
    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    records = source_records(root)
    actual = source_content_identity(records)
    expected = str(manifest.get("source_content_identity") or "")
    manifest_records = manifest.get("files") or []
    if actual != expected:
        raise ValueError(f"SOURCE_CONTENT_IDENTITY_MISMATCH:{expected}:{actual}")
    current = {item["path"]: (item["sha256"], item["size"]) for item in records}
    declared = {str(item["path"]): (str(item["sha256"]), int(item["size"])) for item in manifest_records}
    if current != declared:
        raise ValueError("PACKAGE_MANIFEST_FILE_SET_OR_HASH_MISMATCH")
    return {
        "status": "PASS",
        "source_content_identity": actual,
        "file_count": len(records),
        "canonical_root_identity": "PACKAGE_MANIFEST.json",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("--baseline-commit")
    parser.add_argument("--branch")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    root = Path(args.root)
    if args.self_check:
        print(json.dumps(self_check(root), sort_keys=True))
        return 0
    manifest = build_manifest(root, baseline_commit=args.baseline_commit or "", branch=args.branch or "", regression={})
    if args.write:
        write_manifest(root, manifest)
    print(json.dumps({key: manifest[key] for key in ("schema_version", "file_count", "source_content_identity")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
