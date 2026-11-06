"""Fail-closed, read-only RC7.2 field startup wiring check.

A working DSH AgentTeams DAG is NOT proof that the RC7.2 native Mission host
was selected.  This probe checks the *generated* DSH MCP patch, not prompts,
and deliberately does not claim Field PASS or mutate R1.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

_SHA = re.compile(r"^[0-9a-f]{40}$")
_NATIVE_SERVER = "pfc_aitest_rc72"
_NATIVE_ENTRY = "rc7_release.mcp_server_rc72_authorized"
_LEGACY_ENTRY = "rc7_release.mcp_server_authorized"


def evaluate_wiring(*, package_root: Path, patch_path: Path) -> Dict[str, Any]:
    """Inspect exact portable identity and the actual generated MCP launch plan.

    This is a route/readiness guard only.  Even NATIVE_ROUTE_PRESENT must still
    undergo live Q7/Q8/R1/BSK/AgentTeams field qualification.
    """
    root = Path(package_root).resolve()
    patch = Path(patch_path).resolve()
    source_path = root / "SOURCE_COMMIT"
    source_commit = source_path.read_text(encoding="utf-8").strip() if source_path.is_file() else ""
    issues = []
    if not _SHA.fullmatch(source_commit):
        issues.append("RC72_SOURCE_COMMIT_MISSING_OR_INVALID")

    raw = patch.read_text(encoding="utf-8") if patch.is_file() else ""
    if not raw:
        issues.append("RC72_GENERATED_DSH_MCP_PATCH_MISSING")
    # DSH patches may contain unrelated MCP clients.  The native host must
    # appear as an actual executable Python -m target, not in a comment.
    native_module = re.search(
        r"^\s*args:\s*\[\s*['\"]-m['\"]\s*,\s*['\"]"
        + re.escape(_NATIVE_ENTRY) + r"['\"]\s*\]\s*$",
        raw,
        flags=re.MULTILINE,
    ) is not None
    native_server = re.search(
        r"^\s*serverName:\s*['\"]?" + _NATIVE_SERVER + r"['\"]?\s*$",
        raw,
        flags=re.MULTILINE,
    ) is not None
    legacy_module = _LEGACY_ENTRY in raw
    # A line in a generated YAML patch cannot prove a server actually exists.
    # The portable payload must contain the declared executable module.
    native_file = root / "rc7_release" / "mcp_server_rc72_authorized.py"
    native_module_installed = native_file.is_file()
    if not native_module or not native_server:
        issues.append("RC72_NATIVE_MISSION_HOST_NOT_WIRED")
    if native_module and not native_module_installed:
        issues.append("RC72_NATIVE_MCP_IMPLEMENTATION_MISSING")
    if legacy_module and not native_module:
        issues.append("RC7_ONLY_MCP_ROUTE_ACTIVE")
    # This is not an R1 inspection and cannot certify a Mission or Worker.
    return {
        "schema": "rc72-field-wiring-gate/v1",
        "source_commit": source_commit or None,
        "package_root": str(root),
        "generated_mcp_patch": str(patch),
        "native_mcp_server_declared": bool(native_server),
        "native_mcp_entry_declared": bool(native_module),
        "native_mcp_entry_installed": bool(native_module_installed),
        "legacy_mcp_entry_observed": bool(legacy_module),
        "status": "BLOCKED" if issues else "NATIVE_ROUTE_PRESENT_NOT_FIELD_VERIFIED",
        "reasons": issues,
        "field_verified": False,
        "bank_final": False,
        "mission_started": False,
        "note": (
            "Route presence is not Q7 admission, Captain identity, R1 MissionNode, "
            "WorkerInvocation, NodeGate, BrowserLease or BANK_FINAL evidence."
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only RC7.2 native MCP startup wiring gate")
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-native", action="store_true")
    args = parser.parse_args(argv)
    report = evaluate_wiring(package_root=args.package_root, patch_path=args.patch)
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        # Output is a diagnostic file, never an R1 event or Field PASS receipt.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.require_native and report["status"] == "BLOCKED":
        print("RC72_FIELD_START_BLOCKED: native Mission host is not wired", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
