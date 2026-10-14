from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "pfc.aitest.rc6.tool-profile.v1"
PROFILE_REL = Path(".dsh") / "rc6" / "TOOL_PROFILE.json"

# Discovery is intentionally bounded. Historical PFC tools/config are reused,
# but the bootstrap never performs a recursive scan of the business source tree.
TOOL_SPECS: Dict[str, Dict[str, Any]] = {
    "git": {"env": "PFC_GIT_BIN", "names": ("git", "git.exe"), "probe": ("--version",)},
    "codegraph": {"env": "PFC_CODEGRAPH_BIN", "names": ("codegraph", "codegraph.exe"), "probe": ("--help",)},
    "gitnexus": {"env": "PFC_GITNEXUS_BIN", "names": ("gitnexus", "gitnexus.exe"), "probe": ("--help",)},
    "python": {"env": "PFC_PYTHON", "names": ("python", "python.exe", "python3"), "probe": ("--version",)},
    "java": {"env": "PFC_JAVA_BIN", "names": ("java", "java.exe"), "probe": ("-version",)},
    "maven": {"env": "PFC_MAVEN_BIN", "names": ("mvn", "mvn.cmd", "mvn.exe"), "probe": ("-version",)},
    "browserskill": {"env": "PFC_BROWSERSKILL_BIN", "names": ("browserskill", "browserskill.exe", "browser-skill", "browser-skill.exe"), "probe": ("--help",)},
    "playwright": {"env": "PFC_PLAYWRIGHT_BIN", "names": ("playwright", "playwright.cmd", "playwright.exe"), "probe": ("--version",)},
    "chromium": {"env": "PFC_CHROMIUM_BIN", "names": ("chromium", "chromium.exe", "chrome", "chrome.exe"), "probe": ("--version",)},
    "k6": {"env": "PFC_K6_BIN", "names": ("k6", "k6.exe"), "probe": ("version",)},
    "zap": {"env": "PFC_ZAP_BIN", "names": ("zap.sh", "zap.bat", "zap.exe", "zaproxy"), "probe": ("-version",)},
}

HISTORY_DIRS = (
    Path("tools"), Path(".tools"), Path("bin"), Path("runtime"), Path("offline-tools"),
    Path(".dsh") / "tools", Path(".agents") / "tools", Path(".opencode") / "tools",
)

SPECIAL_SPECS = {
    "4a": {"env": "PFC_4A_SCRIPT", "names": ("foura_auth.py", "4a_auth.py", "foura-auth.py")},
    "cat": {"env": "PFC_CAT_CONFIG", "names": ("cat.json", "cat.yml", "cat.yaml", "cat.properties", "cat.url")},
}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")


