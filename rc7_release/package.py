from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
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
    "START-RC7-ADMIN.cmd",
    "START-RC7-ADMIN.sh",
)
ENTRYPOINTS = tuple("packaging/rc7/%s" % name for name in LAUNCHER_NAMES)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


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


def _manifest_for(package_root: Path, source_commit: str) -> Dict[str, object]:
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
        "build_id": "RC7-%s" % source_commit[:12],
        "architecture": "RC6_CAPABILITY_BASE_DSH_EXECUTION_RC7_CONTROL_PLANE",
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "durable_truth": "R1_EVENT_STREAM",
        "completion_authority": "MISSION_SUFFICIENCY_PLUS_REALITY_EVIDENCE",
        "final_qualification": "FAIL_CLOSED_EXTERNAL_REALITY_EVIDENCE_REQUIRED",
        "real_mission_pass": False,
        "delivery_pass": False,
        "bank_field_pass": False,
        "field_qualification_required": True,
        "workspace_installation": "PACKAGE_LOCAL_NO_SOURCE_INSTALL_REQUIRED",
        "entrypoints": list(ENTRYPOINTS),
        "static_skill_count": len(ALL_SKILLS),
        "files": files,
    }


def write_checksums(package_root: Path) -> None:
    lines = []
    for path in _package_files(package_root):
        rel = _safe_relative(path.relative_to(package_root))
        lines.append("%s  %s" % (sha256_file(path), rel))
    _write_text(package_root / "CHECKSUMS.sha256", "\n".join(lines) + "\n")


def build_package(
    repo_root: Union[str, Path],
    output_dir: Union[str, Path],
    source_commit: str,
    make_zip: bool = True,
) -> Path:
    if not _SHA_RE.match(source_commit or ""):
        raise ValueError("INVALID_SOURCE_COMMIT")
    repo = Path(repo_root).resolve()
    out = Path(output_dir).resolve()
    package_root = out / PACKAGE_NAME
    if package_root.exists():
        shutil.rmtree(str(package_root))
    package_root.mkdir(parents=True)

    for name in SOURCE_DIRS:
        source = repo / name
        if not source.is_dir():
            raise RuntimeError("MISSING_SOURCE_DIR:%s" % name)
        _copy_tree(source, package_root / name)

    launcher_root = repo / LAUNCHER_DIR
    if not launcher_root.is_dir():
        raise RuntimeError("MISSING_RC7_LAUNCHERS")
    _copy_tree(launcher_root, package_root / LAUNCHER_DIR)

    coordinator = repo / RC6_COORDINATOR_DIR
    if not coordinator.is_dir():
        raise RuntimeError("MISSING_RC6_COORDINATOR_SKILL")
    _copy_tree(coordinator, package_root / ".dsh" / "skills" / "pfc-full-chain-test")
    materialize_professional_skills(package_root)

    for relative in (Path("docs") / "RC7_ACCEPTANCE_BASELINE.md", Path("runtime-lock.json")):
        source = repo / relative
        if source.is_file():
            destination = package_root / relative.name
            shutil.copy2(str(source), str(destination))

    _write_text(package_root / "SOURCE_COMMIT", source_commit + "\n")
    _write_text(package_root / "BUILD_ID", "RC7-%s\n" % source_commit[:12])
    _write_text(package_root / "RELEASE_STATUS", BUILD_STATUS + "\n")

    manifest = _manifest_for(package_root, source_commit)
    _write_text(
        package_root / "PACKAGE_MANIFEST.json",
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    write_checksums(package_root)

    for relative in ENTRYPOINTS:
        path = package_root / relative
        if path.suffix.lower() == ".sh" and path.exists():
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    verify_package(package_root)

    if make_zip:
        out.mkdir(parents=True, exist_ok=True)
        zip_path = out / ("%s-%s.zip" % (PACKAGE_NAME, source_commit[:12]))
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(package_root.rglob("*")):
                if path.is_file():
                    arc = Path(package_root.name) / path.relative_to(package_root)
                    archive.write(str(path), arc.as_posix())
        _write_text(Path(str(zip_path) + ".sha256"), "%s  %s\n" % (sha256_file(zip_path), zip_path.name))
    return package_root


def verify_package(package_root: Union[str, Path]) -> Dict[str, object]:
    root = Path(package_root).resolve()
    required = {
        "BUILD_ID",
        "SOURCE_COMMIT",
        "RELEASE_STATUS",
        "PACKAGE_MANIFEST.json",
        "CHECKSUMS.sha256",
        "rc6_runtime/__init__.py",
        "rc7_runtime/__init__.py",
        "rc7_release/final_qualification.py",
        "rc7_release/package.py",
        "rc7_admin/__init__.py",
    }
    required.update(ENTRYPOINTS)
    required.update(".dsh/skills/%s/SKILL.md" % name for name in ALL_SKILLS)
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise RuntimeError("PACKAGE_REQUIRED_FILE_MISSING:" + ",".join(missing))

    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise RuntimeError("PACKAGE_MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("status") != BUILD_STATUS:
        raise RuntimeError("PACKAGE_RELEASE_STATUS_INVALID")
    for key in ("real_mission_pass", "delivery_pass", "bank_field_pass"):
        if manifest.get(key) is not False:
            raise RuntimeError("PACKAGE_FALSE_PASS_FORBIDDEN:%s" % key)
    if manifest.get("durable_truth") != "R1_EVENT_STREAM":
        raise RuntimeError("PACKAGE_DURABLE_TRUTH_INVALID")
    if manifest.get("version_policy") != "CAPABILITY_BASED_NO_EXACT_VERSION_PIN":
        raise RuntimeError("PACKAGE_VERSION_POLICY_INVALID")

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
            raise RuntimeError("PACKAGE_CHECKSUM_MISMATCH:%s" % rel)

    actual = {_safe_relative(path.relative_to(root)) for path in _package_files(root)}
    if actual != set(expected):
        raise RuntimeError("PACKAGE_CHECKSUM_COVERAGE_MISMATCH")
    secret_paths = sorted(rel for rel in actual if _looks_secret(Path(rel)))
    if secret_paths:
        raise RuntimeError("PACKAGE_SECRET_PATH_FORBIDDEN:" + ",".join(secret_paths))

    skill_dirs = {
        path.parent.name
        for path in (root / ".dsh" / "skills").glob("*/SKILL.md")
        if path.parent.name.startswith("pfc-")
    }
    if skill_dirs != set(ALL_SKILLS):
        raise RuntimeError("PACKAGE_STATIC_SKILL_SET_MISMATCH")

    return {
        "status": "PASS",
        "release_status": BUILD_STATUS,
        "source_commit": source_commit,
        "static_skill_count": len(ALL_SKILLS),
        "file_count": len(actual) + 1,
    }


def _source_commit(repo: Path) -> str:
    env_value = os.environ.get("GITHUB_SHA") or os.environ.get("RC7_SOURCE_COMMIT")
    if env_value:
        return env_value.strip()
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    return proc.stdout.strip()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.package")
    sub = parser.add_subparsers(dest="command")
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
        print(json.dumps({"status": "PASS", "package_root": str(root), "source_commit": commit, "release_status": BUILD_STATUS}, sort_keys=True))
        return 0
    if args.command == "verify":
        print(json.dumps(verify_package(args.package_root), sort_keys=True))
        return 0
    parser.error("command required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
