"""Captain N9 signed WorkerInvocation: actual DSH process, R1 and no replay.

The command runner returns a deterministic DSH JSON stream from an isolated
local fixture; this proves the production process boundary and evidence logic,
NOT a bank DSH live identity, RCA, reproduction, or defect confirmation.
"""
import json
import subprocess
import sys

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
from rc7_runtime.rc72_n9_professional_dsh import NativeN9ProfessionalDshAnalysisService
from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from rc7_runtime.rc72_ledger_lock import ledger_lock
from rc72_n2_test_support import BATCH
from test_rc72_n9_captain_qualification import _setup_fenced_business_failure


def _route(tmp_path, monkeypatch, *, exit_code=0, tool="read_only_diagnostic",
           approved_tools=("read_only_diagnostic",), captain_dsh=True,
           command_hook=None):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    calls = []
    candidate = dict(
        finding="INCONCLUSIVE",
        hypotheses=["Only independently reproduced evidence can establish product causality"],
        reproduction_steps=["Obtain a separate authorized reproduction WorkItem"],
        tool_evidence_refs=["dsh-event://tool-call/1"])
    stream = "\n".join((
        json.dumps({"type": "session", "session_id": "session-captain-independent-n9"}),
        json.dumps({"type": "tool_call", "tool_name": tool}),
        json.dumps({"type": "text", "text": json.dumps(candidate)})))
    def command(args, **kwargs):
        with ledger_lock(truth, busy="N9_CAPTAIN_DSH_HELD_LEDGER_DURING_PROCESS"):
            rows = truth.query("rc72_n9_captain_worker_invocation")
            assert len(rows) == 1
            assert truth.query("rc7_task", task_id=rows[0]["workitem_id"])[0]["state"] == "RUNNING"
        if command_hook:
            command_hook(truth, pipeline, owner)
        calls.append(dict(args=args, kwargs=kwargs))
        return subprocess.CompletedProcess(
            args=args, returncode=exit_code, stdout=stream, stderr="")
    patch = tmp_path / "native-n9-patch.json"
    patch.write_text("{}", encoding="utf-8")
    launcher = DshHeadlessWorkerLauncher(
        dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"n9-captain-independent-signed-worker-authority"),
        coordinator_instance_id="APPROVED-N9-PROFESSIONAL-CONTROLLER",
        release_id=pipeline.release_id,
        state_root=str(tmp_path / "n9-private-dsh-worker"),
        command_runner=command)
    specialist = NativeN9ProfessionalDshAnalysisService(
        pipeline, launcher=launcher, allowed_tools=approved_tools,
        captain_governed_dsh=captain_dsh)
    route = NativeN8ProductRecoveryService(pipeline, professional_dsh=specialist)
    return truth, plan, prep, server, pipeline, route, calls, candidate, owner


