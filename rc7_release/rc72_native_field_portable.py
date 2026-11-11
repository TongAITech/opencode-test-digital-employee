"""Native Linux/macOS RC7.2 field package builder with strict platform separation."""
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
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

SCHEMA = "pfc.aitest.rc7.2.native-field.v1"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_DIRS = ("rc6_runtime", "rc6_release", "rc7_runtime", "rc7_release", "rc7_admin")
EXCLUDED_SUFFIXES = {".exe", ".dll", ".cmd", ".bat", ".ps1", ".msi", ".pdb"}
SEAL_FILES = {"NATIVE_FIELD_PACKAGE.json", "CHECKSUMS.sha256"}
GENERATED_DIRS = {"runtime-state", "state", "__pycache__", "qualification-evidence"}


class NativeFieldError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def target_identity() -> Dict[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if system not in {"linux", "darwin"} or arch is None:
        raise NativeFieldError("NATIVE_TARGET_UNSUPPORTED:%s:%s" % (system, machine))
    if system == "linux" and arch not in {"x86_64", "arm64"}:
        raise NativeFieldError("LINUX_ARCH_UNSUPPORTED")
    if system == "darwin" and arch not in {"x86_64", "arm64"}:
        raise NativeFieldError("MACOS_ARCH_UNSUPPORTED")
    suffix = "LINUX" if system == "linux" else "MACOS"
    return {
        "platform": system,
        "architecture": arch,
        "package_name": "PFC-AITest-DSH-RC7.2-%s-%s-FIELD" % (suffix, arch.upper()),
        "target_baseline": "glibc >= 2.28; kernel >= 4.18; native ELF64" if system == "linux" else "macOS >= 14.0; native Mach-O 64-bit",
    }


def _check_host(identity: Dict[str, str]) -> None:
    actual = target_identity()
    if actual != identity:
        raise NativeFieldError("NATIVE_BUILD_HOST_TARGET_MISMATCH")


def _copy_tree(src: Path, dst: Path) -> None:
    from rc7_release.package import _copy_tree as copy_source
    if not src.is_dir():
        raise NativeFieldError("SOURCE_DIR_MISSING:" + str(src))
    copy_source(src, dst)


def _copy_runtime(src: Path, dst: Path) -> None:
    if not src.is_dir() or src.is_symlink():
        raise NativeFieldError("NATIVE_RUNTIME_SOURCE_REQUIRED:" + str(src))
    if dst.exists():
        raise NativeFieldError("NATIVE_RUNTIME_TARGET_EXISTS:" + str(dst))
    shutil.copytree(str(src), str(dst), symlinks=False)


def _copy_packaging(repo: Path, root: Path) -> None:
    # Only POSIX launchers, runtime source, and the native README are copied.
    allow_suffixes = {".sh", ".py", ".xml"}
    for folder in ("packaging/rc7.2",):
        source = repo / folder
        if not source.is_dir():
            continue
        for item in sorted(source.rglob("*")):
            if not item.is_file() or item.suffix.lower() not in allow_suffixes:
                continue
            if item.name.lower() == "aitest.sh":
                continue  # Replace the Windows/Git-Bash launcher with native AITEST.sh.
            relative = item.relative_to(repo)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(item), str(target))


