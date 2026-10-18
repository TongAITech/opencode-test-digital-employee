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
DEFAULT_ENABLED_RUNTIME = (
    "dsh-vision-router",
    "dsh-memento",
)
DIAGNOSTIC_OPTIONAL = (
    "@perrylink/dsh-plugin-doctor",
)
CONDITIONAL_OPTIONAL = (
    "dsh-plugin-anydoc",
    "dsh-error-handling",
)

# Bank profiles may contain private provider/auth plugins (for example the
# wizard provider). Running plugin add/install on the existing web profile can
# rewrite its dependency tree and remove those private plugins. RC7 therefore
# treats bank profiles as immutable by default. Default enhancements are loaded
# only by the per-process RC7 --patch layer; they are never installed into web.
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


def _resolve_dsh(env: Dict[str, str]) -> Optional[str]:
    configured = str(env.get("PFC_RC7_DSH_BIN") or "").strip()
    if configured:
        target = Path(configured).expanduser()
        if target.is_file():
            return str(target.resolve())
    for name in ("dsh.cmd", "dsh.exe", "dsh"):
        found = shutil.which(name, path=env.get("PATH"))
        if found:
            return found
    return None


def _msys_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    text = resolved.as_posix()
    if drive and len(text) >= 2 and text[1] == ":":
        return "/%s/%s" % (drive, text[3:])
    return text


def run_dsh(dsh: str, args: List[str], env: Dict[str, str]) -> Tuple[int, str]:
    target = Path(dsh)
    if os.name == "nt" and target.suffix.lower() not in (".cmd", ".bat", ".exe", ".com"):
        bash = shutil.which("bash.exe", path=env.get("PATH")) or shutil.which("bash.exe")
        if not bash:
            git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            bash = str(git_bash) if git_bash.is_file() else None
        if not bash:
            return 127, "GIT_BASH_REQUIRED_FOR_DSH_POSIX_LAUNCHER"
        return run([bash, _msys_path(target)] + list(args), env)
    return run([dsh] + list(args), env)


def _tier(package: str) -> str:
    if package in REQUIRED:
        return "P0_MISSION"
    if package in DEFAULT_ENABLED_RUNTIME:
        return "P1_DEFAULT_RUNTIME"
    if package in DIAGNOSTIC_OPTIONAL:
        return "DIAGNOSTIC"
    return "CONDITIONAL_OPTIONAL"


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
    dsh = _resolve_dsh(env)
    discovered: Dict[str, Dict[str, object]] = {}
    all_packages = REQUIRED + DEFAULT_ENABLED_RUNTIME + DIAGNOSTIC_OPTIONAL + CONDITIONAL_OPTIONAL
    for package in all_packages:
        p = package_path(vendor, package)
        discovered[package] = {
            "path": str(p),
            "bundled": (p / "package.json").is_file(),
            "tier": _tier(package),
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
    missing_default = [name for name in DEFAULT_ENABLED_RUNTIME if not discovered[name]["bundled"]]
    if missing_default:
        return {
            "status": "FAIL",
            "reason": "DEFAULT_RUNTIME_ENHANCEMENT_PAYLOAD_MISSING",
            "missing": missing_default,
            "plugins": discovered,
            "vendor": str(vendor),
        }

    is_protected = profile in protected_profiles()
    base = {
        "profile": profile,
        "protected_profile": is_protected,
        "plugins": discovered,
        "vendor": str(vendor),
        "mission_required": list(REQUIRED),
        "default_runtime_enhancements": list(DEFAULT_ENABLED_RUNTIME),
        "diagnostic_optional": list(DIAGNOSTIC_OPTIONAL),
        "conditional_optional": list(CONDITIONAL_OPTIONAL),
        "remote_vision_policy": "LOCAL_ONLY_PUBLIC_REMOTE_FORBIDDEN",
        "memento_truth_policy": "NON_AUTHORITATIVE_R1_EVENT_STREAM_ONLY",
        "protected_profile_mutation": "FORBIDDEN",
    }
    if dry_run:
        result = dict(base)
        result.update(
            {
                "status": "PASS",
                "mode": "PAYLOAD_ONLY_NO_PROFILE_MUTATION",
                "dsh": dsh,
                "default_enhancements": "RUNTIME_PATCH_ENABLED",
            }
        )
        return result

    if is_protected:
        result = dict(base)
        result.update(
            {
                "status": "FAIL",
                "reason": "PROTECTED_BANK_PROFILE_MUTATION_FORBIDDEN",
                "protected_profiles": list(protected_profiles()),
            }
        )
        return result
    if not allow_profile_mutation:
        result = dict(base)
        result.update({"status": "FAIL", "reason": "EXPLICIT_PROFILE_MUTATION_AUTHORIZATION_REQUIRED"})
        return result
    if not dsh:
        result = dict(base)
        result.update({"status": "HOLD", "reason": "BANK_DSH_HOST_NOT_FOUND", "field_binding_required": True})
        return result

    version_code, version_out = run_dsh(dsh, ["--version"], env)
    if version_code != 0:
        return {"status": "FAIL", "reason": "DSH_VERSION_PROBE_FAILED", "output": version_out, "dsh": dsh}

    installs = []
    # Only P0 bundle dependencies may be installed into an explicitly mutable,
    # isolated profile. P1 default enhancements remain runtime-patch-only.
    for package in REQUIRED:
        p = Path(str(discovered[package]["path"]))
        spec = "file:" + str(p)
        code, out = run_dsh(dsh, ["plugin", "--profile", profile, "add", spec], env)
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
                "dsh": dsh,
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
            code, out = run_dsh(dsh, ["plugin", "--profile", profile, "add", spec], env)
            diagnostic.append(
                {
                    "package": package,
                    "spec": spec,
                    "exit_code": code,
                    "accepted": code == 0,
                    "output_tail": out[-1000:],
                }
            )

    code, dump = run_dsh(dsh, ["--profile", profile, "--dump-config"], env)
    result = dict(base)
    result.update(
        {
            "status": "PASS" if code == 0 else "FAIL",
            "mode": "ISOLATED_PROFILE_MUTATION",
            "dsh": dsh,
            "dsh_version": version_out.strip(),
            "installs": installs,
            "diagnostic_installs": diagnostic,
            "config_probe_exit_code": code,
            "config_probe_tail": dump[-4000:],
            "default_enhancements": "RUNTIME_PATCH_ENABLED",
        }
    )
    return result


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
