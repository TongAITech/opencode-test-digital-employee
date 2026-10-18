from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from .plugin_payload import materialize_payload, package_path
from .optional_plugin_payload import materialize_payload as materialize_bundled_optional_payload

OPTIONAL_PLUGINS: Tuple[Tuple[str, str], ...] = (
    ("@perrylink/dsh-plugin-doctor", "DIAGNOSTIC"),
    ("dsh-vision-router", "VISION"),
    ("dsh-plugin-anydoc", "DOCUMENT"),
    ("dsh-memento", "MEMORY"),
)
BUILTIN_DSH_SKILLS = ("dsh-error-handling",)
APPROVAL_ENV = "PFC_NPM_REGISTRY_APPROVED"
REGISTRY_ENV = "PFC_NPM_REGISTRY_URL"
STATE_SUBDIR = Path("plugin-runtime") / "optional-enhancements"
ACTIVATION_SUBDIR = Path("plugin-runtime") / "optional-activations"
PUBLIC_REGISTRY_HOSTS = {"registry.npmjs.org", "npmjs.org", "www.npmjs.com", "npmjs.com"}


class OptionalEnhancementError(RuntimeError):
    pass


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _state_root(home: Path) -> Path:
    return Path(os.environ.get("PFC_AITEST_STATE_DIR") or (home / "runtime-state")).expanduser().resolve()


def _optional_root(home: Path) -> Path:
    return _state_root(home) / STATE_SUBDIR


def _activation_root(home: Path) -> Path:
    return _state_root(home) / ACTIVATION_SUBDIR


def _safe_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)[:160]


def activation_receipt_path(home: Path, profile: str, plugin: str) -> Path:
    return _activation_root(home) / _safe_component(profile) / (_safe_component(plugin) + ".json")


def activation_proven(home: Path, profile: str, plugin: str) -> bool:
    receipt = activation_receipt_path(home, profile, plugin)
    if not receipt.is_file():
        return False
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(data.get("status") == "ACTIVE" and data.get("profile") == profile and data.get("plugin") == plugin)


def _manifest(path: Path) -> Optional[Mapping[str, object]]:
    file = path / "package.json"
    if not file.is_file():
        return None
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, Mapping) else None


def _scan(home: Path) -> Tuple[Dict[str, Dict[str, object]], Dict[str, object]]:
    roots: List[Tuple[str, Path]] = []
    static = home / "workspace-template" / "runtime" / "dsh-optional-plugins"
    if static.is_dir():
        roots.append(("PACKAGE_RUNTIME", static))
    bundled_status: Dict[str, object] = {"present": False, "materialized": False, "path": "", "reason": None}
    try:
        bundled = materialize_bundled_optional_payload(home)
        if bundled is not None:
            roots.append(("PACKAGE_VENDOR_ARCHIVE", bundled))
            bundled_status.update({"present": True, "materialized": True, "path": str(bundled)})
    except Exception as exc:
        bundled_status.update({"present": True, "materialized": False, "reason": str(exc)})
    internal = _optional_root(home)
    if internal.is_dir():
        roots.append(("APPROVED_INTERNAL_MIRROR", internal))
    result: Dict[str, Dict[str, object]] = {}
    for name, tier in OPTIONAL_PLUGINS:
        chosen = None
        manifest = None
        source = None
        for source_name, root in roots:
            candidate = package_path(root, name)
            value = _manifest(candidate)
            if value is not None:
                chosen, manifest, source = candidate, value, source_name
                break
        result[name] = {
            "tier": tier,
            "available": chosen is not None,
            "path": str(chosen) if chosen else "",
            "version": manifest.get("version") if manifest else None,
            "source": source,
        }
    return result, bundled_status


