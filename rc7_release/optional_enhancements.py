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

from .plugin_payload import materialize_payload, package_path

OPTIONAL_PLUGINS: Tuple[Tuple[str, str], ...] = (
    ("@perrylink/dsh-plugin-doctor", "DIAGNOSTIC"),
    ("dsh-vision-router", "VISION"),
    ("dsh-plugin-anydoc", "DOCUMENT"),
    ("dsh-memento", "MEMORY"),
    ("dsh-error-handling", "RESILIENCE"),
)
APPROVAL_ENV = "PFC_NPM_REGISTRY_APPROVED"
REGISTRY_ENV = "PFC_NPM_REGISTRY_URL"
STATE_SUBDIR = Path("plugin-runtime") / "optional-enhancements"


class OptionalEnhancementError(RuntimeError):
    pass


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_root(home: Path) -> Path:
    state = Path(os.environ.get("PFC_AITEST_STATE_DIR") or (home / "runtime-state")).expanduser().resolve()
    return state / STATE_SUBDIR


def _manifest(path: Path) -> Optional[Mapping[str, object]]:
    file = path / "package.json"
    if not file.is_file():
        return None
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, Mapping) else None


def _scan(home: Path) -> Dict[str, Dict[str, object]]:
    roots = [home / "workspace-template" / "runtime" / "dsh-optional-plugins", _optional_root(home)]
    result: Dict[str, Dict[str, object]] = {}
    for name, tier in OPTIONAL_PLUGINS:
        chosen = None; manifest = None
        for root in roots:
            candidate = package_path(root, name); value = _manifest(candidate)
            if value is not None:
                chosen, manifest = candidate, value; break
        result[name] = {"tier": tier, "available": chosen is not None, "path": str(chosen) if chosen else "", "version": manifest.get("version") if manifest else None}
    return result


def probe(home: Path) -> Dict[str, object]:
    root = Path(home).expanduser().resolve(); required_payload = "PASS"; required_error = None
    try:
        materialize_payload(root)
    except Exception as exc:
        required_payload = "FAIL"; required_error = str(exc)
    plugins = _scan(root)
    return {
        "status": "PASS" if required_payload == "PASS" else "FAIL",
        "required_dsh_payload": required_payload,
        "required_payload_error": required_error,
        "optional_policy": "DISABLED_BY_DEFAULT_LOCAL_OR_APPROVED_INTERNAL_MIRROR_ONLY",
        "public_registry_forbidden_on_bank_host": True,
        "registry_configured": bool(os.environ.get(REGISTRY_ENV, "").strip()),
        "registry_approved": _enabled(APPROVAL_ENV),
        "plugins": plugins,
        "available_optional": [name for name, row in plugins.items() if row["available"]],
        "missing_optional": [name for name, row in plugins.items() if not row["available"]],
    }


def _npm(home: Path) -> str:
    runtime = home / "workspace-template" / "runtime" / "node"
    for name in ("npm.cmd", "npm.exe", "npm"):
        candidate = runtime / name
        if candidate.is_file(): return str(candidate)
    found = shutil.which("npm.cmd") or shutil.which("npm")
    if found: return found
    raise OptionalEnhancementError("NPM_NOT_FOUND")


def _safe_extract(archive: Path, target: Path) -> None:
    if target.exists(): shutil.rmtree(str(target))
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(archive), "r:gz") as source:
        for member in source.getmembers():
            if not member.isfile(): continue
            parts = Path(member.name).parts
            if not parts or parts[0] != "package": continue
            relative = Path(*parts[1:])
            if not relative.parts or relative.is_absolute() or ".." in relative.parts: raise OptionalEnhancementError("UNSAFE_NPM_TARBALL_PATH")
            dest = target / relative; dest.parent.mkdir(parents=True, exist_ok=True); stream = source.extractfile(member)
            if stream is None: continue
            with stream, dest.open("wb") as output: shutil.copyfileobj(stream, output)


def acquire(home: Path, names: Optional[Iterable[str]] = None) -> Dict[str, object]:
    root = Path(home).expanduser().resolve(); registry = os.environ.get(REGISTRY_ENV, "").strip()
    if not registry or not _enabled(APPROVAL_ENV):
        return {"status": "HOLD", "reason": "APPROVED_INTERNAL_NPM_REGISTRY_REQUIRED", "registry_env": REGISTRY_ENV, "approval_env": APPROVAL_ENV}
    known = {name for name, _ in OPTIONAL_PLUGINS}; selected = list(dict.fromkeys(names or known)); unknown = [name for name in selected if name not in known]
    if unknown: return {"status": "FAIL", "reason": "UNKNOWN_OPTIONAL_PLUGIN", "plugins": unknown}
    npm = _npm(root); vendor = _optional_root(root); vendor.mkdir(parents=True, exist_ok=True); receipts: List[Dict[str, object]] = []
    for name in selected:
        with tempfile.TemporaryDirectory(prefix="rc7-optional-plugin-") as temp:
            proc = subprocess.run([npm, "pack", name, "--json", "--ignore-scripts", "--registry", registry], cwd=temp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            text = (proc.stdout or b"").decode("utf-8", errors="replace")
            if proc.returncode != 0:
                receipts.append({"plugin": name, "status": "UNAVAILABLE", "exit_code": proc.returncode, "output_tail": text[-1200:]}); continue
            try:
                rows = json.loads(text); row = rows[-1] if isinstance(rows, list) else rows; archive = Path(temp) / str(row["filename"]); target = package_path(vendor, name)
                _safe_extract(archive, target); manifest = _manifest(target)
                if not manifest or manifest.get("name") != name: raise OptionalEnhancementError("PLUGIN_PACKAGE_NAME_MISMATCH")
                receipts.append({"plugin": name, "status": "MATERIALIZED", "path": str(target), "version": manifest.get("version")})
            except Exception as exc:
                receipts.append({"plugin": name, "status": "UNAVAILABLE", "reason": str(exc)})
    return {"status": "PASS", "registry": "APPROVED_INTERNAL", "receipts": receipts, "probe": probe(root)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC7 optional DSH enhancement manager"); parser.add_argument("--home", required=True); sub = parser.add_subparsers(dest="command"); sub.add_parser("probe"); acquire_parser = sub.add_parser("acquire"); acquire_parser.add_argument("--plugin", action="append", default=[]); args = parser.parse_args(argv)
    if args.command == "probe": result = probe(Path(args.home))
    elif args.command == "acquire": result = acquire(Path(args.home), args.plugin or None)
    else: parser.error("command required"); return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)); return 0 if result.get("status") in {"PASS", "HOLD"} else 2


if __name__ == "__main__": raise SystemExit(main())
