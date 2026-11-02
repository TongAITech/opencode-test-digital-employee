"""Real local failure/compensation and independent protocol subprocess with HTTP.

The worker is an engineering DSH-protocol adapter, not a real provider/Field
certification. Native runtime authority, raw anchoring and N5 gates are used.
"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n5_existing_data_repair import ExistingDataRepairService
from rc7_runtime.rc72_n5_completion import N5DeliveryGateService
from rc7_runtime.rc72_n5_data_resolution import N5DataResolutionError
from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from rc7_runtime.rc72_n8_repair_boundary import RepairBoundaryService
from test_rc72_n8_repair_boundary import _setup
from test_rc72_n7_execution_preparation import _service

_WORKER = '''
import json, os, sys, uuid
from urllib.request import Request, urlopen
from urllib.parse import quote
context = json.loads(sys.argv[1].rsplit("\\n", 1)[1])
result = context['output_contract']
if result['schema'] == 'RC72_N5_EXISTING_DATA_PREPARATION_V1':
    request = Request(os.environ['N5_ENGINEERING_TARGET'] + '/repair',
        data=json.dumps(dict(data_ref=result['data_ref'])).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    success = 'PREPARED'
else:
    request = os.environ['N5_ENGINEERING_TARGET'] + '/data?ref=' + quote(result['data_ref'], safe='')
    success = 'VERIFIED'
with urlopen(request, timeout=5) as response:
    actual = json.loads(response.read())
result['status'] = success if actual.get('data_exists') is True else 'REPAIR_REQUIRED'
result['verification'] = 'Independent subprocess observed exact DataRef using its authorized tool'
result['gaps'] = [] if result['status'] == success else ['exact data missing']
change = os.environ.get('N5_ENGINEERING_TAMPER')
if change == 'data_ref':
    result['data_ref'] = 'data://unapproved/substitute'
if change == 'preconditions':
    result['precondition_refs'] = ['unapproved-precondition']
if change == 'claim':
    result['n5_pass'] = True
if change == 'revision':
    result['binding_revision'] += 1
print(json.dumps(dict(type='session', session_id=os.environ.get('N5_ENGINEERING_SESSION') or 'session-existing-repair-' + uuid.uuid4().hex)))
print(json.dumps(dict(type='tool_call', tool_name=context['authorized_tools'][0])))
print(json.dumps(dict(type='final', text=json.dumps(result))))
'''


def _launcher(tmp_path, prep, server, calls, *, tamper=None):
    worker = tmp_path / 'existing-repair-worker.py'
    worker.write_bytes(_WORKER.encode('utf-8'))
    patch = tmp_path / 'existing-repair-patch.json'
    patch.write_text('{}', encoding='utf-8')
    def run(command, **kwargs):
        calls.append('DSH_PROTOCOL_PROCESS')
        return subprocess.run([sys.executable, str(worker), command[-1]], **kwargs)
    return DshHeadlessWorkerLauncher(dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
        truth=prep.truth, authority=prep.authority, coordinator_instance_id='repair-coordinator',
        release_id=prep.release_id, state_root=str(tmp_path / 'repair-runtime'), timeout_seconds=20,
        command_runner=run, env=dict(N5_ENGINEERING_TARGET='http://127.0.0.1:%d' % server.server_address[1],
                                    N5_ENGINEERING_TAMPER=tamper or ''))


def _service_setup(tmp_path, monkeypatch, *, restored=True, tamper=None):
    truth, prep, server, p, diagnosis, boundary, cleanup_calls = _setup(tmp_path, monkeypatch)
    try:
        boundary.open(p['preparation_id'])
        contract = truth.query('rc72_n6_executable_contract', contract_id=p['contract_id'])[0]
        binding = next(row for row in truth.query('rc72_n5_data_binding')
                       if row['data_ref'] == contract['data_refs'][0]['data_ref'])
        if restored:
            server.allowed_data_refs.add(binding['data_ref'])
        calls = []
        service = ExistingDataRepairService(boundary,
            launcher=_launcher(tmp_path, prep, server, calls, tamper=tamper), allowed_tools=['query-exact-data-ref'])
        request = service.request(p['preparation_id'], data_requirement_id=binding['data_requirement_id'],
                                  binding_revision=binding['artifact_version'])
        return truth, prep, server, p, binding, service, request, calls, cleanup_calls
    except BaseException:
        server.shutdown()
        server.server_close()
        raise


def _close(server):
    server.shutdown()
    server.server_close()


def test_reuse_only_exact_data_repair_independently_reverifies_and_renews_n5_gate(tmp_path, monkeypatch):
    truth, prep, server, p, old, service, request, calls, cleanup = _service_setup(tmp_path, monkeypatch)
    try:
        assert not truth.query('rc72_n5_data_discovery_attempt')
        failed = truth.query('execution_attempt')[0]
        with pytest.raises(N5DataResolutionError, match='REVERIFICATION_REPAIR_REQUIRED'):
            service._finalizer(p['mission_id']).resolution.verified_binding(data_requirement_id=old['data_requirement_id'])
        result = service.run(request['repair_id'])
        assert result['state'] == 'VERIFIED' and result['data_ref'] == old['data_ref']
        current = truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0]
        assert current['artifact_version'] == old['artifact_version'] + 2
        assert current['verification_history'][0]['verification_evidence_refs'] == old['verification_evidence_refs']
        assert current['verification_evidence_refs'] == [result['evidence_ref']]
        assert current['precondition_refs'] == old['precondition_refs']
        assert not current.get('verification_blocked_by_anchor')
        accepted = N5DeliveryGateService(truth, release_id=p['release_id'], source_commit=p['source_commit']).complete(
            release_batch_id=p['release_batch_id'])
        assert accepted['gate']['decision'] == 'PASS'
        assert truth.query('rc72_mission_node', node_type='N6_EXECUTABLE_READINESS')[0]['state'] == 'READY'
        assert truth.query('execution_attempt')[0] == failed
        assert cleanup == ['CLEANUP', 'VERIFY'] and calls == ['DSH_PROTOCOL_PROCESS'] and server.calls == []
        row = truth.query('rc72_n5_existing_data_repair')[0]
        assert row['identity']['role'] == 'DATA_VERIFIER' and not row['lease']['allowed_artifact_types']
        assert row['lease']['lease_id'] not in prep.authority._leases
        before = truth.store.path.read_bytes()
        assert service.run(request['repair_id']) == result
        assert truth.store.path.read_bytes() == before
        replay = TruthRuntime(truth.store.path)
        restored_prep = _service(replay)
        boundary = RepairBoundaryService(ExecutionDiagnosisService(restored_prep, evidence_root=tmp_path / 'diagnosis'), cleanup_adapters={})
        cold = ExistingDataRepairService(boundary, launcher=_launcher(tmp_path, restored_prep, server, calls),
                                        allowed_tools=['query-exact-data-ref'])
        assert cold.run(request['repair_id']) == result
        assert replay.store.path.read_bytes() == before
        assert calls == ['DSH_PROTOCOL_PROCESS']
    finally:
        _close(server)


def test_failed_independent_repair_retains_suspension_and_locked_n6(tmp_path, monkeypatch):
    truth, _, server, p, old, service, request, calls, _ = _service_setup(tmp_path, monkeypatch, restored=False)
    try:
        result = service.run(request['repair_id'])
        assert result['state'] == 'REPAIR_REQUIRED'
        with pytest.raises(N5DataResolutionError, match='REVERIFICATION_REPAIR_REQUIRED'):
            service._finalizer(p['mission_id']).resolution.verified_binding(data_requirement_id=old['data_requirement_id'])
        assert truth.query('rc72_mission_node', node_type='N6_EXECUTABLE_READINESS')[0]['state'] == 'NOT_STARTED'
        server.allowed_data_refs.add(old['data_ref'])
        blocked = truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0]
        fresh = service.request(p['preparation_id'], data_requirement_id=old['data_requirement_id'],
                                binding_revision=blocked['artifact_version'])
        assert fresh['repair_id'] != request['repair_id']
        assert service.run(fresh['repair_id'])['state'] == 'VERIFIED'
        assert calls == ['DSH_PROTOCOL_PROCESS', 'DSH_PROTOCOL_PROCESS']
    finally:
        _close(server)


@pytest.mark.parametrize('tamper', ['data_ref', 'preconditions', 'claim', 'revision'])
def test_independent_output_cannot_substitute_scope_or_self_pass_n5(tmp_path, monkeypatch, tamper):
    truth, _, server, p, old, service, request, calls, _ = _service_setup(tmp_path, monkeypatch, tamper=tamper)
    try:
        with pytest.raises(ContractError, match='RESULT_SCOPE_INVALID'):
            service.run(request['repair_id'])
        current = truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0]
        assert current['verification_evidence_refs'] == old['verification_evidence_refs']
        assert current['verification_blocked_by_anchor'] == request['repair_id']
        assert truth.query('rc72_mission_node', node_type='N5_TEST_DATA')[0]['state'] == 'RUNNING'
        assert server.calls == [] and calls == ['DSH_PROTOCOL_PROCESS']
    finally:
        _close(server)


@pytest.mark.parametrize('event', ['RC7_EVIDENCE_UPSERTED', 'RC72_N5_DATA_BINDING_UPSERTED',
                                   'RC72_N5_EXISTING_DATA_REPAIR_UPSERTED'])
def test_partial_native_finalization_resumes_without_another_verifier_process(tmp_path, monkeypatch, event):
    truth, _, server, _, old, service, request, calls, _ = _service_setup(tmp_path, monkeypatch)
    try:
        append = truth.append_atomic
        crashed = []
        def interrupted(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            eligible = kind == event and (kind != 'RC72_N5_EXISTING_DATA_REPAIR_UPSERTED' or payload['state'] == 'OBSERVED')
            if eligible and not crashed:
                crashed.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', interrupted)
        with pytest.raises(KeyboardInterrupt):
            service.run(request['repair_id'])
        monkeypatch.setattr(truth, 'append_atomic', append)
        assert service.run(request['repair_id'])['state'] == 'VERIFIED'
        assert calls == ['DSH_PROTOCOL_PROCESS']
        current = truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0]
        assert current['artifact_version'] == old['artifact_version'] + 2
    finally:
        _close(server)


def test_saved_verifier_bytes_are_rechecked_on_completed_replay(tmp_path, monkeypatch):
    truth, _, server, _, _, service, request, _, _ = _service_setup(tmp_path, monkeypatch)
    try:
        service.run(request['repair_id'])
        row = truth.query('rc72_n5_existing_data_repair')[0]
        Path(row['raw_output_ref'][len('file://'):]).write_bytes(b'changed proof')
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError):
            service.run(request['repair_id'])
        assert truth.store.path.read_bytes() == before
    finally:
        _close(server)


def _accepted_data_repair(tmp_path, monkeypatch):
    values = _service_setup(tmp_path, monkeypatch)
    truth, prep, server, p, old, service, request, calls, cleanup = values
    try:
        service.run(request['repair_id'])
        n5 = N5DeliveryGateService(truth, release_id=p['release_id'], source_commit=p['source_commit']).complete(
            release_batch_id=p['release_batch_id'])
        delivery_id = n5['delivery']['delivery_id']
        repaired = service.boundary.diagnosis.record_accepted_repair(p['preparation_id'],
            repair_delivery_id=delivery_id, changed_refs=[old['data_ref']], reason='independent exact DataRef re-verification')
        return values, repaired
    except BaseException:
        _close(server)
        raise


def test_new_native_n5_gate_is_accepted_by_actual_n8_repair_intake(tmp_path, monkeypatch):
    values, repair = _accepted_data_repair(tmp_path, monkeypatch)
    truth, _, server, p, old, service, request, calls, cleanup = values
    try:
        assert repair['changed_refs'] == [old['data_ref']]
        assert repair['original_attempt_id'] == p['attempt_id']
        assert truth.query('rc72_impact_application')[0]['state'] == 'APPLIED'
        assert truth.query('rc72_mission_node', node_type='N6_EXECUTABLE_READINESS')[0]['state'] == 'STALE'
        before = truth.store.path.read_bytes()
        assert service.boundary.diagnosis.record_accepted_repair(p['preparation_id'],
            repair_delivery_id=repair['repair_delivery_id'], changed_refs=repair['changed_refs'], reason=repair['reason']) == repair
        assert truth.store.path.read_bytes() == before
        assert calls == ['DSH_PROTOCOL_PROCESS'] and cleanup == ['CLEANUP', 'VERIFY'] and not server.calls
    finally:
        _close(server)


def test_raw_handoff_recovery_does_not_rerun_a_lost_dispatch_response(tmp_path, monkeypatch):
    truth, _, server, _, _, service, request, calls, _ = _service_setup(tmp_path, monkeypatch)
    try:
        execute = service.launcher.execute
        def lost(*args, **kwargs):
            execute(*args, **kwargs)
            raise KeyboardInterrupt()
        monkeypatch.setattr(service.launcher, 'execute', lost)
        with pytest.raises(KeyboardInterrupt):
            service.run(request['repair_id'])
        assert service.run(request['repair_id'])['state'] == 'VERIFIED'
        assert calls == ['DSH_PROTOCOL_PROCESS']
    finally:
        _close(server)


def test_unknown_dispatch_effect_is_not_automatically_replayed(tmp_path, monkeypatch):
    truth, _, server, _, old, service, request, calls, _ = _service_setup(tmp_path, monkeypatch)
    try:
        def unavailable(*args, **kwargs):
            raise KeyboardInterrupt()
        monkeypatch.setattr(service.launcher, 'execute', unavailable)
        with pytest.raises(KeyboardInterrupt):
            service.run(request['repair_id'])
        # A moved/restored R1 may have no original marker files. The durable
        # dispatch state alone must still prevent another process/action.
        for claim in (service.launcher.state_root / 'existing-data-repair-claims').glob('*.claim'):
            claim.unlink()
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='DISPATCH_UNRESOLVED_NO_REPLAY'):
            service.run(request['repair_id'])
        assert truth.store.path.read_bytes() == before and not calls
        assert truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0].get('verification_blocked_by_anchor')
    finally:
        _close(server)


def test_unfinished_request_blocks_old_n5_proof_even_before_suspension_write(tmp_path, monkeypatch):
    truth, prep, server, p, diagnosis, boundary, cleanup = _setup(tmp_path, monkeypatch)
    try:
        boundary.open(p['preparation_id'])
        contract = truth.query('rc72_n6_executable_contract', contract_id=p['contract_id'])[0]
        old = next(row for row in truth.query('rc72_n5_data_binding') if row['data_ref'] == contract['data_refs'][0]['data_ref'])
        service = ExistingDataRepairService(boundary, launcher=_launcher(tmp_path, prep, server, []),
                                            allowed_tools=['query-exact-data-ref'])
        append = truth.append_atomic
        def interrupted(kind, payload, **kwargs):
            if kind == 'RC72_N5_DATA_BINDING_UPSERTED':
                raise KeyboardInterrupt()
            return append(kind, payload, **kwargs)
        monkeypatch.setattr(truth, 'append_atomic', interrupted)
        with pytest.raises(KeyboardInterrupt):
            service.request(p['preparation_id'], data_requirement_id=old['data_requirement_id'], binding_revision=old['artifact_version'])
        monkeypatch.setattr(truth, 'append_atomic', append)
        assert truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0] == old
        with pytest.raises(N5DataResolutionError, match='REVERIFICATION_REPAIR_REQUIRED'):
            service._finalizer(p['mission_id']).resolution.verified_binding(data_requirement_id=old['data_requirement_id'])
        server.allowed_data_refs.add(old['data_ref'])
        request = service.request(p['preparation_id'], data_requirement_id=old['data_requirement_id'], binding_revision=old['artifact_version'])
        assert service.run(request['repair_id'])['state'] == 'VERIFIED'
    finally:
        _close(server)


def test_data_metadata_change_during_verification_blocks_binding_revision(tmp_path, monkeypatch):
    truth, _, server, _, old, service, request, calls, _ = _service_setup(tmp_path, monkeypatch)
    try:
        runner = service.launcher.command_runner
        def changed(command, **kwargs):
            result = runner(command, **kwargs)
            resource = truth.query('rc72_data_resource', data_ref=old['data_ref'])[0]
            truth.append_atomic('RC72_DATA_RESOURCE_UPSERTED', dict(resource,
                metadata_ref='different-resource', artifact_version=resource['artifact_version'] + 1))
            return result
        monkeypatch.setattr(service.launcher, 'command_runner', changed)
        with pytest.raises(ContractError, match='SOURCE_CONTEXT_CHANGED'):
            service.run(request['repair_id'])
        current = truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0]
        assert current['verification_evidence_refs'] == old['verification_evidence_refs']
        assert current.get('verification_blocked_by_anchor') == request['repair_id']
        assert calls == ['DSH_PROTOCOL_PROCESS']
    finally:
        _close(server)


def test_request_requires_real_completed_compensation_boundary(tmp_path, monkeypatch):
    truth, prep, server, p, diagnosis, boundary, cleanup = _setup(tmp_path, monkeypatch)
    try:
        calls = []
        service = ExistingDataRepairService(boundary, launcher=_launcher(tmp_path, prep, server, calls),
                                            allowed_tools=['query-exact-data-ref'])
        binding = truth.query('rc72_n5_data_binding')[0]
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError):
            service.request(p['preparation_id'], data_requirement_id=binding['data_requirement_id'],
                            binding_revision=binding['artifact_version'])
        assert truth.store.path.read_bytes() == before and not calls and not cleanup
    finally:
        _close(server)


@pytest.mark.parametrize('tamper', ['missing_anchor', 'raw_bytes'])
def test_new_n5_gate_alone_cannot_certify_a_missing_or_changed_failed_ref_proof(tmp_path, monkeypatch, tamper):
    truth, _, server, p, old, service, request, _, _ = _service_setup(tmp_path, monkeypatch)
    try:
        service.run(request['repair_id'])
        if tamper == 'missing_anchor':
            binding = truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0]
            truth.append_atomic('RC72_N5_DATA_BINDING_UPSERTED', dict(binding,
                reverification_anchor_id='missing-anchor', artifact_version=binding['artifact_version'] + 1))
        else:
            proof = truth.query('rc72_n5_existing_data_repair')[0]
            Path(proof['raw_output_ref'][len('file://'):]).write_bytes(b'changed verification bytes')
            # The native N5 gate now rejects damaged bytes before repair intake.
            before = truth.store.path.read_bytes()
            with pytest.raises(ContractError, match='VERIFICATION_PROOF_BYTES_CHANGED'):
                N5DeliveryGateService(truth, release_id=p['release_id'], source_commit=p['source_commit']).complete(
                    release_batch_id=p['release_batch_id'])
            assert truth.store.path.read_bytes() == before
            assert truth.query('rc72_diagnosis_repair') == []
            return
        n5 = N5DeliveryGateService(truth, release_id=p['release_id'], source_commit=p['source_commit']).complete(
            release_batch_id=p['release_batch_id'])
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='N8_REPAIR_(FRESH_DATA_ANCHOR_REQUIRED|DATA_PROOF_BYTES_CHANGED)'):
            service.boundary.diagnosis.record_accepted_repair(p['preparation_id'],
                repair_delivery_id=n5['delivery']['delivery_id'], changed_refs=[old['data_ref']], reason='claimed repaired data')
        assert truth.store.path.read_bytes() == before
        assert truth.query('rc72_diagnosis_repair') == []
    finally:
        _close(server)


def test_actual_physical_preparation_then_distinct_verifier_renews_whole_n5(tmp_path, monkeypatch):
    truth, prep, server, p, old, service, request, calls, cleanup = _service_setup(tmp_path, monkeypatch, restored=False)
    try:
        assert old['data_ref'] not in server.allowed_data_refs
        preparer = _launcher(tmp_path, prep, server, calls)
        made = service.prepare(request['repair_id'], launcher=preparer, allowed_tools=['repair-exact-data-ref'])
        assert made['state'] == 'PREPARED'
        assert server.repair_calls == [old['data_ref']]
        assert truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0].get('verification_blocked_by_anchor')
        before = truth.store.path.read_bytes()
        assert service.prepare(request['repair_id'], launcher=preparer, allowed_tools=['repair-exact-data-ref']) == made
        assert truth.store.path.read_bytes() == before
        done = service.run(request['repair_id'])
        assert done['state'] == 'VERIFIED'
        row = truth.query('rc72_n5_existing_data_repair')[0]
        assert row['producer']['identity']['role'] == 'DATA_PREPARER'
        assert row['producer']['identity']['worker_id'] != row['identity']['worker_id']
        assert row['producer']['dsh_session_id'] != row['dsh_session_id']
        for member in (row, dict(row, **row['producer'])):
            task = truth.query('rc7_task', task_id=member['workitem_id'])[0]
            assert task['state'] == 'PASS' and task['node'] == 'TEST_DATA'
            assert member['lease']['scope_ref'] == 'task:%s/attempt:%s' % (member['workitem_id'], member['verification_attempt_id'])
            assert truth.query('rc7_evaluation', evaluation_id=task['evaluation_id'])[0]['evaluator_ref'] != member['identity']['worker_id']
            assert truth.query('rc7_artifact', artifact_id=task['output_artifact_refs'][0])[0]['content_ref'] == member['raw_output_ref']

        assert list(row['producer']['lease']['allowed_tools']) == ['repair-exact-data-ref']
        assert list(row['lease']['allowed_tools']) == ['query-exact-data-ref']
        accepted = N5DeliveryGateService(truth, release_id=p['release_id'], source_commit=p['source_commit']).complete(
            release_batch_id=p['release_batch_id'])
        repaired = service.boundary.diagnosis.record_accepted_repair(p['preparation_id'],
            repair_delivery_id=accepted['delivery']['delivery_id'], changed_refs=[old['data_ref']], reason='actual scoped data repair')
        assert repaired['original_attempt_id'] == p['attempt_id']
        assert server.repair_calls == [old['data_ref']] and calls == ['DSH_PROTOCOL_PROCESS', 'DSH_PROTOCOL_PROCESS']
        assert cleanup == ['CLEANUP', 'VERIFY'] and server.calls == []
    finally:
        _close(server)


def test_lost_producer_handoff_response_reuses_actual_repair_before_verifier(tmp_path, monkeypatch):
    _, prep, server, _, old, service, request, calls, _ = _service_setup(tmp_path, monkeypatch, restored=False)
    try:
        launcher = _launcher(tmp_path, prep, server, calls)
        execute = launcher.execute
        def interrupted(*args, **kwargs):
            execute(*args, **kwargs)
            raise KeyboardInterrupt()
        monkeypatch.setattr(launcher, 'execute', interrupted)
        with pytest.raises(KeyboardInterrupt):
            service.prepare(request['repair_id'], launcher=launcher, allowed_tools=['repair-exact-data-ref'])
        assert service.prepare(request['repair_id'], launcher=launcher, allowed_tools=['repair-exact-data-ref'])['state'] == 'PREPARED'
        assert service.run(request['repair_id'])['state'] == 'VERIFIED'
        assert server.repair_calls == [old['data_ref']] and len(calls) == 2
    finally:
        _close(server)


def test_unknown_producer_effects_block_both_repair_replay_and_verifier(tmp_path, monkeypatch):
    truth, prep, server, _, _, service, request, calls, _ = _service_setup(tmp_path, monkeypatch, restored=False)
    try:
        launcher = _launcher(tmp_path, prep, server, calls)
        def unavailable(*args, **kwargs):
            raise KeyboardInterrupt()
        monkeypatch.setattr(launcher, 'execute', unavailable)
        with pytest.raises(KeyboardInterrupt):
            service.prepare(request['repair_id'], launcher=launcher, allowed_tools=['repair-exact-data-ref'])
        for claim in (service.launcher.state_root / 'existing-data-repair-claims').glob('*.claim'):
            claim.unlink()
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='PRODUCER_UNRESOLVED'):
            service.run(request['repair_id'])
        with pytest.raises(ContractError, match='DISPATCH_UNRESOLVED_NO_REPLAY'):
            service.prepare(request['repair_id'], launcher=launcher, allowed_tools=['repair-exact-data-ref'])
        assert truth.store.path.read_bytes() == before and not calls
    finally:
        _close(server)


def test_producer_and_verifier_cannot_share_a_dsh_session(tmp_path, monkeypatch):
    truth, prep, server, _, old, service, request, calls, _ = _service_setup(tmp_path, monkeypatch, restored=False)
    try:
        launcher = _launcher(tmp_path, prep, server, calls)
        launcher.env['N5_ENGINEERING_SESSION'] = 'session-forbidden-shared-role-session'
        service.launcher.env['N5_ENGINEERING_SESSION'] = 'session-forbidden-shared-role-session'
        assert service.prepare(request['repair_id'], launcher=launcher, allowed_tools=['repair-exact-data-ref'])['state'] == 'PREPARED'
        with pytest.raises(ContractError, match='VERIFIER_SESSION_REUSED'):
            service.run(request['repair_id'])
        current = truth.query('rc72_n5_data_binding', binding_id=old['binding_id'])[0]
        assert current['verification_evidence_refs'] == old['verification_evidence_refs']
        assert current.get('verification_blocked_by_anchor')
    finally:
        _close(server)


def test_interrupted_independent_workitem_evaluation_resumes_without_duplicate_review(tmp_path, monkeypatch):
    truth, _, server, _, _, service, request, calls, _ = _service_setup(tmp_path, monkeypatch)
    try:
        append = truth.append_atomic
        interrupted = []
        def crash(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            if kind == 'RC7_EVALUATION_UPSERTED' and payload['evaluation_id'].startswith('N5REPAIREVAL-') and not interrupted:
                interrupted.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', crash)
        with pytest.raises(KeyboardInterrupt):
            service.run(request['repair_id'])
        monkeypatch.setattr(truth, 'append_atomic', append)
        assert service.run(request['repair_id'])['state'] == 'VERIFIED'
        events = [item for item in truth.store.iter_raw() if item['event_type'] == 'RC7_EVALUATION_UPSERTED'
                  and item['payload']['evaluation_id'].startswith('N5REPAIREVAL-')]
        assert len(events) == 1 and calls == ['DSH_PROTOCOL_PROCESS']
    finally:
        _close(server)


def test_changed_approved_design_bytes_prevent_physical_repair_before_tools(tmp_path, monkeypatch):
    truth, prep, server, _, _, service, request, calls, _ = _service_setup(tmp_path, monkeypatch, restored=False)
    try:
        artifact = truth.query('rc7_artifact', artifact_id=request['requirement']['source_n4_artifact_id'])[0]
        path = Path(artifact['content_ref'][len('file://'):])
        path.write_bytes(path.read_bytes() + b'\n')
        before = truth.store.path.read_bytes()
        with pytest.raises(RuntimeError, match='HASH_MISMATCH'):
            service.prepare(request['repair_id'], launcher=_launcher(tmp_path, prep, server, calls),
                            allowed_tools=['repair-exact-data-ref'])
        assert truth.store.path.read_bytes() == before and not calls
        assert not getattr(server, 'repair_calls', [])
    finally:
        _close(server)


def test_fresh_process_bootstrap_replays_repair_schema_and_workitems_without_service_import(tmp_path, monkeypatch):
    truth, _, server, _, _, service, request, _, _ = _service_setup(tmp_path, monkeypatch)
    try:
        service.run(request['repair_id'])
        script = """
import json, sys
import rc7_runtime
from rc6_runtime.truth import TruthRuntime
truth = TruthRuntime(sys.argv[1])
row = truth.query('rc72_n5_existing_data_repair')[0]
print(json.dumps(dict(state=row['state'], task=truth.query('rc7_task', task_id=row['workitem_id'])[0]['state'])))
"""
        process = subprocess.run([sys.executable, '-c', script, str(truth.store.path)],
            cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, timeout=30)
        assert process.returncode == 0, process.stderr
        assert json.loads(process.stdout) == dict(state='VERIFIED', task='PASS')
    finally:
        _close(server)
