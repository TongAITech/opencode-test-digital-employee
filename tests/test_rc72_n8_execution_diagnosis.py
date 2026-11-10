from pathlib import Path

import pytest
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment


def _failure(tmp_path, monkeypatch, mode='data'):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    if mode == 'data':
        server.allowed_data_refs.clear()
    else:
        server.precondition_ready = False
    root = tmp_path / 'actual'
    env = LocalHTTPEnvironment(url, root)
    runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
                                  execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
    p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    try:
        result = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert result['state'] == 'FAILED'
        from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
        ExecutionEvidenceService(prep).record(p['preparation_id'])
        return truth, prep, server, p
    except BaseException:
        server.shutdown()
        server.server_close()
        raise


def test_actual_data_failure_independent_process_review_and_n5_back_edge(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        result = service.run(p['preparation_id'])
        assert result['state'] == 'REPAIR_REQUIRED'
        assert result['failure_class'] == 'TEST_DATA_GAP' and result['responsible_node'] == 'N5_TEST_DATA'
        receipt = truth.query('rc72_n8_process_diagnosis')[0]
        assert receipt['diagnostic_process']['pid'] != receipt['review_process']['pid']
        assert receipt['diagnosis_worker_id'] != receipt['reviewer_worker_id'] != p['worker_id']
        assert server.calls == []
        assert truth.query('execution_attempt')[0]['status'] == 'BLOCKED'
        assert truth.query('rc72_mission_node', node_type='N5_TEST_DATA')[0]['state'] == 'NEEDS_REVISION'
        before = list(truth.store.iter_raw())
        assert service.run(p['preparation_id']) == result
        assert list(truth.store.iter_raw()) == before
    finally:
        server.shutdown()
        server.server_close()


def test_unproven_precondition_cause_stays_unknown_without_gate_or_back_edge(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch, 'precondition')
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        result = service.run(p['preparation_id'])
        assert result['state'] == 'BLOCKED' and result['failure_class'] == 'UNKNOWN'
        assert truth.query('rc72_node_gate', node_type='N8_DIAGNOSIS_RECOVERY') == []
        assert truth.query('rc72_back_edge') == []
        before = list(truth.store.iter_raw())
        assert service.run(p['preparation_id']) == result
        assert list(truth.store.iter_raw()) == before
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('tamper', ['bytes', 'signature'])
def test_failure_evidence_tampering_is_rejected_before_diagnostic_process(tmp_path, monkeypatch, tamper):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        row = next(row for row in truth.query('rc7_evidence') if row['kind'] == 'N7_FORMAL_DATA_RECHECK')
        if tamper == 'bytes':
            Path(row['content_ref'][len('file://'):]).write_text('changed')
        else:
            row['check_success'] = True
            row['artifact_version'] += 1
            truth.append_atomic('RC7_EVIDENCE_UPSERTED', row)
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError, match='N8_LIVE_CHECK_'):
            ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis').run(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before
        assert not (tmp_path / 'diagnosis').exists()
    finally:
        server.shutdown()
        server.server_close()


