from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from . import dsh_plugins


PROFILE_MARKER = ".rc7-profile-origin.json"
PROFILE_SCHEMA = "pfc.aitest.rc7.dsh-runtime-profile.v2"
DEFAULT_BASE_PROFILE = "web"
DEFAULT_RUNTIME_PROFILE = "rc7-bank"


class DshRuntimeProfileError(RuntimeError):
    pass


def _dsh_home() -> Path:
    configured = os.environ.get("DSH_HOME")
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".dsh").resolve()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _profile_contract_files(profile: Path) -> Iterable[Path]:
    rows: List[Path] = []
    for name in ("package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "cordis.patch.yml"):
        target = profile / name
        if target.is_file():
            rows.append(target)
    node_modules = profile / "node_modules"
    if node_modules.is_dir():
        for manifest in sorted(node_modules.glob("*/package.json")):
            rows.append(manifest)
        for manifest in sorted(node_modules.glob("@*/*/package.json")):
            rows.append(manifest)
    return tuple(rows)


def profile_snapshot(profile_name: str) -> Dict[str, object]:
    profile = _dsh_home() / "profiles" / profile_name
    if not profile.is_dir():
        return {"profile": profile_name, "exists": False, "digest": None, "files": {}}
    files: Dict[str, Dict[str, object]] = {}
    for path in _profile_contract_files(profile):
        relative = path.relative_to(profile).as_posix()
        files[relative] = {"sha256": _hash_file(path), "size": path.stat().st_size}
    payload = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "profile": profile_name,
        "exists": True,
        "digest": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "files": files,
    }


def _runtime_profile_path(name: str) -> Path:
    return _dsh_home() / "profiles" / name


def _safe_runtime_name(name: str) -> None:
    if not name or name in dsh_plugins.protected_profiles():
        raise DshRuntimeProfileError("RC7_RUNTIME_PROFILE_MUST_NOT_BE_PROTECTED")
    if name in ("web", "headless", "sdk", "sdk-minimal", "acp", "desktop"):
        raise DshRuntimeProfileError("RC7_RUNTIME_PROFILE_MUST_BE_CUSTOM")


