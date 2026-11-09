"""Formal N7Pipeline consumes real Captain-fenced admission and full N7 Oracle.

This is local process/HTTP engineering evidence, not DSH AgentTeams or bank.
"""
import pytest

from rc7_runtime.control_plane import TaskScheduler
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
from rc7_runtime.rc72_captain_scheduling import CaptainFencedWorkItemScheduler
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService

from rc72_n2_test_support import BATCH
from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment


def _cold_handoff_during_n7_io(path, mission_id, team_id, lease_id,
                                captain_session_id, result_queue):
    from rc6_runtime.truth import TruthRuntime
    from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
    from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
    from rc7_runtime.models import ContractError

    truth = TruthRuntime(path)
    fencer = CaptainDispatchFencer(truth, release_id="RC7.2")
    lifecycle = WorkerLifecycleService(truth, release_id="RC7.2")
    try:
        fencer.prepare_handoff(
            mission_id=mission_id, team_id=team_id,
            lease_id=lease_id, captain_session_id=captain_session_id,
            lifecycle=lifecycle, current_node_refs=["N7_EXECUTION"],
            latest_delivery_refs=[], latest_gate_refs=[],
            next_workitem_ids=[])
    except ContractError as exc:
        result_queue.put(str(exc))
    else:
        result_queue.put("UNSAFE_HANDOFF_ALLOWED")


def _governed_pipeline(truth, plan, prep, url, tmp_path):
    team_id = "TEAM-C07-ISOLATED-N7"
    captain_session_id = "CAPTAIN-C07-N7"
    fencer = CaptainDispatchFencer(truth, release_id=prep.release_id)
    owner = fencer.acquire_initial(
        mission_id=plan["mission_id"], team_id=team_id,
        captain_session_id=captain_session_id)
    profiles = {}
    for item in plan["items"]:
        etu = truth.query("rc72_etu", etu_id=item["etu_id"])[0]
        task = truth.query("rc7_task", task_id=item["workitem_id"])[0]
        role = etu["test_level"] + "_EXECUTE"
        profiles.setdefault(role, set()).update(
            list(task["required_capabilities"]) + list(etu["required_capabilities"]))
    role_profiles = {role: sorted(values) for role, values in profiles.items()}
    lifecycle = WorkerLifecycleService(truth, release_id=prep.release_id)
    captain_scheduler = CaptainFencedWorkItemScheduler(
        truth=truth, release_id=prep.release_id,
        fencer=fencer, lifecycle=lifecycle,
        scheduler=TaskScheduler(truth, prep.release_id),
        role_profiles=role_profiles)
    output = tmp_path / "actual-output"
    runner = FormalN7RunnerAdapter(
        prep, evidence_root=output,
        environment_adapter=LocalHTTPEnvironment(url, output),
        execution_env={"RC72_OUTPUT_ROOT": str(output)}, timeout_seconds=30)
    pipeline = N7PipelineService(
        prep, runner=runner, capture_root=tmp_path / "captured",
        captain_scheduler=captain_scheduler,
        captain_session_id=captain_session_id,
        captain_lease_id=owner["lease_id"], team_id=team_id)
    return pipeline, fencer, lifecycle, owner


