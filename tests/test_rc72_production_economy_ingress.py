"""C10 native Mission ingress: 11 role bindings, canonical R1 task identities and audit."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane
from rc7_runtime.models import Artifact, Mission, Task
from rc7_runtime.truth_overlay import append_entity
from rc7_runtime.rc72_model_economy import TokenEconomyError, UsageStatus
from rc7_runtime.rc72_production_economy_ingress import (
    _ROLE_NODE,
    ProductionEconomyBindingError,
    bind_release_batch_model_economy,
    canonical_role_metadata_resolver,
    read_mission_economy_config,
)


class _ProcessLauncher(DshHeadlessWorkerLauncher):
    def __init__(self, truth, role, root):
        self.truth = truth
        self.release_id = "REL-C10"
        self.role = role
        self.state_root = root / role
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.calls = []
        self.command_runner = self._run

    def _run(self, command, **kwargs):
        self.calls.append(tuple(command))
        events = [
            {"type": "session", "session_id": "session-" + self.role},
            {"type": "tool_call", "tool_name": "native-proof-tool"},
            {"type": "final", "usage": {"input_tokens": 9, "output_tokens": 3, "total_tokens": 12}},
        ]
        return SimpleNamespace(
            stdout="\n".join(json.dumps(event) for event in events) + "\n",
            stderr="", returncode=0,
        )

    def _persist_raw_worker_output(self, assignment, stdout, stderr):
        target = self.state_root / (assignment.assignment_id + ".jsonl")
        target.write_text(stdout, encoding="utf-8")
        return "file://" + target.as_posix()

    def execute(self, assignment, prompt):
        proc = self.command_runner(["dsh", "--json", "NATIVE_BOUND\n" + prompt], check=False)
        ref = self._persist_raw_worker_output(assignment, proc.stdout, proc.stderr)
        return SimpleNamespace(evidence_refs=(ref,)), {"candidate": True}


def _fixtures(tmp_path):
    truth = TruthRuntime(tmp_path / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth, Mission(mission_id="MISSION-C10", release_id="REL-C10", goal="canonical independent mission"),
    )
    control.register_task(Task(
        task_id="WI-DESIGN", mission_id="MISSION-C10",
        node="TEST_DESIGN", task_type="PRODUCE", objective="test obligations",
        input_artifact_refs=['ART-VERY-LONG-REQUIREMENT-DOCUMENT-IDENTITY-001','ART-VERY-LONG-CODE-CHANGE-TRACE-IDENTITY-002','ART-VERY-LONG-DESIGN-OBLIGATION-EVIDENCE-003','ART-VERY-LONG-AUTHORIZED-PARENT-EVALUATION-004'],
    ))
    # Source refs are canonical R1 Artifacts, not implicit external URI
    # shortcuts. The real TaskScheduler only promotes a registered Task to
    # READY when *all* required input artifacts are VALID.
    input_refs = truth.query("rc7_task", task_id="WI-DESIGN")[0]["input_artifact_refs"]
    for ref in input_refs:
        append_entity(truth, Artifact(
            artifact_id=ref, mission_id="MISSION-C10",
            artifact_type="upstream_evidence",
            producer_task_id="WI-DESIGN",
            content_ref="file://approved-source/" + ref,
        ), release_id="REL-C10")
    ready = control.scheduler.refresh_ready("MISSION-C10")
    assert {task.task_id for task in ready} == {"WI-DESIGN"}
    leased = control.scheduler.lease_task(
        "MISSION-C10", "WI-DESIGN", worker_ref="worker-design", capabilities=(),
    )
    assert leased is not None
    append_entity(truth, Artifact(
        artifact_id="ART-DESIGN", mission_id="MISSION-C10",
        artifact_type="test_design_candidate",
        producer_task_id="WI-DESIGN", content_ref="file://candidate",
    ), release_id="REL-C10")
    workers = {
        role: SimpleNamespace(launcher=_ProcessLauncher(truth, role, tmp_path))
        for role in _ROLE_NODE
    }
    return truth, control, workers


def _assignment(scope, *, agent="rc72-test", worker="worker-design", attempt="ATT-1"):
    return SimpleNamespace(
        mission_id="MISSION-C10", scope=scope,
        attempt_id=attempt, assignment_id="AS-" + attempt,
        worker_instance_id=worker, agent_id=agent,
    )


def test_real_all_role_binding_tracks_producer_and_independent_reviewer_as_distinct_calls(tmp_path):
    truth, control, workers = _fixtures(tmp_path)
    budget = bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
    )
    assert all(getattr(workers[role].launcher, "_rc72_production_economy_bound", False) for role in _ROLE_NODE)
    assert len(truth.query("rc72_token_budget", budget_id="MISSION-C10")) == 1

    workers["design"].launcher.execute(
        _assignment("task:WI-DESIGN", agent="designer"), "design required cases",
    )
    workers["design_review"].launcher.execute(
        _assignment("ART-DESIGN", agent="independent-reviewer", worker="fresh-reviewer", attempt="ATT-REVIEW"),
        "review canonical candidate",
    )
    calls = truth.query("rc72_token_call", mission_id="MISSION-C10")
    assert len(calls) == 2
    assert {row["workitem_id"] for row in calls} == {"WI-DESIGN"}
    assert {row["attempt_id"] for row in calls} == {"ATT-1", "ATT-REVIEW"}
    assert {row["state"] for row in calls} == {"COMPLETED"}
    assert {row["usage_status"] for row in calls} == {"MEASURED"}
    assert {row["context_projection_status"] for row in calls} == {"REFERENCE_ONLY"}
    assert {row["context_projection_applied_to_prompt"] for row in calls} == {False}
    assert all(row["context_envelope_id"].startswith("CTX-") for row in calls)
    assert budget.summary("MISSION-C10")["native_reference_projection_calls"] == 2
    assert budget.summary("MISSION-C10")["verified_context_savings_bytes"] is None
    assert len(truth.query("rc72_token_usage", mission_id="MISSION-C10")) == 2
    assert budget.summary("MISSION-C10")["actual_total_tokens"] == 24
    assert {row["task_id"] for row in truth.query("rc7_task", mission_id="MISSION-C10")} == {"WI-DESIGN"}


def test_review_artifact_fails_closed_if_cross_mission_or_unproven(tmp_path):
    truth, control, workers = _fixtures(tmp_path)
    resolve = canonical_role_metadata_resolver(truth, role="design_review", mission_id="MISSION-C10")
    with pytest.raises(ProductionEconomyBindingError, match="ARTIFACT_NOT_UNIQUE"):
        resolve(_assignment("ART-FORGED", worker="reviewer"))
    with pytest.raises(ProductionEconomyBindingError, match="REVIEWER_MUST_USE_ARTIFACT_SCOPE"):
        resolve(_assignment("task:WI-DESIGN", worker="reviewer"))


def test_missing_real_producer_lease_blocks_model_inference_without_business_pass(tmp_path):
    truth, control, workers = _fixtures(tmp_path)
    resolve = canonical_role_metadata_resolver(truth, role="design", mission_id="MISSION-C10")
    with pytest.raises(ProductionEconomyBindingError, match="PRODUCER_LEASE_MISMATCH"):
        resolve(_assignment("task:WI-DESIGN", worker="forged-worker"))
    assert truth.query("rc72_token_call", mission_id="MISSION-C10") == []


def test_explicit_deterministic_schedule_reaches_pre_spawn_hard_guard(tmp_path):
    truth, control, workers = _fixtures(tmp_path)
    control.schedule_semantics.record(
        mission_id="MISSION-C10", workitem_id="WI-DESIGN",
        execution_mode="DETERMINISTIC", mission_criticality="BLOCKING",
        semantic_cost_class="LOW", source_ref="plan://deterministic/tool-only",
    )
    bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
    )
    with pytest.raises(TokenEconomyError, match="DETERMINISTIC_STEP_MUST_NOT_USE_LLM"):
        workers["design"].launcher.execute(_assignment("task:WI-DESIGN"), "deterministic query")
    assert workers["design"].launcher.calls == []
    assert truth.query("rc72_token_call", mission_id="MISSION-C10")[0]["state"] == "BLOCKED"
    assert {row["task_id"] for row in truth.query("rc7_task", mission_id="MISSION-C10")} == {"WI-DESIGN"}


def test_resume_retains_canonical_soft_budget_and_does_not_rewrite_test_scope(tmp_path):
    truth, control, workers = _fixtures(tmp_path)
    service = bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
    )
    old_budget = service._budget("MISSION-C10")
    fresh = {
        role: SimpleNamespace(launcher=_ProcessLauncher(truth, role, tmp_path / "fresh"))
        for role in _ROLE_NODE
    }
    bind_release_batch_model_economy(
        truth, workers=fresh, release_id="REL-C10", mission_id="MISSION-C10",
    )
    assert service._budget("MISSION-C10") == old_budget
    assert set(x["task_id"] for x in truth.query("rc7_task", mission_id="MISSION-C10")) == {"WI-DESIGN"}


def test_missing_role_aborts_before_any_launcher_is_instrumented(tmp_path):
    truth, _, workers = _fixtures(tmp_path)
    del workers["design_review"]
    with pytest.raises(ProductionEconomyBindingError, match="ALL_NATIVE_ROLES_REQUIRED"):
        bind_release_batch_model_economy(
            truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
        )
    assert not any(getattr(row.launcher, "_rc72_production_economy_bound", False) for row in workers.values())
    assert truth.query("rc72_token_call", mission_id="MISSION-C10") == []


def test_operator_policy_file_and_strict_validation(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({
        "bank_cost_window": {
            "timezone_name": "Asia/Shanghai",
            "normal_end_hour": 18,
            "discount_end_hour": 21,
            "normal_factor_millis": 1000,
            "discount_factor_millis": 100,
            "unlimited_after_discount": True,
            "post_discount_factor_millis": 0,
        }
    }), encoding="utf-8")
    policy = read_mission_economy_config(str(path))
    assert policy["bank_cost_window"]["timezone_name"] == "Asia/Shanghai"
    truth, _, workers = _fixtures(tmp_path)
    economy = bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
        policy=policy,
    )
    assert economy.cost_window_config.timezone_name == "Asia/Shanghai"
    path.write_text(json.dumps({"bank_cost_window": {"timezone_name": "America/Los_Angeles"}}))
    with pytest.raises(TokenEconomyError, match="TIMEZONE"):
        read_mission_economy_config(str(path))



def test_authorized_calendar_update_versions_r1_without_blocking_required_work(tmp_path):
    truth, _, workers = _fixtures(tmp_path)
    first = bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
    )
    original = first._budget("MISSION-C10")
    changed = {
        "bank_cost_window": {
            "timezone_name": "Asia/Shanghai",
            "normal_end_hour": 18,
            "discount_end_hour": 21,
            "normal_factor_millis": 1000,
            "discount_factor_millis": 100,
            "unlimited_after_discount": True,
            "post_discount_factor_millis": 0,
            "non_working_dates": ["2026-11-05"],
            "makeup_work_dates": ["2026-11-07"],
        },
    }
    fresh = {
        role: SimpleNamespace(launcher=_ProcessLauncher(truth, role, tmp_path / "fresh-update"))
        for role in _ROLE_NODE
    }
    updated = bind_release_batch_model_economy(
        truth, workers=fresh, release_id="REL-C10",
        mission_id="MISSION-C10", policy=changed,
    )
    assert all(getattr(row.launcher, "_rc72_production_economy_bound", False)
               for row in fresh.values())
    refreshed = updated._budget("MISSION-C10")
    assert refreshed["artifact_version"] == original["artifact_version"] + 1
    assert refreshed["bank_cost_window_config"]["non_working_dates"] == ["2026-11-05"]
    assert refreshed["bank_cost_window_config"]["makeup_work_dates"] == ["2026-11-07"]
    assert refreshed["max_total_tokens"] == original["max_total_tokens"]
    assert refreshed["max_model_calls"] == original["max_model_calls"]
    assert {row["task_id"] for row in truth.query("rc7_task", mission_id="MISSION-C10")} == {"WI-DESIGN"}
    assert truth.query("rc72_token_call", mission_id="MISSION-C10") == []


def test_cold_rebind_without_new_config_retains_approved_holiday_calendar(tmp_path):
    truth, _, workers = _fixtures(tmp_path)
    policy = {"bank_cost_window": {
        "non_working_dates": ["2026-11-05"],
        "makeup_work_dates": ["2026-11-07"],
    }}
    first = bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10",
        mission_id="MISSION-C10", policy=policy,
    )
    previous = first._budget("MISSION-C10")
    new_launchers = {
        role: SimpleNamespace(launcher=_ProcessLauncher(truth, role, tmp_path / "cold"))
        for role in _ROLE_NODE
    }
    recovered = bind_release_batch_model_economy(
        truth, workers=new_launchers, release_id="REL-C10",
        mission_id="MISSION-C10",
    )
    assert recovered.cost_window_config.non_working_dates == ("2026-11-05",)
    assert recovered.cost_window_config.makeup_work_dates == ("2026-11-07",)
    assert recovered._budget("MISSION-C10") == previous
    assert all(getattr(row.launcher, "_rc72_production_economy_bound", False)
               for row in new_launchers.values())



def test_legacy_budget_upgrades_bank_window_without_changing_soft_targets(tmp_path):
    truth, _, workers = _fixtures(tmp_path)
    from rc7_runtime.rc72_model_economy import TokenEconomyService

    economy = TokenEconomyService(truth, release_id="REL-C10")
    original = economy.configure_budget(
        mission_id="MISSION-C10", max_total_tokens=321, max_model_calls=9,
        max_single_call_tokens=100, max_retry_tokens=55,
        max_retry_calls=2, max_same_context_calls=3,
    )
    legacy = dict(original)
    legacy.pop("artifact_type", None)
    legacy.pop("bank_cost_window_config", None)
    legacy["artifact_version"] += 1
    truth.append_atomic("RC72_TOKEN_BUDGET_UPSERTED", legacy)
    assert "bank_cost_window_config" not in truth.query(
        "rc72_token_budget", budget_id="MISSION-C10"
    )[0]
    bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
    )
    migrated = economy._budget("MISSION-C10")
    assert migrated["max_total_tokens"] == 321
    assert migrated["max_model_calls"] == 9
    assert migrated["max_retry_tokens"] == 55
    assert migrated["max_same_context_calls"] == 3
    assert migrated["bank_cost_window_config"]["timezone_name"] == "Asia/Shanghai"
    assert migrated["artifact_version"] == legacy["artifact_version"] + 1



def test_signed_observed_n8_retry_actually_rehydrates_dsh_prompt_and_replays_r1(tmp_path):
    import hashlib
    from rc7_runtime.rc72_truth import install_rc72_truth_overlay
    from rc7_runtime.rc72_retry_context import install_rc72_retry_context_overlay
    from rc7_runtime.rc72_retry_context import _retry_delta_digest
    from rc7_runtime.rc72_context_economy import build_retry_delta
    from rc7_runtime.rc72_production_economy_ingress import canonical_role_metadata_resolver

    install_rc72_truth_overlay()
    truth, _, workers = _fixtures(tmp_path)
    assignment = _assignment(
        "task:WI-DESIGN", agent="designer",
        attempt="ATT-CHILD", worker="worker-design",
    )
    task = truth.query("rc7_task", task_id="WI-DESIGN")[0]
    old_refs = list(task["input_artifact_refs"])
    truth.append_atomic("RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED", {
        "binding_id": "BIND-CHILD-N4",
        "release_id": "REL-C10",
        "mission_id": "MISSION-C10",
        "etu_id": "ETU-DESIGN",
        "workitem_id": "WI-DESIGN",
        "case_id": "CASE-DESIGN",
        "attempt_id": "ATT-CHILD",
        "state": "RESERVED",
        "worker_id": "worker-design",
        "session_id": None,
        "task_lease_ref": None,
        "capability_lease_refs": [],
        "resource_lease_refs": [],
        "parent_attempt_id": "ATT-PARENT",
        "mission_node_id": "MN-N4-REAL",
        "mission_node_type": "N4_TEST_DESIGN",
        "mission_node_lineage_status": "RESOLVED",
        "mission_node_lineage_reason": None,
        "created_at": 1,
        "updated_at": 1,
        "artifact_version": 1,
    })
    install_rc72_retry_context_overlay()
    truth.append_atomic("RC72_RETRY_CONTEXT_COMPILED", {
        "retry_context_id": "RETRY-N8-CHILD",
        "release_id": "REL-C10",
        "mission_id": "MISSION-C10",
        "workitem_id": "WI-DESIGN",
        "attempt_id": "ATT-CHILD",
        "parent_attempt_id": "ATT-PARENT",
        "assignment_id": assignment.assignment_id,
        "observation_status": "OBSERVED",
        "context_mode": "RETRY_DELTA",
        "canonical_gap_refs": [],
        "explicit_gap_refs": [],
        "delta_evidence_refs": ["EVD-FIXED"],
        "changed_dependency_refs": ["DEP-NEW"],
        "canonical_lineage_refs_not_in_delta": old_refs,
        "previous_attempt_summary_ref": "PREVIOUS-ATTEMPT-SUMMARY",
        "full_context_reason": None,
        "retry_delta_sha256": _retry_delta_digest(build_retry_delta(
            previous_attempt_summary_ref="PREVIOUS-ATTEMPT-SUMMARY",
            explicit_gap_refs=(),
            delta_evidence_refs=("EVD-FIXED",),
            changed_dependency_refs=("DEP-NEW",),
            full_context_reason=None,
        )),
        "recorded_at": 1,
        "artifact_version": 1,
    })
    metadata = canonical_role_metadata_resolver(
        truth, role="design", mission_id="MISSION-C10"
    )(assignment)
    assert metadata["retry_delta_native_authorized"] is True
    assert metadata["context_mode"] == "RETRY_DELTA"

    economy = bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
    )
    business = {
        "mission_id": "MISSION-C10",
        "workitem_id": "WI-DESIGN",
        "input_refs": old_refs,
        "required_obligations": ["negative", "boundary", "state", "regression"],
        "required_oracles": ["DB", "API", "CAT"],
    }
    shape = {"status": "CANDIDATE", "cases": ["non-happy-path"], "gaps": []}
    original_prompt = (
        "Design the complete accepted requirement. Context="
        + json.dumps(business, ensure_ascii=False, sort_keys=True)
        + " RequiredShape=" + json.dumps(shape, ensure_ascii=False, sort_keys=True)
    )
    workers["design"].launcher.execute(assignment, original_prompt)
    final_prompt = workers["design"].launcher.calls[0][-1]
    assert len(final_prompt.encode()) < len(("NATIVE_BOUND\n" + original_prompt).encode())
    updated_context, updated_shape = final_prompt.split(" Context=", 1)[1].split(" RequiredShape=", 1)
    hydrated = json.loads(updated_context)
    assert hydrated["input_refs"] == ["PREVIOUS-ATTEMPT-SUMMARY", "EVD-FIXED", "DEP-NEW"]
    assert hydrated["required_obligations"] == business["required_obligations"]
    assert hydrated["required_oracles"] == business["required_oracles"]
    assert json.loads(updated_shape) == shape

    call = truth.query("rc72_token_call", mission_id="MISSION-C10")[0]
    assert call["context_projection_status"] == "NATIVE_RETRY_DELTA_VERIFIED"
    assert call["context_projection_applied_to_prompt"] is True
    assert call["context_mode"] == "RETRY_DELTA"
    assert call["parent_attempt_id"] == "ATT-PARENT"
    assert call["native_retry_delta_saved_bytes"] > 0
    assert call["context_sha256"] == hashlib.sha256(final_prompt.encode()).hexdigest()
    summary = economy.summary("MISSION-C10")
    assert summary["native_minimal_prompt_proven_calls"] == 1
    assert summary["observed_native_retry_delta_prompt_saved_bytes"] > 0
    assert summary["verified_prompt_token_savings"] is None

    replay = TruthRuntime(tmp_path / "r1" / "event-stream.jsonl")
    observed = replay.query("rc72_token_call", call_id=call["call_id"])[0]
    assert observed["native_retry_delta_saved_bytes"] == call["native_retry_delta_saved_bytes"]
    assert replay.query("rc7_task", task_id="WI-DESIGN")[0]["input_artifact_refs"] == old_refs


def test_unsigned_retry_observation_cannot_shrink_native_prompt(tmp_path):
    truth, _, workers = _fixtures(tmp_path)
    bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
    )
    assignment = _assignment("task:WI-DESIGN")
    old_refs = truth.query("rc7_task", task_id="WI-DESIGN")[0]["input_artifact_refs"]
    native = "Exact scope Context=" + json.dumps({
        "mission_id": "MISSION-C10", "workitem_id": "WI-DESIGN",
        "input_refs": old_refs,
        "required_oracles": ["DB", "API", "CAT"],
    })
    workers["design"].launcher.execute(assignment, native)
    actual = workers["design"].launcher.calls[0][-1]
    assert json.loads(actual.split(" Context=", 1)[1])["input_refs"] == old_refs
    call = truth.query("rc72_token_call", mission_id="MISSION-C10")[0]
    assert call["context_projection_status"] == "REFERENCE_ONLY"
    assert call["context_projection_applied_to_prompt"] is False
    assert call["native_retry_delta_saved_bytes"] == 0