def test_saved_process_result_recovers_interrupted_acceptance_without_another_process(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        accept = service._accept
        def interrupt(*args):
            raise KeyboardInterrupt()
        monkeypatch.setattr(service, '_accept', interrupt)
        with pytest.raises(KeyboardInterrupt):
            service.run(p['preparation_id'])
        receipt = truth.query('rc72_n8_process_diagnosis')[0]
        monkeypatch.setattr(service, '_accept', accept)
        def no_process(*args):
            raise AssertionError('recorded diagnosis must not run again')
        monkeypatch.setattr(service, '_process', no_process)
        result = service.run(p['preparation_id'])
        assert result['state'] == 'REPAIR_REQUIRED'
        assert truth.query('rc72_n8_process_diagnosis')[0] == receipt
        from rc6_runtime.truth import TruthRuntime
        from test_rc72_n7_execution_preparation import _service
        replay = TruthRuntime(truth.store.path)
        resumed = ExecutionDiagnosisService(_service(replay), evidence_root=tmp_path / 'diagnosis')
        monkeypatch.setattr(resumed, '_process', no_process)
        before = list(replay.store.iter_raw())
        assert resumed.run(p['preparation_id']) == result
        assert list(replay.store.iter_raw()) == before
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


def test_independent_review_rejects_changed_diagnostic_conclusion(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        process = service._process
        def forged(request, path):
            result, proof = process(request, path)
            if request.get('mode') != 'REVIEW':
                result['failure_class'] = 'PRODUCT_DEFECT'
            return result, proof
        monkeypatch.setattr(service, '_process', forged)
        with pytest.raises(ContractError, match='N8_INDEPENDENT_REVIEW_REJECTED'):
            service.run(p['preparation_id'])
        assert truth.query('rc72_n8_process_diagnosis') == []
        assert truth.query('rc72_node_gate', node_type='N8_DIAGNOSIS_RECOVERY') == []
        assert truth.query('rc7_defect') == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('event', ['RC72_NODE_GATE_UPSERTED', 'RC7_GAP_UPSERTED',
    'RC72_BACK_EDGE_UPSERTED', 'RC72_NODE_TRANSITION_UPSERTED', 'RC72_DIAGNOSIS_OUTCOME_UPSERTED'])
def test_partial_gate_and_back_edge_writes_resume_without_duplicate_gap_or_route(tmp_path, monkeypatch, event):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        append = truth.append_atomic
        interrupted = []
        def crash(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            if kind == event and not interrupted and (kind != 'RC72_NODE_TRANSITION_UPSERTED' or payload['kind'] == 'BACK_EDGE'):
                interrupted.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', crash)
        with pytest.raises(KeyboardInterrupt):
            service.run(p['preparation_id'])
        monkeypatch.setattr(truth, 'append_atomic', append)
        def no_process(*args):
            raise AssertionError('accepted process evidence must be reused')
        monkeypatch.setattr(service, '_process', no_process)
        result = service.run(p['preparation_id'])
        assert result['state'] == 'REPAIR_REQUIRED'
        assert len(truth.query('rc7_gap', category='TEST_DATA_GAP')) == 1
        assert len(truth.query('rc72_back_edge')) == 1
        assert len(truth.query('rc72_node_transition', kind='BACK_EDGE')) == 1
        before = list(truth.store.iter_raw())
        assert service.run(p['preparation_id']) == result
        assert list(truth.store.iter_raw()) == before
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


def test_live_data_restoration_cannot_reuse_old_gate_as_accepted_repair(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        service.run(p['preparation_id'])
        receipt = truth.query('rc72_n8_process_diagnosis')[0]
        failed_refs = receipt['result']['affected_refs']
        server.allowed_data_refs.update(failed_refs)
        admission = truth.query('rc72_n7_execution_admission', admission_id=p['admission_id'])[0]
        old_n5 = next(row['delivery_id'] for row in admission['upstream_refs'] if row['node_type'] == 'N5_TEST_DATA')
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError, match='N8_NEW_ACCEPTED_N5_REPAIR_REQUIRED'):
            service.record_accepted_repair(p['preparation_id'], repair_delivery_id=old_n5,
                                          changed_refs=failed_refs, reason='live data appeared again')
        assert list(truth.store.iter_raw()) == before
        assert truth.query('rc72_diagnosis_repair') == []
        assert truth.query('rc72_diagnosis_recovery') == []
        assert truth.query('execution_attempt')[0]['status'] == 'BLOCKED'
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('tamper', ['receipt', 'process_bytes'])
def test_saved_n8_process_proof_cannot_be_changed_during_replay(tmp_path, monkeypatch, tamper):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        service.run(p['preparation_id'])
        row = truth.query('rc72_n8_process_diagnosis')[0]
        if tamper == 'receipt':
            row['result']['failure_class'] = 'PRODUCT_DEFECT'
            row['artifact_version'] += 1
            truth.append_atomic('RC72_N8_PROCESS_DIAGNOSIS_UPSERTED', row)
        else:
            Path(row['review_process']['stdout_ref'][len('file://'):]).write_text('{"accepted":true}')
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError, match='N8_PROCESS_'):
            service.run(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before
        assert truth.query('rc7_defect') == []
    finally:
        server.shutdown()
        server.server_close()


class _MissingExecutableEnvironment(LocalHTTPEnvironment):
    def probe_tool(self, *, tool_id, target_id, layer):
        import json
        from rc7_runtime.execution_environment import ToolProbeResult
        executable = self.root / 'unavailable-tool'
        path = self.root / 'executable-probe.json'
        exists = executable.exists()
        path.write_text(json.dumps(dict(executable=str(executable), exists=exists)))
        return ToolProbeResult(tool_id, exists, 'local-tool://' + tool_id,
            'file://' + str(executable), 'adapter://engineering-local-filesystem',
            'filesystem-probe://' + target_id, 'file://' + str(path), None)


@pytest.mark.parametrize('decision_name', ['DENY', 'DELEGATE_TO_SPECIALIST', 'HUMAN_GATE'])
def test_actual_failed_tool_probe_routes_capability_without_semantic_mutation_or_business_retry(tmp_path, monkeypatch, decision_name):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        server.tool_ready = False
        root = tmp_path / 'actual-capability'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root,
            environment_adapter=_MissingExecutableEnvironment(url, root), timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])['state'] == 'FAILED'
        from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
        ExecutionEvidenceService(prep).record(p['preparation_id'])
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'capability-diagnosis')
        result = service.run(p['preparation_id'])
        assert result['state'] == 'RECOVERY_REQUIRED'
        assert result['failure_class'] == 'CAPABILITY_GAP'
        assert result['action'] == 'CAPABILITY_BROKER' and result['responsible_node'] is None
        assert server.calls == [] and truth.query('rc72_back_edge') == []
        assert truth.query('rc72_diagnosis_outcome')[0]['replacement_attempt_required'] is False
        assert truth.query('rc72_n8_process_diagnosis')[0]['result']['affected_refs'] == ['api_http']
        assert truth.query('execution_attempt')[0]['status'] == 'BLOCKED'
        before = truth.store.path.read_bytes()
        assert service.run(p['preparation_id']) == result
        assert truth.store.path.read_bytes() == before
        from rc7_runtime.rc72_capability_broker import CapabilityBroker, CapabilityDecision
        from rc7_runtime.rc72_capability_broker import CapabilityPolicyRule
        rule = CapabilityPolicyRule(CapabilityDecision(decision_name),
            delegate_role='DATA_PREPARER' if decision_name == 'DELEGATE_TO_SPECIALIST' else None)
        broker = CapabilityBroker(truth, release_id=p['release_id'], authority=prep.authority, policies={'api_http': rule})
        decision = service.request_capability_recovery(p['preparation_id'], broker=broker)
        assert decision.decision.value == decision_name
        request = truth.query('rc72_capability_request')[0]
        assert request['attempt_id'] == p['attempt_id'] and request['workitem_id'] == p['workitem_id']
        assert request['requested_capability'] == 'api_http'
        assert not truth.query('rc72_capability_lease')
        before = truth.store.path.read_bytes()
        assert service.request_capability_recovery(p['preparation_id'], broker=broker) == decision
        assert truth.store.path.read_bytes() == before and server.calls == []
        from rc7_runtime.rc72_capability_broker import CapabilityPolicyRule
        broker.policies['api_http'] = CapabilityPolicyRule(CapabilityDecision.AUTO_GRANT_TEMP_LEASE)
        with pytest.raises(ContractError, match='PHYSICAL_RESTORATION_REQUIRED'):
            service.request_capability_recovery(p['preparation_id'], broker=broker)
        assert truth.store.path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('tamper', ['bytes', 'tool_scope', 'signature'])