def _existing(value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.exists():
        return path.resolve()
    found = shutil.which(value)
    return Path(found).resolve() if found else None


def _bounded_history_candidates(workspace: Path, names: Sequence[str]) -> Iterable[Path]:
    lower = {name.lower() for name in names}
    for rel in HISTORY_DIRS:
        root = workspace / rel
        if not root.is_dir():
            continue
        # At most three levels below a known tool root; never recurse through
        # the whole bank source workspace.
        for path in sorted(root.glob("*")):
            if path.is_file() and path.name.lower() in lower:
                yield path.resolve()
            elif path.is_dir():
                for child in sorted(path.glob("*")):
                    if child.is_file() and child.name.lower() in lower:
                        yield child.resolve()
                    elif child.is_dir():
                        for leaf in sorted(child.glob("*")):
                            if leaf.is_file() and leaf.name.lower() in lower:
                                yield leaf.resolve()


def _discover_binary(tool_id: str, spec: Dict[str, Any], workspace: Path) -> Tuple[Optional[Path], str]:
    env_value = os.environ.get(spec["env"])
    path = _existing(env_value)
    if path:
        return path, "ENV:%s" % spec["env"]

    # Python currently running the installer is a valid reusable Python when no
    # explicit PFC_PYTHON is supplied.
    if tool_id == "python" and sys.executable and Path(sys.executable).is_file():
        return Path(sys.executable).resolve(), "CURRENT_RUNTIME"

    for candidate in _bounded_history_candidates(workspace, spec["names"]):
        return candidate, "HISTORICAL_WORKSPACE"

    for name in spec["names"]:
        found = shutil.which(name)
        if found:
            return Path(found).resolve(), "PATH"
    return None, "NONE"


def _probe(command: Sequence[str], timeout: int = 8) -> Dict[str, Any]:
    try:
        proc = subprocess.run(list(command), capture_output=True, timeout=timeout, check=False)
        stdout = proc.stdout or b""
        stderr = proc.stderr or b""
        combined = (stdout + b"\n" + stderr)[:16384]
        summary = combined.decode("utf-8", errors="replace").strip().replace("\r", " ").replace("\n", " ")[:500]
        return {
            "exit_code": proc.returncode,
            "output_sha256": _sha(combined),
            "summary": summary,
            "status": "PROBE_PASS" if proc.returncode == 0 else "PROBE_FAIL",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        raw = (type(exc).__name__ + ":" + str(exc)).encode("utf-8", errors="replace")
        return {"exit_code": None, "output_sha256": _sha(raw), "summary": type(exc).__name__, "status": "PROBE_FAIL"}


def _binary_entry(tool_id: str, spec: Dict[str, Any], workspace: Path) -> Dict[str, Any]:
    path, provenance = _discover_binary(tool_id, spec, workspace)
    if path is None:
        return {
            "tool_id": tool_id, "status": "NOT_FOUND", "path": None, "provenance": provenance,
            "capability_stage": "NOT_DISCOVERED", "target_ready": False,
            "broker_admission": "DEFERRED_UNTIL_WORKER_TARGET_BINDING",
        }
    probe = _probe((str(path),) + tuple(spec["probe"]))
    return {
        "tool_id": tool_id,
        "status": probe["status"],
        "path": str(path),
        "provenance": provenance,
        "capability_stage": probe["status"],
        "probe": probe,
        "target_ready": False,
        "broker_admission": "DEFERRED_UNTIL_WORKER_TARGET_BINDING",
    }


def _pytest_entry(python_entry: Dict[str, Any]) -> Dict[str, Any]:
    if python_entry.get("status") != "PROBE_PASS" or not python_entry.get("path"):
        return {
            "tool_id": "pytest", "status": "NOT_FOUND", "path": None,
            "provenance": "PYTHON_UNAVAILABLE", "capability_stage": "NOT_DISCOVERED",
            "target_ready": False, "broker_admission": "DEFERRED_UNTIL_WORKER_TARGET_BINDING",
        }
    probe = _probe((str(python_entry["path"]), "-m", "pytest", "--version"))
    return {
        "tool_id": "pytest", "status": probe["status"], "path": str(python_entry["path"]),
        "provenance": "PYTHON_MODULE", "capability_stage": probe["status"], "probe": probe,
        "target_ready": False, "broker_admission": "DEFERRED_UNTIL_WORKER_TARGET_BINDING",
    }


def _discover_special(tool_id: str, workspace: Path) -> Tuple[Optional[Path], str]:
    spec = SPECIAL_SPECS[tool_id]
    env = os.environ.get(spec["env"])
    path = _existing(env)
    if path:
        return path, "ENV:%s" % spec["env"]
    roots = (
        workspace, workspace / "tools", workspace / ".tools", workspace / "scripts",
        workspace / ".dsh", workspace / ".agents", workspace / ".opencode",
    )
    names = {x.lower() for x in spec["names"]}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*")):
            if path.is_file() and path.name.lower() in names:
                return path.resolve(), "HISTORICAL_WORKSPACE"
            if path.is_dir():
                for child in sorted(path.glob("*")):
                    if child.is_file() and child.name.lower() in names:
                        return child.resolve(), "HISTORICAL_WORKSPACE"
    return None, "NONE"


def _foura_entry(workspace: Path, python_entry: Dict[str, Any]) -> Dict[str, Any]:
    path, provenance = _discover_special("4a", workspace)
    if path is None:
        return {
            "tool_id": "4a", "status": "NOT_FOUND", "path": None, "provenance": provenance,
            "capability_stage": "NOT_DISCOVERED", "target_ready": False,
            "broker_admission": "DEFERRED_UNTIL_WORKER_TARGET_BINDING",
        }
    syntax_probe: Optional[Dict[str, Any]] = None
    if path.suffix.lower() == ".py" and python_entry.get("status") == "PROBE_PASS":
        # Use tokenize.open + compile only. Unlike py_compile this creates no
        # __pycache__ beside the historical 4A script and executes none of it.
        check = (
            "import sys,tokenize; p=sys.argv[1]; f=tokenize.open(p); "
            "s=f.read(); f.close(); compile(s,p,'exec')"
        )
        syntax_probe = _probe((str(python_entry["path"]), "-c", check, str(path)))
    return {
        "tool_id": "4a", "status": "BLOCKED_FIELD_AUTH", "path": str(path), "provenance": provenance,
        "capability_stage": "DISCOVERED" if syntax_probe is None or syntax_probe["status"] == "PROBE_PASS" else "PROBE_FAIL",
        "probe": syntax_probe, "target_ready": False,
        "broker_admission": "DEFERRED_UNTIL_REAL_4A_TARGET_AND_AUTH_BINDING",
    }


def _cat_entry(workspace: Path) -> Dict[str, Any]:
    path, provenance = _discover_special("cat", workspace)
    cat_url = os.environ.get("PFC_CAT_URL")
    if path is None and not cat_url:
        return {
            "tool_id": "cat", "status": "NOT_FOUND", "path": None, "provenance": provenance,
            "capability_stage": "NOT_DISCOVERED", "target_ready": False,
            "broker_admission": "DEFERRED_UNTIL_WORKER_TARGET_BINDING",
        }
    # Never print or persist config contents, cookies, credentials or sessions.
    return {
        "tool_id": "cat", "status": "BLOCKED_FIELD_LOGIN", "path": str(path) if path else None,
        "provenance": provenance if path else "ENV:PFC_CAT_URL", "capability_stage": "DISCOVERED",
        "probe": None, "target_ready": False,
        "broker_admission": "DEFERRED_UNTIL_REAL_CAT_TARGET_AND_LOGIN_BINDING",
    }


def build_tool_profile(workspace: str | Path) -> Dict[str, Any]:
    work = Path(workspace).resolve()
    entries: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for tool_id, spec in TOOL_SPECS.items():
        entry = _binary_entry(tool_id, spec, work)
        entries.append(entry)
        by_id[tool_id] = entry
    entries.append(_pytest_entry(by_id["python"]))
    entries.append(_foura_entry(work, by_id["python"]))
    entries.append(_cat_entry(work))

    summary = {
        "probe_pass": sum(1 for x in entries if x["status"] == "PROBE_PASS"),
        "field_blocked": sum(1 for x in entries if str(x["status"]).startswith("BLOCKED_FIELD_")),
        "not_found": sum(1 for x in entries if x["status"] == "NOT_FOUND"),
        "probe_fail": sum(1 for x in entries if x["status"] == "PROBE_FAIL"),
        "target_ready": 0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "workspace": str(work),
        "generated_at_epoch": int(time.time()),
        "truth": "HOST_PRE_ADMISSION_EVIDENCE_ONLY",
        "target_ready_policy": "NEVER_AT_BOOTSTRAP;REQUIRES_REAL_MISSION_WORKER_TARGET_CAPABILITY_ADMISSION",
        "summary": summary,
        "tools": entries,
    }


def bootstrap_tools(workspace: str | Path) -> Dict[str, Any]:
    work = Path(workspace).resolve()
    profile = build_tool_profile(work)
    _write_json(work / PROFILE_REL, profile)
    return profile


def verify_tool_profile(workspace: str | Path) -> Dict[str, Any]:
    path = Path(workspace).resolve() / PROFILE_REL
    if not path.is_file():
        raise RuntimeError("RC6_TOOL_PROFILE_MISSING")
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("RC6_TOOL_PROFILE_SCHEMA_MISMATCH")
    tools = profile.get("tools") or []
    required = set(TOOL_SPECS) | {"pytest", "4a", "cat"}
    ids = {x.get("tool_id") for x in tools if isinstance(x, dict)}
    if ids != required:
        raise RuntimeError("RC6_TOOL_PROFILE_SET_MISMATCH")
    if any(bool(x.get("target_ready")) for x in tools if isinstance(x, dict)):
        raise RuntimeError("RC6_BOOTSTRAP_MUST_NOT_FORGE_TARGET_READY")
    return profile


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc6_release.tool_bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("bootstrap", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--workspace", default=os.environ.get("PFC_WORKSPACE") or (r"D:\PFC" if os.name == "nt" else "/d/PFC"))
    args = parser.parse_args(argv)
    profile = bootstrap_tools(args.workspace) if args.command == "bootstrap" else verify_tool_profile(args.workspace)
    print(json.dumps({"status": "PASS", "workspace": profile["workspace"], "summary": profile["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
