from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from rc6_release.static_skills import ALL_SKILLS, materialize_professional_skills


BUILD_STATUS = "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"
PACKAGE_NAME = "PFC-AITest-DSH-Turnkey-RC7-BANK-WIN10"
MANIFEST_SCHEMA = "pfc.aitest.rc7.package.v1"
SOURCE_DIRS = ("rc6_runtime", "rc6_release", "rc7_runtime", "rc7_release", "rc7_admin")
LAUNCHER_DIR = Path("packaging") / "rc7"
RC6_COORDINATOR_DIR = Path("packaging") / "rc6" / ".dsh" / "skills" / "pfc-full-chain-test"
PACKAGE_LOCAL_PYTHON = Path("workspace-template") / "runtime" / "python" / "python.exe"
PACKAGE_LOCAL_CODEGRAPH = (
    Path("workspace-template") / "runtime" / "code-intelligence" / "codegraph" / "codegraph-server-win32-x64.exe"
)
PACKAGE_LOCAL_BROWSER = Path("workspace-template") / "runtime" / "browser" / "chrome-win64" / "chrome.exe"
BUILD_CODEGRAPH_BIN_ENV = "PFC_RC7_BUILD_CODEGRAPH_BIN"
BUILD_CODEGRAPH_VERSION_ENV = "PFC_RC7_BUILD_CODEGRAPH_VERSION"
BUILD_CODEGRAPH_SHA256_ENV = "PFC_RC7_BUILD_CODEGRAPH_SHA256"
BUILD_BROWSER_DIR_ENV = "PFC_RC7_BUILD_BROWSER_DIR"
BUILD_BROWSER_VERSION_ENV = "PFC_RC7_BUILD_BROWSER_VERSION"
BUILD_BROWSER_SHA256_ENV = "PFC_RC7_BUILD_BROWSER_SHA256"
RUNTIME_GENERATED_DIRS = {"runtime-state", "state", "__pycache__"}
RUNTIME_GENERATED_SUFFIXES = {".pyc", ".pyo"}
SECRET_MARKERS = (
    ".env",
    "secret",
    "credential",
    "password",
    "passwd",
    "token",
    "cookie",
    "apikey",
    "api_key",
)
LAUNCHER_NAMES = (
    "QUALIFY-DSH-REQUIREMENT.cmd",
    "QUALIFY-DSH-REQUIREMENT.sh",
    "QUALIFY-DSH-CODE.cmd",
    "QUALIFY-DSH-CODE.sh",
    "QUALIFY-DSH-TEST-DESIGN.cmd",
    "QUALIFY-DSH-TEST-DESIGN.sh",
    "QUALIFY-DSH-SCRIPT.cmd",
    "QUALIFY-DSH-SCRIPT.sh",
    "QUALIFY-EXECUTION.cmd",
    "QUALIFY-EXECUTION.sh",
    "QUALIFY-FINAL.cmd",
    "QUALIFY-FINAL.sh",
    "QUALIFY-BANK-FINAL.cmd",
    "QUALIFY-BANK-FINAL.sh",
    "START-RC7-BANK-MISSION.cmd",
    "START-RC7-BANK-MISSION.sh",
    "START-RC7-ADMIN.cmd",
    "START-RC7-ADMIN.sh",
)
ENTRYPOINTS = tuple("packaging/rc7/%s" % name for name in LAUNCHER_NAMES)
REQUIRED_PRODUCT_FILES = (
    "rc7_runtime/bank_mission.py",
    "rc7_admin/__main__.py",
    "rc7_admin/server.py",
    "rc7_admin/projection.py",
    "rc7_admin/derived.py",
    "rc7_admin/static/index.html",
)
MISSION_ENTRYPOINT = "packaging/rc7/START-RC7-BANK-MISSION.cmd"
ADMIN_ENTRYPOINT = "packaging/rc7/START-RC7-ADMIN.cmd"
# Runtime, bank mission, recovery and admin must project the same durable truth.
# `state/rc7-r1.jsonl` was an early presentation-era path and is no longer a
# valid default because it creates a second R1 alongside the runtime stream.
SHARED_R1_DEFAULT = "runtime-state/r1/event-stream.jsonl"
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(path: Path) -> str:
    value = path.as_posix()
    if value.startswith("/") or ".." in path.parts:
        raise ValueError("UNSAFE_PACKAGE_PATH")
    return value


def _is_bundled_runtime_relative(path: Path) -> bool:
    parts = tuple(part.lower() for part in path.parts)
    return len(parts) >= 2 and parts[0] == "workspace-template" and parts[1] == "runtime"


