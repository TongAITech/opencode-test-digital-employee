"""Actual MCP entry refuses expired/revoked/foreign-owner calls before I/O."""
import pytest

from rc6_runtime.agent_runtime import AgentRuntimeError
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_native_n5_tool_gate import NativeN5ToolGate, N5ToolHandler
from test_rc72_native_n5_tool_gate import _fenced_setup, READ, WRITE
from test_rc72_n7_member_drain import _close


@pytest.mark.parametrize('change', ['expired', 'revoked', 'owner'])
def test_live_deadline_revocation_and_current_owner_are_checked_before_handler(tmp_path, monkeypatch, change):
    def before(service, gate, truth, prep, server):
        if change == 'expired':
            import rc7_runtime.rc72_native_n5_tool_gate as module
            monkeypatch.setattr(module.time, 'time', lambda: gate.assignment.lease.expires_at)
        elif change == 'revoked':
            prep.authority.revoke_worker_lease(gate.assignment.lease.lease_id)
        else:
            task = prep._one('rc7_task', task_id=gate.scope['workitem_id'])
            task.update(lease_owner='OTHER-WORKER', artifact_version=task['artifact_version'] + 1)
            truth.append_atomic('RC7_TASK_UPSERTED', task)
    truth, prep, server, p, service, request, producer, effects, captured = _fenced_setup(
        tmp_path, monkeypatch, before_worker=before)
    try:
        with pytest.raises((AgentRuntimeError, ContractError)):
            service.run(request['repair_id'])
        assert not effects and not truth.query('rc72_native_tool_call')
        assert truth.query('rc72_native_tool_gate')[0]['state'] == 'CLOSED'
        assert not truth.query('agent_runtime_event', event_name='HANDOFF_RETURNED',
                               assignment_id=truth.query('rc72_n5_existing_data_repair')[0]['assignment_id'])
    finally:
        _close(server)


def test_effect_observed_after_revocation_stays_unknown_and_old_dispatch_cannot_replay(tmp_path, monkeypatch):
    saved = []
    def before(service, gate, truth, prep, server):
        saved.append((gate.assignment, tuple(gate.handlers.values())))
        original = gate.handlers[READ].execute
        def revoke_after_effect(arguments):
            result = original(arguments)
            prep.authority.revoke_worker_lease(gate.assignment.lease.lease_id)
            return result
        gate.handlers[READ] = N5ToolHandler(READ, 'READ', revoke_after_effect)
    truth, prep, server, p, service, request, producer, effects, captured = _fenced_setup(
        tmp_path, monkeypatch, before_worker=before)
    try:
        with pytest.raises((AgentRuntimeError, ContractError)):
            service.run(request['repair_id'])
        assert len(effects) == 1
        call = truth.query('rc72_native_tool_call')[0]
        assert call['state'] == 'UNKNOWN'
        before_bytes = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='UNRESOLVED_NO_REPLAY'):
            service.run(request['repair_id'])
        with pytest.raises(ContractError, match='EXISTING_INVOCATION_RECOVERY_REQUIRED'):
            NativeN5ToolGate(service, saved[0][0], saved[0][1]).open()
        assert truth.store.path.read_bytes() == before_bytes and len(effects) == 1
        binding = prep._one('rc72_n5_data_binding', binding_id=request['original_binding']['binding_id'])
        assert binding['verification_blocked_by_anchor'] == request['repair_id']
    finally:
        _close(server)


def test_transport_replay_and_lost_fsynced_return_do_not_repeat_physical_preparation(tmp_path, monkeypatch):
    truth, prep, server, p, service, request, producer, effects, captured = _fenced_setup(tmp_path, monkeypatch, change='replay')
    try:
        producer.env['NATIVE_ENGINEERING_CHANGE'] = 'replay'
        append, hits = truth.append_atomic, []
        def lost(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            if (kind == 'RC72_NATIVE_TOOL_CALL_UPSERTED' and payload['state'] == 'RETURNED'
                    and payload['tool'] == WRITE and not hits):
                hits.append(True)
                raise OSError('lost journal response after fsync')
            return result
        monkeypatch.setattr(truth, 'append_atomic', lost)
        assert service.prepare(request['repair_id'], launcher=producer, allowed_tools=[WRITE])['state'] == 'PREPARED'
        assert service.run(request['repair_id'])['state'] == 'VERIFIED'
        assert hits and [mode for mode, ref in effects] == ['WRITE', 'READ']
        assert len(server.repair_calls) == 1
        assert len(truth.query('rc72_native_tool_call')) == 2
        assert all(row['state'] == 'RETURNED' for row in truth.query('rc72_native_tool_call'))
    finally:
        _close(server)


def test_inflight_and_unknown_effects_hold_data_custody_across_missions(tmp_path, monkeypatch):
    from rc7_runtime.rc72_data_resources import DataLeaseManager, DataAccessMode
    from test_rc72_resource_process_exclusion import _second_mission
    blocked = []
    def reserve(truth, ref):
        return DataLeaseManager(truth, release_id='RC7.2').acquire(
            data_ref=ref, mission_id='M-SECOND', workitem_id='WI-SECOND',
            attempt_id='ATT-SECOND', worker_id='WORKER-SECOND',
            mode=DataAccessMode.EXCLUSIVE_WRITE, ttl_seconds=300,
            cleanup_policy='release reservation')
    def before(service, gate, truth, prep, server):
        # Independent manually seeded mission; never borrow the first mission's snapshot.
        _second_mission(truth, planning_snapshot_ref='manual-planning://second-mission')
        original = gate.handlers[READ].execute
        def observe_then_revoke(arguments):
            with pytest.raises(Exception, match='NATIVE_TOOL_CUSTODY_HELD'):
                reserve(truth, arguments['data_ref'])
            blocked.append('IN_FLIGHT')
            result = original(arguments)
            prep.authority.revoke_worker_lease(gate.assignment.lease.lease_id)
            return result
        gate.handlers[READ] = N5ToolHandler(READ, 'READ', observe_then_revoke)
    truth, prep, server, p, service, request, producer, effects, captured = _fenced_setup(
        tmp_path, monkeypatch, before_worker=before)
    try:
        with pytest.raises((AgentRuntimeError, ContractError)) as failure:
            service.run(request['repair_id'])
        assert blocked == ['IN_FLIGHT'] and len(effects) == 1, (str(failure.value), truth.query('rc72_native_tool_call'))
        call = truth.query('rc72_native_tool_call')[0]
        assert call['state'] == 'UNKNOWN' and call['access_mode'] == 'READ'
        assert truth.query('rc72_native_tool_gate')[0]['state'] == 'CLOSED'
        with pytest.raises(Exception, match='NATIVE_TOOL_CUSTODY_HELD'):
            reserve(truth, call['data_ref'])
    finally:
        _close(server)
