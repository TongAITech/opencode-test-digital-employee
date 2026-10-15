from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


REQUIRED = (
    "dsh-routing-suite",
    "@wxg-prc-cpg/browser-skill-dsh-plugin",
    "dsh-context",
    "dsh-plugin-bridge",
    "@nanmicoder/dsh-agent-teams",
    "@perrylink/dsh-plugin-doctor",
)
OPTIONAL_DISABLED = (
    "dsh-vision-router",
    "dsh-plugin-anydoc",
    "dsh-memento",
    "dsh-error-handling",
)


def package_path(vendor: Path, package: str) -> Path:
    if package.startswith("@"):
        scope, name = package.split("/", 1)
        return vendor / "node_modules" / scope / name
    return vendor / "node_modules" / package


def run(cmd: List[str], env: Dict[str, str]) -> Tuple[int, str]:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env=env)
    return proc.returncode, proc.stdout


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
    env.setdefault("PFC_PYTHON", str(runtime / "python" / "python.exe"))
    env.setdefault("PFC_CODEGRAPH_BIN", str(runtime / "code-intelligence" / "codegraph" / "codegraph-server-win32-x64.exe"))
    env.setdefault("PFC_CHROMIUM_BIN", str(runtime / "browser" / "chrome-win64" / "chrome.exe"))
    return env


def install(home: Path, profile: str, dry_run: bool = False) -> Dict[str, object]:
    vendor = home / "workspace-template" / "runtime" / "dsh-plugins"
    dsh = shutil.which("dsh", path=prepare_env(home).get("PATH"))
    discovered = {}
    for package in REQUIRED + OPTIONAL_DISABLED:
        p = package_path(vendor, package)
        discovered[package] = {"path": str(p), "bundled": (p / "package.json").is_file()}
    missing = [name for name in REQUIRED if not discovered[name]["bundled"]]
    if missing:
        return {"status": "FAIL", "reason": "REQUIRED_DSH_PLUGIN_PAYLOAD_MISSING", "missing": missing, "plugins": discovered}
    if dry_run:
        return {"status": "PASS", "mode": "DRY_RUN", "dsh": dsh, "plugins": discovered, "optional_default": "DISABLED"}
    if not dsh:
        return {"status": "HOLD", "reason": "BANK_DSH_HOST_NOT_FOUND", "plugins": discovered, "field_binding_required": True}

    env = prepare_env(home)
    version_code, version_out = run([dsh, "--version"], env)
    if version_code != 0:
        return {"status": "FAIL", "reason": "DSH_VERSION_PROBE_FAILED", "output": version_out}

    installs = []
    for package in REQUIRED:
        p = Path(discovered[package]["path"])
        spec = "link:" + str(p)
        code, out = run([dsh, "plugin", "--profile", profile, "add", spec], env)
        accepted = code == 0 or "already" in out.lower() or "exist" in out.lower()
        installs.append({"package": package, "spec": spec, "exit_code": code, "accepted": accepted, "output_tail": out[-2000:]})
        if not accepted:
            return {"status": "FAIL", "reason": "DSH_PLUGIN_INSTALL_FAILED", "dsh_version": version_out.strip(), "installs": installs}

    code, dump = run([dsh, "--profile", profile, "--dump-config"], env)
    return {
        "status": "PASS" if code == 0 else "FAIL",
        "dsh_version": version_out.strip(),
        "profile": profile,
        "installs": installs,
        "config_probe_exit_code": code,
        "config_probe_tail": dump[-4000:],
        "optional_default": "DISABLED",
        "remote_vision_policy": "PUBLIC_REMOTE_FORBIDDEN",
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--home", required=True)
    p.add_argument("--profile", default="web")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--output")
    args = p.parse_args(argv)
    result = install(Path(args.home).resolve(), args.profile, args.dry_run)
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("status") in ("PASS", "HOLD") else 2


if __name__ == "__main__":
    raise SystemExit(main())
