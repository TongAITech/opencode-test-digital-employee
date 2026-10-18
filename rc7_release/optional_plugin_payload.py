from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .plugin_payload import package_path

OPTIONAL_PLUGIN_SPECS: Tuple[Tuple[str, str], ...] = (
    ("@perrylink/dsh-plugin-doctor", "@perrylink/dsh-plugin-doctor"),
    ("dsh-vision-router", "dsh-vision-router"),
    ("dsh-plugin-anydoc", "github:beancookie/dsh-plugin-anydoc#3af159ed06f62f3d2c61ab21c6a2475c71efbfa4"),
    ("dsh-memento", "dsh-memento"),
    ("dsh-error-handling", "dsh-error-handling"),
)
OPTIONAL_PLUGIN_NAMES = tuple(name for name, _ in OPTIONAL_PLUGIN_SPECS)
PAYLOAD_ARCHIVE_RELATIVE = Path("rc7_release") / "vendor" / "dsh-optional-plugins-payload.zip"
PAYLOAD_MANIFEST_RELATIVE = Path("rc7_release") / "vendor" / "dsh-optional-plugins-payload.manifest.json"
PAYLOAD_SCHEMA = "pfc.aitest.rc7.dsh-optional-plugin-payload.v1"


class OptionalPluginPayloadError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _npm() -> str:
    found = shutil.which("npm.cmd") or shutil.which("npm")
    if not found:
        raise OptionalPluginPayloadError("NPM_NOT_FOUND_FOR_OPTIONAL_PLUGIN_PAYLOAD_BUILD")
    return found


def _run(command: Sequence[str], *, cwd: Optional[Path] = None, timeout: int = 300) -> Tuple[int, str]:
    proc = subprocess.run(list(command), cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    return proc.returncode, (proc.stdout or b"").decode("utf-8", errors="replace")


def _safe_tar_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(archive), "r:gz") as handle:
        for member in handle.getmembers():
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            if not parts or parts[0] != "package":
                continue
            relative = Path(*parts[1:])
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                raise OptionalPluginPayloadError("UNSAFE_NPM_TARBALL_PATH:%s" % member.name)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source = handle.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _pack_one(npm: str, expected_name: str, spec: str, vendor: Path, work: Path) -> Dict[str, object]:
    pack_dir = work / hashlib.sha256(expected_name.encode("utf-8")).hexdigest()[:12]
    pack_dir.mkdir(parents=True, exist_ok=True)
    code, output = _run([npm, "pack", spec, "--json", "--ignore-scripts"], cwd=pack_dir)
    if code != 0:
        return {"name": expected_name, "requested_spec": spec, "status": "UNAVAILABLE", "stage": "npm_pack", "output_tail": output[-1500:]}
    try:
        rows = json.loads(output)
        row = rows[-1] if isinstance(rows, list) else rows
        archive = pack_dir / str(row["filename"])
    except Exception as exc:
        return {"name": expected_name, "requested_spec": spec, "status": "UNAVAILABLE", "stage": "npm_pack_parse", "reason": str(exc)}
    target = package_path(vendor, expected_name)
    try:
        if target.exists():
            shutil.rmtree(str(target))
        _safe_tar_extract(archive, target)
        manifest_path = target / "package.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("name") != expected_name:
            raise OptionalPluginPayloadError("PLUGIN_PACKAGE_NAME_MISMATCH")
        dependencies = manifest.get("dependencies") or {}
        if dependencies:
            install_code, install_output = _run([
                npm, "install", "--omit=dev", "--ignore-scripts", "--legacy-peer-deps",
                "--no-audit", "--no-fund", "--package-lock=false"
            ], cwd=target)
            if install_code != 0:
                shutil.rmtree(str(target), ignore_errors=True)
                return {"name": expected_name, "requested_spec": spec, "status": "UNAVAILABLE", "stage": "runtime_dependencies", "output_tail": install_output[-1500:]}
        return {
            "name": expected_name,
            "requested_spec": spec,
            "status": "BUNDLED",
            "resolved_version": manifest.get("version"),
            "engines": manifest.get("engines") or {},
            "peer_dependencies": manifest.get("peerDependencies") or {},
            "runtime_dependency_count": len(dependencies),
            "package_json_sha256": _sha256(manifest_path),
        }
    except Exception as exc:
        shutil.rmtree(str(target), ignore_errors=True)
        return {"name": expected_name, "requested_spec": spec, "status": "UNAVAILABLE", "stage": "materialize", "reason": str(exc)}


