from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


REQUIRED_PLUGIN_SPECS: Tuple[Tuple[str, str], ...] = (
    ("dsh-routing-suite", "dsh-routing-suite"),
    ("@wxg-prc-cpg/browser-skill-dsh-plugin", "@wxg-prc-cpg/browser-skill-dsh-plugin"),
    ("dsh-context", "dsh-context"),
    ("dsh-plugin-bridge", "dsh-plugin-bridge"),
    ("@nanmicoder/dsh-agent-teams", "@nanmicoder/dsh-agent-teams"),
)
REQUIRED_PLUGIN_NAMES = tuple(name for name, _ in REQUIRED_PLUGIN_SPECS)
PAYLOAD_ARCHIVE_RELATIVE = Path("rc7_release") / "vendor" / "dsh-plugins-payload.zip"
PAYLOAD_MANIFEST_RELATIVE = Path("rc7_release") / "vendor" / "dsh-plugins-payload.manifest.json"
PAYLOAD_SCHEMA = "pfc.aitest.rc7.dsh-plugin-payload.v1"
SPEC_OVERRIDE_ENV = "PFC_RC7_DSH_PLUGIN_SPECS_JSON"
VENDOR_OVERRIDE_ENV = "PFC_RC7_DSH_PLUGIN_VENDOR"


class PluginPayloadError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_path(vendor: Path, package: str) -> Path:
    if package.startswith("@"):
        scope, name = package.split("/", 1)
        return vendor / "node_modules" / scope / name
    return vendor / "node_modules" / package


def _resolved_specs() -> Tuple[Tuple[str, str], ...]:
    configured = os.environ.get(SPEC_OVERRIDE_ENV, "").strip()
    if not configured:
        return REQUIRED_PLUGIN_SPECS
    try:
        overrides = json.loads(configured)
    except json.JSONDecodeError as exc:
        raise PluginPayloadError("PLUGIN_SPEC_OVERRIDE_INVALID_JSON") from exc
    if not isinstance(overrides, dict):
        raise PluginPayloadError("PLUGIN_SPEC_OVERRIDE_MUST_BE_OBJECT")
    rows = []
    for name, default_spec in REQUIRED_PLUGIN_SPECS:
        value = overrides.get(name, default_spec)
        if not isinstance(value, str) or not value.strip():
            raise PluginPayloadError("PLUGIN_SPEC_OVERRIDE_INVALID:%s" % name)
        rows.append((name, value.strip()))
    return tuple(rows)


def _npm() -> str:
    found = shutil.which("npm.cmd") or shutil.which("npm")
    if not found:
        raise PluginPayloadError("NPM_NOT_FOUND_FOR_PLUGIN_PAYLOAD_BUILD")
    return found


