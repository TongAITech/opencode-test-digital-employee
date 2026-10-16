from __future__ import annotations

import argparse
import json
import locale
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .plugin_payload import REQUIRED_PLUGIN_NAMES, materialize_payload, package_path


REQUIRED = REQUIRED_PLUGIN_NAMES
DIAGNOSTIC_OPTIONAL = (
    "@perrylink/dsh-plugin-doctor",
)
OPTIONAL_DISABLED = (
    "dsh-vision-router",
    "dsh-plugin-anydoc",
    "dsh-memento",
    "dsh-error-handling",
)

# Bank profiles may contain private provider/auth plugins (for example the
# wizard provider). Running plugin add/install on the existing web profile can
# rewrite its dependency tree and remove those private plugins. RC7 therefore
# treats bank profiles as immutable by default.
DEFAULT_PROTECTED_PROFILES = ("web",)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gb18030"):
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def run(cmd: List[str], env: Dict[str, str]) -> Tuple[int, str]:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    return proc.returncode, _decode(proc.stdout or b"")


def protected_profiles() -> Tuple[str, ...]:
    configured = os.environ.get("PFC_RC7_PROTECTED_DSH_PROFILES", "")
    extra = tuple(item.strip() for item in configured.split(",") if item.strip())
    return tuple(dict.fromkeys(DEFAULT_PROTECTED_PROFILES + extra))


def prepare_env(home: Path) -> Dict[str, str]:
    env = dict(os.environ)
    runtime = home / "workspace-template" / "runtime"
    additions = [
        runtime / "node",
        runtime / "browser" / "browserskill",
        runtime / "ripgrep",
        runtime / "maven" / "bin",
        runtime / "java" / "bin",
        runtime / "allure" / "bin",
        runtime / "k6",
        runtime / "zap",
    ]
    flat: List[str] = []
    for item in additions:
        if item.is_dir():
            flat.append(str(item))
            for exe in item.rglob("bsk.exe"):
                flat.append(str(exe.parent))
                break
            for exe in item.rglob("rg.exe"):
                flat.append(str(exe.parent))
                break
    env["PATH"] = os.pathsep.join(flat + [env.get("PATH", "")])
    env.setdefault("PFC_AITEST_HOME", str(home))
    env.setdefault("PFC_AITEST_STATE_DIR", str(home / "runtime-state"))
    env.setdefault("PFC_PYTHON", str(runtime / "python" / "python.exe"))
    env.setdefault("PFC_CODEGRAPH_BIN", str(runtime / "code-intelligence" / "codegraph" / "codegraph-server-win32-x64.exe"))
    env.setdefault("PFC_CHROMIUM_BIN", str(runtime / "browser" / "chrome-win64" / "chrome.exe"))
    return env


