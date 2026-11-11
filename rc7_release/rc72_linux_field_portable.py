"""Native Linux x86_64 RC7.2 FIELD transport; never a C12/BANK_FINAL claim.

This transport intentionally does not invoke the Windows RC7/RC7.2 package builders.
It copies source and independently sourced Linux runtime payloads, preserves the
Q3 external approval boundary, and never bundles a DSH host executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

SCHEMA = "pfc.aitest.rc7.2.linux-field-transport.v1"
NAME = "PFC-AITest-DSH-RC7.2-UBUNTU22-X64-FIELD"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
SOURCE_DIRS = ("rc6_runtime", "rc6_release", "rc7_runtime", "rc7_release", "rc7_admin")
PACKAGE_SCRIPTS = ("packaging/rc7", "packaging/rc7.2")
REQUIRED = (
    "SOURCE_COMMIT", "LINUX_FIELD_PACKAGE.json", "CHECKSUMS.sha256",
    "packaging/rc7.2/LINUX-FIELD-AITEST.sh",
    "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh",
    "packaging/rc7.2/Q3-FIELD-HANDOFF.sh",
    "rc7_release/rc72_target_linux_attestation.py",
    "rc7_release/rc72_target_linux_reality.py",
    "rc7_runtime/rc72_mission_factory.py",
    "rc7_release/rc72_mission_cli.py",
    "workspace-template/runtime/python/bin/python3",
    "workspace-template/runtime/node/bin/node",
    "workspace-template/runtime/browser/browserskill/bsk",
    "workspace-template/runtime/browser/browserskill-extension/manifest.json",
    "workspace-template/runtime/node-execution/node_modules/playwright/package.json",
)
IGNORED_NAMES = {"CHECKSUMS.sha256", "LINUX_FIELD_PACKAGE.json"}
GENERATED_DIRS = {"runtime-state", "state", "__pycache__", "qualification-evidence"}


class LinuxFieldTransportError(RuntimeError):
    pass


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require_commit(value: str) -> str:
    sha = str(value or "").strip().lower()
    if not SHA_PATTERN.fullmatch(sha):
        raise LinuxFieldTransportError("LINUX_SOURCE_COMMIT_INVALID")
    return sha


def _check_linux_host() -> None:
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise LinuxFieldTransportError("LINUX_X86_64_BUILD_HOST_REQUIRED")


def _copy_tree(src: Path, dst: Path) -> None:
    from rc7_release.package import _copy_tree as copy_source
    if not src.is_dir():
        raise LinuxFieldTransportError("SOURCE_DIR_MISSING:" + str(src))
    copy_source(src, dst)


def _copy_runtime(src: Path, dst: Path) -> None:
    if not src.is_dir() or src.is_symlink():
        raise LinuxFieldTransportError("LINUX_NATIVE_RUNTIME_SOURCE_REQUIRED:" + str(src))
    if dst.exists():
        raise LinuxFieldTransportError("LINUX_RUNTIME_TARGET_ALREADY_EXISTS")
    # Dereference upstream distribution symlinks: no absolute runner path is
    # permitted to remain inside a bank-transfer artifact.
    shutil.copytree(str(src), str(dst), symlinks=False)


def _files(root: Path) -> List[Path]:
    files = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or p.name in IGNORED_NAMES:
            continue
        if any(part in GENERATED_DIRS for part in rel.parts) or p.suffix == ".pyc":
            continue
        if p.is_symlink():
            try:
                p.resolve(strict=True).relative_to(root.resolve())
            except (ValueError, OSError):
                raise LinuxFieldTransportError("LINUX_EXTERNAL_SYMLINK_FORBIDDEN:" + str(rel)) from None
        files.append(p)
    return files


def _write_seal(root: Path, meta: Dict[str, object]) -> None:
    (root / "LINUX_FIELD_PACKAGE.json").write_text(
        json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    lines = []
    for p in _files(root):
        lines.append(digest(p) + "  " + p.relative_to(root).as_posix())
    (root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def stage_package(
    repo_root: Path, output_dir: Path, source_commit: str,
    python_source: Path, node_source: Path, bsk_cli: Path,
    browser_source: Path, extension_source: Path, node_execution_source: Path,
) -> Path:
    _check_linux_host()
    source_commit = require_commit(source_commit)
    repo = Path(repo_root).resolve()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = out / NAME
    if root.exists():
        raise LinuxFieldTransportError("LINUX_STAGE_TARGET_MUST_BE_FRESH")

    root.mkdir()
    for name in SOURCE_DIRS:
        _copy_tree(repo / name, root / name)
    for name in PACKAGE_SCRIPTS:
        _copy_tree(repo / name, root / name)
    coordinator = repo / "packaging/rc6/.dsh/skills/pfc-full-chain-test"
    _copy_tree(coordinator, root / ".dsh/skills/pfc-full-chain-test")
    from rc6_release.static_skills import materialize_professional_skills
    materialize_professional_skills(root)

    for name in ("docs/RC7_ACCEPTANCE_BASELINE.md",):
        src = repo / name
        if src.is_file():
            dest = root / Path(name).name
            shutil.copy2(str(src), str(dest))

    runtime = root / "workspace-template/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    _copy_runtime(Path(python_source).resolve(), runtime / "python")
    _copy_runtime(Path(node_source).resolve(), runtime / "node")
    _copy_runtime(Path(browser_source).resolve(), runtime / "browser/pw-browsers")
    _copy_runtime(Path(extension_source).resolve(), runtime / "browser/browserskill-extension")
    _copy_runtime(Path(node_execution_source).resolve(), runtime / "node-execution")

    cli = Path(bsk_cli).resolve()
    if not cli.is_file() or not os.access(str(cli), os.X_OK):
        raise LinuxFieldTransportError("BSK_LINUX_EXECUTABLE_REQUIRED")
    bsk = runtime / "browser/browserskill/bsk"
    bsk.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(cli), str(bsk))
    bsk.chmod(bsk.stat().st_mode | stat.S_IXUSR)

    py = runtime / "python/bin/python3"
    node = runtime / "node/bin/node"
    if not py.is_file() or not node.is_file():
        raise LinuxFieldTransportError("LINUX_NATIVE_PYTHON_NODE_MISSING")
    for p in (py, node):
        p.chmod(p.stat().st_mode | stat.S_IXUSR)

    (root / "SOURCE_COMMIT").write_text(source_commit + "\n", encoding="utf-8")
    (root / "BUILD_ID").write_text("RC7.2-LINUX-FIELD-" + source_commit[:12] + "\n", encoding="utf-8")
    readme = repo / "packaging/rc7.2/LINUX-FIELD-README.md"
    shutil.copy2(str(readme), str(root / "README-FIRST-LINUX.md"))
    launcher = root / "packaging/rc7.2/LINUX-FIELD-AITEST.sh"
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)

    meta = {
        "schema": SCHEMA, "package_kind": "LINUX_X86_64_FIELD_VALIDATION",
        "package_name": NAME, "source_commit": source_commit,
        "target_baseline": "Ubuntu 22.04 x86_64, glibc >= 2.35",
        "platform": "linux", "architecture": "x86_64",
        "package_local_python": "workspace-template/runtime/python/bin/python3",
        "package_local_node": "workspace-template/runtime/node/bin/node",
        "browserskill_version": "0.4.1",
        "required_entrypoints": list(REQUIRED),
        "dsh_main_payload": {
            "bundled": False, "mode": "EXPLICIT_TARGET_HOST_BINDING",
            "host_path_env": "PFC_RC72_DSH_LINUX_HOST_BIN",
            "optional_sha256_env": "PFC_RC72_DSH_LINUX_HOST_SHA256",
            "bank_authorization_verified": False,
        },
        "restricted_graph_component": {
            "gitnexus_bundled": False, "reason": "POLYFORM_NONCOMMERCIAL_LICENSE_GATE",
            "graph_features_verified": False,
        },
        "q3_target_linux_verified": False,
        "field_verified": False, "real_mission_pass": False, "bank_final": False,
        "qualification_scope": "LINUX_NATIVE_PAYLOAD_AND_SOURCE_CONSISTENCY",
    }
    for rel in REQUIRED:
        if rel not in ("LINUX_FIELD_PACKAGE.json", "CHECKSUMS.sha256") and not (root / rel).is_file():
            raise LinuxFieldTransportError("LINUX_REQUIRED_PAYLOAD_MISSING:" + rel)
    plugins = root / "rc7_release/vendor/dsh-plugins-payload.zip"
    if not plugins.is_file() or plugins.stat().st_size == 0:
        raise LinuxFieldTransportError("LINUX_DSH_PLUGIN_VENDOR_PAYLOAD_REQUIRED")
    meta["plugins_vendor_archive_sha256"] = digest(plugins)

    # Use native runtime and actually prove it is executable before sealing.
    versions = {}
    for name, args in {
        "python": [str(py), "-B", "-c", "import sys;print(sys.version.split()[0])"],
        "node": [str(node), "--version"],
        "browserskill": [str(bsk), "--version"],
    }.items():
        result = subprocess.run(args, cwd=str(root), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=60, check=False)
        if result.returncode:
            raise LinuxFieldTransportError("LINUX_NATIVE_RUNTIME_EXECUTION_FAILED:" + name)
        versions[name] = result.stdout.strip()
    if not versions["node"].startswith("v24."):
        raise LinuxFieldTransportError("LINUX_NODE24_REQUIRED")
    if "0.4.1" not in versions["browserskill"]:
        raise LinuxFieldTransportError("LINUX_BSK_041_REQUIRED")
    if not versions["python"].startswith("3.11."):
        raise LinuxFieldTransportError("LINUX_PYTHON311_REQUIRED")
    meta["native_runtime_versions"] = versions
    _write_seal(root, meta)
    verify_package(root, expected_source_commit=source_commit)
    return root


def verify_package(root: Path, expected_source_commit: Optional[str] = None) -> Dict[str, object]:
    root = Path(root).resolve()
    if not root.is_dir():
        raise LinuxFieldTransportError("LINUX_PACKAGE_ROOT_REQUIRED")
    try:
        meta = json.loads((root / "LINUX_FIELD_PACKAGE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise LinuxFieldTransportError("LINUX_METADATA_REQUIRED") from None
    source = require_commit((root / "SOURCE_COMMIT").read_text(encoding="utf-8").strip())
    if expected_source_commit and source != require_commit(expected_source_commit):
        raise LinuxFieldTransportError("LINUX_SOURCE_COMMIT_MISMATCH")
    if (meta.get("schema") != SCHEMA or meta.get("package_name") != NAME
            or meta.get("source_commit") != source
            or meta.get("platform") != "linux" or meta.get("architecture") != "x86_64"):
        raise LinuxFieldTransportError("LINUX_METADATA_IDENTITY_MISMATCH")
    if (meta.get("field_verified") is not False or meta.get("bank_final") is not False
            or meta.get("real_mission_pass") is not False or meta.get("q3_target_linux_verified") is not False):
        raise LinuxFieldTransportError("LINUX_FALSE_RELEASE_OR_FIELD_PASS_FORBIDDEN")
    if meta.get("dsh_main_payload", {}).get("bundled") is not False:
        raise LinuxFieldTransportError("LINUX_DSH_PAYLOAD_MUST_BE_EXTERNAL")
    if meta.get("restricted_graph_component", {}).get("gitnexus_bundled") is not False:
        raise LinuxFieldTransportError("LINUX_NONCOMMERCIAL_GRAPH_CANNOT_BE_SILENTLY_BUNDLED")
    for rel in REQUIRED:
        if not (root / rel).is_file():
            raise LinuxFieldTransportError("LINUX_REQUIRED_FILE_MISSING:" + rel)
    expected = {}
    for line in (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        if "  " not in line:
            raise LinuxFieldTransportError("LINUX_CHECKSUMS_MALFORMED")
        value, rel = line.split("  ", 1)
        p = Path(rel)
        if p.is_absolute() or ".." in p.parts or not HEX64.fullmatch(value):
            raise LinuxFieldTransportError("LINUX_CHECKSUM_PATH_INVALID")
        if rel in expected:
            raise LinuxFieldTransportError("LINUX_DUPLICATE_CHECKSUM_ENTRY")
        expected[rel] = value.lower()
    actual = {}
    for p in _files(root):
        rel = p.relative_to(root).as_posix()
        actual[rel] = digest(p)
    if actual != expected:
        diff = sorted(set(actual) ^ set(expected))
        mismatch = sorted(rel for rel in actual.keys() & expected.keys() if actual[rel] != expected[rel])
        raise LinuxFieldTransportError("LINUX_PACKAGE_INTEGRITY_MISMATCH:" + ",".join((diff + mismatch)[:8]))
    return {
        "status": "PASS", "schema": SCHEMA,
        "source_commit": source, "package_name": NAME,
        "file_count": len(expected), "checksum_coverage": "EXACT",
        "qualification_scope": "EXTRACTED_LINUX_FIELD_PACKAGE_INTEGRITY",
        "q3_target_linux_verified": False, "field_verified": False, "bank_final": False,
    }


def inspect_linux_dsh(executable: Path, expected_sha256: Optional[str] = None) -> Dict[str, object]:
    path = Path(executable).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise LinuxFieldTransportError("LINUX_DSH_HOST_ABSOLUTE_REGULAR_FILE_REQUIRED")
    if path.name != "dsh" or not os.access(str(path), os.X_OK):
        raise LinuxFieldTransportError("LINUX_DSH_HOST_EXECUTABLE_NAME_REQUIRED")
    with path.open("rb") as f:
        magic = f.read(4)
        if magic == b"\x7fELF":
            f.seek(4)
            if f.read(1) != b"\x02":
                raise LinuxFieldTransportError("LINUX_DSH_ELF64_REQUIRED")
            f.seek(18)
            if f.read(2) != b"\x3e\x00":
                raise LinuxFieldTransportError("LINUX_DSH_ELF_X86_64_REQUIRED")
            executable_kind = "ELF64_X86_64"
        elif magic[:2] == b"#!":
            executable_kind = "SHEBANG_SCRIPT"
        else:
            raise LinuxFieldTransportError("LINUX_DSH_NOT_EXECUTABLE_OR_SCRIPT")
    observed = digest(path)
    if expected_sha256 is not None:
        if not HEX64.fullmatch(expected_sha256):
            raise LinuxFieldTransportError("LINUX_DSH_EXPECTED_SHA256_INVALID")
        if observed != expected_sha256.lower():
            raise LinuxFieldTransportError("LINUX_DSH_EXPECTED_SHA256_MISMATCH")
    return {
        "status": "EXTERNAL_LINUX_HOST_DSH_OBSERVED",
        "executable_path": str(path.resolve()), "executable_kind": executable_kind,
        "sha256": observed, "expected_sha256_matched": expected_sha256 is not None,
        "bank_authorization_verified": False, "vendor_identity_verified": False,
        "field_verified": False, "bank_final": False,
    }


def build_archive(root: Path, archive_path: Path) -> str:
    root = Path(root).resolve()
    verify_package(root)
    archive_path = Path(archive_path).resolve()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(archive_path), "w:gz", compresslevel=5) as bundle:
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if any(part in GENERATED_DIRS for part in rel.parts) or path.suffix == ".pyc":
                continue
            bundle.add(str(path), arcname=(Path(root.name) / rel).as_posix(), recursive=False)
    checksum = digest(archive_path)
    Path(str(archive_path) + ".sha256").write_text(checksum + "  " + archive_path.name + "\n", encoding="utf-8")
    return checksum


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC7.2 native Linux x86_64 field-validation transport")
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage")
    stage.add_argument("--repo-root", required=True)
    stage.add_argument("--output", required=True)
    stage.add_argument("--source-commit", required=True)
    stage.add_argument("--python-root", required=True)
    stage.add_argument("--node-root", required=True)
    stage.add_argument("--bsk-cli", required=True)
    stage.add_argument("--browser-root", required=True)
    stage.add_argument("--extension-root", required=True)
    stage.add_argument("--node-execution-root", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--package-root", required=True)
    verify.add_argument("--expected-source-commit")
    archive = sub.add_parser("archive")
    archive.add_argument("--package-root", required=True)
    archive.add_argument("--output", required=True)
    binding = sub.add_parser("bind")
    binding.add_argument("--executable", required=True)
    binding.add_argument("--expected-sha256")
    binding.add_argument("--output")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "stage":
            root = stage_package(
                Path(args.repo_root), Path(args.output), args.source_commit,
                Path(args.python_root), Path(args.node_root), Path(args.bsk_cli),
                Path(args.browser_root), Path(args.extension_root), Path(args.node_execution_root),
            )
            result = {"status": "PASS", "package_root": str(root), "source_commit": args.source_commit,
                      "field_verified": False, "bank_final": False}
        elif args.command == "verify":
            result = verify_package(Path(args.package_root), args.expected_source_commit)
        elif args.command == "archive":
            checksum = build_archive(Path(args.package_root), Path(args.output))
            result = {"status": "PASS", "archive_sha256": checksum,
                      "archive": args.output, "field_verified": False, "bank_final": False}
        else:
            result = inspect_linux_dsh(Path(args.executable), args.expected_sha256)
            if args.output:
                dest = Path(args.output)
                if dest.is_symlink():
                    raise LinuxFieldTransportError("LINUX_DSH_RECEIPT_SYMLINK_FORBIDDEN")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, LinuxFieldTransportError) as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc), "field_verified": False,
                          "bank_final": False}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
