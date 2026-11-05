"""C07/C04 product-facing governed N9 -> DSH WorkerInvocation regression.

Local deterministic command_runner supplies the *engineering* DSH process
protocol; it is not proof of a live bank DSH provider, a product defect,
reproduction, RCA approval or bank FIELD_PASS.
"""
import json
import subprocess
import sys

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_ledger_lock import ledger_lock
from rc7_runtime.rc72_n9_professional_dsh import NativeN9ProfessionalDshAnalysisService
from rc72_n2_test_support import BATCH
from test_rc72_n9_captain_qualification import _setup_fenced_business_failure


def _specialist(tmp_path, truth, pipeline, calls, *, tools=("read_only_diagnostic",),
                timeout=30, returncode=0, approve=True):
    patch = tmp_path / "captain-n9-patch.json"
    patch.write_text("{}", encoding="utf-8")
    candidate = dict(
        finding="INCONCLUSIVE",
        hypotheses=["Original frozen Oracle discrepancy remains unqualified"],
        reproduction_steps=["Request a separate approved reproduction ETU"],
        tool_evidence_refs=["dsh-event://tool-call/1"])
    output = "\n".join((
        json.dumps({"type": "session", "session_id": "session-captain-n9-independent"}),
        json.dumps({"type": "tool_call", "tool_name": tools[0]}),
        json.dumps({"type": "text", "text": json.dumps(candidate)})))
    def runner(args, **kwargs):
        with ledger_lock(truth, busy="N9_CAPTAIN_DSH_PROCESS_IO_UNDER_GLOBAL_R1_LOCK"):
            assert truth.query("rc72_release_batch", release_batch_id=BATCH)
        env = kwargs["env"]
        assert env["PFC_RC7_DSH_SESSION_MODE"] == "LEASE_BOUND_WORKER"
        assert env["PFC_RC7_MCP_WORKER_ID"].startswith("WRK-")
        assert env["PFC_RC7_MCP_SCOPE_REF"].startswith("task:N9QUAL-")
        assert env["PFC_RC7_MCP_TASK_ID"].startswith("N9QUAL-")
        assert env["PFC_RC7_MCP_WORKER_ID"] != pipeline.captain_session_id
        calls.append(dict(args=args, env=env))
        return subprocess.CompletedProcess(
            args=args, returncode=returncode, stdout=output, stderr="")
    launcher = DshHeadlessWorkerLauncher(
        dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
        truth=truth, authority=RC72AuthorityRuntime(b"governed-n9-independent-host-key-01"),
        coordinator_instance_id="C07-QUALIFIED-INDEPENDENT-N9-HOST",
        release_id=pipeline.release_id, timeout_seconds=timeout,
        state_root=str(tmp_path / "governed-n9-dsh-private"),
        command_runner=runner)
    return NativeN9ProfessionalDshAnalysisService(
        pipeline, launcher=launcher, allowed_tools=tools,
        captain_dsh_host_enabled=approve)


def _run(analyst, original):
    return analyst.analyze(
        preparation_id=original["preparation_id"],
        diagnosis_id=original["diagnosis_id"])