def _run(command: Sequence[str], *, cwd: Optional[Path] = None, timeout: int = 300) -> str:
    proc = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    text = (proc.stdout or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise PluginPayloadError(
            "COMMAND_FAILED:%s\n%s" % (" ".join(command), text[-4000:])
        )
    return text


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
                raise PluginPayloadError("UNSAFE_NPM_TARBALL_PATH:%s" % member.name)
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
    output = _run(
        [npm, "pack", spec, "--json", "--ignore-scripts"],
        cwd=pack_dir,
        timeout=300,
    )
    try:
        rows = json.loads(output)
        row = rows[-1] if isinstance(rows, list) else rows
        filename = row["filename"]
    except Exception as exc:
        raise PluginPayloadError("NPM_PACK_JSON_INVALID:%s" % expected_name) from exc
    archive = pack_dir / str(filename)
    if not archive.is_file():
        raise PluginPayloadError("NPM_PACK_ARCHIVE_MISSING:%s" % expected_name)

    target = package_path(vendor, expected_name)
    if target.exists():
        shutil.rmtree(str(target))
    _safe_tar_extract(archive, target)
    manifest_path = target / "package.json"
    if not manifest_path.is_file():
        raise PluginPayloadError("PLUGIN_PACKAGE_JSON_MISSING:%s" % expected_name)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_name = str(manifest.get("name") or "")
    if actual_name != expected_name:
        raise PluginPayloadError(
            "PLUGIN_PACKAGE_NAME_MISMATCH:%s:%s" % (expected_name, actual_name or "<empty>")
        )

    # Materialize regular runtime dependencies inside each plugin payload. Peer
    # dependencies belong to the bank DSH host and are deliberately not copied.
    dependencies = manifest.get("dependencies") or {}
    if dependencies:
        _run(
            [
                npm,
                "install",
                "--omit=dev",
                "--ignore-scripts",
                "--legacy-peer-deps",
                "--no-audit",
                "--no-fund",
                "--package-lock=false",
            ],
            cwd=target,
            timeout=300,
        )

    return {
        "name": expected_name,
        "requested_spec": spec,
        "resolved_version": manifest.get("version"),
        "engines": manifest.get("engines") or {},
        "peer_dependencies": manifest.get("peerDependencies") or {},
        "runtime_dependency_count": len(dependencies),
        "npm_integrity": row.get("integrity") if isinstance(row, dict) else None,
        "npm_shasum": row.get("shasum") if isinstance(row, dict) else None,
        "package_json_sha256": _sha256(manifest_path),
    }


def inspect_vendor(vendor: Path) -> Dict[str, object]:
    rows: Dict[str, Dict[str, object]] = {}
    missing: List[str] = []
    for name in REQUIRED_PLUGIN_NAMES:
        path = package_path(vendor, name)
        manifest_path = path / "package.json"
        if not manifest_path.is_file():
            missing.append(name)
            rows[name] = {"bundled": False, "path": str(path)}
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows[name] = {
            "bundled": True,
            "path": str(path),
            "name": manifest.get("name"),
            "version": manifest.get("version"),
            "engines": manifest.get("engines") or {},
            "peer_dependencies": manifest.get("peerDependencies") or {},
        }
    return {
        "status": "PASS" if not missing else "FAIL",
        "missing": missing,
        "plugins": rows,
    }


def acquire(repo_root: Path, output_archive: Optional[Path] = None) -> Dict[str, object]:
    repo = Path(repo_root).resolve()
    archive = (output_archive or (repo / PAYLOAD_ARCHIVE_RELATIVE)).resolve()
    manifest_sidecar = repo / PAYLOAD_MANIFEST_RELATIVE
    npm = _npm()
    specs = _resolved_specs()

    with tempfile.TemporaryDirectory(prefix="rc7-dsh-plugin-payload-") as temp:
        work = Path(temp)
        vendor = work / "payload"
        (vendor / "node_modules").mkdir(parents=True, exist_ok=True)
        resolved = []
        for name, spec in specs:
            resolved.append(_pack_one(npm, name, spec, vendor, work / "packs"))
        inspection = inspect_vendor(vendor)
        if inspection.get("status") != "PASS":
            raise PluginPayloadError(
                "REQUIRED_PLUGIN_PAYLOAD_INCOMPLETE:%s" % ",".join(inspection.get("missing", []))
            )
        payload_manifest = {
            "schema_version": PAYLOAD_SCHEMA,
            "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
            "runtime_installation": "PACKAGE_LOCAL_FILE_PAYLOAD_NO_REGISTRY_REQUIRED",
            "required_plugins": list(REQUIRED_PLUGIN_NAMES),
            "resolved_plugins": resolved,
        }
        (vendor / "payload-manifest.json").write_text(
            json.dumps(payload_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            archive.unlink()
        with zipfile.ZipFile(str(archive), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for path in sorted(vendor.rglob("*")):
                if path.is_file():
                    target.write(str(path), path.relative_to(vendor).as_posix())

    result = {
        "status": "PASS",
        "archive": str(archive),
        "archive_sha256": _sha256(archive),
        "archive_size": archive.stat().st_size,
        "schema_version": PAYLOAD_SCHEMA,
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "plugins": resolved,
    }
    manifest_sidecar.parent.mkdir(parents=True, exist_ok=True)
    manifest_sidecar.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _safe_zip_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(archive), "r") as source:
        for info in source.infolist():
            if info.is_dir():
                continue
            relative = Path(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise PluginPayloadError("UNSAFE_PLUGIN_PAYLOAD_PATH:%s" % info.filename)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info, "r") as input_stream, target.open("wb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream)


def materialize_payload(home: Path) -> Path:
    override = os.environ.get(VENDOR_OVERRIDE_ENV, "").strip()
    if override:
        vendor = Path(override).expanduser().resolve()
        if inspect_vendor(vendor).get("status") != "PASS":
            raise PluginPayloadError("PLUGIN_VENDOR_OVERRIDE_INCOMPLETE")
        return vendor

    legacy = Path(home).resolve() / "workspace-template" / "runtime" / "dsh-plugins"
    if legacy.is_dir() and inspect_vendor(legacy).get("status") == "PASS":
        return legacy

    root = Path(home).resolve()
    archive = root / PAYLOAD_ARCHIVE_RELATIVE
    if not archive.is_file():
        raise PluginPayloadError("REQUIRED_DSH_PLUGIN_PAYLOAD_ARCHIVE_MISSING")
    digest = _sha256(archive)
    state_root = Path(os.environ.get("PFC_AITEST_STATE_DIR") or (root / "runtime-state")).resolve()
    vendor = state_root / "plugin-runtime" / ("payload-" + digest[:16])
    marker = vendor / ".payload.sha256"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest:
        if inspect_vendor(vendor).get("status") == "PASS":
            return vendor
    if vendor.exists():
        shutil.rmtree(str(vendor))
    _safe_zip_extract(archive, vendor)
    inspection = inspect_vendor(vendor)
    if inspection.get("status") != "PASS":
        raise PluginPayloadError(
            "MATERIALIZED_PLUGIN_PAYLOAD_INCOMPLETE:%s" % ",".join(inspection.get("missing", []))
        )
    marker.write_text(digest + "\n", encoding="utf-8")
    return vendor


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build or inspect RC7 package-local DSH plugin payload")
    sub = parser.add_subparsers(dest="command")
    acquire_parser = sub.add_parser("acquire")
    acquire_parser.add_argument("--repo-root", default=".")
    acquire_parser.add_argument("--output")
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--home", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "acquire":
            result = acquire(
                Path(args.repo_root),
                Path(args.output).resolve() if args.output else None,
            )
        elif args.command == "inspect":
            vendor = materialize_payload(Path(args.home))
            result = inspect_vendor(vendor)
            result["vendor"] = str(vendor)
        else:
            parser.error("command required")
            return 2
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
