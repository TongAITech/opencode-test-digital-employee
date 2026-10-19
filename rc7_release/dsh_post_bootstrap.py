from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional, Sequence

from . import dsh_plugins, dsh_runtime_profile


def probe_or_repair(
    home: Path,
    *,
    profile: str = dsh_runtime_profile.DEFAULT_RUNTIME_PROFILE,
    attempt_persistent_install: bool = False,
) -> Dict[str, object]:
    """Probe/repair RC7 DSH plugins without owning DSH startup authority.

    This command is intentionally post-start and non-blocking. A broken bank
    DSH npm/package-manager chain must never prevent the DSH process from
    starting. The protected ``web`` profile is never a valid target.
    """
    if profile in dsh_plugins.protected_profiles():
        return {
            "status": "FAIL",
            "reason": "PROTECTED_BANK_PROFILE_MUTATION_FORBIDDEN",
            "profile": profile,
            "startup_authority": "NONE",
        }

    runtime_path = dsh_runtime_profile._runtime_profile_path(profile)
    if not runtime_path.is_dir():
        return {
            "status": "DEGRADED",
            "reason": "RC7_RUNTIME_PROFILE_NOT_FOUND",
            "profile": profile,
            "startup_authority": "NONE",
            "non_blocking": True,
        }

    before = dsh_runtime_profile.required_plugin_state(runtime_path)
    result: Dict[str, object] = {
        "profile": profile,
        "runtime_profile_path": str(runtime_path),
        "startup_authority": "NONE",
        "non_blocking": True,
        "protected_profile_mutation": "FORBIDDEN",
        "required_plugin_state_before": before,
        "persistent_install_attempted": False,
    }

    if before.get("ready_from_clone"):
        result.update(
            {
                "status": "PASS",
                "capability_state": "READY_FROM_CLONE",
                "reason": "NO_PERSISTENT_INSTALL_REQUIRED",
            }
        )
        return result

    if not attempt_persistent_install:
        result.update(
            {
                "status": "DEGRADED",
                "capability_state": "DEGRADED_MISSING_REQUIRED_PLUGIN_MANIFESTS",
                "reason": "POST_START_REPAIR_AVAILABLE_BUT_NOT_REQUESTED",
            }
        )
        return result

    result["persistent_install_attempted"] = True
    try:
        install = dsh_plugins.install(
            Path(home).resolve(),
            profile,
            dry_run=False,
            allow_profile_mutation=True,
            include_diagnostic=False,
        )
    except Exception as exc:
        install = {
            "status": "FAIL",
            "reason": "POST_START_PLUGIN_INSTALL_EXCEPTION",
            "detail": str(exc),
        }
    result["persistent_install"] = install

    after = dsh_runtime_profile.required_plugin_state(runtime_path)
    result["required_plugin_state_after"] = after
    if install.get("status") == "PASS" and after.get("ready_from_clone"):
        result.update(
            {
                "status": "PASS",
                "capability_state": "READY_AFTER_POST_START_REPAIR",
                "reason": "POST_START_PERSISTENT_INSTALL_SUCCEEDED",
            }
        )
    else:
        # Deliberately DEGRADED rather than FAIL. This helper runs after DSH
        # bootstrap and has no authority to terminate an already-usable host.
        result.update(
            {
                "status": "DEGRADED",
                "capability_state": "DEGRADED_PACKAGE_MANAGER_UNAVAILABLE",
                "reason": "PERSISTENT_INSTALL_FAILED_NON_BLOCKING",
            }
        )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe or non-blockingly repair RC7 DSH plugins after DSH startup")
    parser.add_argument("--home", required=True)
    parser.add_argument("--profile", default=dsh_runtime_profile.DEFAULT_RUNTIME_PROFILE)
    parser.add_argument("--attempt-persistent-install", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        result = probe_or_repair(
            Path(args.home).resolve(),
            profile=args.profile,
            attempt_persistent_install=args.attempt_persistent_install,
        )
    except Exception as exc:
        result = {
            "status": "DEGRADED",
            "reason": "POST_START_BOOTSTRAP_EXCEPTION_NON_BLOCKING",
            "detail": str(exc),
            "startup_authority": "NONE",
            "non_blocking": True,
        }
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.require_ready:
        return 0 if result.get("status") == "PASS" else 2
    # Default contract: never stop/retroactively fail DSH because package-manager
    # persistence is unavailable. Protected-profile misuse remains a hard error.
    return 2 if result.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