def test_failed_tool_probe_requires_unchanged_runtime_attestation(tmp_path, monkeypatch, tamper):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        server.tool_ready = False
        root = tmp_path / 'actual-capability'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root,
            environment_adapter=_MissingExecutableEnvironment(url, root), timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
        ExecutionEvidenceService(prep).record(p['preparation_id'])
        row = truth.query('rc7_evidence', kind='N7_FORMAL_TOOL_UNAVAILABLE')[0]
        if tamper == 'bytes':
            Path(row['content_ref'][len('file://'):]).write_bytes(b'changed probe observation')
        else:
            if tamper == 'tool_scope':
                row['check_spec']['tool_id'] = 'unapproved-tool'
            else:
                row['check_runtime_signature'] = '0' * 64
            row['artifact_version'] += 1
            truth.append_atomic('RC7_EVIDENCE_UPSERTED', row)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='N8_LIVE_CHECK_'):
            ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis').run(p['preparation_id'])
        assert truth.store.path.read_bytes() == before
        assert truth.query('rc72_diagnosis_outcome') == [] and server.calls == []
    finally:
        server.shutdown()
        server.server_close()


def test_generic_failed_tool_health_probe_does_not_establish_capability_cause(tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        server.tool_ready = False
        root = tmp_path / 'ambiguous-tool-probe'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root,
            environment_adapter=LocalHTTPEnvironment(url, root), timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
        ExecutionEvidenceService(prep).record(p['preparation_id'])
        result = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis').run(p['preparation_id'])
        assert result['failure_class'] == 'UNKNOWN' and result['state'] == 'BLOCKED'
        assert truth.query('rc72_diagnosis_outcome') == []
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("missing_kind", [
    "rc7_gap", "rc72_back_edge", "rc72_node_transition",
])
def test_accepted_n8_cold_replay_refuses_missing_canonical_semantic_route(
        tmp_path, monkeypatch, missing_kind):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / "diagnosis")
        result = service.run(p["preparation_id"])
        assert result["failure_class"] == "TEST_DATA_GAP"
        assert truth.query("rc72_diagnosis_outcome")[0]["action"] == "SEMANTIC_BACK_EDGE"
        assert truth.query(missing_kind)
        original_query = truth.query

        def missing_link(kind, **filters):
            if kind == missing_kind:
                return []
            return original_query(kind, **filters)

        monkeypatch.setattr(truth, "query", missing_link)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="DIAGNOSIS_CLASSIFICATION_REPLAY_ROUTE_INCOMPLETE"):
            service.run(p["preparation_id"])
        assert truth.store.path.read_bytes() == before
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


