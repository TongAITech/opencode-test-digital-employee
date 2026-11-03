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
        assert len(sessions) == len(plan["items"])
        assert len(admissions) == len(plan["items"])
        assert len(preps) == len(plan["items"])
        assert len({r["session_id"] for r in admissions}) == len(admissions)
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