def install(
    home: Path,
    profile: str,
    dry_run: bool = False,
    *,
    allow_profile_mutation: bool = False,
    include_diagnostic: bool = False,
) -> Dict[str, object]:
    try:
        vendor = materialize_payload(home)
    except Exception as exc:
        return {
            "status": "FAIL",
            "reason": "REQUIRED_DSH_PLUGIN_PAYLOAD_MISSING",
            "detail": str(exc),
            "mission_required": list(REQUIRED),
        }

    env = prepare_env(home)
    dsh = shutil.which("dsh", path=env.get("PATH"))
    discovered: Dict[str, Dict[str, object]] = {}
    for package in REQUIRED + DIAGNOSTIC_OPTIONAL + OPTIONAL_DISABLED:
        p = package_path(vendor, package)
        discovered[package] = {
            "path": str(p),
            "bundled": (p / "package.json").is_file(),
            "tier": "P0_MISSION" if package in REQUIRED else ("DIAGNOSTIC" if package in DIAGNOSTIC_OPTIONAL else "OPTIONAL_DISABLED"),
        }
    missing = [name for name in REQUIRED if not discovered[name]["bundled"]]
    if missing:
        return {
            "status": "FAIL",
            "reason": "REQUIRED_DSH_PLUGIN_PAYLOAD_MISSING",
            "missing": missing,
            "plugins": discovered,
            "vendor": str(vendor),
        }

    is_protected = profile in protected_profiles()
    if dry_run:
        return {
            "status": "PASS",
            "mode": "PAYLOAD_ONLY_NO_PROFILE_MUTATION",
            "dsh": dsh,
            "profile": profile,
            "protected_profile": is_protected,
            "plugins": discovered,
            "vendor": str(vendor),
            "optional_default": "DISABLED",
            "mission_required": list(REQUIRED),
            "diagnostic_optional": list(DIAGNOSTIC_OPTIONAL),
        }

    if is_protected:
        return {
            "status": "FAIL",
            "reason": "PROTECTED_BANK_PROFILE_MUTATION_FORBIDDEN",
            "profile": profile,
            "protected_profiles": list(protected_profiles()),
            "plugins": discovered,
        }
    if not allow_profile_mutation:
        return {
            "status": "FAIL",
            "reason": "EXPLICIT_PROFILE_MUTATION_AUTHORIZATION_REQUIRED",
            "profile": profile,
            "plugins": discovered,
        }
    if not dsh:
        return {
            "status": "HOLD",
            "reason": "BANK_DSH_HOST_NOT_FOUND",
            "plugins": discovered,
            "field_binding_required": True,
        }

    version_code, version_out = run([dsh, "--version"], env)
    if version_code != 0:
        return {"status": "FAIL", "reason": "DSH_VERSION_PROBE_FAILED", "output": version_out}

    installs = []
    for package in REQUIRED:
        p = Path(str(discovered[package]["path"]))
        # Package-local payloads include their regular runtime dependencies.
        # file: keeps the field installation registry-independent; DSH still
        # owns peer-dependency compatibility checks against the actual host.
        spec = "file:" + str(p)
        code, out = run([dsh, "plugin", "--profile", profile, "add", spec], env)
        accepted = code == 0 or "already" in out.lower() or "exist" in out.lower()
        installs.append(
            {
                "package": package,
                "spec": spec,
                "exit_code": code,
                "accepted": accepted,
                "output_tail": out[-2000:],
            }
        )
        if not accepted:
            return {
                "status": "FAIL",
                "reason": "DSH_PLUGIN_INSTALL_FAILED",
                "dsh_version": version_out.strip(),
                "installs": installs,
                "vendor": str(vendor),
            }

    diagnostic = []
    if include_diagnostic:
        for package in DIAGNOSTIC_OPTIONAL:
            if not discovered[package]["bundled"]:
                continue
            p = Path(str(discovered[package]["path"]))
            spec = "file:" + str(p)
            code, out = run([dsh, "plugin", "--profile", profile, "add", spec], env)
            diagnostic.append(
                {
                    "package": package,
                    "spec": spec,
                    "exit_code": code,
                    "accepted": code == 0,
                    "output_tail": out[-1000:],
                }
            )

    code, dump = run([dsh, "--profile", profile, "--dump-config"], env)
    return {
        "status": "PASS" if code == 0 else "FAIL",
        "mode": "ISOLATED_PROFILE_MUTATION",
        "dsh_version": version_out.strip(),
        "profile": profile,
        "vendor": str(vendor),
        "installs": installs,
        "diagnostic_installs": diagnostic,
        "config_probe_exit_code": code,
        "config_probe_tail": dump[-4000:],
        "optional_default": "DISABLED",
        "remote_vision_policy": "PUBLIC_REMOTE_FORBIDDEN",
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--profile", default="web")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-profile-mutation", action="store_true")
    parser.add_argument("--include-diagnostic", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = install(
        Path(args.home).resolve(),
        args.profile,
        args.dry_run,
        allow_profile_mutation=args.allow_profile_mutation,
        include_diagnostic=args.include_diagnostic,
    )
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("status") in ("PASS", "HOLD") else 2


if __name__ == "__main__":
    raise SystemExit(main())
