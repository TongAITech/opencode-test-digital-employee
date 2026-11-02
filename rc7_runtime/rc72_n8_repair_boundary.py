"""Accepted N8 data diagnosis -> scoped compensation -> locked repair boundary.

Fresh cleanup authority never restores the original business execution lease.
No resource is released before frozen cleanup and machine verification succeed.
"""
from copy import deepcopy
from dataclasses import asdict, fields
import hmac
import time

from rc6_runtime import contracts, truth as registry
from rc6_runtime.authority import TaskLease, WorkerIdentity
from .models import ContractError, TaskStatus
from .state_machine import transition_task
from .closed_loop_control import ClosedLoopControlPlane
from .rc72_domain import AutonomousMissionNode, MissionNodeState, MissionNodeRecord
from .rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from .rc72_n7_execution_admission import _hash
from .rc72_n7_cleanup import ExecutionCleanupService, frozen_cleanup_spec
from .rc72_n8_execution_diagnosis import ExecutionDiagnosisService, _CRITERIA as N8_CRITERIA

_KIND = 'rc72_n8_repair_boundary'
_EVENT = 'RC72_N8_REPAIR_BOUNDARY_UPSERTED'


def _validate(payload):
    row = deepcopy(payload)
    for key in ('boundary_id', 'release_id', 'source_commit', 'preparation_id', 'diagnosis_id', 'contract_sha256', 'signature'):
        contracts._require_str(row, key)
    if row.get('purpose') != 'N8_SCOPED_CLEANUP_AND_REPAIR' or row.get('state') not in {'CLEANUP_AUTHORIZED', 'REPAIR_OPEN'}:
        raise contracts.DomainValidationError('N8_REPAIR_BOUNDARY_STATE_INVALID')
    if any(key in row for key in ('field_verified', 'bank_final', 'case_pass', 'delivery_authorized')):
        raise contracts.DomainValidationError('N8_REPAIR_BOUNDARY_COMPLETION_CLAIM_FORBIDDEN')
    row.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(row))
    return row


def install_rc72_n8_repair_boundary_overlay():
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'boundary_id')
    registry.BUCKETS[_KIND] = 'rc72_n8_repair_boundaries'
    registry.IDENTITY_FIELDS[_KIND] = 'boundary_id'