def test_real_formal_n7_pipeline_consumes_captain_fenced_fresh_worker_then_oracle_and_evidence(
        tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        pipeline, _, _, _ = _governed_pipeline(truth, plan, prep, url, tmp_path)
        result = pipeline.complete(release_batch_id=BATCH)
        assert result["state"] == "N7_PASS"
        assert len(server.calls) == len(plan["items"])
        sessions = truth.query("rc72_worker_session", mission_id=plan["mission_id"])
        admissions = truth.query("rc72_captain_etu_admission", mission_id=plan["mission_id"])
        preps = truth.query("rc72_n7_execution_preparation", mission_id=plan["mission_id"])
        execution_sessions = [r for r in sessions if r.get("purpose") == "EXECUTION"]
        review_sessions = [r for r in sessions if r.get("purpose") == "REVIEW"]
        # Independent Evidence Review must have its own Worker/Session, so
        # the total session denominator correctly exceeds the number of ETUs.
        assert len(execution_sessions) == len(plan["items"])
        assert len(review_sessions) == 1
        assert len(sessions) == len(execution_sessions) + len(review_sessions)
        assert len(admissions) == len(plan["items"])
        assert len(preps) == len(plan["items"])
        assert len({r["session_id"] for r in admissions}) == len(admissions)
        assert {r["session_id"] for r in execution_sessions} == {
            a["session_id"] for a in admissions}
        assert review_sessions[0]["session_id"] not in {
            a["session_id"] for a in admissions}
        assert review_sessions[0]["worker_id"] not in {
            a["worker_id"] for a in admissions}
        for prep_row in preps:
            admission = next(x for x in admissions if x["admission_id"] == prep_row["captain_admission_id"])
            assert prep_row["worker_id"] == admission["worker_id"]
            assert prep_row["session_id"] == admission["session_id"]
            assert admission["state"] == "LEASED_AWAITING_SIGNED_AUTHORITY_AND_DSH"
        assert all(row["state"] == "RELEASED" for row in truth.query("rc72_data_lease"))
        before = truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH) == result
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == len(plan["items"])
    finally:
        server.shutdown()
        server.server_close()