def _looks_secret(path: Path) -> bool:
    lower_parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    if name in {".env", ".env.local", ".env.production", "credentials.json", "secrets.json"}:
        return True
    if any(part in {"secrets", "credentials"} for part in lower_parts):
        return True
    return any(marker in name for marker in SECRET_MARKERS if marker != ".env")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _copy_tree(source: Path, destination: Path) -> None:
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        if "__pycache__" in rel.parts or item.suffix in RUNTIME_GENERATED_SUFFIXES or _looks_secret(rel):
            continue
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.suffix.lower() == ".sh":
            _write_text(target, item.read_text(encoding="utf-8"))
            shutil.copystat(str(item), str(target))
        else:
            shutil.copy2(str(item), str(target))


def _copy_runtime_tree(source: Path, destination: Path) -> None:
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        if "__pycache__" in rel.parts or item.suffix in RUNTIME_GENERATED_SUFFIXES:
            continue
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(item), str(target))


def _bundle_current_windows_python(package_root: Path) -> bool:
    if os.name != "nt":
        return False
    python_home = Path(sys.executable).resolve().parent
    python_exe = python_home / "python.exe"
    if not python_exe.is_file():
        raise RuntimeError("BUILD_WINDOWS_PYTHON_RUNTIME_NOT_FOUND")
    target_home = package_root / PACKAGE_LOCAL_PYTHON.parent
    _copy_runtime_tree(python_home, target_home)
    target_exe = package_root / PACKAGE_LOCAL_PYTHON
    if not target_exe.is_file():
        raise RuntimeError("PACKAGE_LOCAL_PYTHON_COPY_FAILED")
    return True


def _bundle_build_codegraph(package_root: Path) -> Dict[str, object]:
    source_value = os.environ.get(BUILD_CODEGRAPH_BIN_ENV, "").strip()
    if not source_value:
        return {"path": PACKAGE_LOCAL_CODEGRAPH.as_posix(), "bundled": False, "resolved_version": None, "sha256": None}
    source = Path(source_value).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError("BUILD_CODEGRAPH_BINARY_NOT_FOUND")
    digest = sha256_file(source)
    declared = os.environ.get(BUILD_CODEGRAPH_SHA256_ENV, "").strip().lower()
    if declared:
        if not _SHA256_RE.match(declared):
            raise RuntimeError("BUILD_CODEGRAPH_SHA256_INVALID")
        if digest != declared:
            raise RuntimeError("BUILD_CODEGRAPH_SHA256_MISMATCH")
    target = package_root / PACKAGE_LOCAL_CODEGRAPH
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(target))
    if sha256_file(target) != digest:
        raise RuntimeError("PACKAGE_CODEGRAPH_COPY_HASH_MISMATCH")
    return {
        "path": PACKAGE_LOCAL_CODEGRAPH.as_posix(),
        "bundled": True,
        "resolved_version": os.environ.get(BUILD_CODEGRAPH_VERSION_ENV, "").strip() or None,
        "sha256": digest,
    }


def _bundle_build_browser(package_root: Path) -> Dict[str, object]:
    source_value = os.environ.get(BUILD_BROWSER_DIR_ENV, "").strip()
    if not source_value:
        return {"path": PACKAGE_LOCAL_BROWSER.as_posix(), "bundled": False, "resolved_version": None, "sha256": None}
    source = Path(source_value).expanduser().resolve()
    source_exe = source / "chrome.exe"
    if not source.is_dir() or not source_exe.is_file():
        raise RuntimeError("BUILD_BROWSER_RUNTIME_NOT_FOUND")
    digest = sha256_file(source_exe)
    declared = os.environ.get(BUILD_BROWSER_SHA256_ENV, "").strip().lower()
    if declared:
        if not _SHA256_RE.match(declared):
            raise RuntimeError("BUILD_BROWSER_SHA256_INVALID")
        if digest != declared:
            raise RuntimeError("BUILD_BROWSER_SHA256_MISMATCH")
    target_dir = package_root / PACKAGE_LOCAL_BROWSER.parent
    _copy_runtime_tree(source, target_dir)
    target_exe = package_root / PACKAGE_LOCAL_BROWSER
    if not target_exe.is_file() or sha256_file(target_exe) != digest:
        raise RuntimeError("PACKAGE_BROWSER_COPY_HASH_MISMATCH")
    return {
        "path": PACKAGE_LOCAL_BROWSER.as_posix(),
        "bundled": True,
        "resolved_version": os.environ.get(BUILD_BROWSER_VERSION_ENV, "").strip() or None,
        "sha256": digest,
    }


