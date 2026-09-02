"""Static checks for the current G1/G2 construction package portable-runtime policy.

This test intentionally follows the current package layout. Historical `AITEST.cmd`
and `field-validation/` paths are not product surfaces in the repaired package.
"""
from __future__ import annotations

import json
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = WORKSPACE_ROOT.parent
FV_ROOT = WORKSPACE_ROOT / ".pfc-internal-field-validation"


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def main() -> int:
    fv_cmd = (FV_ROOT / "FV.cmd").read_text(encoding="utf-8")
    fv_sh = (FV_ROOT / "FV.sh").read_text(encoding="utf-8")
    package_launchers = {
        name: (PACKAGE_ROOT / name).read_text(encoding="utf-8")
        for name in (
            "INSTALL-PFC-AITEST.sh",
            "start-pfc-ai-r1r4.sh",
            "status-pfc-ai-r1r4.sh",
            "stop-pfc-ai-r1r4.sh",
        )
    }
    runtime_common = (WORKSPACE_ROOT / "ai-test" / "runtime" / "aitest_runtime" / "common.py").read_text(encoding="utf-8")
    connectors = (WORKSPACE_ROOT / "ai-test" / "runtime" / "aitest_runtime" / "connectors.py").read_text(encoding="utf-8")
    capability = (WORKSPACE_ROOT / "ai-test" / "runtime" / "aitest_runtime" / "capability.py").read_text(encoding="utf-8")
    offline_plan = json.loads((FV_ROOT / "offline-runtime-plan.v3.json").read_text(encoding="utf-8"))
    opencode = json.loads((WORKSPACE_ROOT / "opencode.json").read_text(encoding="utf-8"))

    all_launchers = {"FV.cmd": fv_cmd, "FV.sh": fv_sh, **package_launchers}
    forbidden_fallbacks = (
        "where py",
        "where python",
        "py -3",
        "command -v python",
        "command -v python3",
        "exec python",
        "exec python3",
    )
    normalized = {name: text.lower().replace("\\", "/") for name, text in all_launchers.items()}
    results = {
        "all_launchers_reference_portable_python": all("runtime/python/python.exe" in text for text in normalized.values()),
        "no_system_python_fallback": all(not contains_any(text, forbidden_fallbacks) for text in all_launchers.values()),
        "controlled_missing_python_failure": all(
            ("portable_python_not_found" in text.lower() or "pfc_portable_python_not_found" in text.lower())
            for text in all_launchers.values()
        ),
        "fv_shell_uses_current_hidden_internal_tool_path": '.pfc-internal-field-validation/tools/fv_tool.py' in fv_sh,
        "fv_cmd_uses_sibling_tools_path": "%~dp0tools\\fv_tool.py" in fv_cmd,
        "doctor_runtime_python_is_exe_only": (
            'WORKSPACE_ROOT / "runtime" / "python" / "python.exe"' in runtime_common
            and 'WORKSPACE_ROOT / "runtime" / "python" / "python",' not in runtime_common
        ),
        "subprocess_helpers_use_runtime_resolver": all(
            "runtime_python_command()" in text and "sys.executable" not in text
            for text in (connectors, capability)
        ),
        "fv_shell_helper_not_bank_runtime_entry": (
            offline_plan["field_validation_helpers"]["fv_shell_helper"]["status"]
            == "NOT_PART_OF_WINDOWS_FIELD_VALIDATION_RUNTIME"
            and not offline_plan["field_validation_helpers"]["fv_shell_helper"]["bank_runbook_referenced"]
        ),
        "codegraph_target_consistent": opencode.get("mcp") == {},
    }
    print(json.dumps({"status": "PASS" if all(results.values()) else "FAIL", "checks": results}, indent=2, sort_keys=True))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
