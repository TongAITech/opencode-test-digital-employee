from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, RuntimeError, RuntimeService, canonical_sha256
from aitest_runtime.r3_2.contracts import ChangeImpactRequest, R31Reference
from aitest_runtime.r3_2.providers import MappingCodeIntelligenceProvider
from aitest_runtime.r3_2.service import R32ApplicationService
from aitest_runtime.r3_3.contracts import BatchDesignRequest, R32Reference as R33R32Reference, StrategyRequest, RISK_DIMENSIONS
from aitest_runtime.r3_3.engine import build_risk_vector
from aitest_runtime.r3_3.service import R33ApplicationService
from aitest_runtime.r3_4.service import R34ApplicationService

from .code_intelligence import analyze_repository
from .contracts import (
    EXTENSION_ID, G3State, HOLD_INTENTS, RECORD_FACT, validate_defect_hypothesis,
    validate_detailed_case, validate_test_intent,
)
from .coverage import BankCoveragePlatformProvider, CoveragePlatformProvider, reconcile_coverage
from .requirement import derive_requirement_intelligence

G3_SCHEMA = "aitest.g3.testing-intelligence.v1"

ROLE_CAPABILITIES = {
    "REQUIREMENT_ANALYST": ("OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT", "G3_REQUIREMENT_INTELLIGENCE"),
    "CODE_ANALYST": ("OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT", "G3_CODE_INTELLIGENCE", "G3_BANK_COVERAGE_READ"),
    "TEST_STRATEGIST": ("OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT", "G3_TEST_STRATEGY"),
    "CASE_DESIGNER": ("OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT", "G3_CASE_DESIGN"),
    "EVALUATOR": ("OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"),
}
ROLE_AGENTS = {
    "REQUIREMENT_ANALYST": "aitest-requirement-analyst",
    "CODE_ANALYST": "aitest-code-analyst",
    "TEST_STRATEGIST": "aitest-test-strategist",
    "CASE_DESIGNER": "aitest-case-designer",
    "EVALUATOR": "aitest-evaluator",
}


