from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
TESTS = Path(__file__).parent
sys.path[:0] = [str(RUNTIME), str(TESTS)]

from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g2_1.router import AgentRoleRegistry
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.g5 import GovernedEvidenceRequest
from aitest_runtime.r3_6.contracts import ARCHITECTURE_BASELINE_REF
from aitest_runtime.r3_6.service import R36ApplicationService
from aitest_runtime.r4_3.service import R43ApplicationService
from test_g4_full_same_mission_product_e2e import (
    DeterministicExecutor,
    binding,
    exec_task,
    g3_cycle,
    intake_request,
    make_repo,
)
from test_g5_adversarial_defect_truth import explicit_code
from test_g5_human_gate_and_duplicate_correlation import ALT, exact_ref, r41
from test_g5_worker_binding_and_recovery import G5_CAPABILITIES


EC3_PRECONFIRMATION_CHECKS = (
    "g4_fail_creates_durable_unexpected_observation",
    "g4_fail_remains_observation_only",
    "missing_g4_lineage_rejected",
    "wrong_g4_lineage_rejected",
    "g5_exact_admission_creates_r36_anomaly",
    "g5_originated_r36_lineage_v7",
    "r36_candidate_created",
    "candidate_hypothesis_and_alternatives_explicit",
    "existing_typed_refs_deepening_durable_ec3",
    "evidence_assessment_durable_ec3",
    "cross_source_correlation_durable_ec3",
    "reproducibility_durable_ec3",
    "false_positive_assessment_durable_ec3",
    "rca_durable_ec3",
    "checkpoint_durable_ec3",
)
CONFIRMATION_BARRIER_CHECKS = (
    "confirmation_action_blocked_before_ec5",
    "no_confirmed_defect_persisted_after_ec3",
    "no_r43_lifecycle_opened_after_ec3",
)
EC4_GOVERNED_EVIDENCE_CHECKS = (
    "new_evidence_gap_returns_governed_work_required",
    "governed_work_truth_is_r1",
    "governed_work_request_is_contract",
    "g5_does_not_execute_provider_directly",
    "g5_does_not_create_workgraph_task_directly",
    "g2_planner_scheduler_router_creates_governed_work",
    "g2_g4_governed_reproduction_creates_durable_evidence",
    "g5_resumes_from_durable_typed_refs",
    "bounded_deepening_is_raw_payload_free",
    "companion_governed_work_path",
)
EC4_RECOVERY_CHECKS = (
    "multiple_checkpoints_event_ordered",
    "checkpoint_workset_digest_cursor_revalidated",
    "historical_checkpoint_session_is_provenance_only",
    "session_rotation_occurs_for_recovery",
    "stale_predecessor_rejected_during_recovery",
    "successor_current_binding_accepted_during_recovery",
    "restart_reconstructs_investigation_from_durable_truth",
    "conversation_history_not_recovery_truth",
    "no_confirmed_defect_persisted_after_ec4",
    "no_r43_lifecycle_opened_after_ec4",
)
FULL_E2E_CHECKS = (
    "cross_source_correlation_durable",
    "evidence_assessment_durable",
    "reproducibility_durable",
    "false_positive_exclusion_durable",
    "ordinary_confirmation_is_r36_confirmed_defect",
    "rca_durable",
    "r43_exact_lifecycle_durable",
    "single_same_mission_chain",
)


def finish(orch, worker_binding, summary):
    return orch.report_task_outcome(
        worker_binding["mission_id"],
        task_id=worker_binding["task_id"],
        attempt_id=worker_binding["attempt_id"],
        session_id=worker_binding["session_id"],
        outcome="SUCCEEDED",
        summary=summary,
    )


def hunter_task(key):
    return {
        "task_key": key,
        "intent": "investigate governed anomaly",
        "acceptance_criteria": [{"id": "truth", "description": "defect truth investigated"}],
        "routing": {
            "role": "DEFECT_HUNTER",
            "required_capabilities": sorted(G5_CAPABILITIES),
            "isolation_policy": "DEDICATED_TASK_SESSION",
            "parallelism_policy": "SERIAL",
        },
    }


def parse(text):
    start = text.find("{")
    end = text.rfind("}")
    try:
        return json.loads(text[start : end + 1]) if start >= 0 and end >= start else {}
    except Exception:
        return {}


def invoke(fn):
    try:
        return fn(), None
    except Exception as exc:
        return None, exc


def confirmed_count(runtime, mission_id):
    return sum(
        item.outcome == "CONFIRMED_DEFECT"
        for item in R36ApplicationService(runtime).state(mission_id).defect_assessments
    )


def lifecycle_count(runtime, mission_id):
    return len(R43ApplicationService(runtime).state(mission_id).confirmed_defect_lifecycles)


def work_graph_task_count(runtime, mission_id):
    state = runtime.replay_composed(mission_id).extension_state("r1_2_work_graph")
    return len(state.tasks) if state is not None else 0


def confirmation_payload(worker_binding, candidate_id, assessment_id, evidence_id, repro_id, fp_id, risk):
    return {
        **worker_binding,
        "candidate_id": candidate_id,
        "defect_assessment": {
            "assessment_id": assessment_id,
            "candidate_id": candidate_id,
            "outcome": "CONFIRMED_DEFECT",
            "final_classification": "PRODUCT_DEFECT",
            "evidence_assessment_refs": [evidence_id],
            "reproducibility_ref": repro_id,
            "false_positive_ref": fp_id,
            "causal_basis_refs": [],
            "unresolved_contradiction_refs": [],
            "evidence_class": "ENGINEERING_EVIDENCE",
            "decision_basis": "same-Mission governed runtime evidence",
        },
        "policy_context": risk,
    }