def _write_seal(root: Path, metadata: Dict[str, object]) -> None:
    (root / "NATIVE_FIELD_PACKAGE.json").write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    lines = []
    for path in _files(root):
        lines.append(sha256(path) + "  " + path.relative_to(root).as_posix())
    (root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _files(root: Path) -> List[Path]:
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or path.name in SEAL_FILES:
            continue
        if any(part in GENERATED_DIRS for part in relative.parts) or path.suffix == ".pyc":
            continue
        result.append(path)
    return result


def _native_binary_check(path: Path, system: str, arch: str) -> None:
    if not path.is_file() or not os.access(str(path), os.X_OK):
        raise NativeFieldError("NATIVE_EXECUTABLE_REQUIRED:" + str(path))
    with path.open("rb") as stream:
        head = stream.read(4096)
    if system == "linux":
        if head[:4] != b"\x7fELF" or len(head) < 20 or head[4] != 2:
            raise NativeFieldError("LINUX_ELF64_REQUIRED:" + str(path))
        machine = int.from_bytes(head[18:20], "little")
        expected = 62 if arch == "x86_64" else 183
        if machine != expected:
            raise NativeFieldError("LINUX_ELF_ARCH_MISMATCH:" + str(path))
    else:
        if head[:4] in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"}:
            endian = "little" if head[:4] == b"\xcf\xfa\xed\xfe" else "big"
            cpu = int.from_bytes(head[4:8], endian)
            expected = 0x01000007 if arch == "x86_64" else 0x0100000c
            if cpu != expected:
                raise NativeFieldError("MACOS_MACHO_ARCH_MISMATCH:" + str(path))
        elif head[:4] in {b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}:
            result = subprocess.run(["lipo", "-archs", str(path)], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, timeout=30, check=False)
            if result.returncode or arch not in result.stdout.split():
                raise NativeFieldError("MACOS_FAT_MACHO_ARCH_MISMATCH:" + str(path))
        else:
            raise NativeFieldError("MACOS_MACHO_REQUIRED:" + str(path))


def _check_no_windows_payload(root: Path) -> None:
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            raise NativeFieldError("WINDOWS_PAYLOAD_IN_NATIVE_PACKAGE:" + relative)
        try:
            with path.open("rb") as stream:
                if stream.read(2) == b"MZ":
                    raise NativeFieldError("WINDOWS_PE_PAYLOAD_IN_NATIVE_PACKAGE:" + relative)
            if path.suffix.lower() == ".zip":
                with zipfile.ZipFile(str(path), "r") as archive:
                    for member in archive.namelist():
                        if Path(member).suffix.lower() in EXCLUDED_SUFFIXES:
                            raise NativeFieldError("WINDOWS_ARCHIVE_MEMBER_IN_NATIVE_PACKAGE:%s:%s" % (relative, member))
        except NativeFieldError:
            raise
        except (OSError, zipfile.BadZipFile) as exc:
            raise NativeFieldError("NATIVE_FILE_READ_FAILED:" + str(path)) from exc


def stage_package(
    repo_root: Path,
    output_dir: Path,
    source_commit: str,
    python_root: Path,
    node_root: Path,
    bsk_cli: Path,
    browser_root: Path,
    extension_root: Path,
    node_execution_root: Path,
    java_root: Path,
    maven_root: Path,
    maven_repository: Path,
    allure_root: Path,
    k6_binary: Path,
    zap_root: Path,
    ripgrep_binary: Path,
    codegraph_binary: Path,
) -> Path:
    identity = target_identity()
    _check_host(identity)
    commit = str(source_commit or "").strip().lower()
    if not COMMIT_RE.fullmatch(commit):
        raise NativeFieldError("SOURCE_COMMIT_INVALID")
    repo = Path(repo_root).resolve()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = out / identity["package_name"]
    if root.exists():
        raise NativeFieldError("NATIVE_STAGE_MUST_BE_FRESH")
    root.mkdir()

    for name in SOURCE_DIRS:
        _copy_tree(repo / name, root / name)
    _copy_packaging(repo, root)
    coordinator = repo / "packaging/rc6/.dsh/skills/pfc-full-chain-test"
    _copy_tree(coordinator, root / ".dsh/skills/pfc-full-chain-test")
    from rc6_release.static_skills import materialize_professional_skills
    materialize_professional_skills(root)

    baseline = repo / "docs/RC7_ACCEPTANCE_BASELINE.md"
    if baseline.is_file():
        shutil.copy2(str(baseline), str(root / "RC7_ACCEPTANCE_BASELINE.md"))

    runtime = root / "workspace-template/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    _copy_runtime(Path(python_root).resolve(), runtime / "python")
    _copy_runtime(Path(node_root).resolve(), runtime / "node")
    _copy_runtime(Path(browser_root).resolve(), runtime / "browser/pw-browsers")
    _copy_runtime(Path(extension_root).resolve(), runtime / "browser/browserskill-extension")
    _copy_runtime(Path(node_execution_root).resolve(), runtime / "node-execution")
    _copy_runtime(Path(java_root).resolve(), runtime / "java")
    _copy_runtime(Path(maven_root).resolve(), runtime / "maven")
    _copy_runtime(Path(maven_repository).resolve(), runtime / "maven-repository")
    _copy_runtime(Path(allure_root).resolve(), runtime / "allure")
    _copy_runtime(Path(zap_root).resolve(), runtime / "zap")

    def copy_executable(source: Path, target: Path) -> None:
        source = Path(source).resolve()
        if not source.is_file() or source.is_symlink() or not os.access(str(source), os.X_OK):
            raise NativeFieldError("NATIVE_TOOL_EXECUTABLE_REQUIRED:" + str(source))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))
        target.chmod(target.stat().st_mode | stat.S_IXUSR)

    suffix = "linux-x64" if identity["platform"] == "linux" and identity["architecture"] == "x86_64" else \
             "linux-arm64" if identity["platform"] == "linux" else \
             "darwin-x64" if identity["architecture"] == "x86_64" else "darwin-arm64"
    codegraph_name = "codegraph-server-" + suffix
    copy_executable(Path(bsk_cli), runtime / "browser/browserskill/bsk")
    copy_executable(Path(k6_binary), runtime / "k6/k6")
    copy_executable(Path(ripgrep_binary), runtime / "ripgrep/rg")
    copy_executable(Path(codegraph_binary), runtime / ("code-intelligence/codegraph/" + codegraph_name))

    python_bin = runtime / "python/bin/python3"
    node_bin = runtime / "node/bin/node"
    java_bin = runtime / "java/bin/java"
    maven_bin = runtime / "maven/bin/mvn"
    allure_bin = runtime / "allure/bin/allure"
    zap_candidates = list((runtime / "zap").rglob("zap.sh"))
    if len(zap_candidates) != 1:
        raise NativeFieldError("ZAP_NATIVE_LAUNCHER_NOT_UNIQUE")
    zap_bin = zap_candidates[0]
    for path in (python_bin, node_bin, java_bin, maven_bin, allure_bin, zap_bin):
        if not path.is_file() or not os.access(str(path), os.X_OK):
            raise NativeFieldError("NATIVE_REQUIRED_RUNTIME_MISSING:" + str(path))
    for path in (python_bin, node_bin, java_bin):
        _native_binary_check(path, identity["platform"], identity["architecture"])
    python_lock = runtime / "python/PACKAGE-PYTHON-LOCK.txt"
    freeze = subprocess.run([str(python_bin), "-B", "-m", "pip", "freeze"],
                            cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=120, check=False)
    if freeze.returncode:
        raise NativeFieldError("NATIVE_PYTHON_FREEZE_FAILED")
    python_lock.write_text(freeze.stdout, encoding="utf-8")
    for path in (runtime / "browser/browserskill/bsk", runtime / "k6/k6",
                 runtime / "ripgrep/rg", runtime / ("code-intelligence/codegraph/" + codegraph_name)):
        _native_binary_check(path, identity["platform"], identity["architecture"])

    settings_src = repo / "packaging/rc7/maven-offline-settings.xml"
    if not settings_src.is_file():
        raise NativeFieldError("MAVEN_OFFLINE_SETTINGS_MISSING")
    settings_target = root / "packaging/rc7/maven-offline-settings.xml"
    settings_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(settings_src), str(settings_target))

    native_launcher = repo / "packaging/rc7.2/NATIVE-FIELD-AITEST.sh"
    if not native_launcher.is_file():
        raise NativeFieldError("NATIVE_FIELD_LAUNCHER_SOURCE_MISSING")
    launcher_target = root / "packaging/rc7.2/AITEST.sh"
    launcher_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(native_launcher), str(launcher_target))
    launcher_target.chmod(launcher_target.stat().st_mode | stat.S_IXUSR)
    start_source = repo / "packaging/rc7.2/start-rc7.2.sh"
    if not start_source.is_file():
        raise NativeFieldError("NATIVE_START_SCRIPT_SOURCE_MISSING")
    start_target = root / "start-rc7.2.sh"
    shutil.copy2(str(start_source), str(start_target))
    start_target.chmod(start_target.stat().st_mode | stat.S_IXUSR)
    readme = repo / "packaging/rc7.2/NATIVE-FIELD-README.md"
    shutil.copy2(str(readme), str(root / "README-FIRST.md"))

    source_marker = root / "SOURCE_COMMIT"
    source_marker.write_text(commit + "\n", encoding="utf-8")
    (root / "BUILD_ID").write_text("RC7.2-NATIVE-" + commit[:12] + "\n", encoding="utf-8")
    alpha_manifest = {
        "plugin": "dsh-alpha",
        "upstream": "https://github.com/songofhawk/dsh-alpha",
        "version": "0.2.2",
        "source_commit": "f417e90ddd0e20f08b82e0b79a8c29fdad45c8f4",
        "status": "LICENSE_HOLD_NOT_BUNDLED",
        "reason": "Upstream repository has no declared license; commercial redistribution permission is not established.",
        "installer": "packaging/rc7.2/dsh-alpha/install-dsh-alpha.sh",
        "required_before_install": ["commercial_use_authorized", "redistribution_authorized", "authorization_reference"],
    }
    alpha_dir = root / "packaging/rc7.2/dsh-alpha"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    (alpha_dir / "PAYLOAD-STATUS.json").write_text(
        json.dumps(alpha_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    for alpha_file in ("README.md", "install-dsh-alpha.sh"):
        alpha_source = repo / "packaging/rc7.2/dsh-alpha" / alpha_file
        if not alpha_source.is_file():
            raise NativeFieldError("DSH_ALPHA_INSTALLER_CONTRACT_MISSING:" + alpha_file)
        shutil.copy2(str(alpha_source), str(alpha_dir / alpha_file))
    (alpha_dir / "install-dsh-alpha.sh").chmod(
        (alpha_dir / "install-dsh-alpha.sh").stat().st_mode | stat.S_IXUSR
    )

    metadata = {
        "schema": SCHEMA,
        "status": "NATIVE_FIELD_CANDIDATE",
        **identity,
        "source_commit": commit,
        "build_id": "RC7.2-NATIVE-" + commit[:12],
        "runtimes": {
            "python": "workspace-template/runtime/python/bin/python3",
            "node": "workspace-template/runtime/node/bin/node",
            "browserskill": "workspace-template/runtime/browser/browserskill/bsk",
            "playwright": "workspace-template/runtime/node-execution/node_modules/playwright/package.json",
            "chromium_root": "workspace-template/runtime/browser/pw-browsers",
            "java": "workspace-template/runtime/java/bin/java",
            "maven": "workspace-template/runtime/maven/bin/mvn",
            "allure": "workspace-template/runtime/allure/bin/allure",
            "k6": "workspace-template/runtime/k6/k6",
            "zap": str(zap_bin.relative_to(root).as_posix()),
            "ripgrep": "workspace-template/runtime/ripgrep/rg",
            "codegraph": "workspace-template/runtime/" + ("code-intelligence/codegraph/" + codegraph_name),
            "maven_repository": "workspace-template/runtime/maven-repository",
        },
        "browser_skill": {"cli": "0.4.1", "extension": "0.4.1"},
        "tool_versions": json.loads(os.environ.get("PFC_RC72_TOOL_VERSIONS_JSON", "{}")),
        "dsh_plugins": {
            "core_payload": "rc7_release/vendor/dsh-plugins-payload.zip",
            "dsh_alpha": alpha_manifest,
        },
        "restricted_graph_component": {
            "gitnexus_bundled": False,
            "reason": "POLYFORM_NONCOMMERCIAL_LICENSE_GATE",
        },
        "field_verified": False,
        "bank_final": False,
        "real_mission_pass": False,
        "q3_target_verified": False,
        "system_prerequisites": {
            "linux": ["glibc >= 2.28", "kernel >= 4.18", "Chromium shared libraries; see README"],
            "darwin": ["macOS >= 14.0"],
        }[identity["platform"]],
    }
    if not (root / "rc7_release/vendor/dsh-plugins-payload.zip").is_file():
        raise NativeFieldError("REQUIRED_DSH_PLUGIN_VENDOR_ARCHIVE_MISSING")
    _check_no_windows_payload(root)
    _write_seal(root, metadata)
    verify_package(root, expected_source_commit=commit)
    return root


def verify_package(root: Path, expected_source_commit: Optional[str] = None) -> Dict[str, object]:
    root = Path(root).resolve()
    if not root.is_dir():
        raise NativeFieldError("NATIVE_PACKAGE_ROOT_REQUIRED")
    metadata_path = root / "NATIVE_FIELD_PACKAGE.json"
    if not metadata_path.is_file():
        raise NativeFieldError("NATIVE_PACKAGE_METADATA_REQUIRED")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    platform_name = str(metadata.get("platform") or "")
    arch = str(metadata.get("architecture") or "")
    expected_name = "PFC-AITest-DSH-RC7.2-%s-%s-FIELD" % ("LINUX" if platform_name == "linux" else "MACOS", arch.upper())
    if metadata.get("schema") != SCHEMA or metadata.get("package_name") != expected_name or root.name != expected_name:
        raise NativeFieldError("NATIVE_PACKAGE_IDENTITY_MISMATCH")
    commit = str((root / "SOURCE_COMMIT").read_text(encoding="utf-8")).strip().lower()
    if not COMMIT_RE.fullmatch(commit) or metadata.get("source_commit") != commit:
        raise NativeFieldError("NATIVE_SOURCE_COMMIT_INVALID")
    if expected_source_commit and commit != expected_source_commit.lower():
        raise NativeFieldError("NATIVE_SOURCE_COMMIT_MISMATCH")
    for key in ("field_verified", "bank_final", "real_mission_pass", "q3_target_verified"):
        if metadata.get(key) is not False:
            raise NativeFieldError("NATIVE_FALSE_PASS_FORBIDDEN:" + key)
    if metadata.get("dsh_plugins", {}).get("dsh_alpha", {}).get("status") != "LICENSE_HOLD_NOT_BUNDLED":
        raise NativeFieldError("DSH_ALPHA_LICENSE_GATE_MUST_REMAIN_VISIBLE")

    required = [
        "SOURCE_COMMIT", "BUILD_ID", "README-FIRST.md", "start-rc7.2.sh",
        "packaging/rc7.2/AITEST.sh", "packaging/rc7.2/NATIVE-FIELD-AITEST.sh",
        "packaging/rc7.2/dsh-alpha/PAYLOAD-STATUS.json",
        "packaging/rc7.2/dsh-alpha/install-dsh-alpha.sh",
        "workspace-template/runtime/python/bin/python3",
        "workspace-template/runtime/node/bin/node",
        "workspace-template/runtime/browser/browserskill/bsk",
        "workspace-template/runtime/browser/browserskill-extension/manifest.json",
        "workspace-template/runtime/node-execution/node_modules/playwright/package.json",
        "workspace-template/runtime/node-execution/package-lock.json",
        "workspace-template/runtime/python/PACKAGE-PYTHON-LOCK.txt",
        "workspace-template/runtime/code-intelligence/codegraph/" + ("codegraph-server-linux-x64" if platform_name == "linux" and arch == "x86_64" else "codegraph-server-linux-arm64" if platform_name == "linux" else "codegraph-server-darwin-x64" if arch == "x86_64" else "codegraph-server-darwin-arm64"),
        "workspace-template/runtime/k6/k6",
        "workspace-template/runtime/ripgrep/rg",
        "workspace-template/runtime/java/bin/java",
        "workspace-template/runtime/maven/bin/mvn",
        "workspace-template/runtime/allure/bin/allure",
        "workspace-template/runtime/maven-repository",
        "rc7_release/vendor/dsh-plugins-payload.zip",
    ]
    for rel in required:
        if not (root / rel).exists():
            raise NativeFieldError("NATIVE_REQUIRED_PATH_MISSING:" + rel)
    zap_scripts = list((root / "workspace-template/runtime/zap").rglob("zap.sh"))
    if len(zap_scripts) != 1:
        raise NativeFieldError("NATIVE_ZAP_LAUNCHER_NOT_UNIQUE")
    _check_no_windows_payload(root)

    checksums = {}
    for line in (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        if "  " not in line:
            raise NativeFieldError("NATIVE_CHECKSUM_FORMAT_INVALID")
        digest, relative = line.split("  ", 1)
        if not HEX_RE.fullmatch(digest) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise NativeFieldError("NATIVE_CHECKSUM_ENTRY_INVALID")
        if relative in checksums:
            raise NativeFieldError("NATIVE_CHECKSUM_DUPLICATE")
        checksums[relative] = digest
    actual = {p.relative_to(root).as_posix(): sha256(p) for p in _files(root)}
    if actual != checksums:
        raise NativeFieldError("NATIVE_CHECKSUM_COVERAGE_MISMATCH")
    return {
        "status": "PASS",
        "package_name": expected_name,
        "source_commit": commit,
        "platform": platform_name,
        "architecture": arch,
        "file_count": len(actual),
        "checksum_coverage": "EXACT",
        "windows_payload_count": 0,
        "field_verified": False,
        "bank_final": False,
    }


def build_archive(root: Path, output: Path) -> Dict[str, str]:
    root = Path(root).resolve()
    verify_package(root)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(output), "w:gz", compresslevel=5) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.add(str(path), arcname=(Path(root.name) / path.relative_to(root)).as_posix(), recursive=False)
    digest = sha256(output)
    Path(str(output) + ".sha256").write_text(digest + "  " + output.name + "\n", encoding="utf-8")
    return {"status": "PASS", "archive": str(output), "sha256": digest, "size": str(output.stat().st_size)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC7.2 native Linux/macOS field package")
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage")
    for name in ("repo-root", "output", "source-commit", "python-root", "node-root", "bsk-cli",
                 "browser-root", "extension-root", "node-execution-root", "java-root", "maven-root",
                 "maven-repository", "allure-root", "k6-binary", "zap-root", "ripgrep-binary", "codegraph-binary"):
        stage.add_argument("--" + name, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--package-root", required=True)
    verify.add_argument("--expected-source-commit")
    archive = sub.add_parser("archive")
    archive.add_argument("--package-root", required=True)
    archive.add_argument("--output", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "stage":
            identity = target_identity()
            _check_host(identity)
            root = stage_package(
                Path(args.repo_root), Path(args.output), args.source_commit,
                Path(args.python_root), Path(args.node_root), Path(args.bsk_cli),
                Path(args.browser_root), Path(args.extension_root), Path(args.node_execution_root),
                Path(args.java_root), Path(args.maven_root), Path(args.maven_repository),
                Path(args.allure_root), Path(args.k6_binary), Path(args.zap_root),
                Path(args.ripgrep_binary), Path(args.codegraph_binary),
            )
            result = {"status": "PASS", "package_root": str(root), "package_name": identity["package_name"],
                      "source_commit": args.source_commit, "field_verified": False, "bank_final": False}
        elif args.command == "verify":
            result = verify_package(Path(args.package_root), args.expected_source_commit)
        else:
            result = build_archive(Path(args.package_root), Path(args.output))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, NativeFieldError) as exc:
        print(json.dumps({"status": "HOLD", "reason": str(exc), "field_verified": False, "bank_final": False},
                         ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
