"""Same-attempt temporal lease amendments with immutable original history.

A renewal is not a fresh Attempt, permission expansion, expiry recovery or a
provider handoff. It must commit every owned resource before live authority can
use its signed amendment. Lost partial renewal blocks execution until reconciled.
"""
from copy import deepcopy
from dataclasses import asdict
import hmac
import time

from rc6_runtime import contracts, truth as registry
from rc6_runtime.authority import TaskLease, WorkerIdentity
from .models import ContractError
from .rc72_ledger_lock import ledger_lock

_KIND = 'rc72_execution_lease_renewal'
_EVENT = 'RC72_EXECUTION_LEASE_RENEWAL_UPSERTED'


def _now():
    return int(time.time())


def _validate(payload):
    row = deepcopy(payload)
    for key in ('renewal_id', 'release_id', 'source_commit', 'preparation_id', 'mission_id', 'release_batch_id',
                'workitem_id', 'attempt_id', 'worker_id', 'session_id', 'signature'):
        contracts._require_str(row, key)
    if row.get('purpose') != 'SAME_ATTEMPT_TEMPORAL_RENEWAL' or row.get('state') not in {'PLANNED', 'APPLIED'}:
        raise contracts.DomainValidationError('N7_RENEWAL_STATE_INVALID')
    for key in ('original_preparation', 'previous_lease', 'renewed_lease', 'policy'):
        if not isinstance(row.get(key), dict):
            raise contracts.DomainValidationError('N7_RENEWAL_CONTEXT_REQUIRED')
    if not isinstance(row.get('targets'), list):
        raise contracts.DomainValidationError('N7_RENEWAL_RESOURCES_REQUIRED')
    for key in ('field_verified', 'bank_final', 'case_pass', 'execution_result'):
        if key in row:
            raise contracts.DomainValidationError('N7_RENEWAL_PREMATURE_CLAIM')
    row.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(row))
    return row


def install_rc72_lease_renewal_overlay():
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'renewal_id')
    registry.IDENTITY_FIELDS[_KIND] = 'renewal_id'
    registry.BUCKETS[_KIND] = 'rc72_execution_lease_renewals'


def _lease(payload):
    values = dict(payload)
    for key in ('allowed_tools', 'allowed_artifact_types'):
        values[key] = tuple(values[key])
    return TaskLease(**values)


def _normalized(value):
    import json
    return json.loads(json.dumps(value))


def _stable_preparation(value):
    return _normalized({key: item for key, item in value.items() if key not in {'status', 'artifact_version'}})


def _signed(preparation, row):
    payload = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
    if not hmac.compare_digest(row['signature'], preparation.authority._sign(payload)):
        raise ContractError('N7_RENEWAL_SIGNATURE_INVALID')
    return row


def _chain(preparation, original, *, pending=False):
    rows = sorted(preparation.truth.query(_KIND, preparation_id=original['preparation_id']), key=lambda r: r['generation'])
    current, previous_id = _lease(original['task_lease']), None
    for generation, row in enumerate(rows, 1):
        _signed(preparation, row)
        if (row['generation'] != generation or row['previous_renewal_id'] != previous_id
                or _stable_preparation(row['original_preparation']) != _stable_preparation(original)
                or row['release_id'] != preparation.release_id or row['source_commit'] != preparation.source_commit
                or any(row.get(key) != original[key] for key in
                       ('mission_id', 'release_batch_id', 'workitem_id', 'attempt_id', 'worker_id', 'session_id'))
                or _normalized(row['previous_lease']) != _normalized(asdict(current))):
            raise ContractError('N7_RENEWAL_LINEAGE_CHANGED')
        proposed = _lease(row['renewed_lease'])
        expected = asdict(current)
        expected.update(expires_at=proposed.expires_at, signature=proposed.signature)
        if (asdict(proposed) != expected or proposed.expires_at <= current.expires_at
                or proposed.expires_at > original['task_lease']['issued_at'] + row['policy']['max_total_seconds']):
            raise ContractError('N7_RENEWAL_SCOPE_OR_WINDOW_CHANGED')
        requested = row.get('requested_at')
        ttl = row.get('ttl_seconds')
        if (not isinstance(requested, int) or isinstance(requested, bool)
                or not isinstance(ttl, int) or isinstance(ttl, bool) or ttl < 1
                or ttl > row['policy']['max_extension_seconds']
                or not current.issued_at <= requested <= current.expires_at
                or proposed.expires_at != requested + ttl
                or row['state'] == 'APPLIED' and not requested <= row.get('applied_at', -1) <= current.expires_at):
            raise ContractError('N7_RENEWAL_DECISION_WINDOW_INVALID')
        wanted = {('rc72_data_lease', 'data_lease_id', value) for value in original['data_lease_ids']}
        wanted |= {('rc72_browser_lease', 'browser_lease_id', value) for value in original['browser_lease_ids']}
        observed = set()
        for target in row['targets']:
            prior = target['original']
            observed.add((target['kind'], target['key'], prior[target['key']]))
            expected_target = dict(prior, expires_at=proposed.expires_at, artifact_version=prior['artifact_version'] + 1)
            if (prior['state'] != 'ACTIVE' or requested > prior['expires_at']
                    or proposed.expires_at <= prior['expires_at'] or target['updated'] != expected_target
                    or any(prior.get(key) != original[key] for key in ('mission_id', 'workitem_id', 'attempt_id', 'worker_id'))):
                raise ContractError('N7_RENEWAL_RESOURCE_SCOPE_CHANGED')
        if observed != wanted or len(row['targets']) != len(wanted):
            raise ContractError('N7_RENEWAL_RESOURCE_DENOMINATOR_CHANGED')
        if row['state'] == 'PLANNED':
            if row is not rows[-1] or not pending:
                raise ContractError('N7_RENEWAL_INCOMPLETE_EXECUTION_SUSPENDED')
            break
        current, previous_id = proposed, row['renewal_id']
    return current, previous_id, rows