def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(RUNTIME) + os.pathsep + str(TESTS)
    proc = subprocess.run(
        [sys.executable, str(TESTS / "test_g4_governed_execution_binding_wave2.py")],
        cwd=str(WORKSPACE),
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
    )
    base = parse(proc.stdout)
    foundation = {
        "existing_g2_g4_runtime_fixture_executes": proc.returncode == 0 and base.get("status") == "PASS",
        "diagnosis_router_fixture": AgentRoleRegistry.default().resolve("DIAGNOSIS").agent_name == "aitest-diagnosis",
        "r36_service_real": callable(R36ApplicationService),
        "r36_historical_baseline_v5_unchanged": ARCHITECTURE_BASELINE_REF == "v5",
        "r43_service_real": callable(R43ApplicationService.open_confirmed_defect_lifecycle),
    }
    supplemental = {"static_markers_are_not_green_authority": True}
    original_names = (
        "g2_plan_defect_hunter_router_current_binding",
        "g4_fail_creates_durable_unexpected_observation",
        "g5_exact_admission_creates_r36_anomaly",
        "r36_candidate_created",
        "new_evidence_gap_returns_governed_work_required",
        "g2_g4_governed_reproduction_creates_durable_evidence",
        "g5_resumes_from_durable_typed_refs",
        "bounded_deepening_is_raw_payload_free",
        "cross_source_correlation_durable",
        "evidence_assessment_durable",
        "reproducibility_durable",
        "false_positive_exclusion_durable",
        "ordinary_confirmation_is_r36_confirmed_defect",
        "rca_durable",
        "r43_exact_lifecycle_durable",
        "single_same_mission_chain",
        "companion_governed_work_path",
    )
    names = set(original_names)
    names.update(EC3_PRECONFIRMATION_CHECKS)
    names.update(CONFIRMATION_BARRIER_CHECKS)
    names.update(EC4_GOVERNED_EVIDENCE_CHECKS)
    names.update(EC4_RECOVERY_CHECKS)
    names.update(FULL_E2E_CHECKS)
    behavior = {name: False for name in sorted(names)}

    command = getattr(product_entry, "g5_command", None)
    hunter = None
    try:
        hunter = AgentRoleRegistry.default().resolve("DEFECT_HUNTER")
    except Exception:
        pass

    if callable(command) and hunter is not None:
        with tempfile.TemporaryDirectory(prefix="g5-same-mission-") as temp_dir:
            root = Path(temp_dir)
            db = root / "runtime-spine.db"
            old_environment = (
                os.environ.get("AITEST_WORKSPACE_ROOT"),
                os.environ.get("AITEST_RUNTIME_SPINE_DB"),
            )
            os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
            os.environ["AITEST_RUNTIME_SPINE_DB"] = str(db)
            repo, base_ref, head_ref = make_repo(
                root,
                "cfg-data",
                {"src/CreditLimitService.java": "class C{boolean ok(long r,long a){return r<a;}}\n"},
                {"src/CreditLimitService.java": "class C{boolean ok(long r,long a){return r<=a;}}\n"},
            )
            repositories = [
                {
                    "repository_id": "cfg-data",
                    "application_id": "cfg-data",
                    "repository_path": str(repo),
                    "base_ref": base_ref,
                    "head_ref": head_ref,
                }
            ]
            runtime = create_canonical_runtime(root, db_path=db)
            orchestration = G21AutonomousOrchestrationService(
                runtime,
                root,
                session_provider=FakeOpenCodeSessionProvider(root),
            )
            coverage = {"provider": MappingCoveragePlatformProvider(CoverageProviderResult("SOURCE_UNAVAILABLE", ())) }
            executor = DeterministicExecutor("API")
            saved = (
                product_entry.orchestration_service,
                product_entry.default_service,
                product_entry.G3TestingIntelligenceService,
                product_entry._G4_CAPABILITY_EXECUTORS,
            )
            product_entry.orchestration_service = lambda _root=None: orchestration
            product_entry.default_service = lambda _runtime, _root: orchestration
            orchestration_fixture = orchestration
            product_entry.G3TestingIntelligenceService = lambda value, orchestration=None: G3TestingIntelligenceService(
                value,
                coverage_provider=coverage["provider"],
                orchestration=orchestration or orchestration_fixture,
            )
            product_entry._G4_CAPABILITY_EXECUTORS = {"API": executor}
            try:
                started = product_entry.orchestration_command("DIRECTOR", "start_test", {"request": intake_request()})
                mission_id = started["intake"]["intake"]["mission_id"]
                cycle = g3_cycle(mission_id, orchestration, coverage, repositories, 1)
                case_fact = cycle["cases"]["ready_cases"][0]["case"]
                case = case_fact["payload"]["r3_3_case"]
                strategy = cycle["strategy"]["strategy"]["strategy_version_id"]
                quality_version, campaigns = r41(runtime, mission_id, "e2e")

                g4 = G4RealExecutionService(
                    runtime,
                    orchestration=orchestration,
                    capability_executors={"API": executor},
                )
                g4.create_goal(
                    mission_id,
                    {
                        "goal_id": "g5-e2e",
                        "project_id": "PFC",
                        "release_id": "G5-EC0",
                        "requirement_scope": ["REQ-018"],
                        "affected_applications": ["cfg-data"],
                        "affected_application_target_versions": {"cfg-data": "G5-EC0"},
                        "coverage_policy": {"target_pct": 95},
                    },
                )
                g4.create_batch(
                    mission_id,
                    {
                        "batch_id": "b1",
                        "goal_id": "g5-e2e",
                        "case_refs": [case_fact["fact_id"]],
                        "strategy_version_id": strategy,
                        "target_application": "cfg-data",
                        "status": "RUNNING",
                    },
                )
                first = orchestration.propose_plan(
                    mission_id,
                    {
                        "objective": "create governed failure",
                        "tasks": [exec_task("G5-FAIL", case_fact["fact_id"])],
                        "dependencies": [],
                    },
                )["next"]
                executor_binding = binding(first)
                execution_payload = {
                    **executor_binding,
                    "case_id": str(case["tc_id"]),
                    "case_version": str(case["case_version_id"]),
                    "case_spec_fact_id": case_fact["fact_id"],
                    "execution_batch_id": "b1",
                }
                g4.record_cursor(
                    mission_id,
                    {**execution_payload, "current_step_index": 0, "pending_step_id": "fail"},
                )
                outcome = g4.execute_capability(
                    mission_id,
                    {
                        **execution_payload,
                        "capability_id": "API",
                        "executor_request": {
                            "url": "https://sut.test/limits",
                            "method": "POST",
                            "authorized_scope": {"environment": "TEST"},
                        },
                        "step": {
                            "step_id": "fail",
                            "expected": "INVARIANT_OK",
                            "fixture_actual": "INVARIANT_BROKEN",
                        },
                        "execution_node": "node-e2e",
                    },
                )
                observation = g4.state(mission_id).by_kind("UNEXPECTED_OBSERVATION")[-1]
                behavior["g4_fail_creates_durable_unexpected_observation"] = (
                    outcome["status"] == "FAIL"
                    and observation.payload.get("status") == "OBSERVATION_ONLY"
                    and observation.payload.get("g5_defect_truth") == "HOLD"
                )
                behavior["g4_fail_remains_observation_only"] = (
                    observation.fact_kind == "UNEXPECTED_OBSERVATION"
                    and observation.mission_id == mission_id
                    and observation.payload.get("oracle_result") == "FAIL"
                    and "CONFIRMED_DEFECT" not in json.dumps(observation.to_dict(), sort_keys=True)
                )
                finish(orchestration, executor_binding, "governed failure captured")

                hunter_first = orchestration.propose_plan(
                    mission_id,
                    {
                        "objective": "diagnose durable observation",
                        "tasks": [hunter_task("H1")],
                        "dependencies": [],
                    },
                )["next"]
                hunter_binding = binding(hunter_first)
                behavior["g2_plan_defect_hunter_router_current_binding"] = (
                    hunter_first["agent"] == "aitest-diagnosis"
                    and hunter_first["route"]["role"] == "DEFECT_HUNTER"
                )

                before_anomalies = len(R36ApplicationService(runtime).state(mission_id).anomalies)
                _, missing_lineage_exc = invoke(
                    lambda: command(
                        "DEFECT_HUNTER",
                        "record_anomaly",
                        {**hunter_binding, "g4_observation_ref": {}},
                    )
                )
                behavior["missing_g4_lineage_rejected"] = (
                    explicit_code(missing_lineage_exc) in {"G5_G4_ADMISSION_INVALID", "G5_G4_LINEAGE_MISSING"}
                    and len(R36ApplicationService(runtime).state(mission_id).anomalies) == before_anomalies
                )
                wrong_observation = {**observation.to_dict(), "mission_id": "wrong-mission"}
                _, wrong_lineage_exc = invoke(
                    lambda: command(
                        "DEFECT_HUNTER",
                        "record_anomaly",
                        {**hunter_binding, "g4_observation_ref": wrong_observation},
                    )
                )
                behavior["wrong_g4_lineage_rejected"] = (
                    explicit_code(wrong_lineage_exc) in {"G5_G4_ADMISSION_INVALID", "G5_G4_LINEAGE_MISSING"}
                    and len(R36ApplicationService(runtime).state(mission_id).anomalies) == before_anomalies
                )

                _, admission_exc = invoke(
                    lambda: command(
                        "DEFECT_HUNTER",
                        "record_anomaly",
                        {**hunter_binding, "g4_observation_ref": observation.to_dict()},
                    )
                )
                r36_state = R36ApplicationService(runtime).state(mission_id)
                anomaly = r36_state.anomalies[-1] if admission_exc is None and r36_state.anomalies else None
                behavior["g5_exact_admission_creates_r36_anomaly"] = (
                    anomaly is not None
                    and anomaly.origin_lineage.get("mission_id") == mission_id
                    and bool(anomaly.origin_lineage.get("g4_observation_ref"))
                )
                behavior["g5_originated_r36_lineage_v7"] = (
                    anomaly is not None
                    and anomaly.origin_lineage.get("architecture_baseline_ref") == "v7"
                    and ARCHITECTURE_BASELINE_REF == "v5"
                )

                candidate_id = "candidate-e2e"
                candidate = None
                if anomaly is not None:
                    _, candidate_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "create_candidate",
                            {
                                **hunter_binding,
                                "candidate_id": candidate_id,
                                "anomaly_refs": [anomaly.anomaly_id],
                                "classification": "PRODUCT_DEFECT_CANDIDATE",
                                "alternative_classifications": ALT,
                                "hypothesis": "same invariant fails under governed execution",
                            },
                        )
                    )
                    candidate = (
                        R36ApplicationService(runtime).state(mission_id).candidate(candidate_id)
                        if candidate_exc is None
                        else None
                    )
                behavior["r36_candidate_created"] = candidate is not None
                behavior["candidate_hypothesis_and_alternatives_explicit"] = (
                    candidate is not None
                    and candidate.classification == "PRODUCT_DEFECT_CANDIDATE"
                    and set(ALT).issubset(set(candidate.alternative_classifications))
                    and "confirmed" not in candidate.hypothesis.lower()
                )

                ec3_deepening = None
                ec3_evidence = None
                ec3_correlation = None
                ec3_repro = None
                ec3_false_positive = None
                ec3_checkpoint = None
                ec3_evidence_id = "evidence-ec3"
                ec3_correlation_id = "corr-ec3"
                ec3_repro_id = "repro-ec3"
                ec3_fp_id = "fp-ec3"
                if candidate is not None:
                    step_ref = str(observation.payload.get("step_result_ref") or "")
                    _, deepening_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "request_evidence_deepening",
                            {
                                **hunter_binding,
                                "candidate_id": candidate_id,
                                "mode": "EXISTING_TYPED_REFS",
                                "evidence_refs": [observation.fact_id, step_ref],
                                "requested_channels": ["G4_FACT"],
                                "cursor": observation.fact_id,
                            },
                        )
                    )
                    state = R36ApplicationService(runtime).state(mission_id)
                    ec3_deepening = state.deepenings[-1] if deepening_exc is None and state.deepenings else None
                    behavior["existing_typed_refs_deepening_durable_ec3"] = (
                        ec3_deepening is not None
                        and observation.fact_id in ec3_deepening.evidence_refs
                        and ec3_deepening.origin_lineage.get("architecture_baseline_ref") == "v7"
                    )

                if ec3_deepening is not None:
                    _, evidence_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "record_evidence_assessment",
                            {
                                **hunter_binding,
                                "candidate_id": candidate_id,
                                "assessment_id": ec3_evidence_id,
                                "evidence_refs": list(ec3_deepening.evidence_refs),
                                "evidence_role": "PRIMARY",
                                "evidence_sufficiency": "SUFFICIENT",
                                "relevance": "DIRECT",
                                "verification_method": "GOVERNED_G4_FACT",
                                "freshness": "CURRENT",
                                "scope_match": "EXACT",
                                "conflict_refs": [],
                                "evidence_class": "ENGINEERING_EVIDENCE",
                            },
                        )
                    )
                    ec3_evidence = (
                        R36ApplicationService(runtime).state(mission_id).evidence_assessment(ec3_evidence_id)
                        if evidence_exc is None
                        else None
                    )
                    behavior["evidence_assessment_durable_ec3"] = ec3_evidence is not None

                    step_fact = g4.state(mission_id).by_id(str(observation.payload.get("step_result_ref") or ""))
                    source_refs = [{"ref_id": observation.fact_id, "digest": observation.digest}]
                    if step_fact is not None:
                        source_refs.append({"ref_id": step_fact.fact_id, "digest": step_fact.digest})
                    _, correlation_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "correlate_sources",
                            {
                                **hunter_binding,
                                "candidate_id": candidate_id,
                                "correlation_id": ec3_correlation_id,
                                "source_refs": source_refs,
                                "correlation_keys": {"business_rule": "REQ-018", "mechanism": "same-boundary"},
                                "method": "TYPED_RUNTIME_CORRELATION",
                                "match_quality": "EXACT",
                                "confidence": 1.0,
                                "time_window": {},
                                "conflict_refs": [],
                            },
                        )
                    )
                    ec3_correlation = (
                        R36ApplicationService(runtime).state(mission_id).correlation(ec3_correlation_id)
                        if correlation_exc is None
                        else None
                    )
                    behavior["cross_source_correlation_durable_ec3"] = ec3_correlation is not None

                    _, repro_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "evaluate_reproducibility",
                            {
                                **hunter_binding,
                                "candidate_id": candidate_id,
                                "reproducibility_id": ec3_repro_id,
                                "status": "REPRODUCED",
                                "attempt_refs": [executor_binding["attempt_id"]],
                                "evidence_refs": list(ec3_deepening.evidence_refs),
                                "controlled_variables": {"build": "same"},
                                "signature": "same-failure",
                                "comparison": "governed observation carries exact invariant failure",
                                "blocking_basis": None,
                            },
                        )
                    )
                    ec3_repro = (
                        R36ApplicationService(runtime).state(mission_id).reproducibility(ec3_repro_id)
                        if repro_exc is None
                        else None
                    )
                    behavior["reproducibility_durable_ec3"] = ec3_repro is not None

                    _, fp_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "assess_false_positive",
                            {
                                **hunter_binding,
                                "candidate_id": candidate_id,
                                "false_positive_id": ec3_fp_id,
                                "status": "NOT_FALSE_POSITIVE",
                                "alternatives_considered": ALT,
                                "evidence_refs": list(ec3_deepening.evidence_refs),
                                "unresolved_refs": [],
                                "decision_basis": "all frozen alternatives considered against governed refs",
                            },
                        )
                    )
                    ec3_false_positive = (
                        R36ApplicationService(runtime).state(mission_id).false_positive(ec3_fp_id)
                        if fp_exc is None
                        else None
                    )
                    behavior["false_positive_assessment_durable_ec3"] = ec3_false_positive is not None

                if all((ec3_evidence, ec3_correlation, ec3_repro, ec3_false_positive)):
                    # Frozen R3.6 requires a DefectAssessment before RCA. EC3 does not
                    # expose G5 assess_defect_truth, so the fixture supplies an exact
                    # non-confirming R3.6 assessment through the existing authority.
                    prerequisite = R36ApplicationService(runtime).assess_defect_truth(
                        {
                            "mission_id": mission_id,
                            "idempotency_key": "ec3:inconclusive-assessment",
                            "origin_lineage": {
                                "mission_id": mission_id,
                                "architecture_baseline_ref": "v7",
                                "source": "EC3_PROGRESSIVE_ORACLE_PREREQUISITE",
                            },
                            "defect_assessment": {
                                "assessment_id": "assessment-ec3-inconclusive",
                                "candidate_id": candidate_id,
                                "outcome": "INCONCLUSIVE",
                                "final_classification": "UNKNOWN_INCONCLUSIVE",
                                "evidence_assessment_refs": [ec3_evidence_id],
                                "reproducibility_ref": ec3_repro_id,
                                "false_positive_ref": ec3_fp_id,
                                "causal_basis_refs": [],
                                "unresolved_contradiction_refs": [],
                                "evidence_class": "ENGINEERING_EVIDENCE",
                                "decision_basis": "pre-confirmation RCA basis only",
                            },
                        }
                    )
                    if prerequisite.ok:
                        _, rca_exc = invoke(
                            lambda: command(
                                "DEFECT_HUNTER",
                                "record_rca",
                                {
                                    **hunter_binding,
                                    "candidate_id": candidate_id,
                                    "rca_id": "rca-ec3",
                                    "cause_class": "UNKNOWN",
                                    "status": "PARTIAL",
                                    "causal_chain_refs": [],
                                    "root_component": "cfg-data",
                                    "contradiction_refs": [],
                                    "decision_basis": "bounded pre-confirmation causal analysis",
                                },
                            )
                        )
                        ec3_rca = (
                            R36ApplicationService(runtime).state(mission_id).rca("rca-ec3")
                            if rca_exc is None
                            else None
                        )
                        behavior["rca_durable_ec3"] = ec3_rca is not None and ec3_rca.status == "PARTIAL"

                if ec3_deepening is not None:
                    receipt = ec3_deepening.workset_receipt
                    _, checkpoint_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "record_checkpoint",
                            {
                                **hunter_binding,
                                "candidate_id": candidate_id,
                                "checkpoint_id": "checkpoint-ec3-1",
                                "cursor": receipt.next_cursor,
                                "workset_digest": receipt.receipt_digest,
                                "session_ref": hunter_binding["session_id"],
                                "omitted_refs": list(receipt.omitted_refs),
                            },
                        )
                    )
                    ec3_checkpoint = (
                        R36ApplicationService(runtime).state(mission_id).checkpoint("checkpoint-ec3-1")
                        if checkpoint_exc is None
                        else None
                    )
                    behavior["checkpoint_durable_ec3"] = (
                        ec3_checkpoint is not None
                        and ec3_checkpoint.workset_digest == receipt.receipt_digest
                        and ec3_checkpoint.session_ref == hunter_binding["session_id"]
                    )

                if all((ec3_evidence, ec3_repro, ec3_false_positive)):
                    confirmed_before = confirmed_count(runtime, mission_id)
                    lifecycle_before = lifecycle_count(runtime, mission_id)
                    barrier_result, barrier_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "assess_defect_truth",
                            confirmation_payload(
                                hunter_binding,
                                candidate_id,
                                "defect-ec3-barrier",
                                ec3_evidence_id,
                                ec3_repro_id,
                                ec3_fp_id,
                                {"severity": "S1", "security_sensitive": True},
                            ),
                        )
                    )
                    behavior["confirmation_action_blocked_before_ec5"] = explicit_code(
                        barrier_exc or barrier_result
                    ) in {"G5_ACTION_FORBIDDEN", "G5_CONFIRMATION_UNSUPPORTED", "G5_HUMAN_GATE_REQUIRED"}
                    behavior["no_confirmed_defect_persisted_after_ec3"] = (
                        confirmed_count(runtime, mission_id) == confirmed_before == 0
                    )
                    behavior["no_r43_lifecycle_opened_after_ec3"] = (
                        lifecycle_count(runtime, mission_id) == lifecycle_before == 0
                    )

                active_hunter_binding = hunter_binding
                if ec3_checkpoint is not None:
                    rotation, rotation_exc = invoke(
                        lambda: orchestration.rotate_session(
                            mission_id,
                            task_id=hunter_binding["task_id"],
                            reasons=["CONTROL_OVERRIDE"],
                        )
                    )
                    execution = runtime.replay_composed(mission_id).extension_state("r1_3b_execution_resume")
                    latest = execution.latest_attempt(hunter_binding["task_id"])
                    behavior["session_rotation_occurs_for_recovery"] = (
                        rotation_exc is None
                        and latest is not None
                        and latest.attempt_id != hunter_binding["attempt_id"]
                        and latest.runtime_session_id != hunter_binding["session_id"]
                        and latest.root_attempt_id == hunter_first["attempt"]["root_attempt_id"]
                    )
                    if behavior["session_rotation_occurs_for_recovery"]:
                        successor_binding = {
                            **hunter_binding,
                            "attempt_id": latest.attempt_id,
                            "session_id": latest.runtime_session_id,
                        }
                        stale_result, stale_exc = invoke(
                            lambda: command(
                                "DEFECT_HUNTER",
                                "record_checkpoint",
                                {
                                    **hunter_binding,
                                    "candidate_id": candidate_id,
                                    "checkpoint_id": "checkpoint-stale",
                                    "cursor": ec3_checkpoint.cursor,
                                    "workset_digest": ec3_checkpoint.workset_digest,
                                    "session_ref": hunter_binding["session_id"],
                                    "omitted_refs": list(ec3_checkpoint.omitted_refs),
                                },
                            )
                        )
                        behavior["stale_predecessor_rejected_during_recovery"] = explicit_code(
                            stale_exc or stale_result
                        ) in {"G5_ATTEMPT_NOT_CURRENT", "G5_SESSION_NOT_OPEN"}
                        context, context_exc = invoke(
                            lambda: command("DEFECT_HUNTER", "work_context", successor_binding)
                        )
                        behavior["successor_current_binding_accepted_during_recovery"] = (
                            context_exc is None
                            and isinstance(context, dict)
                            and context.get("truth_source") == "R1_EVENT_STREAM"
                        )
                        _, checkpoint2_exc = invoke(
                            lambda: command(
                                "DEFECT_HUNTER",
                                "record_checkpoint",
                                {
                                    **successor_binding,
                                    "candidate_id": candidate_id,
                                    "checkpoint_id": "checkpoint-ec4-2",
                                    "cursor": ec3_checkpoint.cursor,
                                    "workset_digest": ec3_checkpoint.workset_digest,
                                    "session_ref": successor_binding["session_id"],
                                    "omitted_refs": list(ec3_checkpoint.omitted_refs),
                                },
                            )
                        )
                        restarted_runtime = create_canonical_runtime(root, db_path=db)
                        restarted_state = R36ApplicationService(restarted_runtime).state(mission_id)
                        checkpoint2 = restarted_state.checkpoint("checkpoint-ec4-2") if checkpoint2_exc is None else None
                        behavior["multiple_checkpoints_event_ordered"] = (
                            checkpoint2 is not None
                            and len(restarted_state.checkpoints) >= 2
                            and restarted_state.checkpoints[-1].checkpoint_id == "checkpoint-ec4-2"
                        )
                        behavior["checkpoint_workset_digest_cursor_revalidated"] = (
                            checkpoint2 is not None
                            and checkpoint2.workset_digest == ec3_checkpoint.workset_digest
                            and checkpoint2.cursor == ec3_checkpoint.cursor
                        )
                        behavior["historical_checkpoint_session_is_provenance_only"] = (
                            checkpoint2 is not None
                            and ec3_checkpoint.session_ref == hunter_binding["session_id"]
                            and checkpoint2.session_ref == successor_binding["session_id"]
                            and ec3_checkpoint.session_ref != checkpoint2.session_ref
                        )
                        behavior["restart_reconstructs_investigation_from_durable_truth"] = (
                            restarted_state.candidate(candidate_id) is not None
                            and restarted_state.deepenings
                            and behavior["multiple_checkpoints_event_ordered"]
                        )
                        behavior["conversation_history_not_recovery_truth"] = (
                            behavior["restart_reconstructs_investigation_from_durable_truth"]
                            and behavior["successor_current_binding_accepted_during_recovery"]
                            and context.get("conversation_is_not_truth") is True
                        )
                        active_hunter_binding = successor_binding

                governed = None
                requested_work = None
                if candidate is not None:
                    tasks_before = work_graph_task_count(runtime, mission_id)
                    executions_before = executor.executions
                    governed, governed_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "request_evidence_deepening",
                            {
                                **active_hunter_binding,
                                "candidate_id": candidate_id,
                                "mode": "NEW_GOVERNED_ACTION",
                                "requested_channels": ["API"],
                                "evidence_gap": "reproduce governed failure",
                                "required_scope": {"project_id": "PFC", "environment_id": "TEST"},
                                "risk_class": "NORMAL",
                            },
                        )
                    )
                    tasks_after = work_graph_task_count(runtime, mission_id)
                    requested_value = governed.get("requested_work") if isinstance(governed, dict) else None
                    requested_work, request_exc = invoke(
                        lambda: GovernedEvidenceRequest.from_dict(requested_value)
                    ) if isinstance(requested_value, dict) else (None, None)
                    behavior["new_evidence_gap_returns_governed_work_required"] = (
                        governed_exc is None
                        and isinstance(governed, dict)
                        and governed.get("status") == "GOVERNED_WORK_REQUIRED"
                    )
                    behavior["governed_work_truth_is_r1"] = (
                        behavior["new_evidence_gap_returns_governed_work_required"]
                        and governed.get("truth_source") == "R1_EVENT_STREAM"
                    )
                    behavior["governed_work_request_is_contract"] = (
                        request_exc is None
                        and requested_work is not None
                        and requested_work.mission_id == mission_id
                        and requested_work.candidate_id == candidate_id
                    )
                    behavior["g5_does_not_create_workgraph_task_directly"] = tasks_after == tasks_before
                    behavior["g5_does_not_execute_provider_directly"] = executor.executions == executions_before

                if behavior["new_evidence_gap_returns_governed_work_required"]:
                    finish(orchestration, active_hunter_binding, "need governed evidence")
                    g4.create_batch(
                        mission_id,
                        {
                            "batch_id": "b2",
                            "goal_id": "g5-e2e",
                            "case_refs": [case_fact["fact_id"]],
                            "strategy_version_id": strategy,
                            "target_application": "cfg-data",
                            "status": "RUNNING",
                        },
                    )
                    task_count_before_plan = work_graph_task_count(runtime, mission_id)
                    second = orchestration.propose_plan(
                        mission_id,
                        {
                            "objective": "governed reproduction",
                            "tasks": [exec_task("G5-REPRO", case_fact["fact_id"])],
                            "dependencies": [],
                        },
                    )["next"]
                    reproduction_binding = binding(second)
                    behavior["g2_planner_scheduler_router_creates_governed_work"] = (
                        work_graph_task_count(runtime, mission_id) > task_count_before_plan
                        and second["route"]["role"] == "EXECUTOR"
                        and second.get("status") == "DISPATCHED"
                    )
                    reproduction_payload = {
                        **reproduction_binding,
                        "case_id": str(case["tc_id"]),
                        "case_version": str(case["case_version_id"]),
                        "case_spec_fact_id": case_fact["fact_id"],
                        "execution_batch_id": "b2",
                    }
                    g4.record_cursor(
                        mission_id,
                        {**reproduction_payload, "current_step_index": 0, "pending_step_id": "repro"},
                    )
                    reproduction = g4.execute_capability(
                        mission_id,
                        {
                            **reproduction_payload,
                            "capability_id": "API",
                            "executor_request": {
                                "url": "https://sut.test/limits",
                                "method": "POST",
                                "authorized_scope": {"environment": "TEST"},
                            },
                            "step": {
                                "step_id": "repro",
                                "expected": "INVARIANT_OK",
                                "fixture_actual": "INVARIANT_BROKEN",
                            },
                            "execution_node": "node-e2e",
                        },
                    )
                    observation2 = g4.state(mission_id).by_kind("UNEXPECTED_OBSERVATION")[-1]
                    behavior["g2_g4_governed_reproduction_creates_durable_evidence"] = (
                        reproduction["status"] == "FAIL" and observation2.fact_id != observation.fact_id
                    )
                    finish(orchestration, reproduction_binding, "reproduced")

                    hunter_second = orchestration.propose_plan(
                        mission_id,
                        {
                            "objective": "resume defect investigation",
                            "tasks": [hunter_task("H2")],
                            "dependencies": [],
                        },
                    )["next"]
                    resumed_binding = binding(hunter_second)
                    _, deepening_exc = invoke(
                        lambda: command(
                            "DEFECT_HUNTER",
                            "request_evidence_deepening",
                            {
                                **resumed_binding,
                                "candidate_id": candidate_id,
                                "mode": "EXISTING_TYPED_REFS",
                                "evidence_refs": [observation.fact_id, observation2.fact_id],
                                "requested_channels": ["API"],
                            },
                        )
                    )
                    r36_state = R36ApplicationService(runtime).state(mission_id)
                    deepening = r36_state.deepenings[-1] if deepening_exc is None and r36_state.deepenings else None
                    behavior["g5_resumes_from_durable_typed_refs"] = (
                        deepening is not None
                        and set(deepening.evidence_refs) >= {observation.fact_id, observation2.fact_id}
                    )
                    behavior["bounded_deepening_is_raw_payload_free"] = (
                        deepening is not None
                        and "password" not in json.dumps(deepening.to_dict()).lower()
                        and "raw_payload" not in json.dumps(deepening.to_dict()).lower()
                    )

                    if deepening is not None:
                        evidence_id = "ea-e2e"
                        _, evidence_exc = invoke(
                            lambda: command(
                                "DEFECT_HUNTER",
                                "record_evidence_assessment",
                                {
                                    **resumed_binding,
                                    "candidate_id": candidate_id,
                                    "assessment_id": evidence_id,
                                    "evidence_refs": [observation.fact_id, observation2.fact_id],
                                    "evidence_role": "PRIMARY",
                                    "evidence_sufficiency": "SUFFICIENT",
                                    "relevance": "DIRECT",
                                    "verification_method": "GOVERNED_REPRODUCTION",
                                    "freshness": "CURRENT",
                                    "scope_match": "EXACT",
                                    "conflict_refs": [],
                                    "evidence_class": "ENGINEERING_EVIDENCE",
                                },
                            )
                        )
                        evidence = (
                            R36ApplicationService(runtime).state(mission_id).evidence_assessment(evidence_id)
                            if evidence_exc is None
                            else None
                        )
                        behavior["evidence_assessment_durable"] = evidence is not None

                        correlation_id = "corr-e2e"
                        _, correlation_exc = invoke(
                            lambda: command(
                                "DEFECT_HUNTER",
                                "correlate_sources",
                                {
                                    **resumed_binding,
                                    "candidate_id": candidate_id,
                                    "correlation_id": correlation_id,
                                    "source_refs": [
                                        {"ref_id": observation.fact_id, "digest": observation.digest},
                                        {"ref_id": observation2.fact_id, "digest": observation2.digest},
                                    ],
                                    "correlation_keys": {"business_rule": "REQ-018", "mechanism": "same-boundary"},
                                    "method": "TYPED_RUNTIME_CORRELATION",
                                    "match_quality": "EXACT",
                                    "confidence": 1.0,
                                    "time_window": {},
                                    "conflict_refs": [],
                                },
                            )
                        )
                        correlation = (
                            R36ApplicationService(runtime).state(mission_id).correlation(correlation_id)
                            if correlation_exc is None
                            else None
                        )
                        behavior["cross_source_correlation_durable"] = correlation is not None

                        repro_id = "repro-e2e"
                        _, repro_exc = invoke(
                            lambda: command(
                                "DEFECT_HUNTER",
                                "evaluate_reproducibility",
                                {
                                    **resumed_binding,
                                    "candidate_id": candidate_id,
                                    "reproducibility_id": repro_id,
                                    "status": "REPRODUCED",
                                    "attempt_refs": [executor_binding["attempt_id"], reproduction_binding["attempt_id"]],
                                    "evidence_refs": [observation.fact_id, observation2.fact_id],
                                    "controlled_variables": {"build": "same"},
                                    "signature": "same-failure",
                                    "comparison": "same invariant reproduced",
                                    "blocking_basis": None,
                                },
                            )
                        )
                        repro = (
                            R36ApplicationService(runtime).state(mission_id).reproducibility(repro_id)
                            if repro_exc is None
                            else None
                        )
                        behavior["reproducibility_durable"] = repro is not None

                        false_positive_id = "fp-e2e"
                        _, fp_exc = invoke(
                            lambda: command(
                                "DEFECT_HUNTER",
                                "assess_false_positive",
                                {
                                    **resumed_binding,
                                    "candidate_id": candidate_id,
                                    "false_positive_id": false_positive_id,
                                    "status": "NOT_FALSE_POSITIVE",
                                    "alternatives_considered": ALT,
                                    "evidence_refs": [observation.fact_id, observation2.fact_id],
                                    "unresolved_refs": [],
                                    "decision_basis": "alternatives excluded",
                                },
                            )
                        )
                        false_positive = (
                            R36ApplicationService(runtime).state(mission_id).false_positive(false_positive_id)
                            if fp_exc is None
                            else None
                        )
                        behavior["false_positive_exclusion_durable"] = false_positive is not None

                        if all((evidence, correlation, repro, false_positive)):
                            ec4_confirmed_before = confirmed_count(runtime, mission_id)
                            ec4_lifecycle_before = lifecycle_count(runtime, mission_id)
                            ec4_barrier_result, ec4_barrier_exc = invoke(
                                lambda: command(
                                    "DEFECT_HUNTER",
                                    "assess_defect_truth",
                                    confirmation_payload(
                                        resumed_binding,
                                        candidate_id,
                                        "defect-ec4-barrier",
                                        evidence_id,
                                        repro_id,
                                        false_positive_id,
                                        {"severity": "S1", "security_sensitive": True},
                                    ),
                                )
                            )
                            behavior["no_confirmed_defect_persisted_after_ec4"] = (
                                explicit_code(ec4_barrier_exc or ec4_barrier_result)
                                in {"G5_ACTION_FORBIDDEN", "G5_CONFIRMATION_UNSUPPORTED", "G5_HUMAN_GATE_REQUIRED"}
                                and confirmed_count(runtime, mission_id) == ec4_confirmed_before
                            )
                            behavior["no_r43_lifecycle_opened_after_ec4"] = (
                                lifecycle_count(runtime, mission_id) == ec4_lifecycle_before == 0
                            )

                            defect_id = "defect-e2e"
                            _, assessment_exc = invoke(
                                lambda: command(
                                    "DEFECT_HUNTER",
                                    "assess_defect_truth",
                                    confirmation_payload(
                                        resumed_binding,
                                        candidate_id,
                                        defect_id,
                                        evidence_id,
                                        repro_id,
                                        false_positive_id,
                                        {
                                            "severity": "S3",
                                            "security_sensitive": False,
                                            "performance_sensitive": False,
                                            "regulatory_sensitive": False,
                                        },
                                    ),
                                )
                            )
                            assessment = (
                                R36ApplicationService(runtime).state(mission_id).defect_assessment(defect_id)
                                if assessment_exc is None
                                else None
                            )
                            behavior["ordinary_confirmation_is_r36_confirmed_defect"] = (
                                assessment is not None and assessment.outcome == "CONFIRMED_DEFECT"
                            )
                            if assessment is not None:
                                rca_id = "rca-e2e"
                                _, rca_exc = invoke(
                                    lambda: command(
                                        "DEFECT_HUNTER",
                                        "record_rca",
                                        {
                                            **resumed_binding,
                                            "candidate_id": candidate_id,
                                            "rca_id": rca_id,
                                            "cause_class": "CODE_LOGIC",
                                            "status": "ESTABLISHED",
                                            "causal_chain_refs": [
                                                {"ref_id": correlation_id, "digest": correlation.correlation_digest}
                                            ],
                                            "root_component": "cfg-data",
                                            "contradiction_refs": [],
                                            "decision_basis": "typed reproduction chain",
                                        },
                                    )
                                )
                                rca = (
                                    R36ApplicationService(runtime).state(mission_id).rca(rca_id)
                                    if rca_exc is None
                                    else None
                                )
                                behavior["rca_durable"] = rca is not None
                                if rca is not None:
                                    _, handoff_exc = invoke(
                                        lambda: command(
                                            "DEFECT_HUNTER",
                                            "handoff_confirmed_defect",
                                            {
                                                **resumed_binding,
                                                "candidate_id": candidate_id,
                                                "defect_assessment_ref": exact_ref(runtime, mission_id, defect_id),
                                                "defect_assessment_digest": assessment.defect_assessment_digest,
                                                "quality_version_ref": quality_version,
                                                "campaign_refs": campaigns,
                                                "rca_refs": [rca_id],
                                                "evidence_refs": [evidence_id],
                                            },
                                        )
                                    )
                                    lifecycles = (
                                        R43ApplicationService(runtime).state(mission_id).confirmed_defect_lifecycles
                                        if handoff_exc is None
                                        else ()
                                    )
                                    behavior["r43_exact_lifecycle_durable"] = len(lifecycles) == 1
                                    if behavior["r43_exact_lifecycle_durable"]:
                                        behavior["single_same_mission_chain"] = (
                                            all(item.mission_id == mission_id for item in g4.state(mission_id).facts)
                                            and R36ApplicationService(runtime).state(mission_id).mission_id == mission_id
                                            and R43ApplicationService(runtime).state(mission_id).mission_id == mission_id
                                        )
                    behavior["companion_governed_work_path"] = all(
                        behavior[name]
                        for name in (
                            "new_evidence_gap_returns_governed_work_required",
                            "g2_planner_scheduler_router_creates_governed_work",
                            "g2_g4_governed_reproduction_creates_durable_evidence",
                            "g5_resumes_from_durable_typed_refs",
                        )
                    )
            finally:
                (
                    product_entry.orchestration_service,
                    product_entry.default_service,
                    product_entry.G3TestingIntelligenceService,
                    product_entry._G4_CAPABILITY_EXECUTORS,
                ) = saved
                if old_environment[0] is None:
                    os.environ.pop("AITEST_WORKSPACE_ROOT", None)
                else:
                    os.environ["AITEST_WORKSPACE_ROOT"] = old_environment[0]
                if old_environment[1] is None:
                    os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
                else:
                    os.environ["AITEST_RUNTIME_SPINE_DB"] = old_environment[1]

    fixture_ok = all(foundation.values())
    runtime_green = all(behavior.values())
    contract = {**behavior, **supplemental}
    missing = [name for name, value in contract.items() if not value]
    status = "PASS" if fixture_ok and runtime_green and not missing else "FAIL"
    truthful_red = fixture_ok and status == "FAIL" and bool(missing)
    progressive = {
        "ec3_preconfirmation": {name: behavior[name] for name in EC3_PRECONFIRMATION_CHECKS},
        "confirmation_barrier": {name: behavior[name] for name in CONFIRMATION_BARRIER_CHECKS},
        "ec4_governed_evidence": {name: behavior[name] for name in EC4_GOVERNED_EVIDENCE_CHECKS},
        "ec4_recovery": {name: behavior[name] for name in EC4_RECOVERY_CHECKS},
        "full_same_mission_e2e": {name: behavior[name] for name in FULL_E2E_CHECKS},
    }
    out = {
        "suite": "test_g5_same_mission_e2e",
        "status": status,
        "fixture_ok": fixture_ok,
        "truthful_red": truthful_red,
        "red_kind": "MISSING_G5_INTEGRATION" if truthful_red else None,
        "foundation_checks": foundation,
        "runtime_behavior_checks": behavior,
        "progressive_stage_checks": progressive,
        "supplemental_checks": supplemental,
        "contract_checks": contract,
        "runtime_green_evidence": runtime_green,
        "oracle_contract": {
            "current_red_is_truthful": truthful_red,
            "future_green_requires_real_runtime": True,
            "static_markers_can_satisfy_e2e_green": False,
        },
        "missing_contract_checks": missing,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
