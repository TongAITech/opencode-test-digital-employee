"""Build a reproducible, platform-specific, offline DSH extension bundle.

Build-time network access is allowed. The resulting bank-side bundle contains
all npm runtime dependencies and the matching Mnemon native Memory CLI; bank
installation never invokes a public registry or downloads a binary.
Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
OUTER_NAME = {
    "win32-x64": "RC72-DSH-ECOSYSTEM-WINDOWS-X64",
    "linux-x64": "RC72-DSH-ECOSYSTEM-LINUX-X64",
}
PLUGINS = (
    {
        "id": "dsh-skills-manager",
        "package": "@michengai/dsh-skills-manager",
        "version": "1.4.1",
        "repository": "https://github.com/MichengAI/dsh-skills-manager",
        "source_commit": "c289281e1728d95e36998265c3b9e5d634cf6b44",
        "license": "Apache-2.0",
        "kind": "DSH_PLUGIN",
        "dsh_range": ">=0.2.0-rc.1 <0.3.0-0",
        "required_files": ("lib/index.js", "cordis.patch.yml", "LICENSE"),
    },
    {
        "id": "dsh-mnemon",
        "package": "dsh-mnemon",
        "version": "0.5.43",
        "repository": "https://github.com/omdsh-dev/dsh-mnemon",
        "source_commit": "e9da7d1d717737defc088ac9afd32c4ca99ff9ef",
        "license": "MIT",
        "kind": "DSH_PLUGIN",
        "dsh_range": ">=0.2.0-rc.2 <0.2.1-0 || >=0.2.1-rc.1 <0.3.0-0",
        "required_files": ("lib/index.js", "cordis.patch.yml", "LICENSE", "THIRD_PARTY_NOTICES.md"),
    },
    {
        "id": "dsh-archify",
        "package": "dsh-archify",
        "version": "0.1.0",
        "repository": "https://github.com/GongYuanCaiJi/dsh-archify",
        "source_commit": "8fc7ba557981af978578e2dd13e6c6ad8df53a7d",
        "license": "MIT",
        "kind": "DSH_PLUGIN_AND_SKILL",
        "dsh_range": "README tested DSH 0.1.0-rc.6; package declares no engines.dsh; actual host load probe required",
        "required_files": ("lib/index.js", "cordis.patch.yml", "LICENSE", "THIRD_PARTY_NOTICES.md", "skills/archify/SKILL.md"),
    },
    {
        "id": "modlens",
        "package": "@liustack/modlens",
        "version": "3.27.3",
        "repository": "https://github.com/liustack/modlens",
        "source_commit": "804f2193ef39e9cbe68c0e23d0701141f440a344",
        "license": "MIT",
        "kind": "DSH_PLUGIN_AND_SKILL",
        "dsh_range": "DSH developer preview; package declares no engines.dsh; actual host load probe required",
        "required_files": ("dsh/index.js", "dist/main.js", "cordis.patch.yml", "LICENSE", "skills/modlens/SKILL.md"),
    },
)
MNEMON_CLI = {
    "version": "0.2.9",
    "repository": "https://github.com/mnemon-dev/mnemon",
    "release_tag": "v0.2.9",
    "source_commit": "b0661c0bcdb8e7c08e9239b6942118e18dd288ad",
    "checksums_asset_sha256": "83426afb6b9530998cf97d2f11900c30de9bf92d4bbba9ff8adc5eaa6adcc127",
    "assets": {
        "win32-x64": {
            "name": "mnemon_0.2.9_windows_amd64.zip",
            "sha256": "13b98293b024792456b0817f8ea41251d5986f51fe484ea5d92f9df63c55c825",
            "url": "https://github.com/mnemon-dev/mnemon/releases/download/v0.2.9/mnemon_0.2.9_windows_amd64.zip",
            "binary": "mnemon.exe",
        },
        "linux-x64": {
            "name": "mnemon_0.2.9_linux_amd64.tar.gz",
            "sha256": "5d2b63d991fca5d4b310751d1497f67fd2b446ea7b8409144cd31762494b394c",
            "url": "https://github.com/mnemon-dev/mnemon/releases/download/v0.2.9/mnemon_0.2.9_linux_amd64.tar.gz",
            "binary": "mnemon",
        },
    },
    "license": "Apache-2.0",
}
CHECKSUMS_URL = "https://github.com/mnemon-dev/mnemon/releases/download/v0.2.9/checksums.txt"
CHECKSUMS_SHA256 = MNEMON_CLI["checksums_asset_sha256"]


class BundleBuildError(RuntimeError):
    pass


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _download(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": "RC7.2-offline-ecosystem-builder"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
    except Exception as exc:
        raise BundleBuildError("BUILD_TIME_DOWNLOAD_FAILED:%s" % url) from exc
    Path(destination).write_bytes(data)
    return data


def _npm():
    for name in ("npm.cmd", "npm", "npm.exe"):
        found = shutil.which(name)
        if found:
            return found
    raise BundleBuildError("NPM_REQUIRED_ON_BUILD_HOST")


def _run(command, cwd=None, timeout=900):
    try:
        proc = subprocess.run(
            [str(x) for x in command], cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, check=False,
        )
    except Exception as exc:
        raise BundleBuildError("BUILD_COMMAND_COULD_NOT_START:%s" % command[0]) from exc
    output = (proc.stdout or b"").decode("utf-8", errors="replace")
    if proc.returncode:
        raise BundleBuildError("BUILD_COMMAND_FAILED:%s:%s" % (command[0], output[-1800:]))
    return output


def _safe_extract_npm(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(archive), "r:gz") as tar:
        for member in tar.getmembers():
            name = PurePosixPath(member.name)
            if not name.parts or name.parts[0] != "package":
                continue
            if member.issym() or member.islnk() or not member.isfile():
                continue
            relative = PurePosixPath(*name.parts[1:])
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                raise BundleBuildError("UNSAFE_NPM_TARBALL_ENTRY")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _license_files(package_root):
    names = ("license", "licence", "copying", "notice")
    return sorted(
        p for p in package_root.iterdir()
        if p.is_file() and any(p.name.lower().startswith(name) for name in names)
    )


def _scan_licenses(package_root):
    rows = []
    unresolved = []
    package_jsons = sorted(package_root.rglob("package.json"))
    for manifest_path in package_jsons:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            unresolved.append(str(manifest_path.relative_to(package_root)))
            continue
        name = manifest.get("name")
        version = manifest.get("version")
        if not name or not version:
            continue
        package_dir = manifest_path.parent
        license_value = manifest.get("license")
        license_files = _license_files(package_dir)
        if not license_value and not license_files:
            unresolved.append("%s@%s" % (name, version))
        rows.append({
            "name": name,
            "version": version,
            "license": license_value or "LicenseRef-File",
            "package_json_sha256": _sha256_file(manifest_path),
            "license_files": [
                {"path": p.name, "sha256": _sha256_file(p)}
                for p in license_files
            ],
            "package_path": str(package_dir.relative_to(package_root)).replace("\\", "/"),
        })
    if unresolved:
        raise BundleBuildError("UNRESOLVED_THIRD_PARTY_LICENSES:%s" % ",".join(unresolved[:20]))
    return rows


def _pack_plugin(npm, spec, target, work):
    package_spec = "%s@%s" % (spec["package"], spec["version"])
    pack_dir = Path(work) / ("pack-" + spec["id"])
    pack_dir.mkdir(parents=True, exist_ok=True)
    output = _run([
        npm, "pack", package_spec, "--json", "--ignore-scripts",
        "--pack-destination", str(pack_dir),
    ], timeout=600)
    try:
        row = json.loads(output)[-1]
        archive = pack_dir / row["filename"]
    except Exception as exc:
        raise BundleBuildError("NPM_PACK_RESULT_INVALID:%s" % spec["id"]) from exc
    if not archive.is_file():
        raise BundleBuildError("NPM_PACK_FILE_MISSING:%s" % spec["id"])
    target = Path(target)
    _safe_extract_npm(archive, target)
    manifest_path = target / "package.json"
    if not manifest_path.is_file():
        raise BundleBuildError("PLUGIN_PACKAGE_JSON_MISSING:%s" % spec["id"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("name") != spec["package"] or manifest.get("version") != spec["version"]:
        raise BundleBuildError("PLUGIN_IDENTITY_MISMATCH:%s" % spec["id"])
    if manifest.get("license") != spec["license"]:
        raise BundleBuildError("PLUGIN_LICENSE_MISMATCH:%s" % spec["id"])
    for relative in spec["required_files"]:
        if not (target / relative).is_file():
            raise BundleBuildError("PLUGIN_REQUIRED_FILE_MISSING:%s:%s" % (spec["id"], relative))
    _run([
        npm, "install", "--omit=dev", "--ignore-scripts",
        "--legacy-peer-deps", "--no-audit", "--no-fund",
        "--package-lock=true", "--prefer-offline",
    ], cwd=target, timeout=1800)
    lock = target / "package-lock.json"
    if not lock.is_file():
        raise BundleBuildError("PLUGIN_DEPENDENCY_LOCK_MISSING:%s" % spec["id"])
    licenses = _scan_licenses(target)
    return {
        "id": spec["id"],
        "package": spec["package"],
        "version": spec["version"],
        "repository": spec["repository"],
        "source_commit": spec["source_commit"],
        "license": spec["license"],
        "kind": spec["kind"],
        "dsh_range": spec["dsh_range"],
        "engines": manifest.get("engines") or {},
        "peer_dependencies": manifest.get("peerDependencies") or {},
        "npm_tarball_integrity": row.get("integrity"),
        "npm_tarball_shasum": row.get("shasum"),
        "package_json_sha256": _sha256_file(manifest_path),
        "package_lock_sha256": _sha256_file(lock),
        "runtime_dependency_count": len(manifest.get("dependencies") or {}),
        "license_inventory": licenses,
    }


def _extract_mnemon_cli(asset, destination, checksums_text):
    row = asset["name"]
    matches = [line.split(None, 1) for line in checksums_text.splitlines()
               if line.strip() and line.strip().endswith(row)]
    if len(matches) != 1 or len(matches[0]) != 2:
        raise BundleBuildError("MNEMON_RELEASE_CHECKSUM_ROW_MISSING")
    if matches[0][0].lower() != asset["sha256"]:
        raise BundleBuildError("MNEMON_RELEASE_CHECKSUMS_FILE_MISMATCH")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rc72-mnemon-cli-") as temp:
        archive = Path(temp) / asset["name"]
        data = _download(asset["url"], archive)
        if _sha256_bytes(data) != asset["sha256"]:
            raise BundleBuildError("MNEMON_NATIVE_BINARY_SHA256_MISMATCH")
        if asset["name"].endswith(".zip"):
            with zipfile.ZipFile(str(archive)) as zf:
                candidates = [x for x in zf.infolist()
                              if PurePosixPath(x.filename).name == asset["binary"] and not x.is_dir()]
                if len(candidates) != 1:
                    raise BundleBuildError("MNEMON_WINDOWS_BINARY_ENTRY_AMBIGUOUS")
                member = candidates[0]
                if ".." in PurePosixPath(member.filename).parts:
                    raise BundleBuildError("MNEMON_WINDOWS_BINARY_PATH_UNSAFE")
                destination.write_bytes(zf.read(member))
        else:
            with tarfile.open(str(archive), "r:gz") as tf:
                candidates = [x for x in tf.getmembers()
                              if PurePosixPath(x.name).name == asset["binary"] and x.isfile()]
                if len(candidates) != 1:
                    raise BundleBuildError("MNEMON_LINUX_BINARY_ENTRY_AMBIGUOUS")
                member = candidates[0]
                if ".." in PurePosixPath(member.name).parts:
                    raise BundleBuildError("MNEMON_LINUX_BINARY_PATH_UNSAFE")
                source = tf.extractfile(member)
                if source is None:
                    raise BundleBuildError("MNEMON_LINUX_BINARY_UNREADABLE")
                destination.write_bytes(source.read())
    if _sha256_file(destination) == "":
        raise BundleBuildError("MNEMON_BINARY_EMPTY")
    if asset["binary"].endswith(".exe"):
        data = destination.read_bytes()[:4096]
        if len(data) < 64 or data[:2] != b"MZ":
            raise BundleBuildError("MNEMON_WINDOWS_BINARY_NOT_PE")
        offset = int.from_bytes(data[60:64], "little")
        full = destination.read_bytes()
        if full[offset:offset + 4] != b"PE\0\0" or int.from_bytes(full[offset + 4:offset + 6], "little") != 0x8664:
            raise BundleBuildError("MNEMON_WINDOWS_BINARY_NOT_AMD64")
    else:
        data = destination.read_bytes()[:20]
        if len(data) < 20 or data[:4] != b"\x7fELF" or int.from_bytes(data[18:20], "little") != 62:
            raise BundleBuildError("MNEMON_LINUX_BINARY_NOT_X86_64")
        destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return _sha256_file(destination)


def _write_deterministic_zip(root, zip_path):
    root = Path(root)
    with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo((root.name + "/" + relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if os.access(str(path), os.X_OK) else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(platform_id, output_dir):
    if platform_id not in OUTER_NAME:
        raise BundleBuildError("UNSUPPORTED_PLATFORM")
    host_ok = (
        platform_id == "win32-x64" and os.name == "nt" and platform.machine().lower() in ("amd64", "x86_64")
    ) or (
        platform_id == "linux-x64" and os.name == "posix" and platform.system().lower() == "linux"
        and platform.machine().lower() in ("amd64", "x86_64")
    )
    if not host_ok:
        raise BundleBuildError("BUILD_HOST_PLATFORM_MISMATCH")
    npm = _npm()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    bundle_name = OUTER_NAME[platform_id]
    with tempfile.TemporaryDirectory(prefix="rc72-ecosystem-build-") as temp:
        stage = Path(temp) / bundle_name
        (stage / "packages").mkdir(parents=True)
        (stage / "runtime" / "mnemon").mkdir(parents=True)
        resolved = []
        for spec in PLUGINS:
            resolved.append(_pack_plugin(
                npm, spec, stage / "packages" / spec["id"], Path(temp) / "work"
            ))
        checksums_path = Path(temp) / "checksums.txt"
        checksums_data = _download(CHECKSUMS_URL, checksums_path)
        if _sha256_bytes(checksums_data) != CHECKSUMS_SHA256:
            raise BundleBuildError("MNEMON_RELEASE_CHECKSUMS_ASSET_SHA256_MISMATCH")
        asset = MNEMON_CLI["assets"][platform_id]
        native_name = asset["binary"]
        native_sha = _extract_mnemon_cli(
            asset, stage / "runtime" / "mnemon" / native_name,
            checksums_data.decode("utf-8", errors="strict"),
        )
        shutil.copy2(str(checksums_path), str(stage / "runtime" / "mnemon" / "checksums.txt"))
        for name in ("install.py", "README.md", "modlens-config.bank-template.json"):
            source = ROOT / "offline-ecosystem" / name
            if not source.is_file():
                raise BundleBuildError("OFFLINE_INSTALLER_SOURCE_MISSING:%s" % name)
            shutil.copy2(str(source), str(stage / name))
        manifest = {
            "schema_version": "pfc.rc72.dsh-ecosystem-offline.v1",
            "status": "BUILD_CANDIDATE_HOST_INSTALL_NOT_BANK_VERIFIED",
            "platform": platform_id,
            "source_repository": "TongAITech/opencode-test-digital-employee",
            "source_branch": "work/rc7.2",
            "source_commit": os.environ.get("GITHUB_SHA", "UNBOUND_LOCAL_BUILD"),
            "extensions": resolved,
            "mnemon_native_cli": {
                "version": MNEMON_CLI["version"],
                "repository": MNEMON_CLI["repository"],
                "release_tag": MNEMON_CLI["release_tag"],
                "source_commit": MNEMON_CLI["source_commit"],
                "license": MNEMON_CLI["license"],
                "asset": asset["name"],
                "sha256": native_sha,
                "path": "runtime/mnemon/" + native_name,
                "supported_architecture": "x86_64",
                "windows_scope": "Memory commands only; Agency unavailable on Windows",
            },
            "installation_policy": {
                "network_required_on_bank_host": False,
                "public_npm_pip_registry_on_bank_host": False,
                "profile_default": "rc7.2-bank",
                "protected_profile": "web",
                "protected_profile_mutation": False,
                "memory_truth_authority": "R1_EVENT_STREAM_ONLY",
                "modlens_default_provider": "openai_internal_endpoint_only",
                "modlens_local_cli_reuse": False,
                "mnemon_default_provider": "mnemon-native-local",
                "mnemon_auto_capture_default": False,
                "mnemon_self_evolution_default": False,
            },
            "explicit_exclusions": ["dsh-qa", "dsh-routing-suite", "WeKnora", "dsh-weknora"],
            "limitations": [
                "A bank DSH host is required and is not bundled.",
                "The bank DSH version must satisfy the manifest engine ranges.",
                "ModLens requires a bank-internal OpenAI-compatible multimodal endpoint before image reading.",
                "Real bank-host activation is not proved by this build workflow.",
            ],
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        packages = []
        for row in resolved:
            packages.append({
                "name": row["package"],
                "versionInfo": row["version"],
                "SPDXID": "SPDXRef-" + row["id"],
                "downloadLocation": row["repository"],
                "filesAnalyzed": False,
                "licenseConcluded": row["license"],
                "licenseDeclared": row["license"],
                "copyrightText": "NOASSERTION",
                "externalRefs": [{
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": "pkg:npm/%s@%s" % (row["package"].replace("@", "").replace("/", "%2f"), row["version"]),
                }],
            })
            for dep in row["license_inventory"]:
                if dep["name"] == row["package"] and dep["version"] == row["version"]:
                    continue
                packages.append({
                    "name": dep["name"],
                    "versionInfo": dep["version"],
                    "SPDXID": "SPDXRef-" + hashlib.sha256(
                        (dep["name"] + "@" + dep["version"] + dep["package_path"]).encode("utf-8")
                    ).hexdigest()[:20],
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                    "licenseConcluded": dep["license"],
                    "licenseDeclared": dep["license"],
                    "copyrightText": "NOASSERTION",
                })
        sbom = {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": bundle_name,
            "documentNamespace": "https://example.invalid/spdx/rc72/" + platform_id + "/" + manifest["source_commit"],
            "creationInfo": {"creators": ["Tool: rc72-dsh-ecosystem-builder"], "comment": "Generated from exact npm tarballs and pinned Mnemon CLI release."},
            "packages": packages,
        }
        (stage / "SBOM.spdx.json").write_text(
            json.dumps(sbom, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        license_lines = [
            "# Third-party licenses",
            "",
            "This inventory is generated from every bundled package.json and preserved license/notice file.",
            "Original LICENSE and THIRD_PARTY_NOTICES files remain inside each plugin package.",
            "",
        ]
        for row in resolved:
            license_lines.append("## %s@%s — %s" % (row["package"], row["version"], row["license"]))
            license_lines.append("")
            license_lines.append("Source: %s @ %s" % (row["repository"], row["source_commit"]))
            license_lines.append("")
            for dep in row["license_inventory"]:
                license_lines.append("- %s@%s — %s" % (dep["name"], dep["version"], dep["license"]))
        (stage / "LICENSES.md").write_text("\n".join(license_lines) + "\n", encoding="utf-8")
        zip_path = out / (bundle_name + ".zip")
        if zip_path.exists():
            raise BundleBuildError("REFUSE_OVERWRITE_EXISTING_BUNDLE")
        _write_deterministic_zip(stage, zip_path)
        digest = _sha256_file(zip_path)
        (Path(str(zip_path) + ".sha256")).write_text(
            "%s  %s\n" % (digest, zip_path.name), encoding="ascii"
        )
        return {
            "status": "BUILD_CANDIDATE",
            "platform": platform_id,
            "archive": str(zip_path),
            "sha256": digest,
            "bytes": zip_path.stat().st_size,
            "plugin_count": len(resolved),
            "mnemon_cli_sha256": native_sha,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build RC7.2 offline DSH ecosystem extension bundle")
    parser.add_argument("--platform", required=True, choices=sorted(OUTER_NAME))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    result = build(args.platform, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
