from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
TESTS = Path(__file__).parent
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(TESTS))

from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import canonical_extension_manifests
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.r2_6.service import HumanGateApplicationService
from aitest_runtime.r3_6.contracts import ARCHITECTURE_BASELINE_REF, CHECKPOINT_RECORDED
from aitest_runtime.r3_6.service import R36ApplicationService
from aitest_runtime.r4_3.service import R43ApplicationService
from test_g4_full_same_mission_product_e2e import DeterministicExecutor, exec_task, g3_cycle
from test_g3_testing_intelligence_product_path import binding, finish, intake_request, make_repo
from test_g5_human_gate_and_duplicate_correlation import ALT, exact_ref, r41, seed
from test_g5_worker_binding_and_recovery import G5_CAPABILITIES, request, task

REQUIRED_DIRECTOR_ACTIONS = {
    "status", "intake_observations", "investigation_status", "open_investigation",
    "request_human_review", "canonical_defects",
}
REQUIRED_WORKER_ACTIONS = {
    "status", "work_context", "record_anomaly", "create_candidate",
    "request_evidence_deepening", "record_evidence_assessment", "correlate_sources",
    "evaluate_reproducibility", "assess_false_positive", "assess_defect_truth",
    "record_rca", "record_checkpoint", "handoff_confirmed_defect",
}
REQUIRED_NON_DURABLE_CONTRACTS = {
    "G5WorkerBinding",
    "G4ObservationAdmission",
    "GovernedEvidenceRequest",
    "DuplicateCorrelationDecision",
    "G5OperationResult",
}
DIRECTOR_RUNTIME_CHECKS = {
    "director_intake_observations_is_r1_read_only",
    "director_intake_reports_admitted_status",
    "director_investigation_status_is_durable_truth",
    "director_investigation_status_uses_latest_valid_checkpoint",
    "director_open_investigation_returns_governed_work",
    "director_open_investigation_does_not_create_plan",
    "director_open_investigation_does_not_create_task",
    "director_existing_hunter_task_reused_only_if_exact",
    "director_canonical_defects_reads_r43",
    "director_canonical_defects_is_same_mission_read_only",
}


def parse_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def invoke(fn):
    try:
        return fn(), None
    except Exception as exc:
        return None, exc


def error_code(value) -> str:
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("error_code") or value.get("code") or value.get("reason") or value.get("message") or "")
    return str(value or "")


def parser_has_g5() -> bool:
    parser = product_entry.parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return "g5" in action.choices
    return False


def g5_source() -> str:
    root = RUNTIME / "aitest_runtime" / "g5"
    if not root.is_dir():
        return ""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.glob("*.py")) if path.is_file())


@contextmanager
def runtime_environment(root: Path):
    old_root = os.environ.get("AITEST_WORKSPACE_ROOT")
    old_db = os.environ.get("AITEST_RUNTIME_SPINE_DB")
    os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
    os.environ["AITEST_RUNTIME_SPINE_DB"] = str(root / "runtime-spine.db")
    try:
        yield
    finally:
        if old_root is None:
            os.environ.pop("AITEST_WORKSPACE_ROOT", None)
        else:
            os.environ["AITEST_WORKSPACE_ROOT"] = old_root
        if old_db is None:
            os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
        else:
            os.environ["AITEST_RUNTIME_SPINE_DB"] = old_db


def durable_counts(runtime, mission_id: str) -> dict[str, int]:
    composed = runtime.replay_composed(mission_id)
    work_graph = composed.extension_state("r1_2_work_graph")
    execution = composed.extension_state("r1_3b_execution_resume")
    return {
        "head_seq": runtime.get_head_seq(mission_id),
        "plans": len(tuple(getattr(work_graph, "plans", ()) or ())),
        "plan_revisions": len(tuple(getattr(work_graph, "revisions", ()) or ())),
        "tasks": len(tuple(getattr(work_graph, "tasks", ()) or ())),
        "attempts": len(tuple(getattr(execution, "attempts", ()) or ())),
        "sessions": len(tuple(getattr(composed.core_state, "sessions", ()) or ())),
    }


def g4_r36_counts(runtime, mission_id: str) -> dict[str, int]:
    composed = runtime.replay_composed(mission_id)
    g4 = composed.extension_state("g4_real_execution_goal_convergence")
    r36 = R36ApplicationService(runtime).state(mission_id)
    return {
        "head_seq": runtime.get_head_seq(mission_id),
        "g4_facts": len(tuple(getattr(g4, "facts", ()) or ())),
        "r36_anomalies": len(r36.anomalies),
    }


def expected_missing_action(value: Any) -> bool:
    return isinstance(value, BaseException) and "G5_ACTION_FORBIDDEN" in str(value)


def director_call(command, action: str, payload: Mapping[str, Any]) -> tuple[dict[str, Any], BaseException | None]:
    value, exc = invoke(lambda: command("DIRECTOR", action, dict(payload)))
    return (value if isinstance(value, dict) else {}), exc


def exact_hunter_task(candidate_id: str, anomaly_id: str) -> dict[str, Any]:
    return {
        "objective": f"Investigate exact candidate {candidate_id}",
        "constraints": [
            {"kind": "candidate_id", "value": candidate_id},
            {"kind": "anomaly_id", "value": anomaly_id},
        ],
        "tasks": [
            {
                "task_key": f"investigate-{candidate_id}",
                "intent": f"Investigate candidate {candidate_id} from anomaly {anomaly_id}",
                "acceptance_criteria": [
                    {
                        "id": "defect-truth",
                        "description": f"Resolve defect truth for {candidate_id}",
                    }
                ],
                "routing": {
                    "role": "DEFECT_HUNTER",
                    "agent_name": "aitest-diagnosis",
                    "required_capabilities": sorted(G5_CAPABILITIES),
                    "isolation_policy": "DEDICATED_TASK_SESSION",
                    "parallelism_policy": "SERIAL",
                },
            }
        ],
        "dependencies": [],
    }