def test_captain_n9_uses_same_fresh_worker_real_dsh_handoff_signed_r1_and_no_n7_replay(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        assert original["failure_class"] == "VALID_TEST_FAILURE"
        calls = []
        analyst = _specialist(tmp_path, truth, pipeline, calls)
        result = _run(analyst, original)
        assert result["status"] == "HOLD"
        assert result["reason"] == "N9_CAUSAL_REVIEW_AND_REAL_REPRODUCTION_REQUIRED"
        assert result["cause_candidate_only"] is True
        assert result["defect_confirmed"] is False
        assert result["reproduction_completed"] is False
        assert result["field_verified"] is False and result["bank_final"] is False
        assert len(server.calls) == len(calls) == 1
        wid = original["qualification_workitem_id"]
        bindings = truth.query("rc72_n9_captain_dsh_invocation", workitem_id=wid)
        assert len(bindings) == 1
        binding = bindings[0]
        assert binding["worker_id"] == original["qualification_worker_id"]
        assert binding["lifecycle_session_id"] == original["qualification_session_id"]
        assert binding["captain_generation"] == owner["generation"]
        assert binding["allowed_tools"] == ["read_only_diagnostic"]
        assert binding["runtime_lease_signature"]
        assert truth.query("rc7_task", task_id=wid)[0]["state"] == "RUNNING"
        admission = truth.query("rc72_captain_etu_admission", workitem_id=wid)[0]
        assert admission["worker_id"] == binding["worker_id"]
        sessions = truth.query("rc72_worker_session",
                               session_id=original["qualification_session_id"])
        assert len(sessions) == 1
        session = sessions[0]
        assert session["runtime_worker_id"] == binding["worker_id"]
        assert session["runtime_assignment_id"] == binding["assignment_id"]
        assert session["dsh_session_id"] == "session-captain-n9-independent"
        handoff = truth.query("agent_runtime_event", scope="task:" + wid)
        assert len([x for x in handoff if x["event_name"] == "HANDOFF_RETURNED"]) == 1
        assert handoff[-1]["worker_instance_id"] == binding["worker_id"]
        assert handoff[-1]["lease_id"] == binding["runtime_lease_id"]
        receipt = truth.query("rc72_n9_professional_dsh_analysis")
        assert len(receipt) == 1
        assert receipt[0]["worker_id"] == original["qualification_worker_id"]
        assert receipt[0]["analysis_id"] == result["analysis_id"]
        assert receipt[0]["candidate"]["finding"] == "INCONCLUSIVE"
        assert not truth.query("rc7_defect")
        assert not truth.query("rc72_node_gate", node_type="N9_DEFECT")
        before = truth.store.path.read_bytes()
        second = _run(analyst, original)
        assert second == result
        assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_captain_n9_unknown_dsh_side_effect_never_replays_process(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        calls = []
        analyst = _specialist(tmp_path, truth, pipeline, calls, returncode=7)
        first = _run(analyst, original)
        assert first["reason"] == "N9_DSH_UNKNOWN_PROCESS_NO_REPLAY"
        assert len(calls) == len(server.calls) == 1
        assert len(truth.query("rc72_n9_captain_dsh_invocation")) == 1
        before = truth.store.path.read_bytes()
        recovered = _run(analyst, original)
        assert recovered["reason"] == "N9_DSH_INTERRUPTED_NO_REPLAY"
        assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1
        assert not truth.query("rc72_n9_professional_dsh_analysis")
        assert not truth.query("rc7_defect")
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("tools", [
    ("api_http",), ("read_only_diagnostic", "api_http"),
    ("read_only_diagnostic", "journey_bsk"), ("shell_exec",),
])
def test_captain_n9_business_or_unknown_tool_rejected_without_process_or_assignment(
        tmp_path, monkeypatch, tools):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        calls = []
        analyst = _specialist(tmp_path, truth, pipeline, calls, tools=tools)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="N9_CAPTAIN_DSH_READONLY_TOOLS_REQUIRED"):
            _run(analyst, original)
        assert truth.store.path.read_bytes() == before
        assert not calls
        assert len(server.calls) == 1
        assert not truth.query("rc72_n9_captain_dsh_invocation")
    finally:
        server.shutdown()
        server.server_close()


def test_captain_n9_expiring_owner_must_renew_before_real_dsh(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        calls = []
        analyst = _specialist(tmp_path, truth, pipeline, calls, timeout=3600)
        before = truth.store.path.read_bytes()
        result = _run(analyst, original)
        assert result["reason"] == "N9_CAPTAIN_DSH_CAPTAIN_TTL_INSUFFICIENT"
        assert truth.store.path.read_bytes() == before
        assert not calls
        assert not truth.query("rc72_n9_captain_dsh_invocation")
        assert len(server.calls) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_captain_n9_wrong_owner_blocks_dsh_before_any_process_io(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        calls = []
        analyst = _specialist(tmp_path, truth, pipeline, calls)
        pipeline.captain_lease_id = "wrong-captain-lease"
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="CAPTAIN_DISPATCH_FENCED"):
            _run(analyst, original)
        assert truth.store.path.read_bytes() == before
        assert not calls
        assert not truth.query("rc72_n9_captain_dsh_invocation")
        assert len(server.calls) == 1
    finally:
        server.shutdown()
        server.server_close()



@pytest.mark.parametrize("returncode", [0, 9])
def test_cold_r1_reentry_preserves_signed_n9_handoff_and_never_runs_second_dsh(
        tmp_path, monkeypatch, returncode):
    """Recover a distinct TruthRuntime and Host; never reuse a chat history."""
    from rc6_runtime.truth import TruthRuntime
    from rc7_runtime.control_plane import TaskScheduler
    from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
    from rc7_runtime.rc72_captain_scheduling import CaptainFencedWorkItemScheduler
    from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
    from rc7_runtime.rc72_n7_execution_preparation import ExecutionPreparationService
    from rc7_runtime.rc72_n7_pipeline import N7PipelineService
    from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
    from rc72_formal_runner_support import LocalHTTPEnvironment

    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        calls = []
        analyst = _specialist(
            tmp_path, truth, pipeline, calls, returncode=returncode)
        first = _run(analyst, original)
        assert first["status"] == "HOLD"
        assert len(calls) == len(server.calls) == 1
        assert (first.get("cause_candidate_only") is True) == (returncode == 0)
        before = truth.store.path.read_bytes()

        cold_truth = TruthRuntime(truth.store.path)
        cold_prep = ExecutionPreparationService(
            cold_truth, release_id=prep.release_id,
            source_commit=prep.source_commit,
            authority=RC72AuthorityRuntime(prep.authority._key),
            tool_registry=prep.tool_registry)
        fencer = CaptainDispatchFencer(cold_truth, release_id=prep.release_id)
        scheduler = CaptainFencedWorkItemScheduler(
            truth=cold_truth, release_id=prep.release_id, fencer=fencer,
            lifecycle=WorkerLifecycleService(
                cold_truth, release_id=prep.release_id),
            scheduler=TaskScheduler(cold_truth, prep.release_id),
            role_profiles=pipeline.captain_scheduler.role_profiles)
        root = pipeline.runner.root
        url = "http://127.0.0.1:%d" % server.server_address[1]
        runner = FormalN7RunnerAdapter(
            cold_prep, evidence_root=root,
            environment_adapter=LocalHTTPEnvironment(url, root),
            execution_env={"RC72_OUTPUT_ROOT": str(root)},
            timeout_seconds=30)
        cold_pipeline = N7PipelineService(
            cold_prep, runner=runner,
            capture_root=pipeline.review.capture_root,
            captain_scheduler=scheduler,
            captain_session_id=owner["captain_session_id"],
            captain_lease_id=owner["lease_id"],
            team_id=owner["team_id"])
        # The second launcher is a fresh host instance with no historical
        # in-memory worker authority; signed R1 and raw DSH bytes must suffice
        # for read-only recovery, but must NEVER imply DSH reexecution.
        cold_calls = []
        cold_analyst = _specialist(
            tmp_path, cold_truth, cold_pipeline, cold_calls)
        recovered = _run(cold_analyst, original)
        if returncode == 0:
            assert recovered == first
            assert recovered["analysis_id"]
        else:
            assert recovered["reason"] == "N9_DSH_INTERRUPTED_NO_REPLAY"
        assert cold_truth.store.path.read_bytes() == before
        assert not cold_calls
        assert len(calls) == len(server.calls) == 1
        assert len(cold_truth.query("rc72_n9_captain_dsh_invocation")) == 1
        assert not cold_truth.query("rc7_defect")
    finally:
        server.shutdown()
        server.server_close()
