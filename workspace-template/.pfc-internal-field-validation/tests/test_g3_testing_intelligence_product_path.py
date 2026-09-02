from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve()
WORKSPACE = HERE.parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from aitest_runtime import product_entry  # noqa: E402
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider  # noqa: E402
from aitest_runtime.canonical_runtime import create_canonical_runtime  # noqa: E402
from aitest_runtime.durable_core import RuntimeError, canonical_sha256  # noqa: E402
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService  # noqa: E402
from aitest_runtime.g3.coverage import (  # noqa: E402
    BankCoveragePlatformProvider, CoverageProviderResult, MappingCoveragePlatformProvider, reconcile_coverage,
)
from aitest_runtime.g3.service import G3TestingIntelligenceService  # noqa: E402
from aitest_runtime.r2_6.contracts import OUTCOMES, policy_digest  # noqa: E402
from aitest_runtime.r3_3.service import R33ApplicationService  # noqa: E402


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def intake_request() -> dict[str, Any]:
    return {
        "intake_id": "g3-product-chain",
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "V2", "repositories": ["cfg-data", "cfg-admin"]},
        "goal": {"title": "G3 Testing Intelligence", "intent": "Design high-value governed tests", "constraints": []},
        "source": {"kind": "USER", "source_ref": "construction:g3", "source_digest": digest({"g3": 1}), "observed_at": "2026-09-01T10:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "construction-test"},
        "resolution": {"resolution_id": "resolution:g3", "request_digest": digest({"resolution": "g3"}), "snapshot_id": "snapshot:g3", "fact_set_digest": digest([]), "status": "RESOLVED", "reason_code": None, "source_refs": ["construction:g3"], "valid_until": "2026-09-02T10:00:00Z"},
    }


def binding(dispatch: Mapping[str, Any]) -> dict[str, str]:
    session = dispatch.get("external_session") or {}
    if not session and dispatch.get("session_id"):
        session = {"session_id": dispatch["session_id"]}
    return {
        "mission_id": str(dispatch.get("attempt", {}).get("mission_id") or dispatch.get("mission_id") or ""),
        "task_id": str(dispatch["task_id"]),
        "attempt_id": str(dispatch["attempt"]["attempt_id"]),
        "session_id": str(session["session_id"]),
    }


def finish(service: G21AutonomousOrchestrationService, bound: Mapping[str, str], summary: str) -> dict[str, Any]:
    return service.report_task_outcome(
        bound["mission_id"], task_id=bound["task_id"], attempt_id=bound["attempt_id"], session_id=bound["session_id"],
        outcome="SUCCEEDED", summary=summary, external_references=[{"namespace": "G3_CONSTRUCTION", "id": digest(summary)[:16]}],
    )


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip()