def _copy_bank_profile(base: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(str(target))
    # Follow links into an independent physical copy. The RC7 runtime clone may
    # later be repaired after DSH has started, but the protected bank profile
    # must never share writable package-manager state with that clone.
    shutil.copytree(str(base), str(target), symlinks=False)


def _package_dir(profile: Path, package: str) -> Path:
    if package.startswith("@"):
        scope, name = package.split("/", 1)
        return profile / "node_modules" / scope / name
    return profile / "node_modules" / package


def required_plugin_state(profile: Path) -> Dict[str, object]:
    plugins: Dict[str, Dict[str, object]] = {}
    missing: List[str] = []
    for package in dsh_plugins.REQUIRED:
        root = _package_dir(profile, package)
        manifest = root / "package.json"
        present = manifest.is_file()
        if not present:
            missing.append(package)
        plugins[package] = {
            "present_in_clone": present,
            "path": str(root),
        }
    return {
        "ready_from_clone": not missing,
        "missing": missing,
        "plugins": plugins,
    }


def prepare_runtime_profile(
    home: Path,
    *,
    base_profile: str = DEFAULT_BASE_PROFILE,
    runtime_profile: str = DEFAULT_RUNTIME_PROFILE,
) -> Dict[str, object]:
    """Prepare a clean RC7 runtime profile without invoking a package manager.

    Bank field evidence showed that ``dsh plugin add`` can fail inside the host
    npm/package-manager chain before DSH gets a chance to start. Startup must
    therefore be monotonic: clone the protected bank profile, prove the source
    stayed unchanged, report plugin readiness, and *never* install packages in
    this pre-start phase. Persistent plugin repair belongs to the post-start,
    non-blocking bootstrap path.
    """
    _safe_runtime_name(runtime_profile)
    if base_profile not in dsh_plugins.protected_profiles():
        raise DshRuntimeProfileError("RC7_BASE_PROFILE_MUST_BE_PROTECTED")

    base = _runtime_profile_path(base_profile)
    target = _runtime_profile_path(runtime_profile)
    if not base.is_dir():
        return {
            "status": "HOLD",
            "reason": "BANK_DSH_BASE_PROFILE_NOT_FOUND",
            "base_profile": base_profile,
            "runtime_profile": runtime_profile,
            "field_binding_required": True,
            "package_manager_prestart": "FORBIDDEN",
        }

    before = profile_snapshot(base_profile)
    if not before.get("exists") or not before.get("digest"):
        return {
            "status": "FAIL",
            "reason": "BANK_DSH_BASE_PROFILE_CONTRACT_EMPTY",
            "base_profile_before": before,
            "package_manager_prestart": "FORBIDDEN",
        }

    marker_path = target / PROFILE_MARKER
    rebuild_reason: Optional[str] = None
    marker: Dict[str, object] = {}
    if not target.is_dir():
        rebuild_reason = "RUNTIME_PROFILE_MISSING"
    else:
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.is_file() else {}
        except Exception:
            marker = {}
        if marker.get("schema_version") != PROFILE_SCHEMA:
            # v1 runtime clones may have been partially mutated by a failed
            # pre-start dsh plugin add. Never reuse them after this repair.
            rebuild_reason = "RUNTIME_PROFILE_POLICY_UPGRADE"
        elif marker.get("base_profile") != base_profile:
            rebuild_reason = "RUNTIME_PROFILE_ORIGIN_MISMATCH"
        elif marker.get("base_digest") != before.get("digest"):
            rebuild_reason = "BANK_BASE_PROFILE_DRIFT"

    if rebuild_reason:
        _copy_bank_profile(base, target)
        marker_path = target / PROFILE_MARKER
        marker_path.write_text(
            json.dumps(
                {
                    "schema_version": PROFILE_SCHEMA,
                    "base_profile": base_profile,
                    "base_digest": before.get("digest"),
                    "runtime_profile": runtime_profile,
                    "clone_policy": "PHYSICAL_COPY_PROTECTED_SOURCE_IMMUTABLE",
                    "startup_policy": "CLONE_FIRST_NO_PACKAGE_MANAGER",
                    "plugin_bootstrap_policy": "POST_START_NON_BLOCKING",
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    # This is deliberately only an observation. Do not call dsh_plugins.install
    # here: DSH must be allowed to start even when its package manager is broken.
    plugin_state = required_plugin_state(target)
    after = profile_snapshot(base_profile)
    protected_unchanged = (
        before.get("exists") == after.get("exists")
        and before.get("digest") == after.get("digest")
    )
    if not protected_unchanged:
        return {
            "status": "FAIL",
            "reason": "PROTECTED_BANK_PROFILE_MUTATED",
            "base_profile_before": before,
            "base_profile_after": after,
            "runtime_profile": runtime_profile,
            "package_manager_prestart": "FORBIDDEN",
        }

    capability_state = (
        "READY_FROM_CLONE"
        if plugin_state.get("ready_from_clone")
        else "DEGRADED_MISSING_REQUIRED_PLUGIN_MANIFESTS"
    )
    return {
        "status": "PASS",
        "base_profile": base_profile,
        "runtime_profile": runtime_profile,
        "runtime_profile_path": str(target),
        "rebuild_reason": rebuild_reason,
        "protected_bank_profile_integrity": "PASS",
        "base_profile_digest": before.get("digest"),
        "startup_policy": "CLONE_FIRST_NO_PACKAGE_MANAGER",
        "package_manager_prestart": "FORBIDDEN",
        "plugin_bootstrap_policy": "POST_START_NON_BLOCKING",
        "persistent_install_attempted": False,
        "required_plugin_state": plugin_state,
        "capability_state": capability_state,
        "startup_blocked_by_plugin_readiness": False,
        # Compatibility field for older evidence readers. This is intentionally
        # SKIPPED, not PASS: no install occurred in the startup path.
        "install": {
            "status": "SKIPPED",
            "reason": "PRESTART_PACKAGE_MANAGER_FORBIDDEN",
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare isolated RC7 DSH runtime profile from the protected bank profile")
    parser.add_argument("--home", required=True)
    parser.add_argument("--base-profile", default=DEFAULT_BASE_PROFILE)
    parser.add_argument("--runtime-profile", default=DEFAULT_RUNTIME_PROFILE)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = prepare_runtime_profile(
            Path(args.home).resolve(),
            base_profile=args.base_profile,
            runtime_profile=args.runtime_profile,
        )
    except Exception as exc:
        result = {"status": "FAIL", "reason": str(exc), "package_manager_prestart": "FORBIDDEN"}
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.require_pass:
        return 0 if result.get("status") == "PASS" else 2
    return 0 if result.get("status") in ("PASS", "HOLD") else 2


if __name__ == "__main__":
    raise SystemExit(main())