def _is_runtime_generated(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    return any(part in RUNTIME_GENERATED_DIRS for part in rel.parts) or path.suffix in RUNTIME_GENERATED_SUFFIXES


def _copy_source_trees(source_root: Path, package_root: Path) -> None:
    for name in SOURCE_DIRS:
        source = source_root / name
        if source.is_dir():
            _copy_tree(source, package_root / name)
    if LAUNCHER_DIR.is_dir():
        _copy_tree(source_root / LAUNCHER_DIR, package_root / LAUNCHER_DIR)


def _copy_product_source(source_root: Path, package_root: Path) -> None:
    for name in SOURCE_DIRS:
        source = source_root / name
        if source.is_dir():
            _copy_tree(source, package_root / name)
    launcher_source = source_root / LAUNCHER_DIR
    if launcher_source.is_dir():
        _copy_tree(launcher_source, package_root / LAUNCHER_DIR)


def _copy_skills(source_root: Path, package_root: Path) -> None:
    materialize_professional_skills(package_root)


def _copy_static_product_files(source_root: Path, package_root: Path) -> None:
    for name in ("README.md", "runtime-lock.json"):
        source = source_root / name
        if source.is_file():
            shutil.copy2(str(source), str(package_root / name))


def _write_identity(package_root: Path, source_commit: str) -> None:
    _write_text(package_root / "SOURCE_COMMIT", source_commit + "\n")
    _write_text(package_root / "BUILD_ID", "RC7-" + source_commit[:12] + "\n")
    _write_text(package_root / "RELEASE_STATUS", BUILD_STATUS + "\n")


def _manifest_entries(package_root: Path) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or _is_runtime_generated(package_root, path):
            continue
        rel = _safe_relative(path.relative_to(package_root))
        entries.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return entries


def _write_checksums(package_root: Path) -> None:
    lines = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or path.name == "CHECKSUMS.sha256" or _is_runtime_generated(package_root, path):
            continue
        rel = _safe_relative(path.relative_to(package_root))
        lines.append("%s  %s" % (sha256_file(path), rel))
    _write_text(package_root / "CHECKSUMS.sha256", "\n".join(lines) + "\n")


def _write_manifest(package_root: Path, source_commit: str, codegraph: Dict[str, object], browser: Dict[str, object]) -> None:
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "package_name": PACKAGE_NAME,
        "source_commit": source_commit,
        "build_status": BUILD_STATUS,
        "durable_truth": "R1_EVENT_STREAM",
        "shared_r1_default": SHARED_R1_DEFAULT,
        "entrypoints": list(ENTRYPOINTS),
        "required_product_files": list(REQUIRED_PRODUCT_FILES),
        "runtime_payload": {
            "python": {"path": PACKAGE_LOCAL_PYTHON.as_posix(), "bundled": (package_root / PACKAGE_LOCAL_PYTHON).is_file()},
            "codegraph": codegraph,
            "browser": browser,
        },
        "files": _manifest_entries(package_root),
    }
    _write_text(package_root / "PACKAGE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _validate_source_commit(source_commit: str) -> str:
    value = source_commit.strip()
    if not _SHA_RE.match(value):
        raise RuntimeError("SOURCE_COMMIT_INVALID")
    return value.lower()


def _validate_product_surface(package_root: Path) -> None:
    for rel in REQUIRED_PRODUCT_FILES:
        if not (package_root / rel).is_file():
            raise RuntimeError("REQUIRED_PRODUCT_FILE_MISSING:%s" % rel)
    for entry in ENTRYPOINTS:
        if not (package_root / entry).is_file():
            raise RuntimeError("REQUIRED_ENTRYPOINT_MISSING:%s" % entry)


def build_package(
    *,
    source_root: Union[str, Path],
    output_dir: Union[str, Path],
    source_commit: str,
) -> Dict[str, object]:
    source_root = Path(source_root).resolve()
    output_dir = Path(output_dir).resolve()
    commit = _validate_source_commit(source_commit)
    package_root = output_dir / PACKAGE_NAME
    if package_root.exists():
        shutil.rmtree(str(package_root))
    package_root.mkdir(parents=True)

    _copy_product_source(source_root, package_root)
    _copy_skills(source_root, package_root)
    _copy_static_product_files(source_root, package_root)
    _bundle_current_windows_python(package_root)
    codegraph = _bundle_build_codegraph(package_root)
    browser = _bundle_build_browser(package_root)
    _write_identity(package_root, commit)
    _validate_product_surface(package_root)
    _write_manifest(package_root, commit, codegraph, browser)
    _write_checksums(package_root)

    zip_path = output_dir / (PACKAGE_NAME + ".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(str(path), _safe_relative(path.relative_to(output_dir)))

    return {
        "package_root": str(package_root),
        "zip_path": str(zip_path),
        "zip_sha256": sha256_file(zip_path),
        "source_commit": commit,
        "build_status": BUILD_STATUS,
        "shared_r1_default": SHARED_R1_DEFAULT,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default=".")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    result = build_package(source_root=args.source_root, output_dir=args.output_dir, source_commit=args.source_commit)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
