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
    ))
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



def test_existing_bank_schedule_drift_blocks_rebinding_before_any_model_call(tmp_path):
    truth, _, workers = _fixtures(tmp_path)
    first = bind_release_batch_model_economy(
        truth, workers=workers, release_id="REL-C10", mission_id="MISSION-C10",
    )
    original = first._budget("MISSION-C10")
    changed = {
        "bank_cost_window": {
            "timezone_name": "Asia/Shanghai",
            "normal_end_hour": 17,
            "discount_end_hour": 20,
            "normal_factor_millis": 1000,
            "discount_factor_millis": 250,
            "unlimited_after_discount": True,
            "post_discount_factor_millis": 0,
        }
    }
    fresh = {
        role: SimpleNamespace(launcher=_ProcessLauncher(truth, role, tmp_path / "fresh-drift"))
        for role in _ROLE_NODE
    }
    with pytest.raises(ProductionEconomyBindingError, match="BANK_SCHEDULE_DRIFT"):
        bind_release_batch_model_economy(
            truth, workers=fresh, release_id="REL-C10",
            mission_id="MISSION-C10", policy=changed,
        )
    assert all(not getattr(row.launcher, "_rc72_production_economy_bound", False)
               for row in fresh.values())
    assert first._budget("MISSION-C10") == original
    assert truth.query("rc72_token_call", mission_id="MISSION-C10") == []


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
