"""C04: actual post-HumanGate independent HTTP process and immutable R1 proofs.

An engineering loopback server is genuinely called by a second subprocess,
through the parent-owned RC7 API proxy. This is NOT bank Field verification,
repair approval, root-cause confirmation or BANK_FINAL.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_canonical_design import CanonicalDesignService
from rc7_runtime.rc72_n9_approved_reproduction_execution import (
    N9ApprovedReproductionExecutionService,
)
from rc7_runtime.runtime_execution import VerifiedScriptExecutionBundle
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator
from rc72_n2_test_support import BATCH, RELEASE, COMMIT
from test_rc72_n9_reproduction_human_gate import _setup_gate, _approval


def _executor(tmp_path, truth, pipeline, gate):
    return N9ApprovedReproductionExecutionService(
        gate, evidence_root=tmp_path/"approved-reproduction-output",
        captain_scheduler=pipeline.captain_scheduler,
        captain_session_id=pipeline.captain_session_id,
        captain_lease_id=pipeline.captain_lease_id,
        team_id=pipeline.team_id,
        timeout_seconds=30)


def _real_reproduction_case(tmp_path, truth, request_id):
    req = truth.query("rc72_n9_reproduction_authorization_request",
                      request_id=request_id)[0]
    contract = truth.query("rc72_n6_executable_contract",
                           contract_id=req["original_contract_id"])[0]
    design = CanonicalDesignService(
        truth, release_id=RELEASE, source_commit=COMMIT).load(release_batch_id=BATCH)
    original = next(c for c in design.cases if c["tc_id"] == req["original_case_id"])
    case = {k: v for k, v in original.items() if k not in {
        "execution", "source_artifact_id", "source_artifact_sha256",
        "source_case_sha256"}}
    case.update(status="FROZEN", case_version=1, release_id=RELEASE,
                expected=json.dumps(original["expected_results"], sort_keys=True))
    assert case["steps"] == contract["steps"]
    assert case["oracle"]["checks"] == contract["oracles"]
    spec = ExecutableSpecBuilder().build(
        case=case, target_requirements=(contract["requirement_id"],),
        test_data_refs=tuple(x["data_ref"] for x in contract["data_refs"]),
        oracle_refs=("oracle://approved-n4",),
        cleanup_policy=contract["cleanup"], runner_type="PYTEST",
        automation_mapping={"reuse": {}})
    source = tmp_path/"test_n9_real_reproduction.py"
    source.write_text(
        'import json,os\n'
        'from urllib.request import Request,urlopen\n'
        'def test_n9_real_reproduction():\n'
        '    cmd={"method":"POST","path":"/config/query",'
        '"body":{"request_id":"independent-n9-reproduction"},'
        '"capture_as":"actual_result"}\n'
        '    req=Request(os.environ["RC7_API_RUNTIME_PROXY_URL"],'
        'data=json.dumps(cmd).encode(),'
        'headers={"Content-Type":"application/json"},method="POST")\n'
        '    with urlopen(req,timeout=10) as response:\n'
        '        actual=json.loads(response.read())\n'
        '    assert actual["status_code"]==200\n'
        '    with open(os.environ["RC6_EXECUTION_MANIFEST"],"a",encoding="utf-8") as stream:\n'
        '        stream.write(json.dumps({"type":"actual_result","value":{"untrusted_child":True}})+"\\n")\n',
        encoding="utf-8")
    script = ScriptArtifact(
        script_id="SCRIPT-N9-APPROVED-REPRO",
        spec_id=spec.spec_id, tc_id=spec.tc_id,
        case_version=spec.case_version, layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source),
        test_symbol="test_n9_real_reproduction",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(), builder_evidence_refs=("evidence://approved-script",),
        revision=1)
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path/"n9-script-preflight"),
        timeout_seconds=30).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
    bundle = VerifiedScriptExecutionBundle(
        upstream_mission_id="APPROVED-N9-SCRIPT-MISSION",
        upstream_task_id="APPROVED-N9-SCRIPT-TASK",
        upstream_evaluation_id="APPROVED-N9-SCRIPT-EVAL",
        upstream_result_ref="file://approved-n9-script-result",
        spec_ref="file://approved-n9-spec",
        frozen_case=case, spec=spec, script=script,
        validation=validation, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    attempt_id = "ATT-C04-FRESH-INDEPENDENT-REPRODUCTION-1"
    prepared = PreparedAttempt(
        status="PREPARED", attempt_id=attempt_id, tc_id=spec.tc_id,
        case_version=spec.case_version, target_id="C04-ENGINEERING-TARGET",
        precondition_evidence=("engineering://verified-original-precondition",),
        initial_state_bindings={}, input_data_bindings={},
        binding_evidence=("engineering://verified-independent-data",),
        cleanup_policy=contract["cleanup"],
        oracle_snapshot={"checks": contract["oracles"]})
    return bundle, prepared, contract


def _broker():
    broker = ToolCapabilityBroker()
    tool = "api-runtime"
    broker.discover(tool, "qualification://c04-api")
    broker.mark_executable(tool, "executable://c04-api")
    broker.register(tool, "registration://c04-api")
    broker.record_probe(tool, success=True, tool_call_ref="probe://c04-api",
                        evidence_ref="probe-evidence://c04-api")
    broker.mark_target_ready(tool, "C04-ENGINEERING-TARGET",
                             "target-ready://c04-api")
    return broker


def _approved_setup(tmp_path, monkeypatch):
    truth, pipeline, route, server, calls, verifier, gate, qualified, owner = (
        _setup_gate(tmp_path, monkeypatch))
    request_id = qualified["reproduction_request_id"]
    att = _approval(truth, request_id, verifier=verifier)
    gate.review(request_id=request_id, attestation_ref=att["attestation_ref"])
    executor = _executor(tmp_path, truth, pipeline, gate)
    bundle, prepared, contract = _real_reproduction_case(tmp_path, truth, request_id)
    url = "http://127.0.0.1:%d" % server.server_address[1]
    return truth, pipeline, server, gate, request_id, executor, bundle, prepared, url


def test_independent_approved_new_business_http_and_oracle_are_real_and_no_replay(
        tmp_path, monkeypatch):
    truth, pipeline, server, gate, req, executor, bundle, prepared, url = (
        _approved_setup(tmp_path, monkeypatch))
    try:
        original_attempt = truth.query("rc72_n9_reproduction_authorization_request",
                                       request_id=req)[0]["original_attempt_id"]
        assert len(server.calls) == 1
        result = executor.execute(
            request_id=req, bundle=bundle, prepared=prepared,
            authority=RC72AuthorityRuntime(b"c04-independent-real-subprocess-authority"),
            tool_broker=_broker(), cwd=str(tmp_path), target_base_url=url)
        assert len(server.calls) == 2
        assert result["status"] == "HOLD"
        assert result["fresh_attempt_id"] == prepared.attempt_id
        assert result["fresh_attempt_id"] != original_attempt
        assert result["conclusive"] is True
        assert result["reproduced"] is True
        assert result["defect_confirmed"] is False
        assert result["rca_completed"] is False
        assert result["regression_verified"] is False
        assert result["field_verified"] is result["bank_final"] is False
        record = truth.query("rc72_n9_approved_reproduction_execution")[0]
        assert record["state"] == "EXECUTED_WITH_DURABLE_EVIDENCE"
        assert record["execution_status"] == "FAIL"
        assert record["task_state"] == "PASS"
        task = truth.query("rc7_task", task_id=result["workitem_id"])[0]
        assert task["state"] == "PASS"
        assert task["lease_owner"] == result["worker_id"]
        assert task["evaluation_id"] == result["evaluation_id"]
        evidence = truth.query("rc7_evidence", evidence_id=result["evidence_ids"][0])
        assert evidence
        assert truth.query("rc7_artifact", artifact_id=result["execution_artifact_id"])
        assert not truth.query("rc7_defect")
        assert not [g for g in truth.query("rc7_gap")
                    if g["category"] == "PRODUCT_DEFECT"]
        before = truth.store.path.read_bytes()
        assert executor.audit(request_id=req)["reproduced"] is True
        with pytest.raises(ContractError, match="NO_BUSINESS_REPLAY"):
            executor.execute(
                request_id=req, bundle=bundle, prepared=prepared,
                authority=RC72AuthorityRuntime(b"second-signing-key-not-effective"),
                tool_broker=_broker(), cwd=str(tmp_path), target_base_url=url)
        assert len(server.calls) == 2
        assert truth.store.path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("change", ["stale_oracle", "old_attempt", "not_approved"])
def test_no_business_effect_without_exact_new_approved_case(
        tmp_path, monkeypatch, change):
    truth, pipeline, server, gate, req, executor, bundle, prepared, url = (
        _approved_setup(tmp_path, monkeypatch))
    try:
        if change == "stale_oracle":
            bad = dict(bundle.frozen_case)
            bad["oracle"] = {"checks": [{"id": "forged"}]}
            bundle = replace(bundle, frozen_case=bad)
        elif change == "old_attempt":
            old = truth.query("rc72_n9_reproduction_authorization_request",
                              request_id=req)[0]["original_attempt_id"]
            prepared = replace(prepared, attempt_id=old)
        else:
            row = dict(truth.query("rc72_n9_reproduction_human_decision")[0])
            row["signature"] = "0"*64
            row["artifact_version"] += 1
            truth.append_atomic("RC72_N9_REPRODUCTION_HUMAN_DECISION_RECORDED", row)
        prior = truth.store.path.read_bytes()
        with pytest.raises(ContractError):
            executor.execute(
                request_id=req, bundle=bundle, prepared=prepared,
                authority=RC72AuthorityRuntime(b"c04-unauthorized-executor"),
                tool_broker=_broker(), cwd=str(tmp_path), target_base_url=url)
        assert len(server.calls) == 1
        assert truth.store.path.read_bytes() == prior
        assert not truth.query("rc72_n9_approved_reproduction_execution")
        assert not truth.query("rc7_task", task_type="DEFECT_REPRODUCTION")
    finally:
        server.shutdown()
        server.server_close()


def test_inflight_before_subprocess_is_unknown_not_automatically_replayed(
        tmp_path, monkeypatch):
    from rc7_runtime import defect_reproduction
    truth, pipeline, server, gate, req, executor, bundle, prepared, url = (
        _approved_setup(tmp_path, monkeypatch))
    try:
        def fail_before_process(*args, **kwargs):
            raise KeyboardInterrupt("engineering crash injection")
        with monkeypatch.context() as patch:
            patch.setattr(defect_reproduction.DefectReproductionExecutionService,
                          "execute_task", fail_before_process)
            with pytest.raises(KeyboardInterrupt):
                executor.execute(
                    request_id=req, bundle=bundle, prepared=prepared,
                    authority=RC72AuthorityRuntime(b"c04-crash-injected-authority"),
                    tool_broker=_broker(), cwd=str(tmp_path), target_base_url=url)
        assert len(server.calls) == 1
        original = truth.query("rc72_n9_approved_reproduction_execution")[0]
        assert original["state"] == "IN_FLIGHT_NO_REPLAY"
        before = truth.store.path.read_bytes()
        cold = TruthRuntime(truth.store.path)
        # The same canonical source's audit must not spawn a new process.
        executor.truth = cold
        executor.gate.truth = cold
        executor.gate.requests.truth = cold
        executor.gate.requests.analyst.truth = cold
        assert executor.audit(request_id=req)["reason"] == "N9_REPRO_UNKNOWN_EFFECT_NO_REPLAY"
        assert cold.store.path.read_bytes() == before
        assert len(server.calls) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_release_batch_driver_c04_product_entry_runs_genuine_new_http_process(
        tmp_path, monkeypatch):
    """No fixture callback: public ReleaseBatchDriver -> N8 -> actual runner."""
    import sys
    from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
    from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
    from rc7_runtime.rc72_release_driver import ReleaseBatchDriver
    from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service
    from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
    from rc72_pip_field_test_support import provider as field_provider
    from test_rc72_n9_reproduction_human_gate import _setup_gate, _approval

    truth, pipeline, route, server, calls, verifier, gate, qualified, owner = (
        _setup_gate(tmp_path, monkeypatch))
    try:
        req = qualified["reproduction_request_id"]
        approval = _approval(truth, req, verifier=verifier)
        gate.review(request_id=req, attestation_ref=approval["attestation_ref"])
        executor = _executor(tmp_path, truth, pipeline, gate)
        bundle, prepared, contract = _real_reproduction_case(tmp_path, truth, req)
        url = "http://127.0.0.1:%d" % server.server_address[1]
        patch_file = tmp_path/"bank-host-no-n1-n2-invocation.json"
        patch_file.write_text("{}", encoding="utf-8")

        def launcher(role):
            def forbidden(*args, **kwargs):
                pytest.fail("Product C04 reproduction must not invoke unrelated DSH")
            return DshHeadlessWorkerLauncher(
                dsh_bin=sys.executable, patch_path=str(patch_file),
                cwd=str(tmp_path), truth=truth,
                authority=RC72AuthorityRuntime(("c04-driver-role-"+role).encode()),
                coordinator_instance_id="c04-live-host",
                release_id=pipeline.release_id,
                state_root=str(tmp_path/("c04-driver-role-"+role)),
                command_runner=forbidden)

        n8 = NativeN8ProductRecoveryService(
            pipeline, professional_dsh=route.professional_dsh,
            reproduction_human_gate=gate,
            reproduction_executor=executor)
        driver = ReleaseBatchDriver(
            truth, source_commit=pipeline.source_commit,
            bank_pip_mirror=field_provider(truth, source_commit=pipeline.source_commit),
            n1_launcher=launcher("n1"), n1_tools=["reality"],
            n2_launcher=launcher("n2"), n2_tools=["requirement"],
            n2_evaluator=DshRequirementEvaluator(
                launcher("review"), allowed_tools=["requirement-review"]),
            n7_pipeline=pipeline, n8_pipeline=n8,
            n9_pipeline=AcceptedScopeN9Service(pipeline))

        assert len(server.calls) == 1
        result = driver.execute_reproduction(
            release_batch_id=BATCH, request_id=req,
            bundle=bundle, prepared=prepared,
            authority=RC72AuthorityRuntime(b"actual-product-c04-driver-authority"),
            tool_broker=_broker(), cwd=str(tmp_path), target_base_url=url)
        assert result["conclusive"] and result["reproduced"]
        assert len(server.calls) == 2
        assert truth.query("rc72_n9_approved_reproduction_execution")
        assert not truth.query("rc7_defect")
        assert not truth.query("rc72_node_gate", node_type="N9_DEFECT")
        from rc7_runtime.models import ContractError
        frozen = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="R1_NOT_UNIQUE:rc7_defect"):
            n8.audit_reproduction_resolution(
                release_batch_id=BATCH, request_id=req,
                defect_id="NOT-A-QUALIFIED-DEFECT")
        with pytest.raises(ContractError, match="R1_NOT_UNIQUE:rc7_defect"):
            driver.audit_reproduction_resolution(
                release_batch_id=BATCH, request_id=req,
                defect_id="NOT-A-QUALIFIED-DEFECT")
        assert truth.store.path.read_bytes() == frozen
        assert len(server.calls) == 2
    finally:
        server.shutdown()
        server.server_close()


def test_c04_cold_audit_detects_changed_execution_bytes_without_second_business_call(
        tmp_path, monkeypatch):
    truth, pipeline, server, gate, req, executor, bundle, prepared, url = (
        _approved_setup(tmp_path, monkeypatch))
    try:
        result = executor.execute(
            request_id=req, bundle=bundle, prepared=prepared,
            authority=RC72AuthorityRuntime(b"actual-c04-audit-file-authority"),
            tool_broker=_broker(), cwd=str(tmp_path), target_base_url=url)
        assert len(server.calls) == 2
        artifact = truth.query("rc7_artifact", artifact_id=result["execution_artifact_id"])[0]
        path = Path(artifact["content_ref"][len("file://"):])
        before = truth.store.path.read_bytes()
        path.write_bytes(path.read_bytes()+b"\nforged-trailer")
        with pytest.raises(ContractError, match="N9_REPRO_EXECUTION_BYTES_CHANGED"):
            executor.audit(request_id=req)
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 2
    finally:
        server.shutdown()
        server.server_close()


def test_c04_cold_audit_rejects_forged_signed_r1_and_cannot_rerun_business(
        tmp_path, monkeypatch):
    truth, pipeline, server, gate, req, executor, bundle, prepared, url = (
        _approved_setup(tmp_path, monkeypatch))
    try:
        executor.execute(
            request_id=req, bundle=bundle, prepared=prepared,
            authority=RC72AuthorityRuntime(b"c04-forged-r1-authority"),
            tool_broker=_broker(), cwd=str(tmp_path), target_base_url=url)
        assert len(server.calls) == 2
        forged = dict(truth.query("rc72_n9_approved_reproduction_execution")[0])
        forged["signature"] = "0"*64
        forged["artifact_version"] += 1
        truth.append_atomic("RC72_N9_APPROVED_REPRODUCTION_EXECUTION_UPSERTED", forged)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="N9_REPRO_RECORD_SIGNATURE_CHANGED"):
            executor.audit(request_id=req)
        with pytest.raises(ContractError):
            executor.execute(
                request_id=req, bundle=bundle, prepared=prepared,
                authority=RC72AuthorityRuntime(b"c04-other-authority"),
                tool_broker=_broker(), cwd=str(tmp_path), target_base_url=url)
        assert len(server.calls) == 2
        assert truth.store.path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()