def test_real_captain_owns_one_signed_fresh_n9_worker_dsh_call_and_cold_no_replay(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, route, calls, candidate, owner = _route(
        tmp_path, monkeypatch)
    try:
        original = pipeline.complete(release_batch_id=BATCH)
        assert original["failure_class"] == "VALID_TEST_FAILURE"
        wid = original["qualification_workitem_id"]
        admitted = truth.query("rc72_captain_etu_admission", workitem_id=wid)[0]
        assert admitted["worker_id"] == original["qualification_worker_id"]
        assert len(server.calls) == 1

        result = route.complete(release_batch_id=BATCH)
        assert result["status"] == "HOLD"
        assert result["reason"] == "N9_CAUSAL_REVIEW_AND_REAL_REPRODUCTION_REQUIRED"
        assert result["cause_candidate_only"] is True
        assert result["defect_confirmed"] is result["reproduction_completed"] is False
        assert result["field_verified"] is result["bank_final"] is False
        assert len(calls) == len(server.calls) == 1
        assert calls[0]["args"][0] == sys.executable
        intent = truth.query("rc72_n9_captain_worker_invocation", workitem_id=wid)
        assert len(intent) == 1
        assert intent[0]["worker_id"] == admitted["worker_id"]
        assert intent[0]["session_id"] == admitted["session_id"]
        assert intent[0]["captain_generation"] == owner["generation"]
        assert intent[0]["scope"] == "task:" + wid
        assert intent[0]["identity"]["worker_id"] == admitted["worker_id"]
        assert intent[0]["lease"]["allowed_tools"] == ["read_only_diagnostic"]
        assert intent[0]["state"] == "SIGNED_DSH_INTENT_NO_REPLAY"
        rows = truth.query("rc72_n9_professional_dsh_analysis")
        assert len(rows) == 1
        assert rows[0]["candidate"] == candidate
        assert rows[0]["worker_id"] == admitted["worker_id"]
        assert rows[0]["dsh_session_id"] == "session-captain-independent-n9"
        task = truth.query("rc7_task", task_id=wid)[0]
        assert task["lease_owner"] == admitted["worker_id"]
        assert task["state"] == "RUNNING"
        session = truth.query("rc72_worker_session", session_id=admitted["session_id"])[0]
        assert session["runtime_worker_id"] == admitted["worker_id"]
        assert session["runtime_assignment_id"] == intent[0]["assignment_id"]
        assert session["task_lease_ref"] == intent[0]["lease_id"]
        assert session["dsh_session_id"] == "session-captain-independent-n9"
        assert not truth.query("rc7_defect")
        assert not truth.query("rc72_node_gate", node_type="N9_DEFECT")
        assert not truth.query("rc7_task", task_type="DEFECT_REPRODUCTION")
        before = truth.store.path.read_bytes()
        assert route.complete(release_batch_id=BATCH) == result
        assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1

        # A freshly reconstructed R1 must not allocate or invoke the old worker.
        cold = TruthRuntime(truth.store.path)
        assert cold.query("rc72_n9_captain_worker_invocation", workitem_id=wid)[0]["worker_id"] == admitted["worker_id"]
        assert cold.query("rc72_n9_professional_dsh_analysis")[0]["analysis_id"] == result["analysis_id"]
    finally:
        server.shutdown()
        server.server_close()


def test_captain_n9_dsh_process_failure_never_replays_on_second_invocation(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, route, calls, _, _ = _route(
        tmp_path, monkeypatch, exit_code=4)
    try:
        pipeline.complete(release_batch_id=BATCH)
        failure = route.complete(release_batch_id=BATCH)
        assert failure["reason"] == "N9_DSH_UNKNOWN_PROCESS_NO_REPLAY"
        assert len(calls) == len(server.calls) == 1
        assert truth.query("rc72_n9_captain_worker_invocation")
        assert not truth.query("rc72_n9_professional_dsh_analysis")
        before = truth.store.path.read_bytes()
        replay = route.complete(release_batch_id=BATCH)
        assert replay["reason"] == "N9_DSH_INTERRUPTED_NO_REPLAY"
        assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1
        assert not truth.query("rc7_defect")
    finally:
        server.shutdown()
        server.server_close()


def test_captain_handoff_cannot_steal_n9_while_live_dsh_tool_process_is_running(
        tmp_path, monkeypatch):
    def during_dsh(truth, pipeline, owner):
        with pytest.raises(ContractError, match="CAPTAIN_HANDOFF_ACTIVE_EXECUTION_RECONCILIATION_REQUIRED"):
            pipeline.captain_scheduler.fencer.prepare_handoff(
                mission_id=owner["mission_id"], lease_id=owner["lease_id"],
                captain_session_id=owner["captain_session_id"],
                team_id=owner["team_id"],
                lifecycle=WorkerLifecycleService(truth, release_id=pipeline.release_id),
                current_node_refs=[], latest_delivery_refs=[],
                latest_gate_refs=[], next_workitem_ids=[])
    truth, plan, prep, server, pipeline, route, calls, _, _ = _route(
        tmp_path, monkeypatch, command_hook=during_dsh)
    try:
        pipeline.complete(release_batch_id=BATCH)
        returned = route.complete(release_batch_id=BATCH)
        assert returned["cause_candidate_only"] is True
        assert len(calls) == len(server.calls) == 1
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("mutation", ["execution_tool", "missing_approved_profile", "unfenced"])
def test_unapproved_captain_dsh_bridge_rejected_before_worker_or_business_io(
        tmp_path, monkeypatch, mutation):
    if mutation == "execution_tool":
        with pytest.raises(ContractError, match="N9_CAPTAIN_SIGNED_READONLY_DSH_HOST_REQUIRED"):
            _route(tmp_path, monkeypatch, approved_tools=("api_http",))
    elif mutation == "missing_approved_profile":
        # The formal Factory must opt in; merely granting N9 tools on the
        # original Captain role profile is never permission to execute.
        truth, plan, prep, server, pipeline, route, calls, _, _ = _route(
            tmp_path, monkeypatch, captain_dsh=False)
        try:
            pipeline.captain_scheduler.role_profiles["N9_QUALIFY"] = frozenset(("api_http",))
            with pytest.raises(ContractError, match="N9_CAPTAIN_SIGNED_READONLY_DSH_HOST_REQUIRED"):
                NativeN9ProfessionalDshAnalysisService(
                    pipeline, launcher=route.professional_dsh.launcher,
                    allowed_tools=("read_only_diagnostic",),
                    captain_governed_dsh=True)
            assert not calls and not server.calls
        finally:
            server.shutdown()
            server.server_close()
    else:
        truth, plan, prep, server, pipeline, route, calls, _, _ = _route(
            tmp_path, monkeypatch, captain_dsh=False)
        try:
            pipeline.captain_scheduler = None
            with pytest.raises(ContractError, match="N9_CAPTAIN_SIGNED_READONLY_DSH_HOST_REQUIRED"):
                NativeN9ProfessionalDshAnalysisService(
                    pipeline, launcher=route.professional_dsh.launcher,
                    allowed_tools=("read_only_diagnostic",),
                    captain_governed_dsh=True)
            assert not calls and not server.calls
        finally:
            server.shutdown()
            server.server_close()


def test_captain_n9_rejects_false_tool_lease_signature_even_with_resealed_intent(
        tmp_path, monkeypatch):
    """Outer R1 intent signature alone cannot counterfeit DSH TaskLease HMAC."""
    truth, plan, prep, server, pipeline, route, calls, _, owner = _route(
        tmp_path, monkeypatch)
    try:
        first = pipeline.complete(release_batch_id=BATCH)
        received = route.complete(release_batch_id=BATCH)
        assert received['cause_candidate_only'] is True
        wid = first['qualification_workitem_id']
        admission = truth.query('rc72_captain_etu_admission', workitem_id=wid)[0]
        task = truth.query('rc7_task', task_id=wid)[0]
        intent = dict(truth.query('rc72_n9_captain_worker_invocation', workitem_id=wid)[0])
        intent.pop('artifact_type')
        intent['lease'] = dict(intent['lease'], signature='0'*64)
        launcher = route.professional_dsh.launcher
        intent['signature'] = launcher.authority._sign({
            k: v for k, v in intent.items() if k != 'signature'})
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError,
                           match='N9_CAPTAIN_DSH_SIGNED_LEASE_SIGNATURE_INVALID'):
            route.professional_dsh.captain_dsh_bridge._verify_intent(
                intent, admission, task, owner)
        assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1
        assert not truth.query('rc7_defect')
    finally:
        server.shutdown()
        server.server_close()


def test_crash_after_real_dsh_handoff_recovers_candidate_from_existing_r1_without_tool_replay(
        tmp_path, monkeypatch):
    """Signed DSH process completed; R1 receipt crash must not strand N9 forever."""
    truth, plan, prep, server, pipeline, route, calls, _, owner = _route(
        tmp_path, monkeypatch)
    try:
        first = pipeline.complete(release_batch_id=BATCH)
        original_append = truth.append_atomic
        def crash_only_before_n9_receipt(event, payload, *args, **kwargs):
            if event == 'RC72_N9_PROFESSIONAL_DSH_ANALYSIS_UPSERTED':
                raise RuntimeError('simulated process crash after real DSH HANDOFF')
            return original_append(event, payload, *args, **kwargs)
        monkeypatch.setattr(truth, 'append_atomic', crash_only_before_n9_receipt)
        with pytest.raises(RuntimeError, match='simulated process crash'):
            route.complete(release_batch_id=BATCH)
        assert len(calls) == len(server.calls) == 1
        assert truth.query('rc72_n9_captain_worker_invocation')
        assert truth.query('agent_runtime_event', event_name='HANDOFF_RETURNED')
        assert not truth.query('rc72_n9_professional_dsh_analysis')
        monkeypatch.setattr(truth, 'append_atomic', original_append)
        recovered = route.complete(release_batch_id=BATCH)
        assert recovered['status'] == 'HOLD'
        assert recovered['cause_candidate_only'] is True
        assert recovered['defect_confirmed'] is False
        assert len(truth.query('rc72_n9_professional_dsh_analysis')) == 1
        assert len(calls) == len(server.calls) == 1
        resumed_r1 = TruthRuntime(truth.store.path)
        assert resumed_r1.query('rc72_n9_professional_dsh_analysis')[0]['analysis_id'] == recovered['analysis_id']
        before = truth.store.path.read_bytes()
        assert route.complete(release_batch_id=BATCH) == recovered
        assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1
        assert not truth.query('rc7_defect')
    finally:
        server.shutdown()
        server.server_close()