def test_formal_n7_pipeline_cannot_bypass_active_captain_with_unfenced_legacy_entry(
        tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        output = tmp_path / "unfenced-output"
        runner = FormalN7RunnerAdapter(
            prep, evidence_root=output,
            environment_adapter=LocalHTTPEnvironment(url, output),
            execution_env={"RC72_OUTPUT_ROOT": str(output)}, timeout_seconds=30)
        pipeline = N7PipelineService(prep, runner=runner, capture_root=tmp_path / "captures")
        CaptainDispatchFencer(truth, release_id=prep.release_id).acquire_initial(
            mission_id=plan["mission_id"],
            team_id="TEAM-EXCLUSIVE-AGENTTEAMS",
            captain_session_id="CAPTAIN-A")
        with pytest.raises(ContractError, match="N7_CAPTAIN_FENCED_ADMISSION_REQUIRED"):
            pipeline.complete(release_batch_id=BATCH)
        assert server.calls == []
        assert truth.query("rc72_n7_execution_preparation", mission_id=plan["mission_id"]) == []
    finally:
        server.shutdown()
        server.server_close()


def test_quiesced_captain_between_governed_n7_preparation_and_tool_execution_blocks_business_io(
        tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        pipeline, fencer, lifecycle, owner = _governed_pipeline(
            truth, plan, prep, url, tmp_path)
        original = pipeline._prepare_governed_item
        def checkpoint_after_prepared(plan_arg, item):
            prepared = original(plan_arg, item)
            fencer.prepare_handoff(
                mission_id=plan_arg["mission_id"],
                team_id="TEAM-C07-ISOLATED-N7",
                lease_id=owner["lease_id"],
                captain_session_id=owner["captain_session_id"],
                lifecycle=lifecycle, current_node_refs=["N7_EXECUTION"],
                latest_delivery_refs=[], latest_gate_refs=[],
                next_workitem_ids=[item["workitem_id"]])
            return prepared
        monkeypatch.setattr(pipeline, "_prepare_governed_item", checkpoint_after_prepared)
        with pytest.raises(ContractError, match="CAPTAIN_DISPATCH_NOT_ACTIVE"):
            pipeline.complete(release_batch_id=BATCH)
        assert server.calls == []
        assert truth.query("rc72_n7_tool_dispatch") == []
        assert not any(row.get("state") == "PASS" for row in
                       truth.query("rc72_mission_node", mission_id=plan["mission_id"],
                                   node_type="N7_EXECUTION"))
    finally:
        server.shutdown()
        server.server_close()



def test_legacy_pipeline_cannot_reenter_an_already_prepared_captain_workitem(tmp_path, monkeypatch):
    """A current old Captain does not authorize unrelated caller entrypoints."""
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        governed, _, _, _ = _governed_pipeline(truth, plan, prep, url, tmp_path)
        item = plan["items"][0]
        prepared = governed._prepare_governed_item(plan, item)
        assert prepared["captain_admission_id"]
        runner = FormalN7RunnerAdapter(
            prep, evidence_root=tmp_path / "legacy-output",
            environment_adapter=LocalHTTPEnvironment(url, tmp_path / "legacy-output"),
            execution_env={"RC72_OUTPUT_ROOT": str(tmp_path / "legacy-output")},
            timeout_seconds=30)
        legacy = N7PipelineService(
            prep, runner=runner, capture_root=tmp_path / "legacy-captured")
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="GOVERNED_ENTRY_REQUIRED"):
            legacy._prepare_governed_item(plan, item)
        assert truth.store.path.read_bytes() == before
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


def test_governed_pipeline_reentry_fences_foreign_captain_without_replaying_business(
        tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        governed, _, _, _ = _governed_pipeline(truth, plan, prep, url, tmp_path)
        item = plan["items"][0]
        prepared = governed._prepare_governed_item(plan, item)
        before = truth.store.path.read_bytes()
        foreign = N7PipelineService(
            prep, runner=governed.runner,
            capture_root=tmp_path / "foreign-captured",
            captain_scheduler=governed.captain_scheduler,
            captain_session_id="CAPTAIN-C07-UNAUTHORIZED",
            captain_lease_id=governed.captain_lease_id,
            team_id=governed.team_id)
        with pytest.raises(ContractError, match="EXISTING_CAPTAIN_SCOPE_MISMATCH"):
            foreign._prepare_governed_item(plan, item)
        assert truth.store.path.read_bytes() == before
        assert governed._prepare_governed_item(plan, item) == prepared
        assert truth.store.path.read_bytes() == before
        assert len(truth.query("rc72_worker_session", mission_id=plan["mission_id"])) == 1
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()



def test_captain_cannot_handoff_during_durable_in_flight_n7_business_invocation(
        tmp_path, monkeypatch):
    """The shared R1 ledger refuses handoff after intent, before tool response."""
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        pipeline, fencer, lifecycle, owner = _governed_pipeline(
            truth, plan, prep, url, tmp_path)
        original_run = pipeline.runner.run_with_dispatch
        blocked = []
        def observe_handoff_during_inflight(*, contract, context, dispatcher):
            active = truth.query(
                "rc72_n7_tool_dispatch", attempt_id=context["attempt_id"])
            assert len(active) == 1 and active[0]["state"] == "IN_FLIGHT"
            with pytest.raises(ContractError, match="CAPTAIN_HANDOFF_ACTIVE_EXECUTION_RECONCILIATION_REQUIRED"):
                fencer.prepare_handoff(
                    mission_id=plan["mission_id"], team_id=pipeline.team_id,
                    lease_id=owner["lease_id"],
                    captain_session_id=owner["captain_session_id"],
                    lifecycle=lifecycle, current_node_refs=["N7_EXECUTION"],
                    latest_delivery_refs=[], latest_gate_refs=[],
                    next_workitem_ids=[])
            blocked.append(True)
            return original_run(contract=contract, context=context, dispatcher=dispatcher)
        monkeypatch.setattr(pipeline.runner, "run_with_dispatch",
                            observe_handoff_during_inflight)
        result = pipeline.complete(release_batch_id=BATCH)
        assert result["state"] == "N7_PASS"
        assert blocked and len(server.calls) == len(plan["items"])
        assert fencer._latest(plan["mission_id"])["state"] == "ACTIVE"
    finally:
        server.shutdown()
        server.server_close()


def test_captain_handoff_after_preflight_before_dispatch_intent_blocks_external_io(
        tmp_path, monkeypatch):
    """The final shared-ledger check closes check -> intent TOCTOU."""
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        pipeline, fencer, lifecycle, owner = _governed_pipeline(
            truth, plan, prep, url, tmp_path)
        old_preflight = pipeline.runner.preflight
        checkpoints = []
        def handoff_during_preflight(*, contract, context):
            old_preflight(contract=contract, context=context)
            receipt = fencer.prepare_handoff(
                mission_id=plan["mission_id"], team_id=pipeline.team_id,
                lease_id=owner["lease_id"],
                captain_session_id=owner["captain_session_id"],
                lifecycle=lifecycle, current_node_refs=["N7_EXECUTION"],
                latest_delivery_refs=[], latest_gate_refs=[],
                next_workitem_ids=[])
            checkpoints.append(receipt.checkpoint_id)
        monkeypatch.setattr(pipeline.runner, "preflight",
                            handoff_during_preflight)
        with pytest.raises(ContractError, match="CAPTAIN_DISPATCH_NOT_ACTIVE"):
            pipeline.complete(release_batch_id=BATCH)
        assert len(checkpoints) == 1
        assert server.calls == []
        assert truth.query("rc72_n7_tool_dispatch") == []
        assert fencer._latest(plan["mission_id"])["state"] == "QUIESCED"
    finally:
        server.shutdown()
        server.server_close()



def test_captain_handoff_rejected_during_external_n7_cleanup_and_verification(
        tmp_path, monkeypatch):
    """Cleanup intent is durable and fenced, not only business execution intent."""
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        pipeline, fencer, lifecycle, owner = _governed_pipeline(
            truth, plan, prep, url, tmp_path)
        checked = []
        for tool, actual_adapter in list(pipeline.cleanup.adapters.items()):
            def guarded_cleanup(*, contract, context, original=actual_adapter):
                matches = truth.query(
                    "rc72_n7_cleanup_call",
                    preparation_id=context["preparation_id"]) if "preparation_id" in context else [
                        row for row in truth.query("rc72_n7_cleanup_call")
                        if row["attempt_id"] == context["attempt_id"]]
                assert len([r for r in matches if r["phase"] == context["phase"]
                            and r["state"] == "IN_FLIGHT"]) == 1
                with pytest.raises(
                        ContractError,
                        match="CAPTAIN_HANDOFF_ACTIVE_EXECUTION_RECONCILIATION_REQUIRED"):
                    fencer.prepare_handoff(
                        mission_id=plan["mission_id"], team_id=pipeline.team_id,
                        lease_id=owner["lease_id"],
                        captain_session_id=owner["captain_session_id"],
                        lifecycle=lifecycle, current_node_refs=["N7_EXECUTION"],
                        latest_delivery_refs=[], latest_gate_refs=[],
                        next_workitem_ids=[])
                checked.append(context["phase"])
                return original(contract=contract, context=context)
            pipeline.cleanup.adapters[tool] = guarded_cleanup
        result = pipeline.complete(release_batch_id=BATCH)
        assert result["state"] == "N7_PASS"
        assert "CLEANUP" in checked and "VERIFY" in checked
        assert fencer._latest(plan["mission_id"])["state"] == "ACTIVE"
        assert len(server.calls) == len(plan["items"])
    finally:
        server.shutdown()
        server.server_close()



def test_independent_python_process_cannot_take_over_captain_during_live_n7_io(
        tmp_path, monkeypatch):
    """The R1 protection holds across interpreters, not Python thread globals."""
    import multiprocessing

    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        pipeline, _, _, owner = _governed_pipeline(
            truth, plan, prep, url, tmp_path)
        original_run = pipeline.runner.run_with_dispatch
        observations = []
        mp_ctx = multiprocessing.get_context("spawn")
        def competing_handoff(*, contract, context, dispatcher):
            out = mp_ctx.Queue()
            child = mp_ctx.Process(
                target=_cold_handoff_during_n7_io,
                args=(str(truth.store.path), plan["mission_id"],
                      pipeline.team_id, owner["lease_id"],
                      owner["captain_session_id"], out))
            child.start()
            child.join(timeout=30)
            assert child.exitcode == 0
            result = out.get(timeout=5)
            assert "CAPTAIN_HANDOFF_ACTIVE_EXECUTION_RECONCILIATION_REQUIRED" in result
            observations.append(result)
            return original_run(
                contract=contract, context=context, dispatcher=dispatcher)
        monkeypatch.setattr(pipeline.runner, "run_with_dispatch", competing_handoff)
        assert pipeline.complete(release_batch_id=BATCH)["state"] == "N7_PASS"
        assert len(observations) == len(plan["items"])
        assert len(server.calls) == len(plan["items"])
    finally:
        server.shutdown()
        server.server_close()


def test_r4_one_execution_slot_handles_multiple_cases_without_whole_plan_deadlock(
        tmp_path, monkeypatch):
    """Actual HTTP/cleanup and whole-plan independent Oracle, no fake PASS."""
    from rc7_runtime.rc72_agentteams_capacity import TeamCapacityPolicy
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        assert len(plan["items"]) > 1
        pipeline, _, _, _ = _governed_pipeline(truth, plan, prep, url, tmp_path)
        pipeline.captain_scheduler.capacity_policy = TeamCapacityPolicy(32, 1)
        result = pipeline.complete(release_batch_id=BATCH)
        assert result["state"] == "N7_PASS"
        assert len(server.calls) == len(plan["items"])
        assert len(truth.query("rc72_captain_etu_admission",
                               mission_id=plan["mission_id"])) == len(plan["items"])
        sessions = truth.query("rc72_worker_session", mission_id=plan["mission_id"])
        assert len([row for row in sessions if row["purpose"] == "EXECUTION"]) == len(plan["items"])
        assert all(row["state"] == "CLOSED" for row in sessions)
        assert all(row["state"] == "RELEASED" for row in truth.query("rc72_data_lease"))
        before = truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH) == result
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == len(plan["items"])
    finally:
        server.shutdown()
        server.server_close()


def test_r4_rebuilt_n7_pipeline_reuses_same_trusted_cleanup_verifier_without_writes(
        tmp_path, monkeypatch):
    from copy import copy
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime

    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        pipeline, _, _, _ = _governed_pipeline(truth, plan, prep, url, tmp_path)
        originally_bound = pipeline.captain_scheduler._n7_cleanup_review
        before = truth.store.path.read_bytes()
        replacement = N7PipelineService(
            prep, runner=pipeline.runner, capture_root=tmp_path / "rebuilt-capture",
            captain_scheduler=pipeline.captain_scheduler,
            captain_session_id=pipeline.captain_session_id,
            captain_lease_id=pipeline.captain_lease_id, team_id=pipeline.team_id)
        assert replacement.review is not originally_bound
        assert pipeline.captain_scheduler._n7_cleanup_review is originally_bound
        assert truth.store.path.read_bytes() == before
        assert server.calls == []

        # A different caller's signing authority cannot switch the canonical
        # cleanup verifier for already running or historical worker sessions.
        untrusted_review = copy(replacement.review)
        untrusted_preparation = copy(prep)
        untrusted_preparation.authority = RC72AuthorityRuntime(
            b"untrusted-different-n7-cleanup-review-authority")
        untrusted_review.preparation = untrusted_preparation
        with pytest.raises(ContractError, match="N7_REVIEW_REBIND_FORBIDDEN"):
            pipeline.captain_scheduler.bind_n7_cleanup_review(untrusted_review)
        assert pipeline.captain_scheduler._n7_cleanup_review is originally_bound

        different_source = copy(replacement.review)
        different_preparation = copy(prep)
        different_preparation.source_commit = "f" * 40
        different_source.preparation = different_preparation
        with pytest.raises(ContractError, match="N7_REVIEW_REBIND_FORBIDDEN"):
            pipeline.captain_scheduler.bind_n7_cleanup_review(different_source)
        assert pipeline.captain_scheduler._n7_cleanup_review is originally_bound
        assert truth.store.path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()