def recommended_plan(intent_type: str) -> dict[str, Any]:
    intent = str(intent_type).upper()
    task_sets = {
        "FULL_RELEASE_TEST": [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST"), ("coverage-gap-analysis", "CODE_ANALYST"), ("test-strategy", "TEST_STRATEGIST"), ("case-design", "CASE_DESIGNER"), ("design-evaluation", "EVALUATOR")],
        "FULL_REQUIREMENT_TEST": [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST"), ("coverage-gap-analysis", "CODE_ANALYST"), ("test-strategy", "TEST_STRATEGIST"), ("case-design", "CASE_DESIGNER"), ("design-evaluation", "EVALUATOR")],
        "RECOMMEND_NEXT_TEST_WORK": [("recommend-next-test-work", "TEST_STRATEGIST")],
        "REQUIREMENT_ANALYSIS": [("requirement-analysis", "REQUIREMENT_ANALYST")],
        "CHANGE_IMPACT_ANALYSIS": [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST")],
        "COVERAGE_GAP_ANALYSIS": [("change-analysis", "CODE_ANALYST"), ("coverage-gap-analysis", "CODE_ANALYST")],
        "TEST_STRATEGY_DESIGN": [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST"), ("coverage-gap-analysis", "CODE_ANALYST"), ("test-strategy", "TEST_STRATEGIST")],
        "TEST_CASE_DESIGN": [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST"), ("coverage-gap-analysis", "CODE_ANALYST"), ("test-strategy", "TEST_STRATEGIST"), ("case-design", "CASE_DESIGNER"), ("design-evaluation", "EVALUATOR")],
        "API_TEST_REQUEST": [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST"), ("test-strategy", "TEST_STRATEGIST"), ("case-design", "CASE_DESIGNER"), ("design-evaluation", "EVALUATOR")],
        "UI_TEST_REQUEST": [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST"), ("test-strategy", "TEST_STRATEGIST"), ("case-design", "CASE_DESIGNER"), ("design-evaluation", "EVALUATOR")],
        "API_SECURITY_TEST_REQUEST": [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST"), ("security-profile", "TEST_STRATEGIST"), ("case-design", "CASE_DESIGNER"), ("design-evaluation", "EVALUATOR")],
        "API_PERFORMANCE_TEST_REQUEST": [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST"), ("performance-profile", "TEST_STRATEGIST"), ("case-design", "CASE_DESIGNER"), ("design-evaluation", "EVALUATOR")],
    }
    default = [("requirement-analysis", "REQUIREMENT_ANALYST"), ("change-analysis", "CODE_ANALYST"), ("coverage-gap-analysis", "CODE_ANALYST"), ("test-strategy", "TEST_STRATEGIST"), ("case-design", "CASE_DESIGNER"), ("design-evaluation", "EVALUATOR")]
    selected = task_sets.get(intent, default)
    tasks: list[dict[str, Any]] = []
    deps: list[dict[str, str]] = []
    for index, (key, role) in enumerate(selected, 1):
        tasks.append({
            "task_key": key,
            "intent": f"G3 {key.replace('-', ' ')} for {intent}",
            "acceptance_criteria": [{"id": f"g3-{key}-evidence", "description": "Result is evidence-bound, durable in R1, and preserves G4/G5 HOLD boundaries"}],
            "routing": {"role": role, "agent_name": ROLE_AGENTS[role], "required_capabilities": list(ROLE_CAPABILITIES[role]), "isolation_policy": "TASK_SCOPED", "parallelism_policy": "SERIAL"},
        })
        if index > 1: deps.append({"from": selected[index-2][0], "to": key})
    return {"objective": f"Execute governed G3 testing intelligence for {intent}", "constraints": [{"kind": "RUNTIME_TRUTH", "value": "R1_EVENT_STREAM_ONLY"}, {"kind": "EXECUTION_BOUNDARY", "value": "G4_HOLD"}, {"kind": "DEFECT_TRUTH_BOUNDARY", "value": "G5_HOLD"}], "tasks": tasks, "dependencies": deps}



class G3TestingIntelligenceService:
    def __init__(self, runtime: RuntimeService, *, coverage_provider: CoveragePlatformProvider | None = None, orchestration: Any | None = None, actor: ActorRef | None = None) -> None:
        runtime.extension_registry.manifest(EXTENSION_ID)
        self.runtime = runtime
        self.coverage_provider = coverage_provider or BankCoveragePlatformProvider()
        self.orchestration = orchestration
        self.actor = actor or ActorRef("SYSTEM", "g3-testing-intelligence")

    def state(self, mission_id: str) -> G3State:
        value = self.runtime.replay_composed(mission_id).extension_state(EXTENSION_ID)
        if not isinstance(value, G3State): raise RuntimeError("G3_STATE_INVALID", mission_id)
        return value

    def _record(self, mission_id: str, fact_kind: str, payload: Mapping[str, Any], *, provenance_refs: list[str] | tuple[str, ...] = (), fact_id: str | None = None) -> dict[str, Any]:
        semantic = {"kind": fact_kind, "mission_id": mission_id, "payload": dict(payload), "provenance_refs": list(provenance_refs)}
        fact_id = fact_id or f"g3:{fact_kind.lower()}:{canonical_sha256(semantic)[:24]}"
        existing = self.state(mission_id).by_id(fact_id)
        if existing is not None:
            return existing.to_dict()
        command_id = f"g3:record:{fact_id}"
        result = self.runtime.execute({
            "command_id": command_id, "type": RECORD_FACT, "mission_id": mission_id, "session_id": None,
            "expected_seq": self.runtime.get_head_seq(mission_id), "actor": self.actor.to_dict(),
            "payload": {"fact_id": fact_id, "fact_kind": fact_kind, "payload": dict(payload), "provenance_refs": list(provenance_refs)},
            "idempotency_key": f"g3:fact:{fact_id}", "correlation_id": command_id, "schema_version": 1,
        })
        if not result.ok: raise result.error or RuntimeError("G3_DURABLE_WRITE_FAILED", fact_id)
        fact = self.state(mission_id).by_id(fact_id)
        if fact is None: raise RuntimeError("G3_FACT_NOT_REPLAYABLE", fact_id)
        return fact.to_dict()

    def status(self, mission_id: str) -> dict[str, Any]:
        state = self.state(mission_id)
        counts: dict[str, int] = {}
        for fact in state.facts: counts[fact.fact_kind] = counts.get(fact.fact_kind, 0) + 1
        return {"schema_version": G3_SCHEMA, "status": "PASS", "truth_source": "R1_EVENT_STREAM", "mission_id": mission_id, "fact_count": len(state.facts), "counts": counts, "g4_real_execution": "HOLD", "g5_defect_truth": "HOLD", "legacy_aitest_db_write": "FORBIDDEN"}

    def work_context(self, mission_id: str) -> dict[str, Any]:
        """Recover specialist input from durable G3 facts, never conversation memory.

        The latest fact of each product kind is exposed as a governed ContextPack
        supplement.  Payload validation at record time already rejects credential/
        secret-shaped fields, so this read surface cannot become a password store.
        """
        state = self.state(mission_id)
        latest: dict[str, dict[str, Any]] = {}
        for fact in state.facts:
            latest[fact.fact_kind] = fact.to_dict()
        test_intents = [fact.to_dict() for fact in state.by_kind("TEST_INTENT")]
        active_test_intent = next((item for item in reversed(test_intents) if item.get("payload", {}).get("status") == "ACCEPTED"), None)
        return {
            "schema_version": G3_SCHEMA,
            "status": "PASS",
            "truth_source": "R1_EVENT_STREAM",
            "conversation_is_not_truth": True,
            "mission_id": mission_id,
            "fact_count": len(state.facts),
            "active_test_intent": active_test_intent,
            "test_intents": test_intents,
            "latest": latest,
            "g4_real_execution": "HOLD",
            "g5_defect_truth": "HOLD",
        }

    def register_intent(self, mission_id: str, intent_type: str, scope: Mapping[str, Any], constraints: Mapping[str, Any] | None = None) -> dict[str, Any]:
        intent = validate_test_intent(intent_type, scope, constraints)
        plan = None if intent["status"] == "HOLD" else recommended_plan(intent["intent_type"])
        fact = self._record(mission_id, "TEST_INTENT", {**intent, "recommended_plan": plan}, provenance_refs=("user:test-intent",))
        return {"schema_version": G3_SCHEMA, "status": intent["status"], "gate": intent.get("gate"), "hold_code": intent.get("hold_code"), "intent": fact, "recommended_plan": fact["payload"]["recommended_plan"], "truth_source": "R1_EVENT_STREAM"}

    def analyze_requirement(self, mission_id: str, scope_identity: str, semantics: Mapping[str, Any]) -> dict[str, Any]:
        result = derive_requirement_intelligence(self.runtime, mission_id, scope_identity, semantics)
        semantic_fact = self._record(mission_id, "REQUIREMENT_SEMANTIC_MODEL", {"scope_identity": scope_identity, **result}, provenance_refs=tuple(str(x) for x in result["semantic_model"]["source_refs"]))
        gaps = []
        for gap in result["knowledge_gaps"]:
            gap_fact = self._record(mission_id, "KNOWLEDGE_GAP", {"scope_identity": scope_identity, **gap}, provenance_refs=(semantic_fact["fact_id"],))
            human = self._record(mission_id, "HUMAN_TASK", {"task_kind": "REQUIREMENT_KNOWLEDGE_GAP", "knowledge_gap_ref": gap_fact["fact_id"], "question": gap["question"], "status": "OPEN"}, provenance_refs=(gap_fact["fact_id"],))
            gaps.append({"gap": gap_fact, "human_task": human})
        return {"status": "PASS" if not gaps else "PARTIAL_KNOWLEDGE_GAPS", "truth_source": "R1_EVENT_STREAM", "requirement": semantic_fact, "knowledge_gaps": gaps, "r3_1_reference": result["r3_1_reference"]}

    def analyze_changes(self, mission_id: str, scope_identity: str, repositories: list[Mapping[str, Any]], r3_1_reference: Mapping[str, Any]) -> dict[str, Any]:
        if not repositories: raise RuntimeError("G3_REPOSITORIES_REQUIRED", "at least one repository is required")
        r31 = R31Reference.from_dict(r3_1_reference)
        analyses = []; refs = []
        for spec in repositories:
            repo_request, envelope, meta = analyze_repository(spec)
            ci = {"provider_id": envelope.provider_id, "provider_version": envelope.provider_version, "requested_capabilities": list(envelope.requested_capabilities), "provider_input_digest": envelope.provider_input_digest}
            request = ChangeImpactRequest(mission_id, scope_identity, repo_request, ci, r31, "g3.change-policy.v1", f"g3-r32:{envelope.provider_input_digest[:24]}", {"type": "AGENT", "id": "aitest-code-analyst"}, f"g3-r32:{meta['repository_id']}")
            result = R32ApplicationService(self.runtime, provider=MappingCodeIntelligenceProvider(envelope)).derive(request)
            if not result.ok or result.derivation is None or result.reconciliation is None:
                raise RuntimeError("G3_R32_DERIVATION_FAILED", result.error_code or meta["repository_id"])
            r32ref = R33R32Reference(result.derivation.derivation_version_id, result.derivation.derivation_fingerprint, result.reconciliation.reconciliation_id, canonical_sha256(result.derivation.identity.compare_identity.to_dict()), canonical_sha256(result.derivation.code_intelligence.to_dict()))
            refs.append(r32ref.to_dict())
            analyses.append({**meta, "application_id": str(spec.get("application_id") or meta["repository_id"]), "changed_files": [x.to_dict() for x in envelope.changed_files], "changed_symbols": [x.to_dict() for x in envelope.changed_symbols], "impact_edges": [x.to_dict() for x in envelope.impact_edges], "impacted_surfaces": [x.to_dict() for x in envelope.impacted_surfaces], "warnings": list(envelope.warnings), "r3_2_reference": r32ref.to_dict(), "r3_2_derivation": result.derivation.to_dict()})
        fact = self._record(mission_id, "MULTI_REPO_CHANGE_ANALYSIS", {"scope_identity": scope_identity, "repositories": analyses, "r3_1_reference": dict(r3_1_reference)}, provenance_refs=tuple(f"r3.2:{x['derivation_version_id']}" for x in refs))
        symbol_truth_obligations = []
        for analysis in analyses:
            for warning in analysis.get("warnings") or []:
                if not str(warning).startswith("MISSING_SYMBOL_MAPPING:"):
                    continue
                path = str(warning).split(":", 1)[1]
                changed_file = next((item for item in analysis.get("changed_files") or [] if item.get("file_path") == path), None)
                symbol_truth_obligations.append({
                    "obligation_kind": "MISSING_SYMBOL_MAPPING", "status": "OPEN",
                    "application_id": analysis["application_id"], "repository_id": analysis["repository_id"], "file_path": path,
                    "changed_line_refs": list((changed_file or {}).get("diff_hunk_refs") or []),
                    "risk_semantics": "FILE_LEVEL_CHANGE_REMAINS_COVERAGE_AND_RISK_OBLIGATION",
                    "resolution_requirement": "RESOLVE_ENCLOSING_SYMBOL_OR_RETAIN_FILE_LINE_LEVEL_TEST_OBLIGATION",
                })
        objective = self._record(mission_id, "CODE_COVERAGE_OBJECTIVE", {
            "scope_identity": scope_identity, "source": "STATIC_CHANGE_TRUTH_ONLY", "actual_coverage": "NOT_ASSERTED",
            "targets": [{"application_id": a["application_id"], "repository_id": a["repository_id"], "changed_files": a["changed_files"], "changed_symbols": a["changed_symbols"], "impacted_surfaces": a["impacted_surfaces"]} for a in analyses],
            "risk_obligations": symbol_truth_obligations,
        }, provenance_refs=(fact["fact_id"],))
        return {"status": "PASS" if all(a["status"] == "COMPLETE" for a in analyses) else "PARTIAL", "truth_source": "R1_EVENT_STREAM", "change_analysis": fact, "coverage_objective": objective, "r3_2_references": refs, "repositories": analyses}

    def acquire_coverage(self, mission_id: str, profile: Mapping[str, Any], query: Mapping[str, Any], *, change_analysis: Mapping[str, Any] | None = None, human_gate_request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        profile_fact = self._record(mission_id, "COVERAGE_PLATFORM_PROFILE", {k: v for k, v in profile.items() if k not in {"authenticated_context_ref"}}, provenance_refs=("bank:incremental-coverage-platform",))
        result = self.coverage_provider.acquire(profile, query)
        if result.status == "AUTH_REQUIRED":
            human = self._record(mission_id, "HUMAN_TASK", {"task_kind": "COVERAGE_PLATFORM_AUTH", "status": "OPEN", "platform_profile_ref": profile_fact["fact_id"], "action": dict(result.human_action or {})}, provenance_refs=(profile_fact["fact_id"],))
            gate = self.orchestration.open_human_gate(dict(human_gate_request)) if self.orchestration is not None and human_gate_request is not None else None
            return {"status": "AUTH_REQUIRED", "truth_source": "R1_EVENT_STREAM", "human_task": human, "human_gate": gate, "actual_coverage": None}
        if result.status == "SOURCE_UNAVAILABLE":
            return {"status": "SOURCE_UNAVAILABLE", "truth_source": "R1_EVENT_STREAM", "actual_coverage": None, "warnings": list(result.warnings)}
        snap = dict(result.snapshot or {})
        snapshot_fact = self._record(mission_id, "INCREMENTAL_COVERAGE_SNAPSHOT", snap, provenance_refs=(profile_fact["fact_id"], str(snap.get("source_identity"))))
        reconciliation = None; gap_facts = []
        if change_analysis is not None:
            repos = list(change_analysis.get("repositories") or change_analysis.get("payload", {}).get("repositories") or [])
            reconciliation = reconcile_coverage(repos, snap)
            rec_fact = self._record(mission_id, "COVERAGE_RECONCILIATION", reconciliation, provenance_refs=(snapshot_fact["fact_id"],))
            for gap in reconciliation["coverage_gaps"]:
                gap_facts.append(self._record(mission_id, "COVERAGE_GAP", gap, provenance_refs=(snapshot_fact["fact_id"], rec_fact["fact_id"])))
            reconciliation = rec_fact
        return {"status": result.status, "truth_source": "R1_EVENT_STREAM", "capabilities": list(result.capabilities), "snapshot": snapshot_fact, "reconciliation": reconciliation, "coverage_gaps": gap_facts, "warnings": list(result.warnings)}

    def create_hypotheses(self, mission_id: str, candidates: list[Mapping[str, Any]], *, source_refs: list[str] | tuple[str, ...] = ()) -> list[dict[str, Any]]:
        output = []
        for value in candidates:
            hypothesis = validate_defect_hypothesis(value)
            output.append(self._record(mission_id, "DEFECT_HYPOTHESIS", hypothesis, provenance_refs=source_refs, fact_id=f"g3:defect-hypothesis:{hypothesis['hypothesis_id']}"))
        return output

    def recommend_next_work(self, mission_id: str, candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
        """Rank next Requirement work lexicographically from explicit evidence only."""
        required = (
            "requirement_id", "business_criticality", "change_breadth", "actual_coverage_gap_count",
            "critical_uncovered_lines", "ambiguity_count", "historical_defect_signal", "release_urgency",
        )
        if not candidates:
            human = self._record(mission_id, "HUMAN_TASK", {"task_kind": "NEXT_WORK_RANKING_FACT_GAP", "status": "OPEN", "missing": ["candidate_requirements"]}, provenance_refs=("g3:recommend-next-work",))
            return {"status": "KNOWLEDGE_REQUIRED", "truth_source": "R1_EVENT_STREAM", "human_task": human}
        normalized = []
        missing_by_requirement: dict[str, list[str]] = {}
        for raw in candidates:
            rid = str(raw.get("requirement_id") or "UNKNOWN")
            missing = [name for name in required if raw.get(name) is None or raw.get(name) == ""]
            if missing:
                missing_by_requirement[rid] = missing
                continue
            item = dict(raw)
            for name in required[1:]:
                value = item[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise RuntimeError("G3_NEXT_WORK_METRIC_INVALID", f"{rid}:{name}")
            normalized.append(item)
        if missing_by_requirement:
            human = self._record(mission_id, "HUMAN_TASK", {"task_kind": "NEXT_WORK_RANKING_FACT_GAP", "status": "OPEN", "missing_by_requirement": missing_by_requirement}, provenance_refs=("g3:recommend-next-work",))
            return {"status": "KNOWLEDGE_REQUIRED", "truth_source": "R1_EVENT_STREAM", "human_task": human, "missing_by_requirement": missing_by_requirement}
        order = ("business_criticality", "critical_uncovered_lines", "actual_coverage_gap_count", "change_breadth", "ambiguity_count", "historical_defect_signal", "release_urgency")
        normalized.sort(key=lambda item: tuple(-float(item[name]) for name in order) + (str(item["requirement_id"]),))
        payload = {
            "portfolio_kind": "RECOMMEND_NEXT_TEST_WORK",
            "selection_semantics": "LEXICOGRAPHIC_EVIDENCE_ONLY",
            "dimensions": list(order),
            "ranked_requirements": normalized,
            "top_requirement_id": str(normalized[0]["requirement_id"]),
            "case_count_is_value": False,
            "automation_count_is_value": False,
        }
        fact = self._record(mission_id, "TEST_STRATEGY_PORTFOLIO", payload, provenance_refs=("g3:recommend-next-work",))
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "recommendation": fact, "top_requirement_id": payload["top_requirement_id"]}

    def create_strategy(self, mission_id: str, scope_identity: str, r3_1_reference: Mapping[str, Any], r3_2_references: list[Mapping[str, Any]], risk_inputs: Mapping[str, Any], hypothesis_candidates: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        if not r3_2_references: raise RuntimeError("G3_R32_REFERENCE_REQUIRED", "strategy requires exact change identity")
        dimensions = risk_inputs.get("dimensions") if isinstance(risk_inputs.get("dimensions"), Mapping) else risk_inputs
        missing = [name for name in RISK_DIMENSIONS if name not in dimensions]
        if missing:
            human = self._record(mission_id, "HUMAN_TASK", {"task_kind": "RISK_FACT_GAP", "status": "OPEN", "missing_dimensions": missing}, provenance_refs=("g3:test-strategy",))
            return {"status": "KNOWLEDGE_REQUIRED", "human_task": human, "missing_risk_dimensions": missing}
        risk = build_risk_vector(risk_inputs, "g3.risk-policy.v1")
        risk_fact = self._record(mission_id, "RISK_VECTOR", risk.to_dict(), provenance_refs=tuple(str(x) for x in risk.evidence_refs))
        hypotheses = self.create_hypotheses(mission_id, hypothesis_candidates or [], source_refs=(risk_fact["fact_id"],))
        r31 = R31Reference.from_dict(r3_1_reference); r32 = R33R32Reference.from_dict(r3_2_references[0])
        request = StrategyRequest(mission_id, scope_identity, r31, r32, risk_inputs, "g3.risk-policy.v1", "r3.3.layer-taxonomy.v1", "g3.case-policy.v1", "g3.batch-policy.v1", None, f"g3-r33-strategy:{canonical_sha256({'scope':scope_identity,'r31':r31.to_dict(),'r32':r32.to_dict(),'risk':risk_inputs})[:24]}", {"type": "AGENT", "id": "aitest-test-strategist"}, "g3-test-strategy")
        result = R33ApplicationService(self.runtime).create_strategy(request)
        if not result.ok or result.strategy is None: raise RuntimeError("G3_R33_STRATEGY_FAILED", result.error_code or "unknown")
        state = self.state(mission_id)
        gaps = [item.to_dict() for item in state.by_kind("COVERAGE_GAP")]
        portfolio = []
        for gap in gaps:
            payload = gap["payload"]
            portfolio.append({"kind": "ACTUAL_COVERAGE_GAP", "ref": gap["fact_id"], "critical_obligation": False, "actual_uncovered": True, "defect_hypothesis": False, "risk_band": payload.get("priority", "HIGH"), "rationale": "actual bank-platform uncovered changed line"})
        for h in hypotheses:
            portfolio.append({"kind": "DEFECT_HYPOTHESIS", "ref": h["fact_id"], "critical_obligation": False, "actual_uncovered": False, "defect_hypothesis": True, "risk_band": h["payload"].get("severity", "MEDIUM"), "rationale": "falsifiable defect-discovery target"})
        rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        portfolio.sort(key=lambda x: (not x["critical_obligation"], not x["actual_uncovered"], not x["defect_hypothesis"], -rank.get(str(x["risk_band"]).upper(), 0), x["ref"]))
        portfolio_fact = self._record(mission_id, "TEST_STRATEGY_PORTFOLIO", {"selection_semantics": "LEXICOGRAPHIC_REACH_FIND", "primary_values": ["INCREMENTAL_COVERAGE_GAIN", "DEFECT_DISCOVERY_VALUE", "RISK_REDUCTION"], "case_count_is_value": False, "automation_count_is_value": False, "r3_3_strategy": result.strategy.to_dict(), "ranked_work": portfolio, "r3_2_references": r3_2_references}, provenance_refs=(risk_fact["fact_id"],) + tuple(h["fact_id"] for h in hypotheses))
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "strategy": result.strategy.to_dict(), "portfolio": portfolio_fact, "risk": risk_fact, "hypotheses": hypotheses}

    def design_cases(self, mission_id: str, strategy_version_id: str, strategy_fingerprint: str, detailed_specs: Mapping[str, Mapping[str, Any]], *, designer_session_ref: str | None = None, batch_limit: int = 200) -> dict[str, Any]:
        request = BatchDesignRequest(strategy_version_id, None, strategy_fingerprint, "", batch_limit, designer_session_ref, f"g3-r33-cases:{canonical_sha256({'strategy':strategy_version_id,'specs':detailed_specs})[:24]}", "g3-case-design")
        result = R33ApplicationService(self.runtime).design_case_batch(request)
        if not result.ok or result.batch is None: raise RuntimeError("G3_R33_CASE_BATCH_FAILED", result.error_code or "unknown")
        ready = []; blocked = []
        state = self.state(mission_id)
        risk_fact_refs = tuple(item.fact_id for item in state.by_kind("RISK_VECTOR"))
        coverage_target_refs = tuple(item.fact_id for item in state.by_kind("CODE_COVERAGE_OBJECTIVE"))
        seen_redundancy_keys: set[str] = set()
        for case in result.standard_cases:
            raw = detailed_specs.get(case.test_point_id)
            if raw is None:
                blocked.append({"case_version_id": case.case_version_id, "test_point_id": case.test_point_id, "reason": "DETAILED_SPEC_MISSING"}); continue
            try: detail = validate_detailed_case(raw)
            except RuntimeError as exc:
                blocked.append({"case_version_id": case.case_version_id, "test_point_id": case.test_point_id, "reason": exc.code, "message": exc.message}); continue
            coverage_gap_refs = tuple(str(x) for x in detail.get("coverage_gap_refs") or ())
            hypothesis_refs = tuple(str(x) for x in detail.get("defect_hypothesis_refs") or ())
            value = {"case_version_id": case.case_version_id, "requirement_obligation_refs": list(case.coverage_obligation_refs), "changed_code_refs": list(case.code_refs) + list(case.change_impact_refs), "coverage_target_refs": list(coverage_target_refs), "coverage_gap_refs": list(coverage_gap_refs), "risk_refs": list(dict.fromkeys(list(case.risk_refs) + list(risk_fact_refs))), "defect_hypothesis_refs": list(hypothesis_refs), "estimated_marginal_coverage_gain": detail.get("estimated_marginal_coverage_gain"), "value_semantics": "REACH_FIND_RISK"}
            if not any(value[name] for name in ("requirement_obligation_refs", "changed_code_refs", "coverage_gap_refs", "risk_refs", "defect_hypothesis_refs")):
                blocked.append({"case_version_id": case.case_version_id, "test_point_id": case.test_point_id, "reason": "CASE_VALUE_LINK_REQUIRED"}); continue
            redundancy_key = canonical_sha256({
                "layer_id": case.layer_id,
                "requirement_obligation_refs": value["requirement_obligation_refs"],
                "changed_code_refs": value["changed_code_refs"],
                "coverage_target_refs": value["coverage_target_refs"],
                "coverage_gap_refs": value["coverage_gap_refs"],
                "risk_refs": value["risk_refs"],
                "defect_hypothesis_refs": value["defect_hypothesis_refs"],
                "ordered_steps": detail["ordered_steps"],
                "oracle": detail["oracle"],
                "evidence_requirements": detail["evidence_requirements"],
            })
            value["redundancy_key"] = redundancy_key
            if redundancy_key in seen_redundancy_keys:
                blocked.append({"case_version_id": case.case_version_id, "test_point_id": case.test_point_id, "reason": "REDUNDANT_CASE_NO_MARGINAL_VALUE", "redundancy_key": redundancy_key}); continue
            seen_redundancy_keys.add(redundancy_key)
            spec_fact = self._record(mission_id, "CASE_SPECIFICATION", {"r3_3_case": case.to_dict(), "detail": detail, "product_case_status": "READY_FOR_AI_REVIEW"}, provenance_refs=(f"r3.3:{case.case_version_id}",))
            link_fact = self._record(mission_id, "CASE_VALUE_LINK", value, provenance_refs=(spec_fact["fact_id"],))
            ready.append({"case": spec_fact, "value_link": link_fact})
        status = "PASS" if ready and not blocked else ("PARTIAL" if ready else "REPAIR_REQUIRED")
        return {"status": status, "truth_source": "R1_EVENT_STREAM", "r3_3_batch": result.batch.to_dict(), "ready_cases": ready, "blocked_cases": blocked}

    def evaluate_case_design(self, mission_id: str, scope_identity: str, r3_1_reference: Mapping[str, Any], r3_2_reference: Mapping[str, Any], case_spec_fact_id: str, *, dimension_assessments: Mapping[str, str] | None = None, reviewer_session_ref: str | None = None, human_gate_request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        fact = self.state(mission_id).by_id(case_spec_fact_id)
        if fact is None or fact.fact_kind != "CASE_SPECIFICATION": raise RuntimeError("G3_CASE_SPEC_NOT_FOUND", case_spec_fact_id)
        case = fact.payload["r3_3_case"]
        from aitest_runtime.r3_4.contracts import R33CaseReference
        r33 = R33CaseReference(case["strategy_version_id"], case["test_point_id"], case["tc_id"], case["case_version_id"], canonical_sha256(case), canonical_sha256(tuple(case.get("source_provenance") or ())), canonical_sha256(tuple(case.get("evidence_requirements") or ())), canonical_sha256(case.get("oracle_contract") or {}))
        common = {"mission_id": mission_id, "scope_identity": scope_identity, "r3_1_reference": dict(r3_1_reference), "r3_2_reference": dict(r3_2_reference), "r3_3_case_reference": r33.to_dict(), "review_policy": {"policy_version": "g3.r3.4.review.v1", "quality_gate": "G3_DETAILED_CASE_REQUIRED"}}
        r34 = R34ApplicationService(self.runtime)
        ctx_result = r34.build_review_context({**common, "idempotency_key": f"g3-r34-context:{case['case_version_id']}"})
        if not ctx_result.ok or ctx_result.reviewer_context is None: raise RuntimeError("G3_R34_CONTEXT_FAILED", ctx_result.error_code or "unknown")
        review_request = {**common, "reviewer_context_id": ctx_result.reviewer_context.reviewer_context_id, "reviewer_context_digest": ctx_result.reviewer_context.reviewer_context_digest, "dimension_assessments": dict(dimension_assessments or {"TRACEABILITY":"PASS","QUALITY":"PASS","COVERAGE":"PASS","ORACLE":"PASS","EVIDENCE":"PASS"}), "review_status": "APPROVED", "reviewer_session_ref": reviewer_session_ref, "idempotency_key": f"g3-r34-review:{case['case_version_id']}"}
        review_result = r34.review_case(review_request)
        if not review_result.ok or review_result.review is None: raise RuntimeError("G3_R34_REVIEW_FAILED", review_result.error_code or "unknown")
        detail = fact.payload["detail"]
        quality = validate_detailed_case(detail)
        evaluation = self._record(mission_id, "DESIGN_EVALUATION", {"case_spec_ref": fact.fact_id, "r3_4_review": review_result.review.to_dict(), "detailed_case_quality": "PASS", "test_fail_is_defect": False, "real_execution": "NOT_PERFORMED"}, provenance_refs=(fact.fact_id, f"r3.4:{review_result.review.case_review_id}"))
        review_req = self._record(mission_id, "HUMAN_REVIEW_REQUEST", {"case_spec_ref": fact.fact_id, "evaluation_ref": evaluation["fact_id"], "status": "PENDING_HUMAN_REVIEW", "review_question": "Approve this detailed standard test case design?"}, provenance_refs=(evaluation["fact_id"],))
        gate = self.orchestration.open_human_gate(dict(human_gate_request)) if self.orchestration is not None and human_gate_request is not None else None
        return {"status": "WAITING_FOR_HUMAN", "truth_source": "R1_EVENT_STREAM", "evaluation": evaluation, "human_review": review_req, "human_gate": gate, "r3_4_review": review_result.review.to_dict(), "detail": quality}

    def design_test_profile(self, mission_id: str, profile_type: str, profile: Mapping[str, Any]) -> dict[str, Any]:
        ptype = str(profile_type).upper()
        if ptype not in {"API", "UI", "SECURITY", "PERFORMANCE"}: raise RuntimeError("G3_TEST_PROFILE_INVALID", ptype)
        data = dict(profile)
        if ptype in {"SECURITY", "PERFORMANCE"}:
            required = {"authorized_scope", "oracle", "safety_contract"}
            if ptype == "PERFORMANCE":
                required.add("slo")
            missing = [name for name in sorted(required) if not data.get(name)]
            if missing: raise RuntimeError("G3_SAFETY_CONTRACT_REQUIRED", ",".join(missing))
        data.update({"profile_type": ptype, "design_only": True, "execution_gate": "HOLD_G4", "real_scan_or_load_executed": False})
        fact = self._record(mission_id, "TEST_PROFILE", data, provenance_refs=("g3:focused-test-intent",))
        return {"status": "PASS", "truth_source": "R1_EVENT_STREAM", "profile": fact, "g4_real_execution": "HOLD"}
