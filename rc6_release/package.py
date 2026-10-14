from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable

BUILD_STATUS = "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"
PACKAGE_NAME = "PFC-AITest-DSH-Turnkey-RC6-BANK-WIN10"
MANIFEST_SCHEMA = "pfc.aitest.rc6.package.v1"
SECRET_MARKERS = (
    ".env", "secret", "credential", "password", "passwd", "token", "cookie", "apikey", "api_key",
)

SOURCE_DIRS = ("rc6_runtime", "rc6_release")
LAUNCHER_DIR = Path("packaging") / "rc6"
RUNTIME_GENERATED_DIRS = {"runtime-state"}
RUNTIME_GENERATED_SUFFIXES = {".pyc", ".pyo"}

SHELL_ENTRYPOINTS = (
    "AITEST.sh",
    "START-AITEST.sh",
    "STOP-AITEST.sh",
    "STATUS.sh",
    "VERIFY.sh",
    "QUALIFY-AGENT-RUNTIME.sh",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _safe_relative(path: Path) -> str:
    value = path.as_posix()
    if value.startswith("/") or ".." in path.parts:
        raise ValueError("UNSAFE_PACKAGE_PATH")
    return value


def _looks_secret(path: Path) -> bool:
    lower_parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    if name in {".env", ".env.local", ".env.production", "credentials.json", "secrets.json"}:
        return True
    return any(marker in name for marker in SECRET_MARKERS if marker != ".env") or any(
        part in {"secrets", "credentials"} for part in lower_parts
    )


def _copy_tree(source: Path, dest: Path) -> None:
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        if "__pycache__" in rel.parts or item.suffix in {".pyc", ".pyo"} or _looks_secret(rel):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _write_text(path: Path, text: str) -> None:
    """Write deterministic LF UTF-8 text on Python 3.8+ and Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _is_runtime_generated(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    return (
        "__pycache__" in rel.parts
        or path.suffix in RUNTIME_GENERATED_SUFFIXES
        or (bool(rel.parts) and rel.parts[0] in RUNTIME_GENERATED_DIRS)
    )


def _package_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "CHECKSUMS.sha256":
            continue
        if _is_runtime_generated(root, path):
            continue
        yield path


def _manifest_for(package_root: Path, source_commit: str) -> dict:
    files = []
    for path in _package_files(package_root):
        rel = _safe_relative(path.relative_to(package_root))
        if rel == "PACKAGE_MANIFEST.json":
            continue
        files.append({"path": rel, "sha256": sha256_file(path), "size": path.stat().st_size})
    return {
        "schema_version": MANIFEST_SCHEMA,
        "status": BUILD_STATUS,
        "source_truth": "GIT_COMMIT",
        "source_commit": source_commit,
        "build_id": f"RC6-{source_commit[:12]}",
        "architecture": "DSH_NATIVE_GOVERNED_RUNTIME",
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "entrypoints": list(SHELL_ENTRYPOINTS),
        "durable_truth": "R1_EVENT_STREAM",
        "agent_runtime_bank_final_gate": "NOT_PROVEN_UNTIL_REAL_DSH_VERTICAL_SLICE_PASS",
        "autonomous_testing_pass": False,
        "full_chain_real": False,
        "bank_field_pass": False,
        "field_qualification_required": True,
        "files": files,
    }


def write_checksums(package_root: Path) -> None:
    lines = []
    for path in _package_files(package_root):
        rel = _safe_relative(path.relative_to(package_root))
        lines.append(f"{sha256_file(path)}  {rel}")
    _write_text(package_root / "CHECKSUMS.sha256", "\n".join(lines) + "\n")


def build_package(repo_root: str | Path, output_dir: str | Path, source_commit: str, make_zip: bool = True) -> Path:
    repo = Path(repo_root).resolve()
    out = Path(output_dir).resolve()
    if len(source_commit) < 12 or any(c not in "0123456789abcdefABCDEF" for c in source_commit):
        raise ValueError("INVALID_SOURCE_COMMIT")
    package_root = out / PACKAGE_NAME
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True)

    for name in SOURCE_DIRS:
        src = repo / name
        if not src.is_dir():
            raise RuntimeError(f"MISSING_SOURCE_DIR:{name}")
        _copy_tree(src, package_root / name)

    launchers = repo / LAUNCHER_DIR
    if not launchers.is_dir():
        raise RuntimeError("MISSING_RC6_LAUNCHERS")
    _copy_tree(launchers, package_root)

    readme = repo / "docs" / "RC6_RELEASE_QUALIFICATION.md"
    if readme.exists():
        shutil.copy2(readme, package_root / "RC6_RELEASE_QUALIFICATION.md")

    _write_text(package_root / "SOURCE_COMMIT", source_commit + "\n")
    _write_text(package_root / "BUILD_ID", f"RC6-{source_commit[:12]}\n")
    _write_text(package_root / "RELEASE_STATUS", BUILD_STATUS + "\n")

    manifest = _manifest_for(package_root, source_commit)
    _write_text(package_root / "PACKAGE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    write_checksums(package_root)

    for shell_name in SHELL_ENTRYPOINTS:
        shell_path = package_root / shell_name
        if shell_path.exists():
            shell_path.chmod(shell_path.stat().st_mode | stat.S_IXUSR)

    verify_package(package_root)

    if make_zip:
        zip_path = out / f"{PACKAGE_NAME}-{source_commit[:12]}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for path in sorted(package_root.rglob("*")):
                if path.is_file():
                    arc = Path(package_root.name) / path.relative_to(package_root)
                    zf.write(path, arc.as_posix())
    return package_root


def verify_package(package_root: str | Path) -> dict:
    root = Path(package_root).resolve()
    required = {
        "AITEST.sh", "START-AITEST.sh", "STOP-AITEST.sh", "STATUS.sh", "VERIFY.sh", "QUALIFY-AGENT-RUNTIME.sh",
        "BUILD_ID", "SOURCE_COMMIT", "RELEASE_STATUS", "PACKAGE_MANIFEST.json", "CHECKSUMS.sha256",
        "rc6_runtime/__init__.py", "rc6_runtime/agent_runtime.py", "rc6_release/mcp_server.py",
        "rc6_release/agent_qualification.py", ".dsh/skills/pfc-full-chain-test/SKILL.md",
    }
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise RuntimeError("PACKAGE_REQUIRED_FILE_MISSING:" + ",".join(missing))

    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise RuntimeError("PACKAGE_MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("status") != BUILD_STATUS or manifest.get("bank_field_pass") is not False:
        raise RuntimeError("PACKAGE_RELEASE_STATUS_INVALID")
    if manifest.get("agent_runtime_bank_final_gate") != "NOT_PROVEN_UNTIL_REAL_DSH_VERTICAL_SLICE_PASS":
        raise RuntimeError("PACKAGE_AGENT_RUNTIME_GATE_INVALID")
    if manifest.get("autonomous_testing_pass") is not False or manifest.get("full_chain_real") is not False:
        raise RuntimeError("PACKAGE_FALSE_RUNTIME_PASS_FORBIDDEN")
    source_commit = (root / "SOURCE_COMMIT").read_text(encoding="utf-8").strip()
    if manifest.get("source_commit") != source_commit:
        raise RuntimeError("PACKAGE_SOURCE_COMMIT_MISMATCH")

    expected = {}
    for line in (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        expected[rel] = digest
    for rel, digest in expected.items():
        path = root / rel
        if not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError(f"PACKAGE_CHECKSUM_MISMATCH:{rel}")

    actual = {_safe_relative(p.relative_to(root)) for p in _package_files(root)}
    if actual != set(expected):
        raise RuntimeError("PACKAGE_CHECKSUM_COVERAGE_MISMATCH")
    secret_paths = sorted(rel for rel in actual if _looks_secret(Path(rel)))
    if secret_paths:
        raise RuntimeError("PACKAGE_SECRET_PATH_FORBIDDEN:" + ",".join(secret_paths))

    return {
        "status": "PASS",
        "release_status": BUILD_STATUS,
        "agent_runtime_bank_final_gate": manifest["agent_runtime_bank_final_gate"],
        "source_commit": source_commit,
        "file_count": len(actual) + 1,
    }


def _source_commit(repo: Path) -> str:
    env = os.environ.get("GITHUB_SHA") or os.environ.get("RC6_SOURCE_COMMIT")
    if env:
        return env.strip()
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc6_release.package")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--repo-root", default=".")
    build.add_argument("--output", default="dist")
    build.add_argument("--source-commit")
    verify = sub.add_parser("verify")
    verify.add_argument("--package-root", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        repo = Path(args.repo_root).resolve()
        commit = args.source_commit or _source_commit(repo)
        root = build_package(repo, args.output, commit)
        print(json.dumps({"status": "PASS", "package_root": str(root), "source_commit": commit, "release_status": BUILD_STATUS}))
        return 0
    result = verify_package(args.package_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
