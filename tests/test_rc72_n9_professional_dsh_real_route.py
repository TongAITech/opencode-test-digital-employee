"""C04 actual N7 SUT discrepancy -> independently admitted N8/N9 DSH process.

The runner is a local deterministic fake DSH command that preserves real
subprocess invocation metadata and actual R1/worker-output process boundaries.
This is an engineering contract, NOT a bank RCA or defect reproduction PASS.
"""
import json
import subprocess
import sys

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
from rc7_runtime.rc72_n9_professional_dsh import NativeN9ProfessionalDshAnalysisService
from rc72_n2_test_support import BATCH
from test_rc72_conclusive_failure_evidence import _failed_business


def _route(tmp_path, monkeypatch, *, complete=True):
    truth,plan,prep,server,url,pipeline=_failed_business(tmp_path,monkeypatch)
    calls=[]
    candidate=dict(
        finding="INCONCLUSIVE",
        hypotheses=["An approved business oracle difference requires real reproduction"],
        reproduction_steps=["Create separate approved ETU and obtain a fresh N7 Attempt"],
        tool_evidence_refs=["dsh-event://tool-call/1"])
    stream="\n".join([
        json.dumps({"type":"session","session_id":"session-independent-n9-1"}),
        json.dumps({"type":"tool_call","tool_name":"api_read_only"}),
        json.dumps({"type":"text","text":json.dumps(candidate)})])
    def command(args, **kwargs):
        # A real DSH worker must not run while the coordinator holds the
        # global R1 lease lock. Another independent worker must be able to
        # register/inspect its own Task during a long analyst invocation.
        from rc7_runtime.rc72_ledger_lock import ledger_lock
        with ledger_lock(truth,busy="N9_DSH_IO_HELD_GLOBAL_LEDGER_LOCK"):
            assert truth.query("rc72_release_batch",release_batch_id=BATCH)
        calls.append(dict(args=args,kwargs=kwargs))
        return subprocess.CompletedProcess(
            args=args,returncode=0 if complete else 2,
            stdout=stream,stderr="")
    launcher=DshHeadlessWorkerLauncher(
        dsh_bin=sys.executable,patch_path=str(tmp_path/"signed-patch.json"),
        cwd=str(tmp_path),truth=truth,
        authority=RC72AuthorityRuntime(b"n9-engineering-independent-dsh-signer"),
        coordinator_instance_id="N9-ENGINEERING-CONTROLLER",
        release_id=prep.release_id,
        state_root=str(tmp_path/"professional-worker"),
        command_runner=command)
    specialist=NativeN9ProfessionalDshAnalysisService(
        pipeline,launcher=launcher,allowed_tools=("api_read_only",))
    route=NativeN8ProductRecoveryService(pipeline,professional_dsh=specialist)
    return truth,plan,prep,server,pipeline,route,calls,candidate


def test_product_n8_routes_real_valid_business_difference_to_actual_scoped_n9_dsh_once(
        tmp_path,monkeypatch):
    truth,plan,prep,server,pipeline,route,calls,candidate=_route(tmp_path,monkeypatch)
    try:
        original=pipeline.complete(release_batch_id=BATCH)
        assert original["failure_class"]=="VALID_TEST_FAILURE"
        assert len(server.calls)==1
        result=route.complete(release_batch_id=BATCH)
        assert result["status"]=="HOLD"
        assert result["reason"]=="N9_CAUSAL_REVIEW_AND_REAL_REPRODUCTION_REQUIRED"
        assert result["cause_candidate_only"] is True
        assert result["defect_confirmed"] is False
        assert result["reproduction_completed"] is False
        assert result["field_verified"] is result["bank_final"] is False
        assert len(calls)==1 and len(server.calls)==1
        assert calls[0]["args"][0]==sys.executable
        receipt=truth.query("rc72_n9_professional_dsh_analysis")
        assert len(receipt)==1
        assert receipt[0]["analysis_id"]==result["analysis_id"]
        assert receipt[0]["candidate"]==candidate
        assert receipt[0]["original_attempt_id"]==truth.query("execution_attempt")[0]["attempt_id"]
        assert receipt[0]["dsh_session_id"]=="session-independent-n9-1"
        assert len(truth.query("rc7_task",task_type="N9_DISCREPANCY_QUALIFICATION"))==1
        assert not truth.query("rc7_defect")
        before=truth.store.path.read_bytes()
        assert route.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before
        assert len(calls)==len(server.calls)==1
    finally:
        server.shutdown();server.server_close()


def test_real_failed_n9_process_does_not_relaunch_or_confirm_product_defect(
        tmp_path,monkeypatch):
    truth,plan,prep,server,pipeline,route,calls,candidate=_route(
        tmp_path,monkeypatch,complete=False)
    try:
        original=pipeline.complete(release_batch_id=BATCH)
        assert original["failure_class"]=="VALID_TEST_FAILURE"
        result=route.complete(release_batch_id=BATCH)
        assert result["status"]=="HOLD"
        assert result["reason"]=="N9_DSH_UNKNOWN_PROCESS_NO_REPLAY"
        assert len(calls)==len(server.calls)==1
        assert truth.query("rc72_n9_professional_dsh_analysis")==[]
        before=truth.store.path.read_bytes()
        resumed=route.complete(release_batch_id=BATCH)
        assert resumed["reason"]=="N9_DSH_INTERRUPTED_NO_REPLAY"
        assert truth.store.path.read_bytes()==before
        assert len(calls)==len(server.calls)==1
        assert not truth.query("rc7_defect")
    finally:
        server.shutdown();server.server_close()