def test_accepted_n8_cold_replay_refuses_forged_outcome_action_without_side_effect(
        tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / "diagnosis")
        assert service.run(p["preparation_id"])["failure_class"] == "TEST_DATA_GAP"
        outcome = truth.query("rc72_diagnosis_outcome")[0]
        forged = dict(outcome, action="RUNTIME_RECOVERY",
                      artifact_version=outcome["artifact_version"] + 1)
        truth.append_atomic("RC72_DIAGNOSIS_OUTCOME_UPSERTED", forged)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="DIAGNOSIS_CLASSIFICATION_REPLAY_ROUTE_CONFLICT"):
            service.run(p["preparation_id"])
        assert truth.store.path.read_bytes() == before
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("damage", ["missing_delivery", "forged_delivery_evidence"])
def test_n8_cold_replay_refuses_missing_or_forged_delivery_before_r1_write(
        tmp_path, monkeypatch, damage):
    """A genuine N7 failure/process diagnosis cannot mint a missing N8 Delivery."""
    from rc7_runtime.rc72_domain import AutonomousMissionNode, MissionNodeState

    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / "diagnosis")
        result = service.run(p["preparation_id"])
        assert result["failure_class"] == "TEST_DATA_GAP"
        receipt = truth.query("rc72_n8_process_diagnosis")[0]
        node = service.runtime.node_by_type(
            p["mission_id"], AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
        service.runtime.mark_stale(node["mission_node_id"], reason="cold R1 re-review")
        service.runtime.transition_state(node["mission_node_id"],
                                         MissionNodeState.READY, reason="resume diagnosis")
        before = truth.store.path.read_bytes()
        original_query = truth.query

        def untrusted_delivery(kind, **filters):
            rows = original_query(kind, **filters)
            if (kind == "rc72_node_delivery"
                    and filters.get("delivery_id") == receipt["delivery_id"]):
                if damage == "missing_delivery":
                    return []
                return [dict(rows[0], evidence_refs=["FORGED-R1-EVIDENCE"])]
            return rows

        monkeypatch.setattr(truth, "query", untrusted_delivery)
        expected = ("N8_ACCEPTED_DELIVERY_NOT_UNIQUE_OR_MISSING"
                    if damage == "missing_delivery" else "N8_ACCEPTED_DELIVERY_LINEAGE_CHANGED")
        with pytest.raises(ContractError, match=expected):
            service.run(p["preparation_id"])
        assert truth.store.path.read_bytes() == before
        assert truth.query("execution_attempt")[0]["status"] == "BLOCKED"
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("damage", ["forged_gate", "wrong_active_delivery_generation"])
def test_r4_n8_replay_checks_forged_gate_and_active_delivery_before_evidence(
        tmp_path, monkeypatch, damage):
    """A saved process receipt cannot write a new Evidence before R1 gate review."""
    from rc7_runtime.rc72_domain import AutonomousMissionNode

    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / "diagnosis")
        assert service.run(p["preparation_id"])["failure_class"] == "TEST_DATA_GAP"
        original_query = truth.query
        if damage == "forged_gate":
            gate = original_query("rc72_node_gate", node_type="N8_DIAGNOSIS_RECOVERY")[0]

            def forged_gate(kind, **filters):
                rows = original_query(kind, **filters)
                if (kind == "rc72_node_gate"
                        and filters.get("gate_id") == gate["gate_id"]):
                    return [dict(rows[0], evidence_refs=["FORGED-DIAGNOSTIC-EVIDENCE"])]
                return rows

            monkeypatch.setattr(truth, "query", forged_gate)
            error = "N8_ACCEPTED_GATE_CONFLICT"
        else:
            original_node = service.runtime.node_by_type

            def wrong_node(mission_id, node_type):
                node = original_node(mission_id, node_type)
                if node_type == AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY:
                    return dict(node, active_delivery_version=9999)
                return node

            monkeypatch.setattr(service.runtime, "node_by_type", wrong_node)
            error = "N8_ACTIVE_DELIVERY_CONFLICT"

        def forbidden_evidence_write(*args, **kwargs):
            raise AssertionError("untrusted cold R1 replay attempted Evidence write")

        monkeypatch.setattr(service.evidence, "_ensure", forbidden_evidence_write)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match=error):
            service.run(p["preparation_id"])
        assert truth.store.path.read_bytes() == before
        assert truth.query("execution_attempt")[0]["status"] == "BLOCKED"
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("damage", [
    "running_wrong_active_generation", "running_foreign_delivery_ref",
])
def test_e_qa_n8_running_cold_replay_must_not_overwrite_active_delivery(
        tmp_path, monkeypatch, damage):
    """E independent QA: a running N8 node must not adopt stale/cross-batch Delivery.

    Source before this regression only prechecked REVIEW_PENDING/PASS and would
    overwrite RUNNING active_delivery_version, mutating R1 Evidence first.
    """
    from rc7_runtime.rc72_domain import AutonomousMissionNode

    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(
            prep, evidence_root=tmp_path / "diagnosis")
        assert service.run(p["preparation_id"])["failure_class"] == "TEST_DATA_GAP"
        original_node = service.runtime.node_by_type

        def incompatible_running_node(mission_id, node_type):
            node = original_node(mission_id, node_type)
            if node_type == AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY:
                if damage == "running_wrong_active_generation":
                    return dict(node, state="RUNNING",
                                active_delivery_version=777,
                                delivery_refs=list(node["delivery_refs"]))
                return dict(node, state="RUNNING",
                            delivery_refs=["N8-FOREIGN-DELIVERY"],
                            active_delivery_version=node["active_delivery_version"])
            return node

        monkeypatch.setattr(service.runtime, "node_by_type",
                            incompatible_running_node)

        def forbid_evidence_write(*args, **kwargs):
            raise AssertionError("E QA: forged RUNNING N8 attempted R1 Evidence write")

        monkeypatch.setattr(service.evidence, "_ensure", forbid_evidence_write)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="N8_ACTIVE_DELIVERY_CONFLICT"):
            service.run(p["preparation_id"])
        assert truth.store.path.read_bytes() == before
        assert truth.query("execution_attempt")[0]["status"] == "BLOCKED"
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()
