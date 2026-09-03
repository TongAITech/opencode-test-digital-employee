from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

BASELINE = "725457e5b475019072ac936fd55756c995ddf69a"
PROTECTED_PREFIXES = (
    "workspace-template/ai-test/runtime/aitest_runtime/autonomous_orchestration.py",
    "workspace-template/ai-test/runtime/aitest_runtime/g2_1/",
    "workspace-template/ai-test/runtime/aitest_runtime/r2_5/",
    "workspace-template/ai-test/runtime/aitest_runtime/r2_6/",
    "workspace-template/ai-test/runtime/aitest_runtime/durable_core",
)


def run(root: Path, *args: str) -> str:
    return subprocess.run(args, cwd=root, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def text(root: Path, relative: str) -> str:
    path = root / relative
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="WAVE2_STATIC_AUDIT_RESULT.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    changed = [line for line in run(root, "git", "diff", "--name-only", f"{BASELINE}..HEAD").splitlines() if line]
    tracked = [line for line in run(root, "git", "ls-files").splitlines() if line]
    g3g4 = [path for path in tracked if "/aitest_runtime/g3/" in path or "/aitest_runtime/g4/" in path]
    source = "\n".join((root / path).read_text(encoding="utf-8", errors="replace") for path in g3g4 if (root / path).is_file())
    service_r24 = text(root, "workspace-template/ai-test/runtime/aitest_runtime/g4/service_r2_4.py")
    service_r25 = text(root, "workspace-template/ai-test/runtime/aitest_runtime/g4/service_r2_5.py")
    service_final = text(root, "workspace-template/ai-test/runtime/aitest_runtime/g4/service.py")
    contracts = text(root, "workspace-template/ai-test/runtime/aitest_runtime/g4/contracts.py")
    product_entry = text(root, "workspace-template/ai-test/runtime/aitest_runtime/product_entry.py")
    control_loop = text(root, "workspace-template/ai-test/runtime/aitest_runtime/control_loop.py")
    codegraph = text(root, "workspace-template/ai-test/runtime/aitest_runtime/g3/codegraph_provider.py")
    broker = text(root, "workspace-template/ai-test/runtime/aitest_runtime/g3/code_intelligence.py")
    probe = text(root, "docs/reviews/OPENCODE_1_18_3_USER_TURN_CAPABILITY_PROBE.md")
    test_names = {
        "test_g4_explicit_user_turn_resume_closure.py",
        "test_g4_package_background_auto_resume_closure.py",
        "test_g4_terminal_prewrite_guard_closure.py",
        "test_g3_codegraph_relationships_closure.py",
        "test_g4_sensitive_ingress_closure.py",
        "test_g3_language_capability_aggregation_closure.py",
    }
    tracked_names = {Path(path).name for path in tracked}
    checks = {
        "protected_g2_g2_1_r2_5_r2_6_unchanged": not any(any(path == prefix or path.startswith(prefix) for prefix in PROTECTED_PREFIXES) for path in changed),
        "no_codegraph_binary_tracked": not any(path.lower().endswith((".exe", ".dll", ".zip", ".tar", ".gz")) and "codegraph" in path.lower() for path in tracked),
        "runtime_lock_tracks_codegraph": '"provider": "codegraph-ai/CodeGraph"' in text(root, "runtime-lock.json"),
        "git_change_truth_present": "GitChangeTruthProvider" in source,
        "provider_neutral_broker_present": "ChangeIntelligenceBroker" in source,
        "codegraph_real_seam_present": "CodeGraphProvider" in source and "CodeGraphProviderResolver" in source,
        "codegraph_unavailable_is_explicit": "CODEGRAPH_UNAVAILABLE" in source,
        "missing_symbol_obligation_present": "MISSING_SYMBOL_MAPPING" in source,
        "g4_governed_execution_binding_present": "GovernedExecutionBinding" in source and "G4_EXECUTION_BINDING_REQUIRED" in source,
        "bank_actual_coverage_authority_preserved": "BANK_INCREMENTAL_COVERAGE_PLATFORM" in source and "BANK_EFFECTIVE_INCREMENTAL" in source,
        "per_app_target_version_binding_present": "affected_application_target_versions" in source,
        "background_auto_resume_present": "auto_resume_human_gates" in source,
        "terminal_transition_guard_present": "G4_GOAL_TRANSITION_FORBIDDEN" in source and "TERMINAL_GOAL_STATUSES" in source,
        "typed_evidence_redaction_present": "TYPED_INGRESS_REDACTION_V1" in source,
        "no_legacy_aitest_db_in_g3_g4_product_source": "aitest.db" not in source,
        "g5_defect_boundary_preserved": "G4_G5_DEFECT_TRUTH_BOUNDARY" in source and "g5_defect_truth" in source,
        "g4_does_not_author_cases": "g4_case_authoring" in source and "FORBIDDEN" in source,
        "root_package_manifest_unique": [path for path in tracked if "/" not in path and "MANIFEST" in path.upper() and path.endswith(".json")] == ["PACKAGE_MANIFEST.json"],

        # F1A: explicit user-turn resume is a deterministic product seam.
        "f1a_durable_user_turn_fact_registered": "HUMAN_GATE_USER_TURN_RESUME_REQUEST" in contracts,
        "f1a_takeover_yields_nonblocking_and_chat_enabled": all(token in service_r24 for token in ("ai_turn", "YIELD", "blocking_tool_call", "False", "chat_input", "ENABLED", "browser_observer", "ai_browser_actuation")),
        "f1a_deterministic_resolver_present": "resolve_human_gate_user_turn" in service_r24 and "REQUEST_TO_VERIFY_COMPLETION" in service_r24,
        "f1a_resolver_queries_r1_pending_gates": "_compatible_explicit_human_gates" in service_r24 and "_human_state(self.runtime, mission_id)" in service_r24,
        "f1a_user_text_not_completion_authority": "user_text_authoritative" in service_r24 and "BROWSER_RUNTIME_FRESH_VERIFICATION" in service_r24,
        "f1a_ambiguity_fail_closed_present": "MULTIPLE_COMPATIBLE_PENDING_HUMAN_GATES" in service_r24 and "CLARIFICATION_REQUIRED" in service_r24,
        "f1a_product_director_action_exposed": "human_gate_user_turn_resume" in product_entry and "resolve_human_gate_user_turn" in product_entry,
        "f1a_opencode_1_18_3_exact_probe_recorded": "v1.18.3" in probe and "OPENCODE_1_18_3_PRE_LLM_USER_MESSAGE_HOOK = AVAILABLE" in probe and "STABLE_PRE_LLM_SHORT_CIRCUIT_INTERCEPTION = NOT_PROVEN" in probe,

        # F1B: AUTO lives on package long-running control loop, not G4 objective tick.
        "f1b_package_background_observer_present": "G4_HUMAN_GATE_BACKGROUND_OBSERVER" in control_loop and "_g4_background_human_gate_tick" in control_loop,
        "f1b_background_observer_non_llm_package_owned": '"non_llm": True' in control_loop and '"package_owned": True' in control_loop,
        "f1b_background_not_objective_control_tick": '"objective_control_tick_dependency": False' in control_loop and "TestObjectiveController" not in control_loop,
        "f1b_long_running_loop_invokes_background_run_tick": "value = run_tick(root)" in control_loop and "g4_human_gate_background" in control_loop,

        # F2: one pre-write terminal guard covers the goal-scoped mutation surface.
        "f2_unified_assert_goal_mutable_present": "def assert_goal_mutable" in service_r25 and "G4_TERMINAL_GOAL_MUTATION_FORBIDDEN" in service_r25,
        "f2_create_batch_blocker_iteration_prewrite_guards": all(f'mutation="{name}"' in service_r25 for name in ("create_batch", "record_blocker_gap", "record_iteration")),
        "f2_human_gate_prewrite_guards": all(f'mutation="{name}"' in service_r25 for name in ("capability_human_gate", "request_human_takeover", "complete_human_takeover", "resolve_human_gate_user_turn")),
        "f2_execute_capability_guard_before_provider_path": 'mutation="execute_capability"' in service_r25,

        # F3: CodeGraph structural enrichment is real and incomplete queries remain obligations.
        "f3_real_codegraph_relationship_tools_present": all(tool in codegraph for tool in ("codegraph_get_callers", "codegraph_get_callees", "codegraph_get_dependency_graph", "codegraph_analyze_impact")),
        "f3_relationship_edges_keep_tool_provenance": "codegraph-tool:{tool}" in codegraph and "ImpactEdge(" in codegraph,
        "f3_failed_relationship_query_downgrades_partial": "CODEGRAPH_RELATIONSHIP_QUERY_FAILED" in codegraph and 'status = "AVAILABLE" if mapping_complete and structural_complete else "PARTIAL"' in codegraph,
        "f3_explicit_structural_relationship_obligation": "CODEGRAPH_STRUCTURAL_RELATIONSHIPS_PARTIAL" in broker,
        "f3_git_truth_not_replaced_by_codegraph": "Git remains the sole changed-file/line authority" in codegraph,

        # F4: typed ingress is applied beyond record_step_result.
        "f4_provider_typed_ingress_present": "def register_capability" in service_final and "capability.provider_metadata" in service_final,
        "f4_blocker_typed_ingress_present": "def record_blocker_gap" in service_final and "blocker.source_refs" in service_final and "sensitive_ingress" in service_final,
        "f4_iteration_typed_ingress_present": "def record_iteration" in service_final and "iteration.new_observations" in service_final and "iteration.human_blockers" in service_final,
        "f4_human_takeover_typed_ingress_present": "takeover.resume_condition" in service_final and "takeover.allowed_scope" in service_final,

        # F5: language capability states merge monotonically instead of last-file-wins.
        "f5_monotonic_language_capability_merge_present": "_merge_capability_status" in broker and "_CAPABILITY_RANK" in broker,
        "f5_language_provider_uses_monotonic_setter": "def set_capability" in broker and "set_capability(lang" in broker,

        "closure_adversarial_test_files_tracked": test_names.issubset(tracked_names),
        "g5_g6_remain_hold_in_validation_runner": '"g5_defect_truth": "HOLD"' in text(root, "tools/run_wave2_validation.py") and '"g6_closed_loop": "HOLD"' in text(root, "tools/run_wave2_validation.py"),
    }
    failed = [key for key, value in checks.items() if not value]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "passed": sum(checks.values()),
        "total": len(checks),
        "failed": failed,
        "checks": checks,
        "baseline": BASELINE,
        "head": run(root, "git", "rev-parse", "HEAD").strip(),
        "changed_files": changed,
    }
    (root / args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