def effective_worker_lease(preparation, original):
    current, _, rows = _chain(preparation, original)
    if rows:
        for target in rows[-1]['targets']:
            observed = preparation._one(target['kind'], **{target['key']: target['updated'][target['key']]})
            if observed != target['updated']:
                raise ContractError('N7_RENEWAL_RESOURCE_PROJECTION_CHANGED')
    return current


def execution_authorization_snapshot(preparation, original):
    """Record the exact effective permission used by a real runtime invocation."""
    current = effective_worker_lease(preparation, original)
    identity = WorkerIdentity(**original['worker_identity'])
    authorized_at = _now()
    preparation.authority._validate_lease(identity, current, authorized_at)
    _, renewal_id, _ = _chain(preparation, original)
    contract = preparation._one('rc72_n6_executable_contract', contract_id=original['contract_id'])
    payload = dict(purpose='RUNTIME_TASK_TEMPORAL_AUTHORIZATION', preparation_id=original['preparation_id'],
        attempt_id=original['attempt_id'], worker_id=original['worker_id'], task_lease=_normalized(asdict(current)),
        release_id=original['release_id'], source_commit=original['source_commit'],
        contract_id=original['contract_id'], contract_sha256=contract['contract_sha256'],
        renewal_id=renewal_id, authorized_at=authorized_at)
    return dict(payload, signature=preparation.authority._sign(payload))


def verify_execution_authorization(preparation, original, snapshot):
    """Historical audit only: this function never restores any live authority."""
    if not isinstance(snapshot, dict):
        raise ContractError('N7_EXECUTION_AUTHORIZATION_REQUIRED')
    payload = {key: value for key, value in snapshot.items() if key != 'signature'}
    if not hmac.compare_digest(snapshot.get('signature', ''), preparation.authority._sign(payload)):
        raise ContractError('N7_EXECUTION_AUTHORIZATION_SIGNATURE_INVALID')
    contract = preparation._one('rc72_n6_executable_contract', contract_id=original['contract_id'])
    if (snapshot.get('purpose') != 'RUNTIME_TASK_TEMPORAL_AUTHORIZATION'
            or any(snapshot.get(key) != original[key] for key in ('preparation_id', 'attempt_id', 'worker_id', 'release_id', 'source_commit', 'contract_id'))
            or snapshot.get('contract_sha256') != contract['contract_sha256']):
        raise ContractError('N7_EXECUTION_AUTHORIZATION_SCOPE_CHANGED')
    lease, base = _lease(snapshot['task_lease']), _lease(original['task_lease'])
    identity = WorkerIdentity(**original['worker_identity'])
    preparation.authority.validate_historical_lease(identity, lease)
    expected = asdict(base)
    expected.update(expires_at=lease.expires_at, signature=lease.signature)
    if (asdict(lease) != expected or lease.scope_ref != 'task:%s/attempt:%s' % (original['workitem_id'], original['attempt_id'])
            or not isinstance(snapshot.get('authorized_at'), int)
            or not lease.issued_at <= snapshot['authorized_at'] <= lease.expires_at):
        raise ContractError('N7_EXECUTION_AUTHORIZATION_SCOPE_OR_TIME_INVALID')
    if snapshot.get('renewal_id') is None:
        if lease != base:
            raise ContractError('N7_EXECUTION_AUTHORIZATION_RENEWAL_REQUIRED')
    else:
        _, _, history = _chain(preparation, original, pending=True)
        rows = [row for row in history if row['renewal_id'] == snapshot['renewal_id']]
        if (len(rows) != 1 or rows[0]['state'] != 'APPLIED'
                or rows[0]['applied_at'] > snapshot['authorized_at']
                or _normalized(rows[0]['renewed_lease']) != _normalized(asdict(lease))):
            raise ContractError('N7_EXECUTION_AUTHORIZATION_RENEWAL_CHANGED')
    return snapshot