class RepairBoundaryService:
    def __init__(self, diagnosis, *, cleanup_adapters, ttl_seconds=300):
        install_rc72_n8_repair_boundary_overlay()
        if not isinstance(diagnosis, ExecutionDiagnosisService):
            raise ContractError('N8_ACCEPTED_PROCESS_DIAGNOSIS_SERVICE_REQUIRED')
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 3600:
            raise ContractError('N8_CLEANUP_TTL_INVALID')
        self.diagnosis, self.preparation, self.truth = diagnosis, diagnosis.preparation, diagnosis.truth
        self.runtime, self.ttl = diagnosis.runtime, ttl_seconds
        self.cleanup = ExecutionCleanupService(self.preparation, adapters=cleanup_adapters, recovery_authorizer=self)

    def _one(self, kind, **filters):
        return self.preparation._one(kind, **filters)

    def _signed(self, row):
        value = {key: item for key, item in row.items() if key not in {'signature', 'artifact_version', 'artifact_type'}}
        if not hmac.compare_digest(row['signature'], self.preparation.authority._sign(value)):
            raise ContractError('N8_REPAIR_BOUNDARY_SIGNATURE_INVALID')
        return row

    def _persist(self, row):
        row = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type'}}
        value = {key: item for key, item in row.items() if key != 'artifact_version'}
        row['signature'] = self.preparation.authority._sign(value)
        self.truth.append_atomic(_EVENT, row)
        return self._one(_KIND, boundary_id=row['boundary_id'])

    def _context(self, preparation_id, *, opened=False):
        p, facts = self.diagnosis._facts(preparation_id)
        case = self._one('rc72_diagnosis_case', source_binding_id=p['binding_id'])
        receipt = self.diagnosis._verify(self._one('rc72_n8_process_diagnosis', diagnosis_id=case['diagnosis_id']))
        outcome = self._one('rc72_diagnosis_outcome', diagnosis_id=case['diagnosis_id'])
        if (receipt['input_sha256'] != _hash(facts) or receipt['result']['failure_class'] != 'TEST_DATA_GAP'
                or outcome['failure_class'] != 'TEST_DATA_GAP' or outcome['action'] != 'SEMANTIC_BACK_EDGE'
                or outcome['responsible_node'] != 'N5_TEST_DATA'):
            raise ContractError('N8_ACCEPTED_DATA_REPAIR_REQUIRED')
        n8 = self.runtime.node_by_type(p['mission_id'], AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
        gates = [row for row in self.truth.query('rc72_node_gate', delivery_id=receipt['delivery_id'])
                 if row['gate_id'] in n8['gate_refs']]
        delivery = self._one('rc72_node_delivery', delivery_id=receipt['delivery_id'])
        if (n8['state'] != 'PASS' or n8['active_delivery_version'] != delivery['version']
                or delivery['delivery_id'] not in n8['delivery_refs']
                or len(gates) != 1 or gates[0]['decision'] != 'PASS'
                or gates[0]['reviewer_worker_id'] != receipt['reviewer_worker_id']
                or gates[0]['reviewer_session_id'] != receipt['reviewer_session_id']
                or gates[0]['criteria'] != N8_CRITERIA or gates[0]['passed'] != N8_CRITERIA or gates[0]['failed']):
            raise ContractError('N8_ACCEPTED_REVIEW_GATE_REQUIRED')
        # No cleanup can be sent to a changed environment or changed business source.
        admission = self._one('rc72_n7_execution_admission', admission_id=p['admission_id'])
        for parent in admission['upstream_refs']:
            if parent['node_type'] == 'N6_EXECUTABLE_READINESS' and not opened:
                node = self._one('rc72_mission_node', mission_id=p['mission_id'], node_type=parent['node_type'])
                delivery = self._one('rc72_node_delivery', delivery_id=parent['delivery_id'])
                gate = self._one('rc72_node_gate', gate_id=parent['gate_id'])
                if _hash([node, delivery, gate]) != parent['digest']:
                    raise ContractError('N8_REPAIR_ORIGINAL_N6_SCOPE_CHANGED')
            if parent['node_type'] in {'N5_TEST_DATA', 'N6_EXECUTABLE_READINESS'}:
                continue
            node = self._one('rc72_mission_node', mission_id=p['mission_id'], node_type=parent['node_type'])
            delivery = self._one('rc72_node_delivery', delivery_id=parent['delivery_id'])
            gate = self._one('rc72_node_gate', gate_id=parent['gate_id'])
            if (node['state'] != 'PASS' or delivery['version'] != node['active_delivery_version']
                    or parent['delivery_id'] not in node['delivery_refs'] or _hash([node, delivery, gate]) != parent['digest']):
                raise ContractError('N8_CLEANUP_UPSTREAM_SOURCE_CHANGED')
        for other in self.truth.query('rc72_n7_execution_preparation', mission_id=p['mission_id']):
            if other['preparation_id'] != preparation_id and other['status'] == 'PREPARED':
                raise ContractError('N8_REPAIR_OTHER_EXECUTION_MUST_DRAIN')
        for kind in ('rc72_data_lease', 'rc72_browser_lease'):
            if any(row['state'] in {'ACTIVE', 'EXPIRED'} and row['attempt_id'] != p['attempt_id']
                   for row in self.truth.query(kind, mission_id=p['mission_id'])):
                raise ContractError('N8_REPAIR_OTHER_RESOURCE_OWNER_MUST_DRAIN')
        n5 = self.runtime.node_by_type(p['mission_id'], AutonomousMissionNode.N5_TEST_DATA)
        if n5['state'] not in ({'NEEDS_REVISION', 'RUNNING'} if opened else {'NEEDS_REVISION'}):
            raise ContractError('N8_REPAIR_N5_STATE_INVALID')
        for kind in (AutonomousMissionNode.N9_DEFECT, AutonomousMissionNode.N10_RELEASE_CONVERGENCE):
            if self.runtime.node_by_type(p['mission_id'], kind)['state'] != 'NOT_STARTED':
                raise ContractError('N8_REPAIR_DOWNSTREAM_RECONCILIATION_REQUIRED')
        c = self._one('rc72_n6_executable_contract', contract_id=p['contract_id'])
        data_refs = {row['data_ref'] for row in c['data_refs']}
        browser_instances = {self._one('rc72_browser_lease', browser_lease_id=value)['browser_instance_id'] for value in p['browser_lease_ids']}
        for kind, key, values in (('rc72_data_lease', 'data_ref', data_refs),
                                  ('rc72_browser_lease', 'browser_instance_id', browser_instances)):
            if any(row['state'] in {'ACTIVE', 'EXPIRED'} and row[key] in values and row['attempt_id'] != p['attempt_id']
                   for row in self.truth.query(kind)):
                raise ContractError('N8_REPAIR_SHARED_RESOURCE_OWNER_MUST_DRAIN')
        return p, c, case

    def _check_old_node_versions(self, p, grant):
        for kind, original in grant['original_nodes'].items():
            node = self._one('rc72_mission_node', mission_id=p['mission_id'], node_type=kind)
            if node['delivery_refs'] != original['delivery_refs'] or node['gate_refs'] != original['gate_refs']:
                raise ContractError('N8_REPAIR_NEWER_DOWNSTREAM_DELIVERY_CONFLICT')
            if node['active_delivery_version'] != original['active_delivery_version'] and not (
                    node['state'] == 'NOT_STARTED' and node['active_delivery_version'] is None):
                raise ContractError('N8_REPAIR_DOWNSTREAM_VERSION_CONFLICT')

    def authorize_cleanup(self, p, c, phase, tool):
        grant = self._signed(self._one(_KIND, preparation_id=p['preparation_id']))
        if grant['state'] != 'CLEANUP_AUTHORIZED' or phase not in {'CLEANUP', 'VERIFY'} or grant['contract_sha256'] != c['contract_sha256']:
            raise ContractError('N8_CLEANUP_SCOPE_INVALID')
        self._context(p['preparation_id'])
        self._check_old_node_versions(p, grant)
        # The durable signed boundary suspends business authority before any
        # compensation I/O, including when compensation later fails.
        self.preparation.authority.revoke_worker_lease(p['task_lease']['lease_id'])
        for kind, key, ids in (('rc72_data_lease', 'data_lease_id', p['data_lease_ids']),
                               ('rc72_browser_lease', 'browser_lease_id', p['browser_lease_ids'])):
            for value in ids:
                resource = self._one(kind, **{key: value})
                if resource['state'] not in {'ACTIVE', 'EXPIRED'} or any(resource[k] != p[k] for k in ('mission_id', 'workitem_id', 'attempt_id', 'worker_id')):
                    raise ContractError('N8_CLEANUP_RESOURCE_CUSTODY_CHANGED')
        for value in p['data_lease_ids']:
            resource = self._one('rc72_data_lease', data_lease_id=value)
            if resource['state'] == 'ACTIVE' and int(resource['expires_at']) >= time.time():
                self.preparation.data.assert_usable(data_lease_id=value, mission_id=p['mission_id'],
                    workitem_id=p['workitem_id'], attempt_id=p['attempt_id'], worker_id=p['worker_id'], data_ref=resource['data_ref'])
        for value in p['browser_lease_ids']:
            resource = self._one('rc72_browser_lease', browser_lease_id=value)
            plan = self._one('rc72_n7_execution_plan', plan_id=p['plan_id'])
            snapshot = self._one('rc72_decomposition_snapshot', snapshot_id=plan['snapshot_id'])
            planned = next(row for row in snapshot['planning_cases'] if row['case_id'] == p['case_id'])
            instance = self._one('rc72_browser_instance', browser_instance_id=resource['browser_instance_id'])
            if instance['state'] != 'READY' or instance.get('auth_asset_ref') != planned['browser_context']:
                raise ContractError('N8_CLEANUP_BROWSER_CONTEXT_CHANGED')
            if resource['state'] == 'ACTIVE' and int(resource['expires_at']) >= time.time():
                self.preparation.browser.assert_usable(browser_lease_id=value, mission_id=p['mission_id'],
                    workitem_id=p['workitem_id'], attempt_id=p['attempt_id'], worker_id=p['worker_id'],
                    access_mode=resource['access_mode'], auth_asset_ref=planned['browser_context'])
        identity = WorkerIdentity(**grant['cleanup_identity'])
        session = self._one('rc72_worker_session', session_id=identity.session_id)
        if session['state'] != 'ACTIVE' or session['worker_id'] != identity.worker_id:
            raise ContractError('N8_CLEANUP_ACTOR_NOT_ACTIVE')
        lease = dict(grant['cleanup_lease'])
        for key in ('allowed_artifact_types', 'allowed_tools'):
            lease[key] = tuple(lease[key])
        lease = TaskLease(**lease)
        self.preparation.authority.restore_signed_worker_lease(identity, lease,
            expected_scope='cleanup:%s/%s' % (p['preparation_id'], c['contract_sha256']))
        self.preparation.authority.authorize_tool(identity.worker_id, lease.lease_id, tool)
        if identity.phase != 'N8_RECOVERY_CLEANUP' or lease.allowed_artifact_types:
            raise ContractError('N8_CLEANUP_AUTHORITY_INVALID')
        return grant['boundary_id']

    def _audit_cleanup_proof(self, grant):
        from .oracle_runtime import DeterministicOracleRuntime
        p, c, _, _, _, _ = self.diagnosis.evidence.observation(grant['preparation_id'])
        if grant['contract_sha256'] != c['contract_sha256']:
            raise ContractError('N8_COMPLETED_CLEANUP_SCOPE_CHANGED')
        cleanup, verification = frozen_cleanup_spec(c)
        # These calls must exist: this is read-only replay, never a new dispatch.
        calls = self.truth.query('rc72_n7_cleanup_call', preparation_id=p['preparation_id'])
        if {row['phase'] for row in calls} != {'CLEANUP', 'VERIFY'} or len(calls) != 2:
            raise ContractError('N8_COMPLETED_CLEANUP_RECEIPTS_MISSING')
        action = self.cleanup._call(p, c, 'CLEANUP', cleanup['tool'])
        observed = self.cleanup._call(p, c, 'VERIFY', verification['tool'], action['call_id'])
        actual = observed.get('raw_result', {}).get('data_results', {})
        refs = sorted(row['data_ref'] for row in c['data_refs'])
        if action['state'] != 'RETURNED' or observed['state'] != 'RETURNED' or set(actual) != set(refs):
            raise ContractError('N8_COMPLETED_CLEANUP_PROOF_CHANGED')
        for row in (action, observed):
            if row['receipt_sha256'] != _hash(row['raw_result']):
                raise ContractError('N8_COMPLETED_CLEANUP_PROOF_CHANGED')
        results = {ref: DeterministicOracleRuntime().evaluate(verification, actual[ref],
            dict(attempt_id=p['attempt_id'], data_ref=ref, cleanup_call_ref=action['call_id'],
                 verification_call_ref=observed['call_id'], receipt_sha256=observed['receipt_sha256'])) for ref in refs}
        expected_id = 'N7CLEANEV-' + _hash([p['attempt_id'], action['receipt_sha256'], observed['receipt_sha256'], results])[:24]
        evidence = self._one('rc7_evidence', evidence_id=grant.get('cleanup_evidence_ref') or expected_id)
        if (expected_id != (grant.get('cleanup_evidence_ref') or expected_id) or not all(row['passed'] for row in results.values())
                or evidence['content_hash'] != _hash(results) or evidence['data_assertions'] != results
                or evidence.get('kind') != 'N7_CLEANUP_DATA_REVERIFIED'
                or evidence.get('subject_refs') != [p['workitem_id'], p['attempt_id']] + refs
                or evidence.get('cleanup_call_ref') != action['call_id']
                or evidence.get('verification_call_ref') != observed['call_id']
                or evidence.get('source_ref') != 'r1://artifact/' + observed['call_id']
                or evidence.get('content_ref') != 'r1://artifact/' + observed['call_id']):
            raise ContractError('N8_COMPLETED_CLEANUP_EVIDENCE_CHANGED')
        canonical = self._one('evidence', id=expected_id)
        if (canonical.get('attempt_id') != p['attempt_id'] or canonical.get('tc_id') != p['case_id']
                or canonical.get('kind') != 'N7_CLEANUP_DATA_REVERIFIED'
                or canonical.get('release_id') != p['release_id']
                or canonical.get('requirement_id') != c['requirement_id']
                or canonical.get('source_artifact_ref') != observed['call_id']
                or evidence.get('mission_id') != p['mission_id']):
            raise ContractError('N8_COMPLETED_CLEANUP_CANONICAL_EVIDENCE_CHANGED')
        return p, c, expected_id

    def _audit_completed(self, grant):
        p, c, expected_id = self._audit_cleanup_proof(grant)
        expected_data = dict(zip(p['data_lease_ids'], sorted(c['data_refs'], key=lambda row: row['data_ref'])))
        for kind, key, ids in (('rc72_data_lease', 'data_lease_id', p['data_lease_ids']),
                               ('rc72_browser_lease', 'browser_lease_id', p['browser_lease_ids'])):
            for value in ids:
                resource = self._one(kind, **{key: value})
                if (resource['state'] != 'RELEASED'
                        or (kind == 'rc72_data_lease' and resource['data_ref'] != expected_data[value]['data_ref']) or resource.get('release_reason') != 'verified N7 cleanup evidence ' + expected_id
                        or any(resource[k] != p[k] for k in ('mission_id', 'workitem_id', 'attempt_id', 'worker_id'))):
                    raise ContractError('N8_COMPLETED_RESOURCE_RELEASE_CHANGED')
        return dict(state='REPAIR_OPEN', boundary_id=grant['boundary_id'], cleanup_evidence_ref=expected_id)

    def authorize_expired_release(self, resource, cleanup_evidence_ref):
        """Only signed accepted N8 compensation can relinquish expired custody."""
        preparations = self.truth.query('rc72_n7_execution_preparation', attempt_id=resource['attempt_id'])
        if len(preparations) != 1:
            raise ContractError('N8_EXPIRED_RESOURCE_PREPARATION_NOT_UNIQUE')
        preparation_id = preparations[0]['preparation_id']
        grant = self._signed(self._one(_KIND, preparation_id=preparation_id))
        if grant['state'] != 'CLEANUP_AUTHORIZED':
            raise ContractError('N8_EXPIRED_RESOURCE_RECOVERY_SCOPE_REQUIRED')
        self._context(preparation_id, opened=True)
        self._check_old_node_versions(preparations[0], grant)
        p, c, expected_id = self._audit_cleanup_proof(grant)
        # New expired-resource recovery requires authentic runtime observations;
        # legacy unsigned cleanup receipts cannot acquire this extra authority.
        for phase in ('CLEANUP', 'VERIFY'):
            call = self._one('rc72_n7_cleanup_call', preparation_id=preparation_id, phase=phase)
            signed = {key: value for key, value in call.items()
                      if key not in {'runtime_signature', 'artifact_type', 'artifact_version'}}
            if not hmac.compare_digest(call.get('runtime_signature', ''), self.preparation.authority._sign(signed)):
                raise ContractError('N8_EXPIRED_CLEANUP_RUNTIME_PROOF_REQUIRED')
        key, ids = ('data_lease_id', p['data_lease_ids']) if 'data_lease_id' in resource else ('browser_lease_id', p['browser_lease_ids'])
        if (resource[key] not in ids or cleanup_evidence_ref != expected_id
                or any(resource[k] != p[k] for k in ('mission_id', 'workitem_id', 'attempt_id', 'worker_id'))):
            raise ContractError('N8_EXPIRED_CLEANUP_RESOURCE_OR_PROOF_MISMATCH')
        return expected_id

    def open(self, preparation_id):
        prior = self.truth.query(_KIND, preparation_id=preparation_id)
        grant = self._signed(self._one(_KIND, preparation_id=preparation_id)) if prior else None
        if grant is not None and grant['state'] == 'REPAIR_OPEN':
            return self._audit_completed(grant)
        p, c, case = self._context(preparation_id, opened=grant is not None)
        if grant is None:
            cleanup, verify = frozen_cleanup_spec(c)
            worker = self.preparation.lifecycle.assign_fresh_worker(mission_id=p['mission_id'], team_id=case['team_id'],
                role=p['worker_identity']['role'], etu_id=p['etu_id'], workitem_id=p['workitem_id'],
                canonical_refs=dict(etu_refs=[p['etu_id']], executable_contract_refs=[p['contract_id']],
                                    data_refs=[ref['data_ref'] for ref in c['data_refs']]), parent_session_id=p['session_id'])
            identity = self.preparation.authority.adopt_identity(worker_id=worker.worker_id, role=p['worker_identity']['role'],
                phase='N8_RECOVERY_CLEANUP', layer=p['worker_identity']['layer'], generation=0, session_id=worker.session_id)
            lease = self.preparation.authority.issue_lease(identity.worker_id,
                'cleanup:%s/%s' % (preparation_id, c['contract_sha256']), (), tuple(sorted({cleanup['tool'], verify['tool']})), ttl_seconds=self.ttl)
            nodes = {kind.value: self.runtime.node_by_type(p['mission_id'], kind) for kind in
                     (AutonomousMissionNode.N6_EXECUTABLE_READINESS, AutonomousMissionNode.N7_EXECUTION)}
            grant = self._persist(dict(boundary_id='N8BOUND-' + _hash([preparation_id, case['diagnosis_id']])[:24],
                purpose='N8_SCOPED_CLEANUP_AND_REPAIR', release_id=p['release_id'], source_commit=p['source_commit'],
                preparation_id=preparation_id, diagnosis_id=case['diagnosis_id'], contract_sha256=c['contract_sha256'],
                state='CLEANUP_AUTHORIZED', cleanup_identity=asdict(identity), cleanup_lease=asdict(lease),
                original_nodes=nodes, artifact_version=1))
        cleaned = self.cleanup.run(preparation_id)
        if cleaned['state'] != 'CLEANUP_VERIFIED':
            return dict(state=cleaned['state'], boundary_id=grant['boundary_id'], resources_released=False)
        return self._open_after_cleanup(p, case, grant, cleaned['evidence_ref'])

    def _open_after_cleanup(self, p, case, grant, evidence_ref):
        self._check_old_node_versions(p, grant)
        binding = self._one('rc72_workitem_attempt_binding', binding_id=p['binding_id'])
        if binding['state'] != 'SUPERSEDED':
            entity = WorkItemAttemptBinding(**{f.name: binding[f.name] for f in fields(WorkItemAttemptBinding) if f.name in binding})
            entity.state = WorkItemAttemptState.SUPERSEDED
            self.preparation.lifecycle.repository.persist(entity, artifact_version=binding['artifact_version'] + 1)
        control = ClosedLoopControlPlane(self.truth, p['release_id'], p['mission_id'])
        task = self._one('rc7_task', task_id=p['workitem_id'])
        if task['state'] != 'STALE':
            entity = control.scheduler.task(p['workitem_id'])
            transition_task(entity, TaskStatus.STALE)
            control.scheduler._persist_task(entity, task['artifact_version'] + 1)
        current = self._one('rc72_n7_execution_preparation', preparation_id=p['preparation_id'])
        if current['status'] != 'INTERRUPTED':
            self.truth.append_atomic('RC72_N7_EXECUTION_PREPARATION_UPSERTED', dict(current, status='INTERRUPTED', artifact_version=current['artifact_version'] + 1))
        for session_id in (p['session_id'], grant['cleanup_identity']['session_id']):
            if self._one('rc72_worker_session', session_id=session_id)['state'] == 'ACTIVE':
                self.preparation.lifecycle.checkpoint_and_close(session_id, reason='accepted N8 compensation completed')
        self.preparation.authority.revoke_worker_lease(p['task_lease']['lease_id'])
        self.preparation.authority.revoke_worker_lease(grant['cleanup_lease']['lease_id'])
        for kind in (AutonomousMissionNode.N6_EXECUTABLE_READINESS, AutonomousMissionNode.N7_EXECUTION):
            node = self.runtime.node_by_type(p['mission_id'], kind)
            if node['state'] == 'NOT_STARTED' and node.get('active_delivery_version') is None:
                continue
            entity = MissionNodeRecord(**{f.name: node[f.name] for f in fields(MissionNodeRecord) if f.name in node})
            entity.state, entity.active_delivery_version, entity.exited_at = MissionNodeState.NOT_STARTED, None, None
            entity.revision += 1
            self.runtime.repository.persist(entity, artifact_version=node['artifact_version'] + 1)
        n5 = self.runtime.node_by_type(p['mission_id'], AutonomousMissionNode.N5_TEST_DATA)
        if n5['state'] == 'NEEDS_REVISION':
            self.runtime.transition_state(n5['mission_node_id'], MissionNodeState.RUNNING, reason='accepted N8 cleanup opens data repair')
        self._persist(dict(grant, state='REPAIR_OPEN', cleanup_evidence_ref=evidence_ref, artifact_version=grant['artifact_version'] + 1))
        return dict(state='REPAIR_OPEN', boundary_id=grant['boundary_id'], cleanup_evidence_ref=evidence_ref)


install_rc72_n8_repair_boundary_overlay()
