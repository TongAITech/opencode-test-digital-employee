"""Bank-field qualification for RC7 P0 DSH plugin activation and effects.

Presence in the transport ZIP is not runtime proof.  A plugin is considered
field-effective only when (1) the isolated ``rc7-bank`` profile proves the P0
package was accepted while the protected bank profile remained intact and (2)
canonical R1 truth shows the capability effect during the exact Mission.

The effect checks are deliberately capability-based and do not pin plugin or
host versions.  They also do not claim causal attribution: activation plus a
matching runtime effect is the strongest proof available without trusting
model-authored text.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import rc6_runtime.agent_runtime  # noqa: F401 - installs WORKER_* R1 overlay
from rc6_runtime.truth import TruthRuntime

from rc7_runtime.node_tool_conformance import NODE_TOOL_CALL_KIND
from rc7_runtime.session_continuity import SESSION_ARTIFACT, install_session_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay

from .dsh_plugins import REQUIRED


SCHEMA_VERSION = "pfc.aitest.rc7.plugin-effect-qualification.v1"


def _load_json(path: str) -> Dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        return {"status": "HOLD", "reason": "DSH_RUNTIME_PROFILE_EVIDENCE_NOT_FOUND", "path": str(target)}
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "FAIL", "reason": "DSH_RUNTIME_PROFILE_EVIDENCE_INVALID", "detail": str(exc), "path": str(target)}
    if not isinstance(value, dict):
        return {"status": "FAIL", "reason": "DSH_RUNTIME_PROFILE_EVIDENCE_NOT_OBJECT", "path": str(target)}
    return value


def _canonical_tool_name(value: str) -> str:
    name = str(value or "").strip().lower().replace("-", "_")
    marker = "pfc_aitest_rc7__"
    if marker in name:
        return name.split(marker, 1)[1]
    if name.startswith("mcp__") and "__" in name[5:]:
        return name.rsplit("__", 1)[-1]
    return name


def _worker_calls(truth: TruthRuntime, mission_id: str) -> Tuple[Dict[str, str], ...]:
    rows: List[Dict[str, str]] = []
    seen = set()
    for event in truth.store.iter_raw():
        if event.get("event_type") != "WORKER_TOOL_CALLED":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("mission_id") != mission_id:
            continue
        call = payload.get("tool_call")
        if not isinstance(call, dict):
            continue
        worker = str(payload.get("worker_instance_id") or "").strip()
        scope = str(payload.get("scope") or "").strip()
        name = str(call.get("tool_name") or "").strip()
        ref = str(call.get("call_ref") or "").strip()
        if not worker or not scope or not name or not ref:
            continue
        identity = (worker, scope, ref)
        if identity in seen:
            continue
        seen.add(identity)
        rows.append({
            "worker": worker,
            "scope": scope,
            "tool_name": name,
            "canonical_tool": _canonical_tool_name(name),
            "call_ref": ref,
        })
    return tuple(rows)


def _node_tool_names(truth: TruthRuntime, mission_id: str) -> Set[str]:
    names: Set[str] = set()
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != NODE_TOOL_CALL_KIND:
            continue
        source = str(row.get("source_ref") or "")
        if source.startswith("mcp://pfc-aitest-rc7/"):
            names.add(_canonical_tool_name(source.rsplit("/", 1)[-1]))
    return names


def _activation(profile: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    install = profile.get("install") if isinstance(profile.get("install"), dict) else {}
    rows = install.get("installs") if isinstance(install.get("installs"), list) else []
    by_package = {
        str(row.get("package") or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get("package") or "")
    }
    result: Dict[str, Dict[str, Any]] = {}
    profile_ready = (
        profile.get("status") == "PASS"
        and profile.get("protected_bank_profile_integrity") == "PASS"
        and install.get("status") == "PASS"
    )
    for package in REQUIRED:
        row = by_package.get(package)
        accepted = bool(row and row.get("accepted") is True and int(row.get("exit_code", 1)) == 0)
        result[package] = {
            "status": "PASS" if profile_ready and accepted else "HOLD",
            "accepted": accepted,
            "profile_ready": profile_ready,
            "exit_code": row.get("exit_code") if row else None,
        }
    return result


def evaluate_plugin_effects(
    *,
    r1_path: str,
    mission_id: str,
    runtime_profile_evidence: str,
) -> Dict[str, Any]:
    install_rc7_truth_overlay()
    install_session_overlay()
    truth = TruthRuntime(Path(r1_path).expanduser().resolve())
    profile = _load_json(runtime_profile_evidence)
    activation = _activation(profile) if profile.get("status") == "PASS" else {
        package: {"status": "HOLD", "accepted": False, "profile_ready": False}
        for package in REQUIRED
    }

    calls = _worker_calls(truth, mission_id)
    node_tools = _node_tool_names(truth, mission_id)
    task_rows = truth.query("rc7_task", mission_id=mission_id)
    owner_by_task = {
        str(row.get("task_id") or ""): str(row.get("lease_owner") or "")
        for row in task_rows
        if str(row.get("task_id") or "")
    }
    owner_scoped = [
        row for row in calls
        if row["scope"].startswith("task:")
        and owner_by_task.get(row["scope"][len("task:"):]) == row["worker"]
    ]
    distinct_workers = sorted({row["worker"] for row in owner_scoped})

    handoffs = [
        row for row in truth.query(SESSION_ARTIFACT, mission_id=mission_id)
        if str(row.get("status") or "") == "ACTIVATED"
    ]
    session_refs = sorted({
        str(ref)
        for row in handoffs
        for ref in (row.get("predecessor_session_ref"), row.get("successor_session_ref"))
        if isinstance(ref, str) and ref
    })

    bridge_calls = [
        row for row in calls
        if row["canonical_tool"] in node_tools
        and (
            "pfc_aitest_rc7" in row["tool_name"].lower()
            or row["tool_name"].lower().startswith("mcp__")
        )
    ]
    browser_calls = [
        row for row in calls
        if any(token in row["canonical_tool"] for token in ("browser", "browserskill", "browser_skill", "bsk", "playwright"))
    ]

    effects: Dict[str, Dict[str, Any]] = {
        "dsh-routing-suite": {
            "status": "PASS" if owner_scoped else "HOLD",
            "capability": "OWNER_SCOPED_RUNTIME_ROUTING",
            "evidence_refs": [row["call_ref"] for row in owner_scoped[:20]],
        },
        "@wxg-prc-cpg/browser-skill-dsh-plugin": {
            "status": "PASS" if browser_calls else "HOLD",
            "capability": "REAL_BROWSER_AUTOMATION_CALL",
            "evidence_refs": [row["call_ref"] for row in browser_calls[:20]],
        },
        "dsh-context": {
            # Bank Final deliberately requires A->B->C, i.e. at least two
            # activated handoffs and three distinct session identities.
            "status": "PASS" if len(handoffs) >= 2 and len(session_refs) >= 3 else "HOLD",
            "capability": "DURABLE_SESSION_A_B_C_CONTINUITY",
            "activated_handoffs": len(handoffs),
            "session_refs": session_refs,
        },
        "dsh-plugin-bridge": {
            "status": "PASS" if bridge_calls else "HOLD",
            "capability": "DSH_TO_RC7_MCP_REAL_CALL",
            "evidence_refs": [row["call_ref"] for row in bridge_calls[:20]],
            "matched_tools": sorted({row["canonical_tool"] for row in bridge_calls}),
        },
        "@nanmicoder/dsh-agent-teams": {
            "status": "PASS" if len(distinct_workers) >= 2 else "HOLD",
            "capability": "MULTI_WORKER_TASK_EXECUTION",
            "worker_ids": distinct_workers,
        },
    }

    blockers: List[str] = []
    for package in REQUIRED:
        if activation.get(package, {}).get("status") != "PASS":
            blockers.append("PLUGIN_ACTIVATION_NOT_PROVEN:%s" % package)
        effect = effects.get(package)
        if not effect or effect.get("status") != "PASS":
            blockers.append("PLUGIN_CAPABILITY_EFFECT_NOT_PROVEN:%s" % package)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not blockers else "HOLD",
        "qualification_kind": "BANK_FIELD_PLUGIN_ACTIVATION_PLUS_CAPABILITY_EFFECT",
        "attribution_policy": "ACTIVATION_PLUS_RUNTIME_EFFECT_NOT_CAUSALITY_CLAIM",
        "runtime_profile_evidence": str(Path(runtime_profile_evidence).expanduser().resolve()),
        "protected_bank_profile_integrity": profile.get("protected_bank_profile_integrity"),
        "activation": activation,
        "effects": effects,
        "blocking_reasons": blockers,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.plugin_effect_qualification")
    parser.add_argument("--r1", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--runtime-profile-evidence", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    result = evaluate_plugin_effects(
        r1_path=args.r1,
        mission_id=args.mission_id,
        runtime_profile_evidence=args.runtime_profile_evidence,
    )
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.require_pass and result.get("status") != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