class ExecutionLeaseRenewalService:
    def __init__(self, preparation, *, max_extension_seconds=300, max_total_seconds=86400):
        from .rc72_n7_execution_preparation import ExecutionPreparationService
        if not isinstance(preparation, ExecutionPreparationService):
            raise ContractError('N7_RENEWAL_NATIVE_PREPARATION_REQUIRED')
        for value in (max_extension_seconds, max_total_seconds):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ContractError('N7_RENEWAL_POLICY_INVALID')
        install_rc72_lease_renewal_overlay()
        self.preparation, self.truth, self.authority = preparation, preparation.truth, preparation.authority
        self.policy = dict(max_extension_seconds=max_extension_seconds, max_total_seconds=max_total_seconds)

    def _persist(self, row, **changes):
        payload = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
        payload.update(changes)
        payload = _normalized(payload)
        self.truth.append_atomic(_EVENT, dict(payload, signature=self.authority._sign(payload),
                                             artifact_version=row.get('artifact_version', 0) + 1))
        return _signed(self.preparation, self.preparation._one(_KIND, renewal_id=row['renewal_id']))

    def _live(self, original, previous, *, dispatcher, at=None):
        p = self.preparation._one('rc72_n7_execution_preparation', preparation_id=original['preparation_id'])
        if p != original or p['status'] != 'PREPARED':
            raise ContractError('N7_RENEWAL_PREPARATION_CHANGED')
        _, _, contract, etu, _, plan = self.preparation._current_tuple(p)
        self.preparation._current_resources(p, contract, etu, plan, locked=True)
        binding = self.preparation._one('rc72_workitem_attempt_binding', binding_id=p['binding_id'])
        task = self.preparation._one('rc7_task', task_id=p['workitem_id'])
        session = self.preparation._one('rc72_worker_session', session_id=p['session_id'])
        if (binding['state'] not in {'PREPARED', 'RUNNING', 'EVIDENCE_READY'}
                or binding['attempt_id'] != p['attempt_id'] or binding['worker_id'] != p['worker_id']
                or binding['task_lease_ref'] != previous.lease_id
                or binding['resource_lease_refs'] != p['data_lease_ids'] + p['browser_lease_ids']
                or task['state'] not in {'LEASED', 'RUNNING'} or task['lease_owner'] != p['worker_id']
                or session['state'] != 'ACTIVE' or session['worker_id'] != p['worker_id']
                or self.truth.query('rc72_n8_repair_boundary', preparation_id=p['preparation_id'])
                or self.truth.query('rc72_diagnosis_case', source_binding_id=p['binding_id'])):
            raise ContractError('N7_RENEWAL_CURRENT_OWNED_WORKER_REQUIRED')
        identity = WorkerIdentity(**p['worker_identity'])
        self.authority._validate_lease(identity, previous, _now() if at is None else at)
        calls = self.truth.query('rc72_n7_tool_dispatch', preparation_id=p['preparation_id'])
        if calls:
            from .rc72_n7_tool_dispatch import SignedToolDispatchService
            if len(calls) != 1 or calls[0]['state'] == 'FAILED':
                raise ContractError('N7_RENEWAL_FAILURE_REQUIRES_DIAGNOSIS')
            if calls[0]['state'] == 'IN_FLIGHT':
                if (not isinstance(dispatcher, SignedToolDispatchService) or dispatcher.preparation is not self.preparation
                        or p['preparation_id'] not in dispatcher._live_invocations):
                    raise ContractError('N7_RENEWAL_LIVE_DISPATCH_CONTROLLER_REQUIRED')
            else:
                from .rc72_n7_execution_evidence import ExecutionEvidenceService
                from .rc72_formal_runner import verified_formal_receipt
                _, c, _, _, dispatch, oracle = ExecutionEvidenceService(self.preparation).observation(p['preparation_id'])
                formal = verified_formal_receipt(self.preparation, p, c, dispatch.get('raw_result') or {})
                if not oracle['passed'] or formal and formal['runner_result']['exit_code'] != 0:
                    raise ContractError('N7_RENEWAL_FAILURE_REQUIRES_DIAGNOSIS')
        return identity

    def renew(self, preparation_id, *, renewal_id, ttl_seconds, dispatcher=None):
        if not isinstance(renewal_id, str) or not renewal_id.strip():
            raise ContractError('N7_RENEWAL_ID_REQUIRED')
        if (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 1
                or ttl_seconds > self.policy['max_extension_seconds']):
            raise ContractError('N7_RENEWAL_TTL_OUTSIDE_POLICY')
        with ledger_lock(self.truth, busy='N7_RENEWAL_LEDGER_BUSY'):
            p = self.preparation._one('rc72_n7_execution_preparation', preparation_id=preparation_id)
            previous, prior_id, history = _chain(self.preparation, p, pending=True)
            matches = self.truth.query(_KIND, renewal_id=renewal_id)
            if matches:
                row = _signed(self.preparation, self.preparation._one(_KIND, renewal_id=renewal_id))
                if row['preparation_id'] != preparation_id or row['ttl_seconds'] != ttl_seconds:
                    raise ContractError('N7_RENEWAL_REQUEST_REPLAY_CONFLICT')
                if row['state'] == 'APPLIED':
                    return row  # History only; never restores expired/revoked permission.
            else:
                if history and history[-1]['state'] == 'PLANNED':
                    raise ContractError('N7_RENEWAL_INCOMPLETE_EXECUTION_SUSPENDED')
                identity = self._live(p, previous, dispatcher=dispatcher)
                requested_at = _now()
                self.authority._validate_lease(identity, previous, requested_at)
                expires = requested_at + ttl_seconds
                if expires <= previous.expires_at or expires > p['task_lease']['issued_at'] + self.policy['max_total_seconds']:
                    raise ContractError('N7_RENEWAL_WINDOW_OUTSIDE_POLICY')
                targets = []
                for kind, key, ids in (('rc72_data_lease', 'data_lease_id', p['data_lease_ids']),
                                      ('rc72_browser_lease', 'browser_lease_id', p['browser_lease_ids'])):
                    for identifier in ids:
                        original = self.preparation._one(kind, **{key: identifier})
                        if (original['state'] != 'ACTIVE' or _now() > original['expires_at']
                                or expires <= original['expires_at']
                                or any(original[k] != p[k] for k in ('mission_id', 'workitem_id', 'attempt_id', 'worker_id'))):
                            raise ContractError('N7_RENEWAL_LIVE_RESOURCE_CUSTODY_REQUIRED')
                        updated = dict(original, expires_at=expires, artifact_version=original['artifact_version'] + 1)
                        targets.append(dict(kind=kind, key=key, original=original, updated=updated))
                renewed = asdict(previous)
                renewed['expires_at'] = expires
                renewed['signature'] = self.authority._sign({k: v for k, v in renewed.items() if k != 'signature'})
                row = self._persist(dict(renewal_id=renewal_id, purpose='SAME_ATTEMPT_TEMPORAL_RENEWAL',
                    release_id=p['release_id'], source_commit=p['source_commit'], preparation_id=preparation_id,
                    **{key: p[key] for key in ('mission_id', 'release_batch_id', 'workitem_id', 'attempt_id', 'worker_id', 'session_id')},
                    original_preparation=p, generation=len(history) + 1, previous_renewal_id=prior_id,
                    previous_lease=asdict(previous), renewed_lease=renewed, targets=targets,
                    ttl_seconds=ttl_seconds, requested_at=requested_at, policy=self.policy, state='PLANNED'))
            # A planned renewal cannot revive authority after its prior deadline.
            identity = self._live(p, _lease(row['previous_lease']), dispatcher=dispatcher)
            pending = []
            for target in row['targets']:
                current = self.preparation._one(target['kind'], **{target['key']: target['original'][target['key']]})
                if current != target['updated']:
                    if current != target['original'] or _now() > current['expires_at']:
                        raise ContractError('N7_RENEWAL_RESOURCE_CHANGED_OR_EXPIRED')
                    pending.append(target)
            for target in pending:
                event = 'RC72_DATA_LEASE_UPSERTED' if target['kind'] == 'rc72_data_lease' else 'RC72_BROWSER_LEASE_UPSERTED'
                self.truth.append_atomic(event, target['updated'])
            commit_at = _now()
            identity = self._live(p, _lease(row['previous_lease']), dispatcher=dispatcher, at=commit_at)
            row = self._persist(row, state='APPLIED', applied_at=commit_at)
            self.authority.restore_renewed_worker_lease(identity, _lease(p['task_lease']), _lease(row['renewed_lease']))
            return row


install_rc72_lease_renewal_overlay()
