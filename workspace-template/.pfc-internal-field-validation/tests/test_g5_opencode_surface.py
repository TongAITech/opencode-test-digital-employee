from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME))

TOOL_PATH = WORKSPACE / ".opencode" / "tools" / "aitest.ts"
AGENT_PATH = WORKSPACE / ".opencode" / "agents" / "aitest-diagnosis.md"
ENTRY_PATH = RUNTIME / "aitest_runtime" / "product_entry.py"

REQUIRED_WORKER_ACTIONS = (
    "status", "work_context", "record_anomaly", "create_candidate",
    "request_evidence_deepening", "record_evidence_assessment", "correlate_sources",
    "evaluate_reproducibility", "assess_false_positive", "assess_defect_truth",
    "record_rca", "record_checkpoint", "handoff_confirmed_defect",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def segment(source: str, start: str, end: str | None = None) -> str:
    if start not in source:
        return ""
    value = source.split(start, 1)[1]
    if end and end in value:
        value = value.split(end, 1)[0]
    return value


def main() -> int:
    tool = read(TOOL_PATH)
    agent = read(AGENT_PATH)
    entry = read(ENTRY_PATH)

    foundation = {
        "opencode_tool_exists": bool(tool),
        "diagnosis_agent_exists": bool(agent),
        "g3_subprocess_wrapper_is_canonical": '"aitest_runtime.product_entry", "g3"' in tool and "AITEST_G3_TRUTH_CONTRACT_FAILED" in tool,
        "g4_subprocess_wrapper_is_canonical": '"aitest_runtime.product_entry", "g4"' in tool and "AITEST_G4_TRUTH_CONTRACT_FAILED" in tool,
        "diagnosis_currently_observation_not_defect": "Observation" in agent and "not automatically a product defect" in agent,
        "diagnosis_currently_excludes_common_false_positives": all(word in agent.lower() for word in ("stale", "data", "auth", "environment", "deployment", "tool")),
    }

    g5_helper = segment(tool, "async function g5(", "const pending")
    diagnosis = segment(tool, "export const diagnosis = tool({", "export const knowledge = tool({")

    forbidden_helper_markers = (
        "create_session", "rotate_session", "close_session",
        "click(", "navigate(", "form_fill", "execute_query", "CAT_LOG_READ_ONLY",
        "AUTO_CONFIRMED", "confirmed_defect = true",
    )

    contract = {
        "g5_subprocess_helper_present": bool(g5_helper),
        "g5_helper_calls_product_entry_g5": bool(g5_helper) and '"aitest_runtime.product_entry", "g5"' in g5_helper,
        "g5_helper_uses_diagnosis_role": bool(g5_helper) and "DIAGNOSIS" in g5_helper,
        "g5_helper_requires_json": bool(g5_helper) and "AITEST_G5_NOT_JSON" in g5_helper,
        "g5_helper_requires_r1_truth": bool(g5_helper) and "AITEST_G5_TRUTH_CONTRACT_FAILED" in g5_helper and "R1_EVENT_STREAM" in g5_helper,
        "diagnosis_calls_canonical_g5_helper": bool(diagnosis) and "return g5(context as ToolContext, \"DIAGNOSIS\"" in diagnosis,
        "diagnosis_no_longer_returns_pending_g5_hold": bool(diagnosis) and 'pending("DIAGNOSIS"' not in diagnosis,
        "diagnosis_exposes_frozen_worker_actions": bool(diagnosis) and all(action in diagnosis for action in REQUIRED_WORKER_ACTIONS),
        "g5_helper_does_not_own_provider_or_session_lifecycle": bool(g5_helper) and all(marker not in g5_helper for marker in forbidden_helper_markers),
        "product_entry_registers_g5_cli": 'sp.add_parser("g5")' in entry and "g5_command(" in entry,
        "agent_requires_governed_new_evidence_path": bool(agent) and all(marker in agent for marker in ("G2", "G3", "G4")) and any(marker in agent.lower() for marker in ("governed", "正式", "受控")),
        "agent_does_not_claim_direct_cat_db_api_ui_authority": bool(agent) and not any(marker in agent.lower() for marker in ("directly query cat", "direct cat", "直接查询cat", "直接访问db", "直接调用api")),
    }

    fixture_ok = all(foundation.values())
    missing = [name for name, value in contract.items() if not value]
    status = "PASS" if fixture_ok and not missing else "FAIL"
    truthful_red = fixture_ok and status == "FAIL" and bool(missing)
    out = {
        "suite": "test_g5_opencode_surface",
        "status": status,
        "passed": sum(bool(v) for v in {**foundation, **contract}.values()),
        "total": len(foundation) + len(contract),
        "fixture_ok": fixture_ok,
        "truthful_red": truthful_red,
        "red_kind": "MISSING_G5_INTEGRATION" if truthful_red else None,
        "foundation_checks": foundation,
        "contract_checks": contract,
        "missing_contract_checks": missing,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