def inspect_vendor(vendor: Path) -> Dict[str, object]:
    rows: Dict[str, Dict[str, object]] = {}
    bundled: List[str] = []
    missing: List[str] = []
    for name in OPTIONAL_PLUGIN_NAMES:
        path = package_path(vendor, name)
        manifest_path = path / "package.json"
        if not manifest_path.is_file():
            rows[name] = {"bundled": False, "path": str(path)}
            missing.append(name)
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        ok = manifest.get("name") == name
        rows[name] = {"bundled": ok, "path": str(path), "version": manifest.get("version")}
        (bundled if ok else missing).append(name)
    status = "PASS" if len(bundled) == len(OPTIONAL_PLUGIN_NAMES) else ("PARTIAL" if bundled else "EMPTY")
    return {"status": status, "bundled": bundled, "missing": missing, "plugins": rows}


def acquire(repo_root: Path, output_archive: Optional[Path] = None) -> Dict[str, object]:
    repo = Path(repo_root).resolve()
    archive = (output_archive or (repo / PAYLOAD_ARCHIVE_RELATIVE)).resolve()
    sidecar = repo / PAYLOAD_MANIFEST_RELATIVE
    npm = _npm()
    with tempfile.TemporaryDirectory(prefix="rc7-optional-plugin-payload-") as temp:
        work = Path(temp)
        vendor = work / "payload"
        (vendor / "node_modules").mkdir(parents=True, exist_ok=True)
        resolved = [_pack_one(npm, name, spec, vendor, work / "packs") for name, spec in OPTIONAL_PLUGIN_SPECS]
        inspection = inspect_vendor(vendor)
        payload_manifest = {
            "schema_version": PAYLOAD_SCHEMA,
            "status": inspection["status"],
            "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
            "runtime_installation": "PACKAGE_LOCAL_BUNDLED_OPTIONAL_PAYLOAD",
            "optional_plugins": list(OPTIONAL_PLUGIN_NAMES),
            "resolved_plugins": resolved,
            "bundled": inspection["bundled"],
            "missing": inspection["missing"],
        }
        (vendor / "payload-manifest.json").write_text(json.dumps(payload_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            archive.unlink()
        with zipfile.ZipFile(str(archive), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for path in sorted(vendor.rglob("*")):
                if path.is_file():
                    target.write(str(path), path.relative_to(vendor).as_posix())
    result = {
        "schema_version": PAYLOAD_SCHEMA,
        "status": payload_manifest["status"],
        "archive": str(archive),
        "archive_sha256": _sha256(archive),
        "archive_size": archive.stat().st_size,
        "bundled": payload_manifest["bundled"],
        "missing": payload_manifest["missing"],
        "resolved_plugins": resolved,
    }
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def _safe_zip_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(archive), "r") as source:
        for info in source.infolist():
            if info.is_dir():
                continue
            relative = Path(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise OptionalPluginPayloadError("UNSAFE_OPTIONAL_PLUGIN_PAYLOAD_PATH:%s" % info.filename)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info, "r") as input_stream, target.open("wb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream)


def materialize_payload(home: Path) -> Optional[Path]:
    root = Path(home).resolve()
    archive = root / PAYLOAD_ARCHIVE_RELATIVE
    if not archive.is_file():
        return None
    digest = _sha256(archive)
    state_root = Path(__import__("os").environ.get("PFC_AITEST_STATE_DIR") or (root / "runtime-state")).resolve()
    vendor = state_root / "plugin-runtime" / "optional-bundled" / ("payload-" + digest[:16])
    marker = vendor / ".payload.sha256"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest:
        return vendor
    if vendor.exists():
        shutil.rmtree(str(vendor))
    _safe_zip_extract(archive, vendor)
    marker.write_text(digest + "\n", encoding="utf-8")
    return vendor


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build/inspect package-local optional DSH plugin payload")
    sub = parser.add_subparsers(dest="command")
    acquire_parser = sub.add_parser("acquire")
    acquire_parser.add_argument("--repo-root", default=".")
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--home", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "acquire":
            result = acquire(Path(args.repo_root))
        elif args.command == "inspect":
            vendor = materialize_payload(Path(args.home))
            result = inspect_vendor(vendor) if vendor is not None else {"status": "EMPTY", "bundled": [], "missing": list(OPTIONAL_PLUGIN_NAMES)}
        else:
            parser.error("command required")
            return 2
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in {"PASS", "PARTIAL", "EMPTY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