def build_director_runtime_fixture(root: Path, command) -> dict[str, Any]:
    db = root / "runtime-spine.db"
    runtime = create_canonical_runtime(root, db_path=db)
    orchestration = G21AutonomousOrchestrationService(
        runtime,
        root,
        session_provider=FakeOpenCodeSessionProvider(root),
    )
    coverage = {
        "provider": MappingCoveragePlatformProvider(
            CoverageProviderResult("SOURCE_UNAVAILABLE", ())
        )
    }
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
    product_entry.G3TestingIntelligenceService = (
        lambda value, orchestration=None: G3TestingIntelligenceService(
            value,
            coverage_provider=coverage["provider"],
            orchestration=orchestration or orchestration_fixture,
        )
    )
    product_entry._G4_CAPABILITY_EXECUTORS = {"API": executor}
    try:
        repo, base_ref, head_ref = make_repo(
            root,
            "director-cfg-data",
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
        started = product_entry.orchestration_command(
            "DIRECTOR", "start_test", {"request": intake_request()}
        )
        mission_id = started["intake"]["intake"]["mission_id"]
        cycle = g3_cycle(mission_id, orchestration, coverage, repositories, 1)
        case_fact = cycle["cases"]["ready_cases"][0]["case"]
        case = case_fact["payload"]["r3_3_case"]
        strategy_id = cycle["strategy"]["strategy"]["strategy_version_id"]
        quality_version_ref, campaign_refs = r41(runtime, mission_id, "director")

        g4 = G4RealExecutionService(
            runtime,
            orchestration=orchestration,
            capability_executors={"API": executor},
        )
        g4.create_goal(
            mission_id,
            {
                "goal_id": "g5-director",
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
                "batch_id": "director-batch",
                "goal_id": "g5-director",
                "case_refs": [case_fact["fact_id"]],
                "strategy_version_id": strategy_id,
                "target_application": "cfg-data",
                "status": "RUNNING",
            },
        )
        dispatched = orchestration.propose_plan(
            mission_id,
            {
                "objective": "Create two governed unexpected observations",
                "tasks": [exec_task("DIRECTOR-FAIL", case_fact["fact_id"])],
                "dependencies": [],
            },
        )["next"]
        executor_binding = binding(dispatched)
        observations = []
        for index, step_id in enumerate(("director-admitted", "director-unadmitted")):
            execution_payload = {
                **executor_binding,
                "case_id": str(case["tc_id"]),
                "case_version": str(case["case_version_id"]),
                "case_spec_fact_id": case_fact["fact_id"],
                "execution_batch_id": "director-batch",
            }
            g4.record_cursor(
                mission_id,
                {
                    **execution_payload,
                    "current_step_index": index,
                    "completed_step_ids": ["director-admitted"] if index else [],
                    "pending_step_id": step_id,
                },
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
                        "step_id": step_id,
                        "expected": "INVARIANT_OK",
                        "fixture_actual": f"INVARIANT_BROKEN_{index}",
                    },
                    "execution_node": "node-director",
                },
            )
            if outcome.get("status") != "FAIL":
                raise RuntimeError("DIRECTOR_G4_FAIL_FIXTURE_INVALID")
            observations.append(g4.state(mission_id).by_kind("UNEXPECTED_OBSERVATION")[-1])
        finish(orchestration, executor_binding, "two governed observations captured")

        hunter_dispatch = orchestration.propose_plan(
            mission_id,
            {
                "objective": "Admit and investigate one governed observation",
                "tasks": [exact_hunter_task("candidate-director", observations[0].fact_id)["tasks"][0]],
                "dependencies": [],
            },
        )["next"]
        hunter_binding = binding(hunter_dispatch)
        admitted_result = command(
            "DEFECT_HUNTER",
            "record_anomaly",
            {**hunter_binding, "g4_observation_ref": observations[0].to_dict()},
        )
        r36 = R36ApplicationService(runtime)
        anomaly = r36.state(mission_id).anomalies[-1]
        candidate_id = "candidate-director"
        command(
            "DEFECT_HUNTER",
            "create_candidate",
            {
                **hunter_binding,
                "candidate_id": candidate_id,
                "anomaly_refs": [anomaly.anomaly_id],
                "classification": "PRODUCT_DEFECT_CANDIDATE",
                "alternative_classifications": ALT,
                "hypothesis": "same governed invariant fails",
                "affected_scope": {"component": "cfg-data"},
            },
        )
        command(
            "DEFECT_HUNTER",
            "request_evidence_deepening",
            {
                **hunter_binding,
                "candidate_id": candidate_id,
                "mode": "EXISTING_TYPED_REFS",
                "evidence_refs": [
                    observations[0].fact_id,
                    str(observations[0].payload["step_result_ref"]),
                ],
                "requested_channels": ["G4_FACT"],
                "cursor": observations[0].fact_id,
            },
        )
        deepening = r36.state(mission_id).deepenings[-1]
        evidence_id = "evidence-director"
        correlation_id = "correlation-director"
        repro_id = "repro-director"
        false_positive_id = "fp-director"
        command(
            "DEFECT_HUNTER",
            "record_evidence_assessment",
            {
                **hunter_binding,
                "candidate_id": candidate_id,
                "assessment_id": evidence_id,
                "evidence_refs": list(deepening.evidence_refs),
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
        command(
            "DEFECT_HUNTER",
            "correlate_sources",
            {
                **hunter_binding,
                "candidate_id": candidate_id,
                "correlation_id": correlation_id,
                "source_refs": [
                    {"ref_id": observations[0].fact_id, "digest": observations[0].digest},
                    {
                        "ref_id": observations[1].fact_id,
                        "digest": observations[1].digest,
                    },
                ],
                "correlation_keys": {
                    "business_rule": "REQ-018",
                    "mechanism": "same-boundary",
                },
                "method": "TYPED_RUNTIME_CORRELATION",
                "match_quality": "EXACT",
                "confidence": 1.0,
                "time_window": {},
                "conflict_refs": [],
            },
        )
        command(
            "DEFECT_HUNTER",
            "evaluate_reproducibility",
            {
                **hunter_binding,
                "candidate_id": candidate_id,
                "reproducibility_id": repro_id,
                "status": "REPRODUCED",
                "attempt_refs": [executor_binding["attempt_id"]],
                "evidence_refs": list(deepening.evidence_refs),
                "controlled_variables": {"build": "same"},
                "signature": "director-same-failure",
                "comparison": "same governed failure reproduced",
                "blocking_basis": None,
            },
        )
        command(
            "DEFECT_HUNTER",
            "assess_false_positive",
            {
                **hunter_binding,
                "candidate_id": candidate_id,
                "false_positive_id": false_positive_id,
                "status": "NOT_FALSE_POSITIVE",
                "alternatives_considered": ALT,
                "evidence_refs": list(deepening.evidence_refs),
                "unresolved_refs": [],
                "decision_basis": "all frozen alternatives excluded",
            },
        )
        origin = {
            "mission_id": mission_id,
            "architecture_baseline_ref": "v7",
            "source": "PRE_EC6_DIRECTOR_ORACLE_PREREQUISITE",
        }
        r36.assess_defect_truth(
            {
                "mission_id": mission_id,
                "idempotency_key": "director:assessment:inconclusive",
                "origin_lineage": origin,
                "defect_assessment": {
                    "assessment_id": "assessment-director-inconclusive",
                    "candidate_id": candidate_id,
                    "outcome": "INCONCLUSIVE",
                    "final_classification": "UNKNOWN_INCONCLUSIVE",
                    "evidence_assessment_refs": [evidence_id],
                    "reproducibility_ref": repro_id,
                    "false_positive_ref": false_positive_id,
                    "causal_basis_refs": [],
                    "unresolved_contradiction_refs": [],
                    "evidence_class": "ENGINEERING_EVIDENCE",
                    "decision_basis": "pre-confirmation investigation remains explicit",
                },
            }
        )
        command(
            "DEFECT_HUNTER",
            "record_rca",
            {
                **hunter_binding,
                "candidate_id": candidate_id,
                "rca_id": "rca-director",
                "cause_class": "UNKNOWN",
                "status": "PARTIAL",
                "causal_chain_refs": [],
                "root_component": "cfg-data",
                "contradiction_refs": [],
                "decision_basis": "bounded causal analysis",
            },
        )
        receipt = deepening.workset_receipt
        for checkpoint_id in ("checkpoint-z-older", "checkpoint-a-latest"):
            command(
                "DEFECT_HUNTER",
                "record_checkpoint",
                {
                    **hunter_binding,
                    "candidate_id": candidate_id,
                    "checkpoint_id": checkpoint_id,
                    "cursor": receipt.next_cursor,
                    "workset_digest": receipt.receipt_digest,
                    "session_ref": hunter_binding["session_id"],
                    "omitted_refs": list(receipt.omitted_refs),
                },
            )
        checkpoint_event = max(
            (
                event
                for event in runtime.list_events(mission_id)
                if event.event_type == CHECKPOINT_RECORDED
                and event.entity_id in {"checkpoint-z-older", "checkpoint-a-latest"}
            ),
            key=lambda event: event.seq,
        )
        if checkpoint_event.entity_id != "checkpoint-a-latest":
            raise RuntimeError("DIRECTOR_CHECKPOINT_EVENT_ORDER_FIXTURE_INVALID")

        confirmed_id = "assessment-director-confirmed"
        command(
            "DEFECT_HUNTER",
            "assess_defect_truth",
            {
                **hunter_binding,
                "candidate_id": candidate_id,
                "defect_assessment": {
                    "assessment_id": confirmed_id,
                    "candidate_id": candidate_id,
                    "outcome": "CONFIRMED_DEFECT",
                    "final_classification": "PRODUCT_DEFECT",
                    "evidence_assessment_refs": [evidence_id],
                    "reproducibility_ref": repro_id,
                    "false_positive_ref": false_positive_id,
                    "causal_basis_refs": [],
                    "unresolved_contradiction_refs": [],
                    "evidence_class": "ENGINEERING_EVIDENCE",
                    "decision_basis": "governed evidence confirms ordinary defect",
                },
                "policy_context": {
                    "severity": "S3",
                    "security_sensitive": False,
                    "performance_sensitive": False,
                    "regulatory_sensitive": False,
                },
            },
        )
        assessment_ref = exact_ref(runtime, mission_id, confirmed_id)
        command(
            "DEFECT_HUNTER",
            "handoff_confirmed_defect",
            {
                **hunter_binding,
                "candidate_id": candidate_id,
                "defect_assessment_ref": assessment_ref,
                "defect_assessment_digest": assessment_ref["source_digest"],
                "quality_version_ref": quality_version_ref,
                "campaign_refs": campaign_refs,
            },
        )
        lifecycle = R43ApplicationService(runtime).state(
            mission_id
        ).confirmed_defect_lifecycles[-1]
        finish(orchestration, hunter_binding, "initial director investigation complete")
        exact_dispatch = orchestration.propose_plan(
            mission_id, exact_hunter_task(candidate_id, anomaly.anomaly_id)
        )["next"]
        exact_binding = binding(exact_dispatch)
        exact_task_id = exact_binding["task_id"]
        command(
            "DIRECTOR",
            "request_human_review",
            {
                **exact_binding,
                "candidate_id": candidate_id,
                "gate_id": "gate-director-status",
                "policy_context": {"severity": "S1", "security_sensitive": True},
            },
        )
        gate = HumanGateApplicationService(runtime).state(mission_id).gate(
            "gate-director-status"
        )
        if gate is None:
            raise RuntimeError("DIRECTOR_HUMAN_GATE_FIXTURE_INVALID")

        negative_started = orchestration.start_test(request("director-no-suitable"))
        negative_mission_id = negative_started["intake"]["intake"]["mission_id"]
        negative_seed = seed(runtime, negative_mission_id, "director-no-suitable")
        wrong_dispatch = orchestration.propose_plan(
            negative_mission_id,
            task(
                "EXECUTOR",
                ["OPENCODE_AGENT_SESSION", "TASK_OUTCOME_REPORT"],
            ),
        )["next"]
        wrong_task_id = binding(wrong_dispatch)["task_id"]

        composed = runtime.replay_composed(mission_id)
        work_graph = composed.extension_state("r1_2_work_graph")
        session_control = composed.extension_state("g2_1_session_control")
        exact_task = work_graph.task(exact_task_id)
        exact_plan = work_graph.plan(exact_task.plan_id)
        exact_revision = work_graph.revision(exact_task.plan_revision_id)
        exact_route = session_control.route(exact_task_id)
        return {
            "runtime": runtime,
            "mission_id": mission_id,
            "observations": tuple(observations),
            "admitted_anomaly": anomaly,
            "admitted_result": admitted_result,
            "candidate_id": candidate_id,
            "ids": {
                "anomaly": anomaly.anomaly_id,
                "deepening": deepening.deepening_id,
                "evidence": evidence_id,
                "correlation": correlation_id,
                "reproducibility": repro_id,
                "false_positive": false_positive_id,
                "defect_assessment": confirmed_id,
                "rca": "rca-director",
                "checkpoint": checkpoint_event.entity_id,
                "checkpoint_event_seq": checkpoint_event.seq,
                "gate": gate.gate_id,
            },
            "lifecycle": lifecycle,
            "exact_task": {
                "plan": exact_plan,
                "revision": exact_revision,
                "task": exact_task,
                "route": exact_route,
            },
            "negative": {
                "mission_id": negative_mission_id,
                "candidate_id": negative_seed["candidate_id"],
                "anomaly_id": "anomaly-director-no-suitable",
                "wrong_task_id": wrong_task_id,
            },
        }
    finally:
        (
            product_entry.orchestration_service,
            product_entry.default_service,
            product_entry.G3TestingIntelligenceService,
            product_entry._G4_CAPABILITY_EXECUTORS,
        ) = saved


def _ref_matches(value: Any, *, ref_type: str, ref_id: str, digest: str) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("ref_type") == ref_type
        and value.get("ref_id") == ref_id
        and value.get("digest") == digest
    )


def evaluate_director_runtime(command, fixture: Mapping[str, Any]) -> tuple[dict[str, bool], bool]:
    checks = {name: False for name in DIRECTOR_RUNTIME_CHECKS}
    runtime = fixture["runtime"]
    mission_id = fixture["mission_id"]
    candidate_id = fixture["candidate_id"]
    observations = fixture["observations"]
    admitted_anomaly = fixture["admitted_anomaly"]
    ids = fixture["ids"]
    lifecycle = fixture["lifecycle"]
    expected_missing_only = []

    intake_before = g4_r36_counts(runtime, mission_id)
    intake, intake_exc = director_call(
        command, "intake_observations", {"mission_id": mission_id}
    )
    intake_after = g4_r36_counts(runtime, mission_id)
    expected_missing_only.append(intake_exc is None or expected_missing_action(intake_exc))
    entries = intake.get("observations") if isinstance(intake.get("observations"), list) else []
    entries_by_id = {
        str((entry.get("observation_ref") or {}).get("ref_id")): entry
        for entry in entries
        if isinstance(entry, Mapping) and isinstance(entry.get("observation_ref"), Mapping)
    }
    admitted_entry = entries_by_id.get(observations[0].fact_id) or {}
    unadmitted_entry = entries_by_id.get(observations[1].fact_id) or {}
    exact_observation_refs = all(
        _ref_matches(
            entries_by_id.get(observation.fact_id, {}).get("observation_ref"),
            ref_type="G4_UNEXPECTED_OBSERVATION",
            ref_id=observation.fact_id,
            digest=observation.digest,
        )
        for observation in observations
    )
    checks["director_intake_observations_is_r1_read_only"] = (
        intake_exc is None
        and intake.get("status") == "PASS"
        and intake.get("truth_source") == "R1_EVENT_STREAM"
        and intake.get("mission_id") == mission_id
        and exact_observation_refs
        and intake_before == intake_after
    )
    checks["director_intake_reports_admitted_status"] = (
        intake_exc is None
        and admitted_entry.get("admission_status") == "ADMITTED"
        and _ref_matches(
            admitted_entry.get("r3_6_anomaly_ref"),
            ref_type="R3_6_TEST_ANOMALY",
            ref_id=admitted_anomaly.anomaly_id,
            digest=admitted_anomaly.anomaly_digest,
        )
        and unadmitted_entry.get("admission_status") == "NOT_ADMITTED"
        and unadmitted_entry.get("r3_6_anomaly_ref") is None
    )

    investigation_before = runtime.get_head_seq(mission_id)
    investigation, investigation_exc = director_call(
        command,
        "investigation_status",
        {"mission_id": mission_id, "candidate_id": candidate_id},
    )
    investigation_after = runtime.get_head_seq(mission_id)
    expected_missing_only.append(
        investigation_exc is None or expected_missing_action(investigation_exc)
    )
    investigations = (
        investigation.get("r3_6_investigations")
        if isinstance(investigation.get("r3_6_investigations"), list)
        else []
    )
    selected = next(
        (
            item
            for item in investigations
            if isinstance(item, Mapping)
            and isinstance(item.get("candidate"), Mapping)
            and item["candidate"].get("candidate_id") == candidate_id
        ),
        {},
    )
    collection_expectations = {
        "anomalies": ("anomaly_id", ids["anomaly"]),
        "deepenings": ("deepening_id", ids["deepening"]),
        "evidence_assessments": ("assessment_id", ids["evidence"]),
        "correlations": ("correlation_id", ids["correlation"]),
        "reproducibility_assessments": (
            "reproducibility_id",
            ids["reproducibility"],
        ),
        "false_positive_assessments": (
            "false_positive_id",
            ids["false_positive"],
        ),
        "defect_assessments": ("assessment_id", ids["defect_assessment"]),
        "rca_records": ("rca_id", ids["rca"]),
    }
    durable_collections = all(
        any(
            isinstance(item, Mapping) and item.get(id_field) == expected_id
            for item in selected.get(collection_name, [])
        )
        for collection_name, (id_field, expected_id) in collection_expectations.items()
    )
    gate_visible = any(
        isinstance(item, Mapping) and item.get("gate_id") == ids["gate"]
        for item in investigation.get("r2_6_gate_state", [])
    )
    lifecycle_visible = any(
        isinstance(item, Mapping)
        and item.get("ref_id") == lifecycle.lifecycle_id
        and item.get("digest") == lifecycle.lifecycle_digest
        for item in investigation.get("r4_3_lifecycle_refs", [])
    )
    checks["director_investigation_status_is_durable_truth"] = (
        investigation_exc is None
        and investigation.get("status") == "PASS"
        and investigation.get("truth_source") == "R1_EVENT_STREAM"
        and investigation.get("conversation_is_not_truth") is True
        and investigation.get("read_only") is True
        and investigation.get("mission_id") == mission_id
        and durable_collections
        and gate_visible
        and lifecycle_visible
        and investigation_before == investigation_after
    )
    latest = selected.get("latest_valid_checkpoint") if isinstance(selected, Mapping) else None
    durable_state = R36ApplicationService(runtime).state(mission_id)
    durable_checkpoint = durable_state.checkpoint(ids["checkpoint"])
    durable_receipt = durable_state.deepening(ids["deepening"]).workset_receipt
    checks["director_investigation_status_uses_latest_valid_checkpoint"] = (
        investigation_exc is None
        and isinstance(latest, Mapping)
        and latest.get("event_seq") == ids["checkpoint_event_seq"]
        and isinstance(latest.get("checkpoint"), Mapping)
        and latest["checkpoint"] == durable_checkpoint.to_dict()
        and latest.get("workset_receipt") == durable_receipt.to_dict()
        and latest["checkpoint"].get("checkpoint_id") == "checkpoint-a-latest"
        and latest["checkpoint"].get("workset_digest")
        == durable_receipt.receipt_digest
        and latest["checkpoint"].get("cursor") == durable_receipt.next_cursor
        and tuple(latest["checkpoint"].get("omitted_refs") or ())
        == durable_receipt.omitted_refs
    )

    negative = fixture["negative"]
    no_task_before = durable_counts(runtime, negative["mission_id"])
    no_task_result, no_task_exc = director_call(
        command,
        "open_investigation",
        {
            "mission_id": negative["mission_id"],
            "candidate_id": negative["candidate_id"],
            "anomaly_refs": [negative["anomaly_id"]],
            "objective": f"Investigate exact candidate {negative['candidate_id']}",
        },
    )
    no_task_after = durable_counts(runtime, negative["mission_id"])
    expected_missing_only.append(no_task_exc is None or expected_missing_action(no_task_exc))
    proposal = no_task_result.get("planner_proposal")
    proposal_tasks = proposal.get("tasks") if isinstance(proposal, Mapping) else None
    proposal_task = proposal_tasks[0] if isinstance(proposal_tasks, list) and len(proposal_tasks) == 1 else {}
    proposal_route = proposal_task.get("routing") if isinstance(proposal_task, Mapping) else {}
    proposal_is_bounded = (
        isinstance(proposal, Mapping)
        and isinstance(proposal.get("objective"), str)
        and 0 < len(proposal["objective"]) <= 512
        and isinstance(proposal.get("constraints"), list)
        and isinstance(proposal.get("dependencies"), list)
        and isinstance(proposal_task, Mapping)
        and negative["candidate_id"] in json.dumps(proposal_task, sort_keys=True)
        and len(json.dumps(proposal, sort_keys=True)) <= 12288
    )
    exact_proposal_route = (
        isinstance(proposal_route, Mapping)
        and proposal_route.get("role") == "DEFECT_HUNTER"
        and proposal_route.get("agent_name") == "aitest-diagnosis"
        and set(proposal_route.get("required_capabilities") or ()) == G5_CAPABILITIES
        and len(proposal_route.get("required_capabilities") or ())
        == len(G5_CAPABILITIES)
        and proposal_route.get("isolation_policy") == "DEDICATED_TASK_SESSION"
        and proposal_route.get("parallelism_policy") == "SERIAL"
    )
    governed_required = (
        no_task_exc is None
        and no_task_result.get("status") == "GOVERNED_WORK_REQUIRED"
        and no_task_result.get("truth_source") == "R1_EVENT_STREAM"
        and no_task_result.get("next_required_action") == "G2_PLAN_REVISION_REQUIRED"
        and proposal_is_bounded
        and exact_proposal_route
    )
    checks["director_open_investigation_returns_governed_work"] = governed_required
    checks["director_open_investigation_does_not_create_plan"] = (
        governed_required
        and no_task_before["head_seq"] == no_task_after["head_seq"]
        and no_task_before["plans"] == no_task_after["plans"]
        and no_task_before["plan_revisions"] == no_task_after["plan_revisions"]
    )
    checks["director_open_investigation_does_not_create_task"] = (
        governed_required
        and no_task_before["tasks"] == no_task_after["tasks"]
        and no_task_before["attempts"] == no_task_after["attempts"]
        and no_task_before["sessions"] == no_task_after["sessions"]
    )

    exact_before = durable_counts(runtime, mission_id)
    exact_result, exact_exc = director_call(
        command,
        "open_investigation",
        {
            "mission_id": mission_id,
            "candidate_id": candidate_id,
            "anomaly_refs": [ids["anomaly"]],
            "objective": f"Investigate exact candidate {candidate_id}",
        },
    )
    exact_after = durable_counts(runtime, mission_id)
    expected_missing_only.append(exact_exc is None or expected_missing_action(exact_exc))
    existing = exact_result.get("existing_governed_task")
    exact_entities = fixture["exact_task"]
    exact_refs = (
        isinstance(existing, Mapping)
        and _ref_matches(
            existing.get("plan_ref"),
            ref_type="R1_PLAN",
            ref_id=exact_entities["plan"].plan_id,
            digest=canonical_sha256(exact_entities["plan"].to_dict()),
        )
        and _ref_matches(
            existing.get("plan_revision_ref"),
            ref_type="R1_PLAN_REVISION",
            ref_id=exact_entities["revision"].revision_id,
            digest=canonical_sha256(exact_entities["revision"].to_dict()),
        )
        and _ref_matches(
            existing.get("task_ref"),
            ref_type="R1_TASK",
            ref_id=exact_entities["task"].task_id,
            digest=canonical_sha256(exact_entities["task"].to_dict()),
        )
        and _ref_matches(
            existing.get("route_ref"),
            ref_type="G2_1_TASK_ROUTE",
            ref_id=exact_entities["task"].task_id,
            digest=exact_entities["route"].route_digest,
        )
    )
    negative_rejects_wrong_and_cross_mission = (
        no_task_exc is None
        and no_task_result.get("next_required_action") == "G2_PLAN_REVISION_REQUIRED"
        and no_task_result.get("existing_governed_task") is None
        and negative["wrong_task_id"]
        not in json.dumps(no_task_result, sort_keys=True)
        and exact_entities["task"].task_id
        not in json.dumps(no_task_result, sort_keys=True)
    )
    checks["director_existing_hunter_task_reused_only_if_exact"] = (
        exact_exc is None
        and exact_result.get("truth_source") == "R1_EVENT_STREAM"
        and exact_result.get("next_required_action") == "EXISTING_GOVERNED_TASK"
        and exact_refs
        and exact_before == exact_after
        and negative_rejects_wrong_and_cross_mission
    )

    canonical_before = (
        runtime.get_head_seq(mission_id),
        len(R43ApplicationService(runtime).state(mission_id).confirmed_defect_lifecycles),
    )
    canonical, canonical_exc = director_call(
        command, "canonical_defects", {"mission_id": mission_id}
    )
    canonical_after = (
        runtime.get_head_seq(mission_id),
        len(R43ApplicationService(runtime).state(mission_id).confirmed_defect_lifecycles),
    )
    expected_missing_only.append(canonical_exc is None or expected_missing_action(canonical_exc))
    defect_entries = (
        canonical.get("canonical_defects")
        if isinstance(canonical.get("canonical_defects"), list)
        else []
    )
    lifecycle_entry = next(
        (
            item
            for item in defect_entries
            if isinstance(item, Mapping)
            and item.get("lifecycle_id") == lifecycle.lifecycle_id
        ),
        {},
    )
    checks["director_canonical_defects_reads_r43"] = (
        canonical_exc is None
        and canonical.get("status") == "PASS"
        and canonical.get("truth_source") == "R1_EVENT_STREAM"
        and canonical.get("mission_id") == mission_id
        and lifecycle_entry == lifecycle.to_dict()
        and lifecycle_entry.get("lifecycle_digest") == lifecycle.lifecycle_digest
    )
    negative_canonical_before = runtime.get_head_seq(negative["mission_id"])
    negative_canonical, negative_canonical_exc = director_call(
        command,
        "canonical_defects",
        {"mission_id": negative["mission_id"]},
    )
    negative_canonical_after = runtime.get_head_seq(negative["mission_id"])
    expected_missing_only.append(
        negative_canonical_exc is None
        or expected_missing_action(negative_canonical_exc)
    )
    negative_defects = (
        negative_canonical.get("canonical_defects")
        if isinstance(negative_canonical.get("canonical_defects"), list)
        else None
    )
    checks["director_canonical_defects_is_same_mission_read_only"] = (
        checks["director_canonical_defects_reads_r43"]
        and negative_canonical_exc is None
        and negative_canonical.get("truth_source") == "R1_EVENT_STREAM"
        and negative_defects == []
        and lifecycle.lifecycle_id not in json.dumps(negative_canonical, sort_keys=True)
        and canonical_before == canonical_after
        and negative_canonical_before == negative_canonical_after
    )
    return checks, all(expected_missing_only)


def main() -> int:
    foundation = {
        "product_entry_importable": callable(product_entry.parser),
        "r36_service_available": callable(R36ApplicationService),
        "r43_service_available": callable(R43ApplicationService),
        "r36_historical_baseline_unchanged": ARCHITECTURE_BASELINE_REF == "v5",
        "no_g5_durable_extension_registered": all(
            "g5" not in str(getattr(manifest, "extension_id", "")).lower()
            for manifest in canonical_extension_manifests()
        ),
    }

    g5_module, g5_import_error = invoke(lambda: importlib.import_module("aitest_runtime.g5"))
    source = g5_source()
    command = getattr(product_entry, "g5_command", None)

    direct_status = {}
    direct_exc = None
    if callable(command):
        with tempfile.TemporaryDirectory(prefix="g5-product-status-") as td:
            old_root = os.environ.get("AITEST_WORKSPACE_ROOT")
            old_db = os.environ.get("AITEST_RUNTIME_SPINE_DB")
            os.environ["AITEST_WORKSPACE_ROOT"] = td
            os.environ["AITEST_RUNTIME_SPINE_DB"] = str(Path(td) / "runtime-spine.db")
            try:
                direct_status, direct_exc = invoke(lambda: command("DIRECTOR", "status", {}))
            finally:
                if old_root is None: os.environ.pop("AITEST_WORKSPACE_ROOT", None)
                else: os.environ["AITEST_WORKSPACE_ROOT"] = old_root
                if old_db is None: os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
                else: os.environ["AITEST_RUNTIME_SPINE_DB"] = old_db

    cli = {}
    cli_returncode = None
    if parser_has_g5():
        with tempfile.TemporaryDirectory(prefix="g5-product-cli-") as td:
            env = os.environ.copy()
            env["AITEST_WORKSPACE_ROOT"] = td
            env["AITEST_RUNTIME_SPINE_DB"] = str(Path(td) / "runtime-spine.db")
            env["PYTHONPATH"] = str(RUNTIME) + os.pathsep + env.get("PYTHONPATH", "")
            proc = subprocess.run(
                [sys.executable, "-m", "aitest_runtime.product_entry", "g5", "--role", "DIRECTOR", "--action", "status", "--payload", "{}"],
                cwd=str(WORKSPACE), env=env, text=True, capture_output=True, timeout=60,
            )
            cli_returncode = proc.returncode
            cli = parse_json(proc.stdout)

    invalid_role = invalid_role_exc = invalid_action = invalid_action_exc = None
    if callable(command):
        invalid_role, invalid_role_exc = invoke(lambda: command("EXECUTOR", "status", {}))
        invalid_action, invalid_action_exc = invoke(lambda: command("DIRECTOR", "execute_provider", {}))

    runtime_behavior = {
        "g5_command_callable": callable(command),
        "g5_cli_registered": parser_has_g5(),
        "director_status_is_r1_truth": isinstance(direct_status, dict)
        and direct_exc is None
        and direct_status.get("truth_source") == "R1_EVENT_STREAM",
        "cli_status_is_json_r1_truth": cli_returncode == 0
        and cli.get("truth_source") == "R1_EVENT_STREAM",
        "invalid_role_fails_with_g5_role_forbidden": "G5_ROLE_FORBIDDEN"
        in error_code(invalid_role_exc or invalid_role),
        "invalid_action_fails_closed": any(
            code in error_code(invalid_action_exc or invalid_action)
            for code in ("G5_ACTION_FORBIDDEN", "G5_DIRECT_EXECUTION_FORBIDDEN")
        ),
        **{name: False for name in DIRECTOR_RUNTIME_CHECKS},
    }
    fixture_error = None
    if callable(command):
        with tempfile.TemporaryDirectory(prefix="g5-director-runtime-") as td:
            with runtime_environment(Path(td)):
                fixture, fixture_error = invoke(
                    lambda: build_director_runtime_fixture(Path(td), command)
                )
                if isinstance(fixture, dict) and fixture_error is None:
                    observations = fixture["observations"]
                    r36_state = R36ApplicationService(fixture["runtime"]).state(
                        fixture["mission_id"]
                    )
                    exact_route = fixture["exact_task"]["route"]
                    foundation.update(
                        {
                            "director_runtime_fixture_constructed": True,
                            "two_exact_g4_observations_exist": len(observations) == 2
                            and all(
                                item.fact_kind == "UNEXPECTED_OBSERVATION"
                                and item.payload.get("status") == "OBSERVATION_ONLY"
                                and item.payload.get("g5_defect_truth") == "HOLD"
                                for item in observations
                            ),
                            "one_observation_is_g5_admitted": any(
                                item.origin_lineage.get("source") == "G5_G4_ADMISSION"
                                and (
                                    item.origin_lineage.get("g4_observation_ref") or {}
                                ).get("ref_id")
                                == observations[0].fact_id
                                and (
                                    item.origin_lineage.get("g4_observation_ref") or {}
                                ).get("digest")
                                == observations[0].digest
                                for item in r36_state.anomalies
                            ),
                            "one_observation_remains_unadmitted": all(
                                (
                                    item.origin_lineage.get("g4_observation_ref") or {}
                                ).get("ref_id")
                                != observations[1].fact_id
                                for item in r36_state.anomalies
                            ),
                            "rich_r36_investigation_fixture_exists": all(
                                (
                                    r36_state.candidate(fixture["candidate_id"]),
                                    r36_state.deepening(fixture["ids"]["deepening"]),
                                    r36_state.evidence_assessment(
                                        fixture["ids"]["evidence"]
                                    ),
                                    r36_state.correlation(fixture["ids"]["correlation"]),
                                    r36_state.reproducibility(
                                        fixture["ids"]["reproducibility"]
                                    ),
                                    r36_state.false_positive(
                                        fixture["ids"]["false_positive"]
                                    ),
                                    r36_state.defect_assessment(
                                        fixture["ids"]["defect_assessment"]
                                    ),
                                    r36_state.rca(fixture["ids"]["rca"]),
                                    r36_state.checkpoint("checkpoint-z-older"),
                                    r36_state.checkpoint("checkpoint-a-latest"),
                                )
                            ),
                            "latest_checkpoint_event_order_opposes_lexical_order": fixture[
                                "ids"
                            ]["checkpoint"]
                            == "checkpoint-a-latest"
                            and "checkpoint-a-latest" < "checkpoint-z-older",
                            "r2_6_gate_fixture_exists": fixture["ids"]["gate"]
                            == "gate-director-status",
                            "r4_3_lifecycle_fixture_exists": bool(
                                fixture["lifecycle"].lifecycle_id
                                and fixture["lifecycle"].lifecycle_digest
                            ),
                            "exact_existing_hunter_task_fixture_exists": exact_route.role
                            == "DEFECT_HUNTER"
                            and exact_route.agent_name == "aitest-diagnosis"
                            and set(exact_route.required_capabilities)
                            == G5_CAPABILITIES,
                            "negative_wrong_role_task_fixture_exists": bool(
                                fixture["negative"]["wrong_task_id"]
                            ),
                        }
                    )
                    director_checks, expected_missing_only = evaluate_director_runtime(
                        command, fixture
                    )
                    runtime_behavior.update(director_checks)
                    foundation[
                        "director_actions_fail_closed_without_programming_exception"
                    ] = expected_missing_only
                else:
                    foundation.update(
                        {
                            "director_runtime_fixture_constructed": False,
                            "director_actions_fail_closed_without_programming_exception": False,
                        }
                    )

    integration_contract = {
        "g5_package_importable": g5_module is not None and g5_import_error is None,
        "g5_non_durable_contracts_present": g5_module is not None and all(
            getattr(g5_module, name, None) is not None
            for name in REQUIRED_NON_DURABLE_CONTRACTS
        ),
    }
    supplemental = {
        "director_action_registry_present": bool(source) and all(action in source for action in REQUIRED_DIRECTOR_ACTIONS),
        "worker_action_registry_present": bool(source) and all(action in source for action in REQUIRED_WORKER_ACTIONS),
        "r1_truth_contract_present": bool(source) and "R1_EVENT_STREAM" in source,
        "legacy_defect_module_not_imported": bool(source) and "aitest_runtime.defects" not in source and "AUTO_CONFIRMED" not in source,
        "static_registry_is_not_green_authority": True,
    }
    contract = {**integration_contract, **runtime_behavior, **supplemental}

    fixture_ok = all(foundation.values())
    missing = [name for name, value in contract.items() if not value]
    status = "PASS" if fixture_ok and not missing else "FAIL"
    truthful_red = fixture_ok and status == "FAIL" and bool(missing)
    out = {
        "suite": "test_g5_product_path",
        "status": status,
        "passed": sum(bool(v) for v in {**foundation, **contract}.values()),
        "total": len(foundation) + len(contract),
        "fixture_ok": fixture_ok,
        "truthful_red": truthful_red,
        "red_kind": "MISSING_G5_INTEGRATION" if truthful_red else None,
        "foundation_checks": foundation,
        "runtime_behavior_checks": runtime_behavior,
        "supplemental_checks": supplemental,
        "contract_checks": contract,
        "runtime_green_evidence": all(runtime_behavior.values()),
        "oracle_contract": {
            "current_red_is_truthful": truthful_red,
            "future_green_requires_real_runtime": True,
            "static_registry_is_green_authority": False,
            "director_runtime_check_names": sorted(DIRECTOR_RUNTIME_CHECKS),
        },
        "fixture_error": (
            {
                "type": type(fixture_error).__name__,
                "message": str(fixture_error),
            }
            if fixture_error is not None
            else None
        ),
        "missing_contract_checks": missing,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