def probe(home: Path, profile: Optional[str] = None) -> Dict[str, object]:
    root = Path(home).expanduser().resolve()
    required_payload = "PASS"
    required_error = None
    try:
        materialize_payload(root)
    except Exception as exc:
        required_payload = "FAIL"
        required_error = str(exc)
    plugins, bundled_status = _scan(root)
    target_profile = str(profile or os.environ.get("PFC_RC7_DSH_PROFILE") or "rc7-field").strip()
    for name, row in plugins.items():
        row["active_profile"] = target_profile
        row["activation_proven"] = activation_proven(root, target_profile, name)
    registry = os.environ.get(REGISTRY_ENV, "").strip()
    host = (urlparse(registry).hostname or "").lower() if registry else ""
    return {
        "status": "PASS" if required_payload == "PASS" else "FAIL",
        "required_dsh_payload": required_payload,
        "required_payload_error": required_error,
        "optional_policy": "BUNDLED_FIRST_THEN_APPROVED_INTERNAL_MIRROR_DISABLED_BY_DEFAULT",
        "bundled_optional_payload": bundled_status,
        "public_registry_forbidden_on_bank_host": True,
        "registry_configured": bool(registry),
        "registry_approved": _enabled(APPROVAL_ENV),
        "public_registry_detected": host in PUBLIC_REGISTRY_HOSTS,
        "profile": target_profile,
        "plugins": plugins,
        "available_optional": [name for name, row in plugins.items() if row["available"]],
        "active_optional": [name for name, row in plugins.items() if row["activation_proven"]],
        "missing_optional": [name for name, row in plugins.items() if not row["available"]],
        "builtin_dsh_skills": list(BUILTIN_DSH_SKILLS),
        "error_handling_model": "DSH_BUILTIN_SKILL_NOT_NPM_PLUGIN",
    }


def _npm(home: Path) -> str:
    runtime = home / "workspace-template" / "runtime" / "node"
    for name in ("npm.cmd", "npm.exe", "npm"):
        candidate = runtime / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("npm.cmd") or shutil.which("npm")
    if found:
        return found
    raise OptionalEnhancementError("NPM_NOT_FOUND")


def _safe_extract(archive: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(str(target))
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(archive), "r:gz") as source:
        for member in source.getmembers():
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            if not parts or parts[0] != "package":
                continue
            relative = Path(*parts[1:])
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                raise OptionalEnhancementError("UNSAFE_NPM_TARBALL_PATH")
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            stream = source.extractfile(member)
            if stream is None:
                continue
            with stream, dest.open("wb") as output:
                shutil.copyfileobj(stream, output)


def _selected(names: Optional[Iterable[str]]) -> Tuple[List[str], List[str]]:
    known = {name for name, _ in OPTIONAL_PLUGINS}
    selected = list(dict.fromkeys(names or [name for name, _ in OPTIONAL_PLUGINS]))
    return selected, [name for name in selected if name not in known]