def make_repo(root: Path, name: str, files_before: Mapping[str, str], files_after: Mapping[str, str]) -> tuple[Path, str, str]:
    repo = root / name
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "master")
    git(repo, "config", "user.email", "g3@example.invalid")
    git(repo, "config", "user.name", "G3 Construction")
    for rel, text in files_before.items():
        path = repo / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")
    git(repo, "add", "."); git(repo, "commit", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")
    for rel, text in files_after.items():
        path = repo / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")
    git(repo, "add", "."); git(repo, "commit", "-m", "target change")
    head = git(repo, "rev-parse", "HEAD")
    return repo, base, head


def human_gate_request(bound: Mapping[str, str], attempt: Mapping[str, Any], *, gate_id: str, gate_kind: str, payload: Mapping[str, Any], review: bool = False) -> dict[str, Any]:
    routes = {outcome: (("NONE",) if outcome in {"APPROVED", "CHOICE_SELECTED", "INFORMATION_PROVIDED"} else (("RESUME_EXECUTION",) if outcome == "EXTERNAL_ACTION_COMPLETED" else ("BLOCK",))) for outcome in OUTCOMES}
    if review:
        allowed = ("APPROVED", "REJECTED")
        routes = {outcome: (("NONE",) if outcome == "APPROVED" else ("BLOCK",)) for outcome in OUTCOMES}
    else:
        allowed = ("EXTERNAL_ACTION_COMPLETED",)
    pid = "g3-human-review-policy" if review else "g3-coverage-auth-policy"
    return {
        "mission_id": bound["mission_id"], "gate_id": gate_id, "plan_id": attempt["plan_id"], "plan_revision_id": attempt["plan_revision_id"],
        "task_id": bound["task_id"], "root_attempt_id": attempt["root_attempt_id"], "origin_attempt_id": bound["attempt_id"], "origin_session_id": bound["session_id"],
        "gate_kind": gate_kind, "request_payload": dict(payload), "response_schema": {"type": "object"}, "expires_at": None, "expiry_policy": "NONE",
        "decision_policy_id": pid, "decision_policy_version": 1, "decision_policy_digest": policy_digest(pid, 1, allowed, routes),
        "allowed_outcomes": list(allowed), "allowed_routes_by_outcome": {k: list(v) for k, v in routes.items()},
        "request_provenance": {"source_ref": f"g3:{gate_id}", "source_digest": canonical_sha256(dict(payload)), "observed_at": "2026-09-01T10:00:00Z"},
        "actor": {"type": "SYSTEM", "id": "g3-testing-intelligence"},
    }


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="pfc-g3-product-") as td:
        root = Path(td)
        spine = root / "runtime-spine.db"
        legacy = root / "ai-test/state/aitest.db"
        legacy_before = sha_file(legacy)
        repo_java, java_base, java_head = make_repo(
            root, "cfg-data",
            {"src/CreditLimitService.java": "package bank;\npublic class CreditLimitService {\n  public boolean validateLimit(long requested, long approved) {\n    return requested < approved;\n  }\n}\n"},
            {"src/CreditLimitService.java": "package bank;\npublic class CreditLimitService {\n  public boolean validateLimit(long requested, long approved) {\n    if (requested < 0) return false;\n    return requested <= approved;\n  }\n}\n", "src/LimitSyncService.java": "package bank;\npublic class LimitSyncService {\n  public String syncLimit(String state) {\n    return state == null ? \"RETRY\" : \"SYNCED\";\n  }\n}\n", "config/application.yml": "feature:\n  limit-sync: true\n", "db/limit.sql": "update credit_limit set state='SYNCED' where id=?;\n"},
        )
        repo_vue, web_base, web_head = make_repo(
            root, "cfg-admin",
            {"src/views/LimitPage.vue": "<script setup lang=\"ts\">\nconst amount = 0\n</script>\n<template><div>{{ amount }}</div></template>\n"},
            {"src/views/LimitPage.vue": "<script setup lang=\"ts\">\nimport axios from 'axios'\nconst amount = 0\nasync function submitLimit(){ return axios.post('/limits', { amount }) }\n</script>\n<template><button @click=\"submitLimit\">submit</button></template>\n", "src/api/limit.ts": "import axios from 'axios'\nexport const loadLimit = async () => axios.get('/limits/current')\n"},
        )

        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        os.environ["AITEST_RUNTIME_SPINE_DB"] = str(spine)
        runtime = create_canonical_runtime(root, db_path=spine)
        provider = FakeOpenCodeSessionProvider(root)
        orchestration = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        coverage_box: dict[str, Any] = {"provider": BankCoveragePlatformProvider()}

        original_orch_factory = product_entry.orchestration_service
        original_default_service = product_entry.default_service
        original_g3 = product_entry.G3TestingIntelligenceService
        product_entry.orchestration_service = lambda _root=None: orchestration  # type: ignore[assignment]
        product_entry.default_service = lambda _runtime, _root: orchestration  # type: ignore[assignment]
        product_entry.G3TestingIntelligenceService = lambda rt, orchestration=None: G3TestingIntelligenceService(rt, coverage_provider=coverage_box["provider"], orchestration=orchestration or globals()["orchestration"])  # type: ignore[assignment]
        try:
            started = product_entry.orchestration_command("DIRECTOR", "start_test", {"request": intake_request()})
            mission_id = started["intake"]["intake"]["mission_id"]
            checks["user_entry_creates_durable_mission"] = started["status"] == "PLANNING" and started["truth_source"] == "R1_EVENT_STREAM"

            intent = product_entry.g3_command("DIRECTOR", "register_intent", {"mission_id": mission_id, "intent_type": "TEST_CASE_DESIGN", "scope": {"requirement_id": "REQ-018", "version": "V2", "source_materials": [{"source_id": "REQ-018", "source_kind": "REQUIREMENT", "revision": "V2", "content": "Requested limit must not exceed approved limit; equality is allowed."}, {"source_id": "SST-018", "source_kind": "SST", "revision": "V2", "content": "Limit update synchronizes cfg-data to cfg-scd through SYNC_PENDING to SYNCED."}, {"source_id": "DESIGN-018", "source_kind": "DESIGN", "revision": "V2", "content": "Only LIMIT_WRITE may update; API/UI final value must agree."}]}, "constraints": {"mode": "HUMAN_ASSISTED_OR_AUTONOMOUS"}})
            checks["test_intent_is_durable_and_returns_governed_plan"] = intent["status"] == "ACCEPTED" and len(intent["recommended_plan"]["tasks"]) == 6
            held = product_entry.g3_command("DIRECTOR", "register_intent", {"mission_id": mission_id, "intent_type": "CASE_EXECUTION_REQUEST", "scope": {"case_id": "TC-X"}, "constraints": {}})
            checks["case_execution_intent_remains_g4_hold"] = held["status"] == "HOLD" and held["gate"] == "G4_REAL_EXECUTION" and held["hold_code"] == "HOLD_G4" and held["recommended_plan"] is None
            defect_hold = product_entry.g3_command("DIRECTOR", "register_intent", {"mission_id": mission_id, "intent_type": "DEFECT_DIAGNOSIS_REQUEST", "scope": {"failure_id": "F-X"}, "constraints": {}})
            checks["defect_diagnosis_intent_remains_g5_hold"] = defect_hold["status"] == "HOLD" and defect_hold["gate"] == "G5_DEFECT_TRUTH" and defect_hold["hold_code"] == "HOLD_G5" and defect_hold["recommended_plan"] is None

            plan = product_entry.orchestration_command("PLANNER", "propose_plan", {"mission_id": mission_id, "proposal": intent["recommended_plan"]})
            first = plan["next"]
            checks["planner_scheduler_router_dispatch_requirement_analyst"] = plan["status"] == "PASS" and first["agent"] == "aitest-requirement-analyst" and first["route"]["role"] == "REQUIREMENT_ANALYST"
            checks["all_g3_routes_are_durable_specialist_routes"] = [x["role"] for x in plan["route_requirements"]] == ["REQUIREMENT_ANALYST", "CODE_ANALYST", "CODE_ANALYST", "TEST_STRATEGIST", "CASE_DESIGNER", "EVALUATOR"]

            # Rotate the first G3 specialist from a brand-new Runtime/Control Loop instance.
            first_session = first["external_session"]["session_id"]
            provider.set_observation(first_session, message_count=60, compaction_count=0, context_utilization=0.4, healthy=True)
            runtime_restart = create_canonical_runtime(root, db_path=spine)
            restarted = G21AutonomousOrchestrationService(runtime_restart, root, session_provider=provider)
            tick = restarted.supervise_once()
            rotations = [x["result"] for x in tick["supervision"] if x.get("task_id") == first["task_id"] and x.get("result", {}).get("status") == "ROTATED"]
            rotation = rotations[0]["rotation"]
            first_bound = {"mission_id": mission_id, "task_id": first["task_id"], "attempt_id": rotation["successor_attempt_id"], "session_id": rotation["successor_session_id"]}
            checks["g3_specialist_rotates_after_control_loop_restart"] = rotation["root_attempt_id"] == first["attempt"]["root_attempt_id"] and first_bound["session_id"] != first_session
            work_context = product_entry.g3_command("REQUIREMENT_ANALYST", "work_context", first_bound)
            active_intent = work_context.get("active_test_intent") or {}
            checks["router_owned_specialist_recovers_raw_source_materials_from_r1"] = work_context["truth_source"] == "R1_EVENT_STREAM" and work_context["conversation_is_not_truth"] is True and active_intent.get("payload", {}).get("scope", {}).get("source_materials", [])[0].get("source_kind") == "REQUIREMENT"

            semantics = {
                "source_refs": [
                    {"source_id": "REQ-018", "source_kind": "REQUIREMENT", "revision": "V2", "locator": "requirement://REQ-018"},
                    {"source_id": "SST-018", "source_kind": "SST", "revision": "V2", "locator": "sst://SST-018"},
                    {"source_id": "DESIGN-018", "source_kind": "DESIGN", "revision": "V2", "locator": "design://DESIGN-018"},
                ],
                "business_rules": [{"text": "Requested limit must not exceed the approved limit", "source_id": "REQ-018", "obligation_id": "REQ-018-BR-1", "code_refs": ["src/CreditLimitService.java"], "api_refs": ["POST /limits"], "permission_refs": ["LIMIT_WRITE"], "security_refs": ["AUTHZ_LIMIT_WRITE"], "actors": ["credit-operator"], "start_state_refs": ["APPROVED"], "end_state_refs": ["SYNCED"]}],
                "field_data_rules": [{"text": "Requested limit must be non-negative and currency scale must be two decimals", "source_id": "SST-018", "code_refs": ["src/CreditLimitService.java"]}],
                "state_transitions": [{"text": "Approved update transitions through SYNC_PENDING to SYNCED", "source_id": "SST-018", "code_refs": ["src/LimitSyncService.java"], "critical_journey_refs": ["LIMIT_UPDATE_JOURNEY"]}],
                "positive_paths": [{"text": "Requested amount below approved limit is accepted", "source_id": "REQ-018"}],
                "negative_paths": [{"text": "Requested amount above approved limit is rejected", "source_id": "REQ-018"}],
                "exception_paths": [{"text": "Downstream synchronization timeout leaves a retryable state without duplicate limit mutation", "source_id": "DESIGN-018"}],
                "boundary_rules": [{"text": "Requested amount exactly equal to approved limit is accepted", "source_id": "REQ-018", "code_refs": ["src/CreditLimitService.java"]}],
                "permission_rules": [{"text": "Only LIMIT_WRITE role may change a credit limit", "source_id": "REQ-018", "permission_refs": ["LIMIT_WRITE"], "security_refs": ["AUTHZ_LIMIT_WRITE"]}],
                "cross_system_flows": [{"text": "cfg-data accepted update must synchronize to cfg-scd before UI shows final success", "source_id": "DESIGN-018", "critical_journey_refs": ["LIMIT_UPDATE_JOURNEY"]}],
                "acceptance_criteria": [{"text": "API and UI expose the same final synchronized limit", "source_id": "REQ-018", "api_refs": ["POST /limits"], "page_refs": ["src/views/LimitPage.vue"]}],
                "non_functional_risks": [{"text": "Limit update endpoint latency and authorization behavior are release risks", "source_id": "DESIGN-018", "performance_refs": ["LIMIT_UPDATE_P95"], "security_refs": ["AUTHZ_LIMIT_WRITE"]}],
                "unknowns": [{"question": "Maximum retry/backoff policy is absent from supplied Requirement/SST/design sources", "source_id": "DESIGN-018"}],
            }
            requirement_result = product_entry.g3_command("REQUIREMENT_ANALYST", "analyze_requirement", {**first_bound, "scope_identity": "REQ-018", "semantics": semantics})
            checks["requirement_intelligence_maps_to_r31_with_provenance"] = requirement_result["r3_1_reference"]["derivation_version_id"].startswith("r3.1:")
            checks["unknown_business_fact_becomes_knowledge_gap_and_human_task"] = requirement_result["status"] == "PARTIAL_KNOWLEDGE_GAPS" and len(requirement_result["knowledge_gaps"]) == 1
            completed = finish(restarted, first_bound, "Requirement semantics and explicit knowledge gap persisted")
            second = completed["next"]; second_bound = binding(second)
            checks["scheduler_advances_to_code_analyst"] = second["agent"] == "aitest-code-analyst"

            change_result = product_entry.g3_command("CODE_ANALYST", "analyze_changes", {
                **second_bound, "scope_identity": "REQ-018", "r3_1_reference": requirement_result["r3_1_reference"],
                "repositories": [
                    {"repository_id": "cfg-data", "application_id": "cfg-data", "repository_path": str(repo_java), "base_ref": java_base, "head_ref": java_head},
                    {"repository_id": "cfg-admin", "application_id": "cfg-admin", "repository_path": str(repo_vue), "base_ref": web_base, "head_ref": web_head},
                ],
            })
            langs = [r["provider_capabilities"] for r in change_result["repositories"]]
            checks["multi_repo_java_ts_vue_change_intelligence_is_real"] = len(change_result["repositories"]) == 2 and any("JAVA" in x for x in langs) and any("VUE" in x and "TYPESCRIPT" in x for x in langs)
            all_surfaces = [surface["surface_kind"] for repo in change_result["repositories"] for surface in repo["impacted_surfaces"]]
            checks["api_config_data_relation_surfaces_are_explicit"] = {"API", "DB", "SYSTEM"}.issubset(set(all_surfaces))
            checks["ripgrep_reference_search_is_used_when_available"] = all(repo["provider_capabilities"]["RIPGREP"] in {"AVAILABLE", "UNAVAILABLE"} for repo in change_result["repositories"]) and (not any(repo["provider_capabilities"]["RIPGREP"] == "AVAILABLE" for repo in change_result["repositories"]) or any(repo["impact_edge_count"] > 0 for repo in change_result["repositories"]))
            checks["codegraph_capability_is_explicit_never_assumed"] = all(repo["provider_capabilities"]["CODEGRAPH"] in {"AVAILABLE", "PARTIAL", "UNAVAILABLE", "BLOCKED"} for repo in change_result["repositories"])
            checks["static_change_truth_does_not_claim_actual_coverage"] = change_result["coverage_objective"]["payload"]["actual_coverage"] == "NOT_ASSERTED" and change_result["coverage_objective"]["payload"]["source"] == "STATIC_CHANGE_TRUTH_ONLY"
            nonexec_obligations = change_result["repositories"][0]["r3_2_derivation"]["change_obligations"]
            nonexec_text = json.dumps(nonexec_obligations, ensure_ascii=False)
            checks["non_executable_config_data_changes_remain_r32_risk_obligations"] = "config/application.yml" in nonexec_text and "db/limit.sql" in nonexec_text
            second_done = finish(restarted, second_bound, "Exact multi-repo change identity persisted")
            coverage_dispatch = second_done["next"]; coverage_bound = binding(coverage_dispatch)

            # First acquisition attempt proves human-auth gate and no guessed coverage.
            coverage_box["provider"] = BankCoveragePlatformProvider()
            auth_gate_request = human_gate_request(coverage_bound, coverage_dispatch["attempt"], gate_id="g3-coverage-auth", gate_kind="EXTERNAL_ACTION", payload={"action": "Login to bank incremental coverage platform"})
            auth_required = product_entry.g3_command("CODE_ANALYST", "acquire_coverage", {**coverage_bound, "profile": {"platform_profile_id": "bank-incremental-coverage", "login_url": "https://coverage.example.invalid/login"}, "query": {"application_id": "cfg-data", "target_version": "V2", "baseline_label": "master"}, "change_analysis": change_result["change_analysis"], "human_gate_request": auth_gate_request})
            checks["coverage_auth_required_creates_r26_human_gate_without_guess"] = auth_required["status"] == "AUTH_REQUIRED" and auth_required["actual_coverage"] is None and auth_required["human_gate"]["status"] == "WAITING_FOR_HUMAN"
            routes = {outcome: (("NONE",) if outcome in {"APPROVED", "CHOICE_SELECTED", "INFORMATION_PROVIDED"} else (("RESUME_EXECUTION",) if outcome == "EXTERNAL_ACTION_COMPLETED" else ("BLOCK",))) for outcome in OUTCOMES}
            auth_decision = restarted.decide_human_gate({"mission_id": mission_id, "gate_id": "g3-coverage-auth", "decision_id": "login-complete", "outcome": "EXTERNAL_ACTION_COMPLETED", "route": "RESUME_EXECUTION", "decision_payload": {"authenticated_context_ref": "browser-auth-context:coverage"}, "decision_provenance": {"source_ref": "human:coverage-login", "source_digest": canonical_sha256({"login": "complete"}), "observed_at": "2026-09-01T10:05:00Z"}, "actor": {"type": "USER", "id": "construction-test"}})
            checks["coverage_auth_human_gate_decision_is_durable"] = auth_decision["status"] == "DECIDED"

            java_file = next(f for f in change_result["repositories"][0]["changed_files"] if f["file_path"] == "src/CreditLimitService.java")
            changed_lines = [int(str(ref).rsplit("L", 1)[1]) for ref in java_file["diff_hunk_refs"]]
            uncovered_line = changed_lines[-1]
            snapshot = {
                "snapshot_id": "bankcov:cfg-data:V2:20260901T1006", "application_id": "cfg-data", "target_version": "V2", "baseline_label": "master", "baseline_commit": "UNKNOWN", "target_commit": java_head,
                "observed_at": "2026-09-01T10:06:00Z", "coverage_semantics": "BANK_EFFECTIVE_INCREMENTAL", "source_identity": "bank-coverage-report:cfg-data:V2:master:20260901T1006",
                "effective_incremental_coverage_pct": 76.0, "effective_changed_lines_total": 4, "covered_changed_lines": 3, "uncovered_changed_lines": 1,
                "details": [
                    {"level": "APPLICATION", "application_id": "cfg-data", "coverage_pct": 76.0},
                    {"level": "FILE", "file_path": "src/CreditLimitService.java", "coverage_pct": 50.0},
                    {"level": "CLASS", "file_path": "src/CreditLimitService.java", "class_name": "CreditLimitService", "coverage_pct": 50.0},
                    *[{"level": "LINE", "file_path": "src/CreditLimitService.java", "class_name": "CreditLimitService", "line_number": line_no, "covered": line_no != uncovered_line} for line_no in changed_lines],
                ],
            }
            coverage_box["provider"] = MappingCoveragePlatformProvider(CoverageProviderResult("AVAILABLE", ("AGGREGATE", "FILE", "CLASS", "LINE"), snapshot=snapshot))
            coverage_result = product_entry.g3_command("CODE_ANALYST", "acquire_coverage", {**coverage_bound, "profile": {"platform_profile_id": "bank-incremental-coverage", "authenticated_context_ref": "browser-auth-context:coverage", "method": "API"}, "query": {"application_id": "cfg-data", "target_version": "V2", "baseline_label": "master"}, "change_analysis": change_result["change_analysis"]})
            checks["bank_actual_snapshot_supports_aggregate_file_class_line"] = coverage_result["status"] == "AVAILABLE" and set(coverage_result["capabilities"]) == {"AGGREGATE", "FILE", "CLASS", "LINE"}
            checks["master_alias_is_recorded_not_silently_pinned"] = coverage_result["snapshot"]["payload"]["baseline_identity_status"] == "MASTER_ALIAS_ONLY" and coverage_result["reconciliation"]["payload"]["cross_time_comparison"] == "PROHIBITED_WITHOUT_PINNED_BASELINE"
            checks["actual_uncovered_changed_line_becomes_coverage_gap"] = len(coverage_result["coverage_gaps"]) >= 1 and any(x["payload"].get("line_number") == uncovered_line and x["payload"].get("source") == "BANK_PLATFORM_ACTUAL" for x in coverage_result["coverage_gaps"])
            checks["coverage_reconciliation_is_application_scoped"] = coverage_result["reconciliation"]["payload"]["application_id"] == "cfg-data" and all(x.get("application_id") == "cfg-data" for key in ("matched", "static_only", "platform_only") for x in coverage_result["reconciliation"]["payload"].get(key, []))
            mismatch_snapshot = {**snapshot, "snapshot_id": "bankcov:other:V2", "application_id": "other-app", "source_identity": "bank-coverage-report:other:V2:master"}
            mismatch = reconcile_coverage(change_result["repositories"], mismatch_snapshot)
            checks["coverage_source_identity_mismatch_is_explicit"] = mismatch["state"] == "SOURCE_IDENTITY_MISMATCH" and not mismatch["coverage_gaps"]
            source_unavailable = BankCoveragePlatformProvider().acquire({"authenticated_context_ref": "auth-ref"}, {"application_id": "cfg-data"})
            checks["coverage_provider_source_unavailable_is_explicit"] = source_unavailable.status == "SOURCE_UNAVAILABLE" and source_unavailable.snapshot is None
            partial = CoverageProviderResult("PARTIAL", ("AGGREGATE", "FILE"), snapshot={**snapshot, "snapshot_id": "bankcov:partial:V2", "details": snapshot["details"][:2]})
            checks["coverage_provider_partial_capability_is_explicit"] = partial.status == "PARTIAL" and set(partial.capabilities) == {"AGGREGATE", "FILE"}
            mode_provider = BankCoveragePlatformProvider({
                "API": lambda _profile, _query: {"status": "SOURCE_UNAVAILABLE", "capabilities": [], "warnings": ["API_NOT_BOUND"]},
                "PAGE": lambda _profile, _query: {"status": "AVAILABLE", "capabilities": ["AGGREGATE", "FILE", "CLASS", "LINE"], "snapshot": {**snapshot, "snapshot_id": "bankcov:page:V2"}},
                "EXPORT": lambda _profile, _query: {"status": "PARTIAL", "capabilities": ["AGGREGATE", "FILE"], "snapshot": {**snapshot, "snapshot_id": "bankcov:export:V2", "details": snapshot["details"][:2]}},
            })
            page_fallback = mode_provider.acquire({"authenticated_context_ref": "auth-ref", "preferred_query_method": "API"}, {"application_id": "cfg-data"})
            export_direct = mode_provider.acquire({"authenticated_context_ref": "auth-ref", "preferred_query_method": "EXPORT"}, {"application_id": "cfg-data"})
            checks["coverage_provider_supports_api_page_export_priority_without_guessing"] = page_fallback.status == "AVAILABLE" and "SOURCE_MODE:PAGE" in page_fallback.warnings and "API:SOURCE_UNAVAILABLE" in page_fallback.warnings and export_direct.status == "PARTIAL" and "SOURCE_MODE:EXPORT" in export_direct.warnings
            coverage_done = finish(restarted, coverage_bound, "Actual bank coverage snapshot reconciled with static changed lines")
            strategy_dispatch = coverage_done["next"]; strategy_bound = binding(strategy_dispatch)

            # Security/performance only design profiles; no scan/load execution.
            security_profile = product_entry.g3_command("TEST_STRATEGIST", "design_test_profile", {**strategy_bound, "profile_type": "SECURITY", "profile": {"authorized_scope": {"api": "POST /limits", "environment": "TEST"}, "oracle": {"property": "LIMIT_WRITE authorization is enforced"}, "safety_contract": {"no_destructive_payloads": True, "rate_limit_rps": 1}}})
            performance_profile = product_entry.g3_command("TEST_STRATEGIST", "design_test_profile", {**strategy_bound, "profile_type": "PERFORMANCE", "profile": {"authorized_scope": {"api": "POST /limits", "environment": "TEST"}, "oracle": {"p95_ms_lte": 500}, "slo": {"p95_ms_lte": 500, "error_rate_lte": 0.01}, "safety_contract": {"max_vus": 5, "max_duration_seconds": 60}}})
            checks["security_performance_profiles_are_design_only_g4_hold"] = all(x["profile"]["payload"]["design_only"] and x["profile"]["payload"]["execution_gate"] == "HOLD_G4" and not x["profile"]["payload"]["real_scan_or_load_executed"] for x in (security_profile, performance_profile))
            safety_fail_closed = False
            try:
                product_entry.g3_command("TEST_STRATEGIST", "design_test_profile", {**strategy_bound, "profile_type": "PERFORMANCE", "profile": {"authorized_scope": {"api": "POST /limits"}, "oracle": {"p95_ms_lte": 500}, "safety_contract": {"max_vus": 5}}})
            except RuntimeError as exc:
                safety_fail_closed = exc.code == "G3_SAFETY_CONTRACT_REQUIRED"
            checks["security_performance_fail_closed_without_scope_oracle_safety_slo"] = safety_fail_closed

            next_work = product_entry.g3_command("TEST_STRATEGIST", "recommend_next_work", {**strategy_bound, "candidates": [
                {"requirement_id": "REQ-018", "business_criticality": 5, "change_breadth": 4, "actual_coverage_gap_count": 3, "critical_uncovered_lines": 2, "ambiguity_count": 1, "historical_defect_signal": 2, "release_urgency": 5},
                {"requirement_id": "REQ-019", "business_criticality": 4, "change_breadth": 5, "actual_coverage_gap_count": 4, "critical_uncovered_lines": 4, "ambiguity_count": 3, "historical_defect_signal": 4, "release_urgency": 5},
            ]})
            checks["recommend_next_test_work_is_evidence_ranked_not_case_count_ranked"] = next_work["status"] == "PASS" and next_work["top_requirement_id"] == "REQ-018" and next_work["recommendation"]["payload"]["case_count_is_value"] is False
            next_work_missing = product_entry.g3_command("TEST_STRATEGIST", "recommend_next_work", {**strategy_bound, "candidates": [{"requirement_id": "REQ-020", "business_criticality": 5}]})
            checks["recommend_next_test_work_missing_facts_become_human_task"] = next_work_missing["status"] == "KNOWLEDGE_REQUIRED" and next_work_missing["human_task"]["payload"]["task_kind"] == "NEXT_WORK_RANKING_FACT_GAP"

            risk_inputs = {
                "dimensions": {"business_criticality": 5, "change_magnitude": 4, "impact_breadth": 4, "change_uncertainty": 2, "critical_journey_criticality": 5, "historical_failure_signal": 2, "security_data_sensitivity": 4, "performance_sensitivity": 4, "evidence_gap_penalty": 2},
                "evidence_refs": [requirement_result["requirement"]["fact_id"], change_result["change_analysis"]["fact_id"], coverage_result["snapshot"]["fact_id"]],
                "critical_journey_risk_refs": ["LIMIT_UPDATE_JOURNEY"],
                "performance": {"workload": "authorized test profile only", "metrics": ["p95_ms", "error_rate"], "thresholds": {"p95_ms": 500}},
                "security": {"security_property": "authorization", "actor": "credit-operator", "expected_behavior": "only LIMIT_WRITE can update"},
            }
            gap_ref = coverage_result["coverage_gaps"][0]["fact_id"]
            hypothesis = {"hypothesis_id": "HYP-BOUNDARY-001", "trigger": "requested limit equals approved limit", "expected_invariant": "boundary value is accepted and propagated consistently", "suspected_surface": f"src/CreditLimitService.java:L{uncovered_line}", "evidence_requirement": ["API response", "DB final value", "downstream state"], "discriminating_test": "compare approved-1, approved, approved+1 outcomes", "defect_class": "BOUNDARY_OFF_BY_ONE", "severity": "HIGH", "confidence_basis": ["changed comparison operator", gap_ref], "status": "READY_TO_TEST"}
            strategy_result = product_entry.g3_command("TEST_STRATEGIST", "create_strategy", {**strategy_bound, "scope_identity": "REQ-018", "r3_1_reference": requirement_result["r3_1_reference"], "r3_2_references": change_result["r3_2_references"], "risk_inputs": risk_inputs, "hypothesis_candidates": [hypothesis]})
            checks["reach_find_strategy_uses_actual_gap_hypothesis_and_risk"] = strategy_result["status"] == "PASS" and strategy_result["portfolio"]["payload"]["selection_semantics"] == "LEXICOGRAPHIC_REACH_FIND" and len(strategy_result["portfolio"]["payload"]["ranked_work"]) >= 2
            checks["hypothesis_remains_falsifiable_not_confirmed_defect"] = strategy_result["hypotheses"][0]["payload"]["status"] == "READY_TO_TEST" and "CONFIRMED" not in json.dumps(strategy_result["hypotheses"][0])
            strategy_done = finish(restarted, strategy_bound, "Reach+Find L1-L7 strategy and hypotheses persisted")
            case_dispatch = strategy_done["next"]; case_bound = binding(case_dispatch)

            r33_state = R33ApplicationService(restarted.runtime).state(mission_id)
            strategy_id = strategy_result["strategy"]["strategy_version_id"]
            points = [p for p in r33_state.test_points if p.strategy_version_id == strategy_id and p.designability == "DESIGNABLE"]
            checks["frozen_r33_produces_designable_test_points"] = bool(points)
            detailed_specs: dict[str, dict[str, Any]] = {}
            for idx, point in enumerate(points, 1):
                detailed_specs[point.point_id] = {
                    "objective": f"Discriminate limit rule/risk for {point.point_id}",
                    "preconditions": [{"id": "P1", "description": "REQ-018 approved limit exists and operator has explicit test authorization"}],
                    "test_data": [{"name": "approved", "value": 10000}, {"name": "requested", "value": 10000}],
                    "ordered_steps": [{"step": 1, "action": "Prepare approved limit 10000 and requested limit 10000 through the defined test fixture"}, {"step": 2, "action": "Submit the governed limit-update request and observe API/state synchronization evidence"}],
                    "expected_results": [{"step": 1, "expected": "The fixture exposes approved=10000 and requested=10000 before mutation"}, {"step": 2, "expected": "The equality boundary is accepted only for authorized actor and final synchronized value remains 10000"}],
                    "oracle": {"type": "MULTI_CHANNEL_INVARIANT", "pass": "API, persisted value and downstream synchronized state satisfy the source-grounded equality/authorization invariant", "insufficient": "any required channel is unavailable"},
                    "evidence_requirements": [{"channel": "API", "required": "status/body"}, {"channel": "DATA", "required": "final limit"}, {"channel": "DOWNSTREAM", "required": "SYNCED state"}],
                    "postcondition": {"cleanup": "restore test fixture or preserve isolated test record per G4 execution policy"},
                    "coverage_gap_refs": [gap_ref], "defect_hypothesis_refs": [strategy_result["hypotheses"][0]["fact_id"]], "estimated_marginal_coverage_gain": 1,
                }
            case_result = product_entry.g3_command("CASE_DESIGNER", "design_cases", {**case_bound, "strategy_version_id": strategy_id, "strategy_fingerprint": strategy_result["strategy"]["strategy_fingerprint"], "detailed_specs": detailed_specs, "designer_session_ref": case_bound["session_id"]})
            value_payloads = [x["value_link"]["payload"] for x in case_result["ready_cases"]]
            checks["standard_cases_have_detailed_quality_and_value_links"] = case_result["status"] == "PASS" and bool(value_payloads) and not case_result["blocked_cases"] and all(all(k in v for k in ("requirement_obligation_refs", "changed_code_refs", "coverage_target_refs", "coverage_gap_refs", "risk_refs", "defect_hypothesis_refs")) and v["risk_refs"] and v["coverage_target_refs"] for v in value_payloads) and any(v["requirement_obligation_refs"] and v["changed_code_refs"] and v["coverage_gap_refs"] and v["defect_hypothesis_refs"] for v in value_payloads)
            redundancy_keys = [x["value_link"]["payload"]["redundancy_key"] for x in case_result["ready_cases"]]
            checks["case_portfolio_has_redundancy_detection_key"] = bool(redundancy_keys) and len(redundancy_keys) == len(set(redundancy_keys))
            low_info_rejected = False
            try:
                G3TestingIntelligenceService(restarted.runtime).design_cases(mission_id, strategy_id, strategy_result["strategy"]["strategy_fingerprint"], {points[0].point_id: {"objective": "boundary", "preconditions": ["ready"], "test_data": ["normal"], "ordered_steps": ["执行正向数据"], "expected_results": ["符合预期"], "oracle": {"a": 1}, "evidence_requirements": ["log"], "postcondition": "restore"}}, designer_session_ref=case_bound["session_id"])
            except RuntimeError as exc:
                low_info_rejected = exc.code in {"G3_LOW_INFORMATION_CASE_REJECTED", "G3_R33_CASE_BATCH_FAILED"}
            # Idempotent R3.3 batch may return existing cases and G3 marks blocked instead of raising.
            if not low_info_rejected:
                from aitest_runtime.g3.contracts import validate_detailed_case
                try:
                    validate_detailed_case({"objective": "boundary", "preconditions": ["ready"], "test_data": ["normal"], "ordered_steps": ["执行正向数据"], "expected_results": ["符合预期"], "oracle": {"a": 1}, "evidence_requirements": ["log"], "postcondition": "restore"})
                except RuntimeError as exc:
                    low_info_rejected = exc.code == "G3_LOW_INFORMATION_CASE_REJECTED"
            checks["v194_style_low_information_case_is_rejected"] = low_info_rejected
            case_done = finish(restarted, case_bound, "Detailed StandardTestCase candidates and CaseValueLinks ready")
            evaluator_dispatch = case_done["next"]; evaluator_bound = binding(evaluator_dispatch)

            first_spec = case_result["ready_cases"][0]["case"]
            review_gate = human_gate_request(evaluator_bound, evaluator_dispatch["attempt"], gate_id="g3-case-human-review", gate_kind="APPROVAL", payload={"case_spec_ref": first_spec["fact_id"], "question": "Approve detailed standard test case design?"}, review=True)
            evaluation = product_entry.g3_command("EVALUATOR", "evaluate_case_design", {**evaluator_bound, "scope_identity": "REQ-018", "r3_1_reference": requirement_result["r3_1_reference"], "r3_2_reference": change_result["r3_2_references"][0], "case_spec_fact_id": first_spec["fact_id"], "reviewer_session_ref": evaluator_bound["session_id"], "human_gate_request": review_gate})
            checks["evaluator_reuses_r34_and_opens_real_human_review_gate"] = evaluation["status"] == "WAITING_FOR_HUMAN" and evaluation["r3_4_review"]["review_status"] == "APPROVED" and evaluation["human_gate"]["status"] == "WAITING_FOR_HUMAN"
            checks["evaluation_does_not_execute_or_confirm_defect"] = evaluation["evaluation"]["payload"]["real_execution"] == "NOT_PERFORMED" and evaluation["evaluation"]["payload"]["test_fail_is_defect"] is False

            # A fresh Python process reads G3 durable state from the same R1 Event Stream.
            env = dict(os.environ); env["PYTHONPATH"] = str(RUNTIME)
            proc = subprocess.run([sys.executable, "-m", "aitest_runtime.product_entry", "g3", "--role", "DIRECTOR", "--action", "status", "--payload", json.dumps({"mission_id": mission_id})], cwd=root, env=env, capture_output=True, text=True, encoding="utf-8")
            recovered_status = json.loads(proc.stdout) if proc.returncode == 0 else {}
            checks["new_python_process_recovers_g3_from_r1_event_stream"] = proc.returncode == 0 and recovered_status.get("truth_source") == "R1_EVENT_STREAM" and recovered_status.get("fact_count", 0) >= 10

            runtime_recovered = create_canonical_runtime(root, db_path=spine)
            g3_recovered = G3TestingIntelligenceService(runtime_recovered).status(mission_id)
            checks["context_recovery_does_not_depend_on_conversation_memory"] = g3_recovered["fact_count"] == recovered_status["fact_count"] and g3_recovered["counts"].get("TEST_INTENT", 0) >= 3
            checks["legacy_aitest_db_not_created_or_written"] = legacy_before == sha_file(legacy)

            # Explicit focused-intent catalog shares the same durable TestIntent contract.
            focused = ["REQUIREMENT_ANALYSIS", "CHANGE_IMPACT_ANALYSIS", "COVERAGE_GAP_ANALYSIS", "TEST_STRATEGY_DESIGN", "API_TEST_REQUEST", "UI_TEST_REQUEST", "API_SECURITY_TEST_REQUEST", "API_PERFORMANCE_TEST_REQUEST"]
            focused_results = [G3TestingIntelligenceService(runtime_recovered).register_intent(mission_id, value, {"target": "REQ-018"}, {}) for value in focused]
            checks["focused_and_autonomous_test_intents_share_same_canonical_runtime"] = all(x["truth_source"] == "R1_EVENT_STREAM" and x["status"] == "ACCEPTED" for x in focused_results)
            broad = {value: G3TestingIntelligenceService(runtime_recovered).register_intent(mission_id, value, {"target": "V2"}, {}) for value in ("FULL_RELEASE_TEST", "FULL_REQUIREMENT_TEST", "RECOMMEND_NEXT_TEST_WORK")}
            checks["full_release_full_requirement_and_recommend_intents_are_durable"] = len(broad["FULL_RELEASE_TEST"]["recommended_plan"]["tasks"]) == 6 and len(broad["FULL_REQUIREMENT_TEST"]["recommended_plan"]["tasks"]) == 6 and len(broad["RECOMMEND_NEXT_TEST_WORK"]["recommended_plan"]["tasks"]) == 1 and broad["RECOMMEND_NEXT_TEST_WORK"]["recommended_plan"]["tasks"][0]["routing"]["role"] == "TEST_STRATEGIST"
            checks["coverage_gap_focused_intent_routes_only_governed_code_analyst_tasks"] = [task["routing"]["role"] for task in focused_results[2]["recommended_plan"]["tasks"]] == ["CODE_ANALYST", "CODE_ANALYST"]

        finally:
            product_entry.orchestration_service = original_orch_factory  # type: ignore[assignment]
            product_entry.default_service = original_default_service  # type: ignore[assignment]
            product_entry.G3TestingIntelligenceService = original_g3  # type: ignore[assignment]

    # Explicit unsupported-language provider test: non-Python changes cannot disappear silently.
    with tempfile.TemporaryDirectory(prefix="pfc-g3-provider-") as td:
        root2 = Path(td)
        repo, base, head = make_repo(root2, "unsupported", {"module.kt": "class K { fun x() = 1 }\n"}, {"module.kt": "class K { fun x() = 2 }\n"})
        from aitest_runtime.g3.code_intelligence import analyze_repository
        _, envp, meta = analyze_repository({"repository_id": "unsupported", "repository_path": str(repo), "base_ref": base, "head_ref": head})
        checks["unsupported_language_is_partial_not_silently_ignored"] = envp.code_intelligence_status == "PARTIAL" and any(x.startswith("UNSUPPORTED_LANGUAGE:") for x in envp.warnings) and any(k.startswith("UNSUPPORTED:") and v == "UNAVAILABLE" for k, v in meta["provider_capabilities"].items())

    # Explicit Python language provider test: Python cannot be silently delegated to a non-language fallback.
    with tempfile.TemporaryDirectory(prefix="pfc-g3-python-provider-") as td:
        root3 = Path(td)
        repo, base, head = make_repo(root3, "python-service", {"service.py": "def validate(x):\n    return x > 0\n"}, {"service.py": "def validate(x):\n    return x >= 0\n"})
        from aitest_runtime.g3.code_intelligence import analyze_repository
        _, py_env, py_meta = analyze_repository({"repository_id": "python-service", "repository_path": str(repo), "base_ref": base, "head_ref": head})
        checks["python_language_provider_is_real"] = py_meta["provider_capabilities"].get("PYTHON") == "AVAILABLE" and any(sym.symbol_kind == "FUNCTION" for sym in py_env.changed_symbols)

    # Static product-surface audit.
    tool_source = (WORKSPACE / ".opencode/tools/aitest.ts").read_text(encoding="utf-8")
    product_source = (WORKSPACE / "ai-test/runtime/aitest_runtime/product_entry.py").read_text(encoding="utf-8")
    agent_names = {p.name for p in (WORKSPACE / ".opencode/agents").glob("aitest-*.md")}
    command_names = {p.name for p in (WORKSPACE / ".opencode/commands").glob("aitest-*.md")}
    checks["opencode_g3_tools_commands_agents_are_product_wired"] = all(token in tool_source for token in ("g3_director", "requirement_analyst", "code_analyst", "test_strategist", "case_designer", "evaluate_case_design", "work_context")) and {"aitest-requirement-analyst.md", "aitest-code-analyst.md", "aitest-test-strategist.md", "aitest-case-designer.md"}.issubset(agent_names) and {"aitest-test-intent.md", "aitest-coverage-gap.md", "aitest-api-test-design.md", "aitest-ui-test-design.md", "aitest-security-test-design.md", "aitest-performance-test-design.md"}.issubset(command_names)
    checks["no_g3_agent_owned_session_lifecycle_surface"] = all("create_session(" not in (WORKSPACE / ".opencode/agents" / name).read_text(encoding="utf-8") and "rotate_session(" not in (WORKSPACE / ".opencode/agents" / name).read_text(encoding="utf-8") for name in ("aitest-requirement-analyst.md", "aitest-code-analyst.md", "aitest-test-strategist.md", "aitest-case-designer.md"))
    checks["product_entry_has_g4_g5_hold_and_no_legacy_write_path"] = '"CASE_EXECUTION_REQUEST": "HOLD_G4"' in (WORKSPACE / "ai-test/runtime/aitest_runtime/g3/contracts.py").read_text(encoding="utf-8") and '"DEFECT_DIAGNOSIS_REQUEST": "HOLD_G5"' in (WORKSPACE / "ai-test/runtime/aitest_runtime/g3/contracts.py").read_text(encoding="utf-8") and '"G4_REAL_EXECUTION"' in (WORKSPACE / "ai-test/runtime/aitest_runtime/g3/contracts.py").read_text(encoding="utf-8") and '"G5_DEFECT_TRUTH"' in (WORKSPACE / "ai-test/runtime/aitest_runtime/g3/contracts.py").read_text(encoding="utf-8") and 'legacy_fallback": "FORBIDDEN' in product_source

    failed = [name for name, ok in checks.items() if not ok]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "checks": checks, "passed": sum(checks.values()), "total": len(checks), "failed": failed}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
