"""Admit durable N7 observations into inherited Attempt/Assertion/Evidence.

This boundary performs no tool calls and grants no completion. Historical
receipts remain recordable after TTL expiry or an upstream STALE transition;
the original signed tuple and immutable contract are checked for audit only.
"""
from copy import deepcopy
from dataclasses import fields

from rc6_runtime.authority import TaskLease, WorkerIdentity
from .models import ContractError
from .oracle_runtime import DeterministicOracleRuntime
from .rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from .rc72_n6_completion import _digest
from .rc72_n7_execution_admission import _hash


class ExecutionEvidenceError(ContractError):
    pass


class ExecutionEvidenceService:
    def __init__(self, preparation):
        self.preparation = preparation
        self.truth = preparation.truth

    def _one(self, kind, **filters):
        return self.preparation._one(kind, **filters)

    def _ensure(self, kind, event, key, payload):
        rows = self.truth.query(kind, **{key: payload[key]})
        if rows:
            if len(rows) != 1 or any(rows[0].get(name) != value for name, value in payload.items()):
                raise ExecutionEvidenceError('N7_EVIDENCE_REPLAY_CONFLICT:' + kind)
            return rows[0]
        self.truth.append_atomic(event, payload)
        return self._one(kind, **{key: payload[key]})

    def observation(self, preparation_id):
        p = self._one('rc72_n7_execution_preparation', preparation_id=preparation_id)
        c = self._one('rc72_n6_executable_contract', contract_id=p['contract_id'])
        b = self._one('rc72_workitem_attempt_binding', binding_id=p['binding_id'])
        a = self._one('rc72_n7_execution_admission', admission_id=p['admission_id'])
        d = self._one('rc72_n7_tool_dispatch', preparation_id=preparation_id)
        identity = WorkerIdentity(**p['worker_identity'])
        lease = dict(p['task_lease'])
        for key in ('allowed_artifact_types', 'allowed_tools'):
            lease[key] = tuple(lease[key])
        lease = TaskLease(**lease)
        # Verify HMAC at original issuance time solely to admit historical
        # observations. This cannot restore an expired lease or authorize I/O.
        self.preparation.authority.validate_historical_lease(identity, lease)
        context = {key: deepcopy(p[key]) for key in ('workitem_id', 'attempt_id', 'worker_id',
                    'session_id', 'data_lease_ids', 'browser_lease_ids')}
        etu = self._one('rc72_etu', etu_id=p['etu_id'])
        expected_id = 'N7CALL-' + _hash([preparation_id, c['contract_sha256'], c['tool_route']['tool']])[:24]
        if (d['dispatch_id'] != expected_id or identity.phase != 'N7_EXECUTION'
                or identity.role != etu['test_level'] + '_EXECUTE' or identity.layer != etu['test_level']
                or identity.generation != p['attempt_generation'] - 1
                or b.get('mission_id') != p['mission_id']
                or p['release_id'] != self.preparation.release_id or p['source_commit'] != self.preparation.source_commit
                or c['contract_sha256'] != _digest(c) or d['contract_sha256'] != c['contract_sha256']
                or d['request_sha256'] != _hash({'contract': c, 'context': context})
                or identity.worker_id != p['worker_id'] or identity.session_id != p['session_id']
                or lease.worker_id != p['worker_id'] or lease.allowed_artifact_types
                or lease.scope_ref != 'task:%s/attempt:%s' % (p['workitem_id'], p['attempt_id'])
                or d['tool'] != c['tool_route']['tool'] or d['tool'] not in lease.allowed_tools
                or b.get('task_lease_ref') != lease.lease_id or b.get('session_id') != p['session_id']
                or b.get('case_id') != p['case_id'] or b.get('etu_id') != p['etu_id']
                or b.get('resource_lease_refs') != p['data_lease_ids'] + p['browser_lease_ids']):
            raise ExecutionEvidenceError('N7_OBSERVATION_BINDING_MISMATCH')
        for key in ('release_id', 'source_commit', 'contract_id'):
            if c.get(key) != p.get(key) or d.get(key) != p.get(key) or a.get(key) != p.get(key):
                raise ExecutionEvidenceError('N7_OBSERVATION_SOURCE_MISMATCH')
        for key in ('mission_id', 'release_batch_id', 'case_id'):
            if c.get(key) != p.get(key) or a.get(key) != p.get(key):
                raise ExecutionEvidenceError('N7_OBSERVATION_CASE_MISMATCH')
        for key in ('attempt_id', 'worker_id', 'workitem_id'):
            if b.get(key) != p.get(key) or d.get(key) != p.get(key):
                raise ExecutionEvidenceError('N7_OBSERVATION_OWNER_MISMATCH')
        if d.get('authorization_protocol') is not None:
            from .rc72_lease_renewal import verify_execution_authorization
            if d['authorization_protocol'] != 'TEMPORAL_LEASE_V1':
                raise ExecutionEvidenceError('N7_EXECUTION_AUTHORIZATION_PROTOCOL_INVALID')
            verify_execution_authorization(self.preparation, p, d.get('execution_authorization'))
        oracle = None
        if d['state'] == 'RETURNED':
            if d['receipt_sha256'] != _hash(d['raw_result']):
                raise ExecutionEvidenceError('N7_RECEIPT_HASH_MISMATCH')
            oracle = DeterministicOracleRuntime().evaluate({'checks': deepcopy(c['oracles'])},
                deepcopy(d['raw_result']), {'contract_sha256': c['contract_sha256'],
                    'dispatch_id': d['dispatch_id'], 'attempt_id': p['attempt_id'],
                    'receipt_sha256': d['receipt_sha256']})
            if 'oracle_result' in d and d['oracle_result'] != oracle:
                raise ExecutionEvidenceError('N7_ORACLE_REPLAY_CONFLICT')
        return p, c, b, a, d, oracle

    def record(self, preparation_id):
        p, c, b, admission, dispatch, oracle = self.observation(preparation_id)
        # Use the admitted N4 delivery revision, never an invented Case version.
        parent = next(ref for ref in admission['upstream_refs'] if ref['node_type'] == 'N4_TEST_DESIGN')
        delivery = self._one('rc72_node_delivery', delivery_id=parent['delivery_id'])
        if delivery['mission_id'] != p['mission_id']:
            raise ExecutionEvidenceError('N7_CASE_REVISION_MISSION_MISMATCH')
        evidence_id = 'N7EV-' + _hash([dispatch['dispatch_id'], dispatch['state'],
            dispatch.get('receipt_sha256'), oracle])[:24]
        ref = 'r1://artifact/' + dispatch['dispatch_id']
        self._ensure('rc7_evidence', 'RC7_EVIDENCE_UPSERTED', 'evidence_id', dict(
            evidence_id=evidence_id, release_id=p['release_id'], mission_id=p['mission_id'],
            kind='N7_EXECUTION_OBSERVATION', source_ref=ref, content_ref=ref,
            content_hash=_hash({k: v for k, v in dispatch.items() if k not in {'artifact_version', 'artifact_type', 'oracle_result'}}), subject_refs=[p['workitem_id'], p['attempt_id'], p['case_id']],
            artifact_version=1))
        self._ensure('evidence', 'EVIDENCE_UPSERTED', 'id', dict(
            id=evidence_id, release_id=p['release_id'], kind='N7_EXECUTION_OBSERVATION',
            ref=ref, source_artifact_ref=dispatch['dispatch_id'], requirement_id=c['requirement_id'],
            tc_id=p['case_id'], attempt_id=p['attempt_id'], artifact_version=1))
        check_refs = sorted(row['evidence_id'] for row in self.truth.query('rc7_evidence', mission_id=p['mission_id'])
            if row.get('kind') in {'N7_FORMAL_PRECONDITION', 'N7_FORMAL_DATA_RECHECK', 'N7_FORMAL_TOOL_PROBE', 'N7_FORMAL_TOOL_UNAVAILABLE'}
            and p['attempt_id'] in row.get('subject_refs', []))
        observation_refs = [evidence_id] + check_refs
        assertion_id = None
        if oracle is not None:
            assertion_id = 'N7ASSERT-' + _hash([p['attempt_id'], oracle])[:24]
            self._ensure('assertion', 'ASSERTION_UPSERTED', 'id', dict(
                id=assertion_id, release_id=p['release_id'], attempt_id=p['attempt_id'], tc_id=p['case_id'],
                oracle_ref=oracle['assertion_ref'], passed=oracle['passed'], details=deepcopy(oracle['details']),
                evidence_refs=observation_refs, artifact_version=1))
        from .rc72_formal_runner import verified_formal_receipt
        formal = verified_formal_receipt(self.preparation, p, c, dispatch.get('raw_result') or {})
        # An adapter exception after the durable external-I/O intent may have
        # committed remotely even when no returned receipt exists. Its R1
        # UNKNOWN status must remain incident evidence, not an inferred FAIL
        # or an Oracle comparison against a missing result.
        reason = ('TOOL_SIDE_EFFECTS_UNKNOWN' if dispatch['state'] in {'IN_FLIGHT', 'UNKNOWN'} else
                  'TOOL_INVOCATION_FAILED' if dispatch['state'] == 'FAILED' else
                  'RUNNER_PROCESS_FAILED' if formal and formal['runner_result']['exit_code'] != 0 else
                  'RUNNER_TOOL_EVIDENCE_MISSING' if formal and not formal['required_tool_observed'] else
                  'ORACLE_FAILED' if not oracle['passed'] else 'CLEANUP_AND_EVIDENCE_CLOSURE_REQUIRED')
        payload = dict(attempt_id=p['attempt_id'], release_id=p['release_id'],
            requirement_id=c['requirement_id'], tc_id=p['case_id'], case_version=formal['frozen_case']['case_version'] if formal else delivery['version'],
            case_version_source='FROZEN_CASE_FINGERPRINT' if formal else 'N4_DELIVERY_VERSION', case_revision_ref=delivery['delivery_id'],
            target_id=formal['target_identity']['target_id'] if formal else c['environment']['source_ref'],
            target_identity_scope='FULL_TARGET_IDENTITY' if formal else 'N1_ENVIRONMENT_SOURCE',
            layer=self._one('rc72_etu', etu_id=p['etu_id'])['test_level'], status='BLOCKED',
            worker_id=p['worker_id'], lease_id=p['task_lease']['lease_id'], mission_id=p['mission_id'],
            parent_attempt_id=b.get('parent_attempt_id'), workitem_id=p['workitem_id'], contract_id=c['contract_id'], contract_sha256=c['contract_sha256'],
            tool_call_refs=[dispatch['dispatch_id']], evidence_refs=observation_refs,
            formal_runner_receipt_ref=formal['runner_receipt_id'] if formal else None,
            actual_result=deepcopy(dispatch.get('raw_result')), assertion_ref=assertion_id,
            assertion_passed=oracle['passed'] if oracle else None, reason=reason, artifact_version=1)
        attempt = self._ensure('execution_attempt', 'EXECUTION_ATTEMPT_UPSERTED', 'attempt_id', payload)
        if b['state'] in {'PREPARED', 'RUNNING'}:
            entity = WorkItemAttemptBinding(**{field.name: b[field.name]
                for field in fields(WorkItemAttemptBinding) if field.name in b})
            entity.state = WorkItemAttemptState.EVIDENCE_READY
            self.preparation.lifecycle.repository.persist(entity, artifact_version=b['artifact_version'] + 1)
        return attempt

    def begin_diagnosis(self, preparation_id):
        from .rc72_diagnosis_orchestration import DiagnosisOrchestrator
        from .rc72_state_machine import RC72StateMachine
        attempt = self.record(preparation_id)
        if attempt['reason'] == 'CLEANUP_AND_EVIDENCE_CLOSURE_REQUIRED':
            raise ExecutionEvidenceError('N7_FAILURE_REQUIRED_FOR_DIAGNOSIS')
        p = self._one('rc72_n7_execution_preparation', preparation_id=preparation_id)
        runtime = RC72StateMachine(self.truth, release_id=p['release_id'])
        return DiagnosisOrchestrator(self.truth, release_id=p['release_id'],
            state_machine=runtime, worker_lifecycle=self.preparation.lifecycle).begin_failure_diagnosis(
                mission_id=p['mission_id'], team_id='TEAM-' + p['mission_id'],
                source_binding_id=p['binding_id'], failure_evidence_refs=attempt['evidence_refs'],
                executable_contract_refs=[p['contract_id']], reason=attempt['reason'])
