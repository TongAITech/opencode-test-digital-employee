from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from rc7_release import package as rc7_package


BUILD_STATUS = "ENGINEERING_CANDIDATE_NOT_BANK_FINAL"
RC72_PACKAGE_NAME = "PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10"
RC72_MANIFEST_SCHEMA = "pfc.aitest.rc7.2.package.v1"
RC72_BUILD_ID_PREFIX = "RC7.2-"
RC72_RELEASE_FAMILY = "RC7.2"
RC72_ARCHITECTURE = "RELEASE_BATCH_N1_N10_AUTONOMOUS_TEST_RUNTIME"
RC72_IDENTITY_FILE = "RC72_RELEASE_IDENTITY.json"
RC72_Q2B_REQUIRED_FILES = (
    "rc7_release/rc72_windows_clean_qualification.py",
    "packaging/rc7.2/AITEST.sh",
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def discover_required_rc72_runtime_files(repo_root: Union[str, Path]) -> Tuple[str, ...]:
    repo = Path(repo_root).resolve()
    runtime = repo / "rc7_runtime"
    if not runtime.is_dir():
        raise ValueError("RC72_RUNTIME_DIR_MISSING")
    files = tuple(
        sorted(
            path.relative_to(repo).as_posix()
            for path in runtime.glob("rc72_*.py")
            if path.is_file()
        )
    )
    if not files:
        raise ValueError("RC72_RUNTIME_FILES_MISSING")
    return files


def _validate_source_commit(value: str) -> str:
    commit = str(value or "").strip()
    if not _SHA_RE.match(commit):
        raise ValueError("INVALID_SOURCE_COMMIT")
    return commit.lower()


def promote_manifest_to_rc72(
    base_manifest: Mapping[str, object],
    *,
    source_commit: str,
    required_runtime_files: Sequence[str],
) -> Dict[str, object]:
    commit = _validate_source_commit(source_commit)
    base_source = str(base_manifest.get("source_commit") or "").strip().lower()
    if base_source != commit:
        raise ValueError("SOURCE_COMMIT_MISMATCH")

    manifest = dict(base_manifest)
    manifest.update(
        {
            "schema_version": RC72_MANIFEST_SCHEMA,
            "status": BUILD_STATUS,
            "source_commit": commit,
            "build_id": RC72_BUILD_ID_PREFIX + commit[:12],
            "package_name": RC72_PACKAGE_NAME,
            "release_family": RC72_RELEASE_FAMILY,
            "architecture": RC72_ARCHITECTURE,
            "business_root": "RELEASE_BATCH",
            "runtime_control_backbone": "N1_N10_MISSION_GRAPH",
            "required_rc72_runtime_files": list(required_runtime_files),
            "required_q2b_files": list(RC72_Q2B_REQUIRED_FILES),
            "field_verified": False,
            "bank_final": False,
            "real_mission_pass": False,
            "delivery_pass": False,
            "bank_field_pass": False,
        }
    )
    return manifest


def validate_rc72_manifest(
    manifest: Mapping[str, object],
    *,
    expected_source_commit: Optional[str] = None,
) -> Dict[str, object]:
    if manifest.get("schema_version") != RC72_MANIFEST_SCHEMA:
        raise ValueError("RC72_MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("status") != BUILD_STATUS:
        raise ValueError("RC72_RELEASE_STATUS_INVALID")
    if manifest.get("package_name") != RC72_PACKAGE_NAME:
        raise ValueError("RC72_PACKAGE_NAME_MISMATCH")
    if manifest.get("release_family") != RC72_RELEASE_FAMILY:
        raise ValueError("RC72_RELEASE_FAMILY_MISMATCH")
    if manifest.get("architecture") != RC72_ARCHITECTURE:
        raise ValueError("RC72_ARCHITECTURE_MISMATCH")
    if manifest.get("business_root") != "RELEASE_BATCH":
        raise ValueError("RC72_BUSINESS_ROOT_INVALID")
    if manifest.get("runtime_control_backbone") != "N1_N10_MISSION_GRAPH":
        raise ValueError("RC72_RUNTIME_BACKBONE_INVALID")
    if manifest.get("field_verified") is not False:
        raise ValueError("RC72_FIELD_CLAIM_FORBIDDEN")
    if manifest.get("bank_final") is not False:
        raise ValueError("RC72_BANK_FINAL_CLAIM_FORBIDDEN")
    for key in ("real_mission_pass", "delivery_pass", "bank_field_pass"):
        if manifest.get(key) is not False:
            raise ValueError("RC72_FALSE_PASS_FORBIDDEN:%s" % key)

    source_commit = _validate_source_commit(str(manifest.get("source_commit") or ""))
    if expected_source_commit is not None:
        expected = _validate_source_commit(expected_source_commit)
        if source_commit != expected:
            raise ValueError("RC72_SOURCE_COMMIT_MISMATCH")
    if manifest.get("build_id") != RC72_BUILD_ID_PREFIX + source_commit[:12]:
        raise ValueError("RC72_BUILD_ID_MISMATCH")

    required = tuple(str(item) for item in (manifest.get("required_rc72_runtime_files") or ()))
    if len(set(required)) != len(required):
        raise ValueError("RC72_REQUIRED_RUNTIME_DUPLICATE")
    required_q2b = tuple(str(item) for item in (manifest.get("required_q2b_files") or ()))
    if set(required_q2b) != set(RC72_Q2B_REQUIRED_FILES):
        raise ValueError("RC72_Q2B_REQUIRED_FILE_MANIFEST_MISMATCH")

    actual_files = {
        str(item.get("path"))
        for item in (manifest.get("files") or ())
        if isinstance(item, dict) and item.get("path")
    }
    missing = sorted(item for item in required if item not in actual_files)
    if missing:
        raise ValueError("RC72_RUNTIME_FILE_MISSING:" + ",".join(missing))
    missing_q2b = sorted(item for item in RC72_Q2B_REQUIRED_FILES if item not in actual_files)
    if missing_q2b:
        raise ValueError("RC72_Q2B_FILE_MISSING:" + ",".join(missing_q2b))
    return dict(manifest)


def _manifest_files(package_root: Path) -> List[Dict[str, object]]:
    files: List[Dict[str, object]] = []
    for path in rc7_package._package_files(package_root):
        rel = rc7_package._safe_relative(path.relative_to(package_root))
        if rel == "PACKAGE_MANIFEST.json":
            continue
        files.append(
            {
                "path": rel,
                "sha256": rc7_package.sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    return files


def _write_identity(package_root: Path, source_commit: str) -> None:
    identity = {
        "schema": "pfc.aitest.rc7.2.release-identity.v1",
        "release_family": RC72_RELEASE_FAMILY,
        "package_name": RC72_PACKAGE_NAME,
        "source_commit": source_commit,
        "build_id": RC72_BUILD_ID_PREFIX + source_commit[:12],
        "business_root": "RELEASE_BATCH",
        "runtime_control_backbone": "N1_N10_MISSION_GRAPH",
        "field_verified": False,
        "bank_final": False,
    }
    rc7_package._write_text(
        package_root / RC72_IDENTITY_FILE,
        json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    rc7_package._write_text(package_root / "BUILD_ID", identity["build_id"] + "\n")
    rc7_package._write_text(package_root / "RELEASE_FAMILY", RC72_RELEASE_FAMILY + "\n")
    rc7_package._write_text(package_root / "RELEASE_STATUS", BUILD_STATUS + "\n")


def _install_rc72_launchers(repo_root: Path, package_root: Path) -> None:
    source = repo_root / "packaging" / "rc7.2"
    if not source.is_dir():
        raise RuntimeError("RC72_PACKAGING_DIR_MISSING")
    target = package_root / "packaging" / "rc7.2"
    if target.exists():
        shutil.rmtree(str(target))
    rc7_package._copy_tree(source, target)
    launcher = target / "AITEST.sh"
    if not launcher.is_file():
        raise RuntimeError("RC72_GIT_BASH_LAUNCHER_MISSING")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)


def _rewrite_manifest(package_root: Path, repo_root: Path, source_commit: str) -> Dict[str, object]:
    manifest_path = package_root / "PACKAGE_MANIFEST.json"
    base_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = discover_required_rc72_runtime_files(repo_root)
    manifest = promote_manifest_to_rc72(
        base_manifest,
        source_commit=source_commit,
        required_runtime_files=required,
    )
    manifest["files"] = _manifest_files(package_root)
    rc7_package._write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    rc7_package.write_checksums(package_root)
    return manifest


def verify_package(
    package_root: Union[str, Path],
    *,
    expected_source_commit: Optional[str] = None,
) -> Dict[str, object]:
    root = Path(package_root).resolve()
    required_files = {
        "BUILD_ID",
        "SOURCE_COMMIT",
        "RELEASE_FAMILY",
        "RELEASE_STATUS",
        RC72_IDENTITY_FILE,
        "PACKAGE_MANIFEST.json",
        "CHECKSUMS.sha256",
        "rc7_release/rc72_package.py",
        "rc7_runtime/__init__.py",
    }.union(RC72_Q2B_REQUIRED_FILES)
    missing = sorted(name for name in required_files if not (root / name).is_file())
    if missing:
        raise RuntimeError("RC72_PACKAGE_REQUIRED_FILE_MISSING:" + ",".join(missing))

    source_commit = _validate_source_commit((root / "SOURCE_COMMIT").read_text(encoding="utf-8").strip())
    if expected_source_commit is not None and source_commit != _validate_source_commit(expected_source_commit):
        raise RuntimeError("RC72_SOURCE_COMMIT_MISMATCH")

    if (root / "BUILD_ID").read_text(encoding="utf-8").strip() != RC72_BUILD_ID_PREFIX + source_commit[:12]:
        raise RuntimeError("RC72_BUILD_ID_MISMATCH")
    if (root / "RELEASE_FAMILY").read_text(encoding="utf-8").strip() != RC72_RELEASE_FAMILY:
        raise RuntimeError("RC72_RELEASE_FAMILY_MISMATCH")
    if (root / "RELEASE_STATUS").read_text(encoding="utf-8").strip() != BUILD_STATUS:
        raise RuntimeError("RC72_RELEASE_STATUS_INVALID")

    identity = json.loads((root / RC72_IDENTITY_FILE).read_text(encoding="utf-8"))
    if identity.get("source_commit") != source_commit:
        raise RuntimeError("RC72_IDENTITY_SOURCE_MISMATCH")
    if identity.get("field_verified") is not False or identity.get("bank_final") is not False:
        raise RuntimeError("RC72_IDENTITY_FALSE_PASS_FORBIDDEN")

    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    try:
        validate_rc72_manifest(manifest, expected_source_commit=source_commit)
    except ValueError as exc:
        raise RuntimeError(str(exc))

    required_runtime = tuple(str(item) for item in manifest.get("required_rc72_runtime_files") or ())
    missing_runtime = sorted(name for name in required_runtime if not (root / name).is_file())
    if missing_runtime:
        raise RuntimeError("RC72_RUNTIME_FILE_MISSING:" + ",".join(missing_runtime))

    expected: Dict[str, str] = {}
    for line in (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        expected[rel] = digest
    for rel, digest in expected.items():
        path = root / rel
        if not path.is_file() or rc7_package.sha256_file(path) != digest:
            raise RuntimeError("RC72_PACKAGE_CHECKSUM_MISMATCH:%s" % rel)

    actual = {
        rc7_package._safe_relative(path.relative_to(root))
        for path in rc7_package._package_files(root)
    }
    if actual != set(expected):
        raise RuntimeError("RC72_PACKAGE_CHECKSUM_COVERAGE_MISMATCH")

    package_python = root / rc7_package.PACKAGE_LOCAL_PYTHON
    if not package_python.is_file():
        raise RuntimeError("RC72_PACKAGE_LOCAL_PYTHON_MISSING")
    if manifest.get("package_local_python_bundled") is not True:
        raise RuntimeError("RC72_PACKAGE_LOCAL_PYTHON_MANIFEST_INVALID")

    return {
        "status": "PASS",
        "qualification_scope": "Q2_WINDOWS_CLEAN_UNPACK_PACKAGE_IDENTITY",
        "release_status": BUILD_STATUS,
        "release_family": RC72_RELEASE_FAMILY,
        "package_name": RC72_PACKAGE_NAME,
        "source_commit": source_commit,
        "build_id": RC72_BUILD_ID_PREFIX + source_commit[:12],
        "required_rc72_runtime_count": len(required_runtime),
        "q2b_required_file_count": len(RC72_Q2B_REQUIRED_FILES),
        "file_count": len(actual) + 1,
        "package_local_python": rc7_package.PACKAGE_LOCAL_PYTHON.as_posix(),
        "package_local_python_bundled": True,
        "field_verified": False,
        "bank_final": False,
    }


def build_package(
    repo_root: Union[str, Path],
    output_dir: Union[str, Path],
    source_commit: str,
    make_zip: bool = True,
) -> Path:
    commit = _validate_source_commit(source_commit)
    repo = Path(repo_root).resolve()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    base_root = rc7_package.build_package(repo, out, commit, make_zip=False)
    package_root = out / RC72_PACKAGE_NAME
    if package_root.exists():
        shutil.rmtree(str(package_root))
    base_root.rename(package_root)

    _install_rc72_launchers(repo, package_root)
    _write_identity(package_root, commit)
    _rewrite_manifest(package_root, repo, commit)
    verify_package(package_root, expected_source_commit=commit)

    if make_zip:
        zip_path = out / ("%s-%s.zip" % (RC72_PACKAGE_NAME, commit[:12]))
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(package_root.rglob("*")):
                if path.is_file():
                    arc = Path(package_root.name) / path.relative_to(package_root)
                    archive.write(str(path), arc.as_posix())
        rc7_package._write_text(
            Path(str(zip_path) + ".sha256"),
            "%s  %s\n" % (rc7_package.sha256_file(zip_path), zip_path.name),
        )
    return package_root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.rc72_package")
    sub = parser.add_subparsers(dest="command")

    build = sub.add_parser("build")
    build.add_argument("--repo-root", default=".")
    build.add_argument("--output", default="dist")
    build.add_argument("--source-commit", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--package-root", required=True)
    verify.add_argument("--expected-source-commit")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "build":
        root = build_package(args.repo_root, args.output, args.source_commit, make_zip=True)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "package_root": str(root),
                    "package_name": RC72_PACKAGE_NAME,
                    "source_commit": _validate_source_commit(args.source_commit),
                    "release_status": BUILD_STATUS,
                    "field_verified": False,
                    "bank_final": False,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "verify":
        result = verify_package(
            args.package_root,
            expected_source_commit=args.expected_source_commit,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    _parser().error("command required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
