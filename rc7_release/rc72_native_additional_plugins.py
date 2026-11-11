"""Pinned, license-audited additional DSH plugin offline payload for RC7.2.

No network operation occurs at field installation. Build-time fetches run on
the exact runner OS/arch; all checks are fail-closed and produce a sidecar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

SCHEMA = "pfc.aitest.rc72.dsh-additional-plugins.v1"
ARCHIVE_REL = Path("rc7_release/vendor/dsh-additional-plugins-payload.zip")
MANIFEST_REL = Path("rc7_release/vendor/dsh-additional-plugins-payload.manifest.json")
PINNED_PACKAGES: Tuple[Tuple[str, str, str], ...] = (
    ("@michengai/dsh-skills-manager", "1.4.1", "Apache-2.0"),
    ("dsh-mnemon", "0.5.44", "MIT"),
    ("dsh-archify", "0.1.0", "MIT"),
    ("@liustack/modlens", "3.27.3", "MIT"),
    ("graph-memory", "1.6.0-beta.17", "MIT"),
)
GRAPH_REPO = "https://github.com/adoresever/graph-memory.git"
GRAPH_COMMIT = "5841b1987c3967998818764c9d4238add5f3aa7c"
WINDOWS_SUFFIXES = {".exe", ".dll", ".cmd", ".bat", ".ps1", ".msi", ".pdb"}


class AdditionalPluginError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for b in iter(lambda: stream.read(1048576), b""):
            h.update(b)
    return h.hexdigest()


def _run(cmd: Sequence[str], cwd: Optional[Path] = None, timeout: int = 420) -> str:
    result = subprocess.run(list(cmd), cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise AdditionalPluginError("PLUGIN_COMMAND_FAILED:%s:%s" % (" ".join(cmd), result.stdout[-1500:]))
    return result.stdout


def _package_dir(vendor: Path, name: str) -> Path:
    if name.startswith("@"):
        namespace, base = name.split("/", 1)
        return vendor / "node_modules" / namespace / base
    return vendor / "node_modules" / name


def _unpack_npm(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(archive), "r:gz") as source:
        for member in source:
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            if len(parts) < 2 or parts[0] != "package":
                continue
            rel = Path(*parts[1:])
            if rel.is_absolute() or ".." in rel.parts or rel.suffix.lower() in WINDOWS_SUFFIXES:
                if ".." in rel.parts or rel.is_absolute():
                    raise AdditionalPluginError("PLUGIN_ARCHIVE_UNSAFE_PATH")
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            obj = source.extractfile(member)
            if obj is None:
                raise AdditionalPluginError("PLUGIN_ARCHIVE_MEMBER_READ_FAIL")
            with obj, dest.open("wb") as dst:
                shutil.copyfileobj(obj, dst)
            dest.chmod(member.mode & 0o777)


def _clean_platform_shims(target: Path) -> None:
    for item in target.rglob("*"):
        if item.is_file() and (item.suffix.lower() in WINDOWS_SUFFIXES):
            item.unlink()
    for item in target.rglob("*"):
        if item.is_file():
            with item.open("rb") as stream:
                if stream.read(2) == b"MZ":
                    raise AdditionalPluginError("PLUGIN_WINDOWS_PE_PAYLOAD_FORBIDDEN:" + str(item))


def _npm_pack(npm: str, spec: str, cwd: Path) -> Tuple[Path, dict]:
    out = _run([npm, "pack", spec, "--json", "--ignore-scripts", "--no-audit"], cwd)
    try:
        items = json.loads(out)
        row = items[-1] if isinstance(items, list) else items
        archive = cwd / row["filename"]
        if not archive.is_file():
            raise ValueError("missing tarball")
        return archive, row
    except (ValueError, KeyError, TypeError) as exc:
        raise AdditionalPluginError("PLUGIN_NPM_PACK_RESPONSE_INVALID:" + spec) from exc


def _prepare_graph(npm: str, git: str, work: Path) -> Tuple[Path, dict]:
    source = work / "graph-memory-source"
    _run([git, "clone", "--no-tags", GRAPH_REPO, str(source)], work, timeout=480)
    _run([git, "checkout", "--detach", GRAPH_COMMIT], source)
    revision = _run([git, "rev-parse", "HEAD"], source).strip().lower()
    if revision != GRAPH_COMMIT:
        raise AdditionalPluginError("GRAPH_MEMORY_COMMIT_MISMATCH")
    _run([npm, "install", "--ignore-scripts", "--no-audit", "--no-fund"], source, timeout=480)
    _run([npm, "run", "build"], source, timeout=480)
    if not (source / "dist/index.js").is_file() or not (source / "dist/dsh.js").is_file():
        raise AdditionalPluginError("GRAPH_MEMORY_BUNDLE_NOT_BUILT")
    return _npm_pack(npm, ".", source)


def acquire(repo_root: Path) -> Dict[str, object]:
    repo = Path(repo_root).resolve()
    npm, git = shutil.which("npm"), shutil.which("git")
    if not npm or not git:
        raise AdditionalPluginError("NATIVE_NPM_AND_GIT_REQUIRED")
    with tempfile.TemporaryDirectory(prefix="rc72-native-plugin-additions-") as temp:
        work = Path(temp)
        vendor = work / "vendor"
        rows: List[dict] = []
        for name, version, license_name in PINNED_PACKAGES:
            pack_work = work / hashlib.sha256(name.encode()).hexdigest()[:12]
            pack_work.mkdir(parents=True, exist_ok=True)
            if name == "graph-memory":
                tarball, npm_meta = _prepare_graph(npm, git, pack_work)
            else:
                tarball, npm_meta = _npm_pack(npm, name + "@" + version, pack_work)
            target = _package_dir(vendor, name)
            _unpack_npm(tarball, target)
            manifest_file = target / "package.json"
            if not manifest_file.is_file():
                raise AdditionalPluginError("PLUGIN_MANIFEST_MISSING:" + name)
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if manifest.get("name") != name or manifest.get("version") != version:
                raise AdditionalPluginError("PLUGIN_IDENTITY_MISMATCH:" + name)
            if manifest.get("license") != license_name:
                raise AdditionalPluginError("PLUGIN_LICENSE_MISMATCH:" + name)
            license_files = [p for p in target.iterdir() if p.is_file() and p.name.lower().startswith("license")]
            if not license_files:
                # Published npm packages are allowed to reference upstream LICENSE,
                # but the build must carry the license text before bank redistribution.
                if name == "graph-memory":
                    source_license = pack_work / "graph-memory-source/LICENSE"
                    if source_license.is_file():
                        shutil.copy2(source_license, target / "LICENSE")
                        license_files = [target / "LICENSE"]
            if not license_files:
                raise AdditionalPluginError("PLUGIN_LICENSE_FILE_MISSING:" + name)
            dependencies = manifest.get("dependencies") or {}
            if dependencies:
                _run([npm, "install", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund",
                      "--legacy-peer-deps", "--package-lock=false"], target, timeout=600)
            _clean_platform_shims(target)
            entry = manifest.get("main") or (manifest.get("exports", {}).get(".") if isinstance(manifest.get("exports"), dict) else None)
            rows.append({
                "name": name,
                "version": version,
                "license": license_name,
                "npm_tarball_sha256": sha256(tarball),
                "npm_integrity": npm_meta.get("integrity"),
                "source_commit": GRAPH_COMMIT if name == "graph-memory" else None,
                "runtime_dependency_count": len(dependencies),
                "package_json_sha256": sha256(manifest_file),
                "license_files": [p.name for p in license_files],
                "main": entry,
            })
        meta = {
            "schema": SCHEMA,
            "status": "PASS",
            "all_required_bundled": True,
            "required_count": len(PINNED_PACKAGES),
            "packages": rows,
            "dsh_alpha": {
                "status": "LICENSE_HOLD_NOT_BUNDLED",
                "reason": "Commercial-use and bank redistribution authorization not established.",
            },
            "install_policy": "PACKAGE_LOCAL_OFFLINE_PROFILE_ACTIVATION_REQUIRED",
        }
        (vendor / "payload-manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        archive = repo / ARCHIVE_REL
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            archive.unlink()
        with zipfile.ZipFile(str(archive), "w", zipfile.ZIP_DEFLATED, compresslevel=8) as z:
            for path in sorted(vendor.rglob("*")):
                if path.is_file():
                    z.write(str(path), path.relative_to(vendor).as_posix())
        result = {
            **meta,
            "archive": str(archive),
            "archive_sha256": sha256(archive),
            "archive_size": archive.stat().st_size,
        }
        (repo / MANIFEST_REL).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result


def inspect(repo_root: Path) -> Dict[str, object]:
    repo = Path(repo_root)
    archive = repo / ARCHIVE_REL
    manifest = repo / MANIFEST_REL
    if not archive.is_file() or not manifest.is_file():
        raise AdditionalPluginError("ADDITIONAL_PLUGIN_PAYLOAD_MISSING")
    m = json.loads(manifest.read_text(encoding="utf-8"))
    if m.get("schema") != SCHEMA or not m.get("all_required_bundled") or m.get("required_count") != len(PINNED_PACKAGES):
        raise AdditionalPluginError("ADDITIONAL_PLUGIN_MANIFEST_INVALID")
    if sha256(archive) != m.get("archive_sha256"):
        raise AdditionalPluginError("ADDITIONAL_PLUGIN_SHA256_MISMATCH")
    with zipfile.ZipFile(str(archive), "r") as z:
        names = set(z.namelist())
        for name, version, license_name in PINNED_PACKAGES:
            rel = "node_modules/" + name + "/"
            p = rel + "package.json"
            if p not in names:
                raise AdditionalPluginError("ADDITIONAL_PLUGIN_PACKAGE_MISSING:" + name)
            d = json.loads(z.read(p))
            if d.get("name") != name or d.get("version") != version or d.get("license") != license_name:
                raise AdditionalPluginError("ADDITIONAL_PLUGIN_IDENTITY_INVALID:" + name)
        if any(Path(x).suffix.lower() in WINDOWS_SUFFIXES for x in names):
            raise AdditionalPluginError("ADDITIONAL_PLUGIN_WINDOWS_SHIM_PRESENT")
    return {"status": "PASS", "plugin_count": len(PINNED_PACKAGES), "sha256":m["archive_sha256"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("acquire","inspect"))
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    try:
        result = acquire(Path(args.repo_root)) if args.command == "acquire" else inspect(Path(args.repo_root))
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except (AdditionalPluginError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status":"HOLD","reason":str(exc),"bank_final":False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