def acquire(home: Path, names: Optional[Iterable[str]] = None) -> Dict[str, object]:
    root = Path(home).expanduser().resolve()
    registry = os.environ.get(REGISTRY_ENV, "").strip()
    host = (urlparse(registry).hostname or "").lower() if registry else ""
    if host in PUBLIC_REGISTRY_HOSTS:
        return {"status": "FAIL", "reason": "PUBLIC_NPM_REGISTRY_FORBIDDEN", "registry_host": host}
    if not registry or not _enabled(APPROVAL_ENV):
        return {"status": "HOLD", "reason": "APPROVED_INTERNAL_NPM_REGISTRY_REQUIRED", "registry_env": REGISTRY_ENV, "approval_env": APPROVAL_ENV}
    selected, unknown = _selected(names)
    if unknown:
        return {"status": "FAIL", "reason": "UNKNOWN_OPTIONAL_PLUGIN", "plugins": unknown}
    npm = _npm(root)
    vendor = _optional_root(root)
    vendor.mkdir(parents=True, exist_ok=True)
    receipts: List[Dict[str, object]] = []
    existing, _ = _scan(root)
    for name in selected:
        if existing.get(name, {}).get("available"):
            receipts.append({"plugin": name, "status": "ALREADY_MATERIALIZED", "path": existing[name]["path"], "version": existing[name]["version"], "source": existing[name].get("source")})
            continue
        with tempfile.TemporaryDirectory(prefix="rc7-optional-plugin-") as temp:
            proc = subprocess.run([npm, "pack", name, "--json", "--ignore-scripts", "--registry", registry], cwd=temp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            text = (proc.stdout or b"").decode("utf-8", errors="replace")
            if proc.returncode != 0:
                receipts.append({"plugin": name, "status": "UNAVAILABLE", "exit_code": proc.returncode, "output_tail": text[-1200:]})
                continue
            try:
                rows = json.loads(text)
                row = rows[-1] if isinstance(rows, list) else rows
                archive = Path(temp) / str(row["filename"])
                target = package_path(vendor, name)
                _safe_extract(archive, target)
                manifest = _manifest(target)
                if not manifest or manifest.get("name") != name:
                    raise OptionalEnhancementError("PLUGIN_PACKAGE_NAME_MISMATCH")
                receipts.append({"plugin": name, "status": "MATERIALIZED", "path": str(target), "version": manifest.get("version")})
            except Exception as exc:
                receipts.append({"plugin": name, "status": "UNAVAILABLE", "reason": str(exc)})
    unavailable = [row["plugin"] for row in receipts if row["status"] == "UNAVAILABLE"]
    return {
        "status": "HOLD" if unavailable else "PASS",
        "reason": "REQUESTED_OPTIONAL_PLUGIN_UNAVAILABLE" if unavailable else None,
        "registry": "APPROVED_INTERNAL",
        "unavailable": unavailable,
        "receipts": receipts,
        "probe": probe(root),
    }


def activate(home: Path, profile: str, names: Iterable[str], *, allow_profile_mutation: bool = False) -> Dict[str, object]:
    from . import dsh_plugins
    root = Path(home).expanduser().resolve()
    selected, unknown = _selected(names)
    if unknown:
        return {"status": "FAIL", "reason": "UNKNOWN_OPTIONAL_PLUGIN", "plugins": unknown}
    if not selected:
        return {"status": "FAIL", "reason": "OPTIONAL_PLUGIN_SELECTION_REQUIRED"}
    target_profile = str(profile or "").strip()
    if not target_profile:
        return {"status": "FAIL", "reason": "DSH_PROFILE_REQUIRED"}
    if target_profile in dsh_plugins.protected_profiles():
        return {"status": "FAIL", "reason": "PROTECTED_BANK_PROFILE_MUTATION_FORBIDDEN", "profile": target_profile}
    if not allow_profile_mutation:
        return {"status": "FAIL", "reason": "EXPLICIT_PROFILE_MUTATION_AUTHORIZATION_REQUIRED", "profile": target_profile}
    scanned, _ = _scan(root)
    missing = [name for name in selected if not scanned.get(name, {}).get("available")]
    if missing:
        return {"status": "HOLD", "reason": "OPTIONAL_PLUGIN_NOT_MATERIALIZED", "missing": missing, "profile": target_profile}
    env = dsh_plugins.prepare_env(root)
    dsh = dsh_plugins._resolve_dsh(env)
    if not dsh:
        return {"status": "HOLD", "reason": "BANK_DSH_HOST_NOT_FOUND", "profile": target_profile}
    version_code, version_out = dsh_plugins.run_dsh(dsh, ["--version"], env)
    if version_code != 0:
        return {"status": "FAIL", "reason": "DSH_VERSION_PROBE_FAILED", "output": version_out[-1000:]}
    activations: List[Dict[str, object]] = []
    for name in selected:
        path = Path(str(scanned[name]["path"]))
        code, output = dsh_plugins.run_dsh(dsh, ["plugin", "--profile", target_profile, "add", "file:" + str(path)], env)
        accepted = code == 0 or "already" in output.lower() or "exist" in output.lower()
        row = {"plugin": name, "profile": target_profile, "exit_code": code, "accepted": accepted, "output_tail": output[-1500:]}
        activations.append(row)
        if not accepted:
            return {"status": "FAIL", "reason": "OPTIONAL_PLUGIN_ACTIVATION_FAILED", "profile": target_profile, "activations": activations}
        receipt = activation_receipt_path(root, target_profile, name)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({"status": "ACTIVE", "plugin": name, "profile": target_profile, "path": str(path), "dsh_version": version_out.strip()}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"status": "PASS", "profile": target_profile, "dsh_version": version_out.strip(), "activations": activations, "probe": probe(root, target_profile)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC7 optional DSH enhancement manager")
    parser.add_argument("--home", required=True)
    sub = parser.add_subparsers(dest="command")
    probe_parser = sub.add_parser("probe")
    probe_parser.add_argument("--profile")
    acquire_parser = sub.add_parser("acquire")
    acquire_parser.add_argument("--plugin", action="append", default=[])
    activate_parser = sub.add_parser("activate")
    activate_parser.add_argument("--profile", required=True)
    activate_parser.add_argument("--plugin", action="append", required=True)
    activate_parser.add_argument("--allow-profile-mutation", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "probe":
        result = probe(Path(args.home), args.profile)
    elif args.command == "acquire":
        result = acquire(Path(args.home), args.plugin or None)
    elif args.command == "activate":
        result = activate(Path(args.home), args.profile, args.plugin, allow_profile_mutation=args.allow_profile_mutation)
    else:
        parser.error("command required")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") in {"PASS", "HOLD"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
