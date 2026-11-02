"""Signed at-most-once capability decisions and recoverable audit projections.

A missing issuance receipt after ISSUING is unknown authority, never permission
to issue again. Completed replay is historical; only assert_usable may restore a
signed child after current parent/binding/revocation/TTL checks.
"""
from dataclasses import asdict
import hmac
import json

from rc6_runtime import contracts, truth as registry
from rc6_runtime.authority import TaskLease
from .models import ContractError
from .rc72_ledger_lock import ledger_lock

_KIND = 'rc72_capability_resolution'
_EVENT = 'RC72_CAPABILITY_RESOLUTION_UPSERTED'


def _validate(payload):
    row = dict(payload)
    for key in ('request_id', 'release_id', 'mission_id', 'signature'):
        contracts._require_str(row, key)
    if row.get('purpose') != 'EXACT_CAPABILITY_DECISION' or row.get('state') not in {'PLANNED', 'ISSUING', 'OBSERVED'}:
        raise contracts.DomainValidationError('CAPABILITY_RESOLUTION_STATE_INVALID')
    for key in ('request', 'rule', 'parent'):
        if not isinstance(row.get(key), dict):
            raise contracts.DomainValidationError('CAPABILITY_RESOLUTION_CONTEXT_REQUIRED')
    if any(key in row for key in ('field_verified', 'bank_final', 'case_pass', 'execution_result')):
        raise contracts.DomainValidationError('CAPABILITY_RESOLUTION_PREMATURE_CLAIM')
    if row['state'] == 'OBSERVED' and (not isinstance(row.get('decided_at'), int)
            or row.get('child') is not None and not isinstance(row['child'], dict)):
        raise contracts.DomainValidationError('CAPABILITY_RESOLUTION_OBSERVATION_REQUIRED')
    row.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(row))
    return row


def install_rc72_capability_resolution_overlay():
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'request_id')
    registry.IDENTITY_FIELDS[_KIND] = 'request_id'
    registry.BUCKETS[_KIND] = 'rc72_capability_resolutions'




class CapabilityResolutionService:
    def __init__(self, broker):
        install_rc72_capability_resolution_overlay()
        self.broker, self.truth, self.authority = broker, broker.truth, broker.authority

    def _signed(self, row):
        raw = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
        if not hmac.compare_digest(row['signature'], self.authority._sign(raw)):
            raise ContractError('CAPABILITY_RESOLUTION_SIGNATURE_INVALID')
        return row

    def _persist(self, row, **changes):
        raw = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
        raw.update(changes)
        self.truth.append_atomic(_EVENT, dict(raw, signature=self.authority._sign(raw),
                                             artifact_version=row.get('artifact_version', 0) + 1))
        return self._signed(self.broker._one(_KIND, request_id=row['request_id']))

    def _ensure(self, kind, event, identity, payload, *, project=True):
        expected = dict(payload, release_id=self.broker.release_id, artifact_version=1)
        rows = self.truth.query(kind, **{identity: payload[identity]})
        if rows:
            # A revoked capability remains revoked; historical replay cannot undo it.
            ignored = {'artifact_type', 'artifact_version'}
            if kind == 'rc72_capability_lease':
                ignored |= {'state', 'revoked_at', 'revoked_reason'}
            if len(rows) != 1 or any(rows[0].get(key) != value for key, value in expected.items() if key not in ignored):
                raise ContractError('CAPABILITY_RESOLUTION_PROJECTION_CONFLICT:' + kind)
        else:
            if not project:
                raise ContractError('CAPABILITY_DECISION_PROJECTION_REQUIRED')
            self.broker._append(event, payload)

    def _finish(self, row, *, project=True):
        from .rc72_capability_broker import CapabilityBrokerResult, CapabilityDecision
        if row['state'] != 'OBSERVED':
            raise ContractError('CAPABILITY_ISSUANCE_EFFECT_UNKNOWN')
        self._ensure('rc72_capability_request', 'RC72_CAPABILITY_REQUEST_UPSERTED', 'request_id', row['request'], project=project)
        child = row.get('child')
        if child:
            cap = dict(row['request'])
            for key in ('state', 'created_at', 'reason'):
                cap.pop(key)
            cap.update(capability_lease_id=row['capability_lease_id'], signed_task_lease_id=child['lease_id'],
                       scope_ref=child['scope_ref'], issued_at=child['issued_at'], expires_at=child['expires_at'],
                       state='ACTIVE', revoked_at=None, revoked_reason=None)
            self._ensure('rc72_capability_lease', 'RC72_CAPABILITY_LEASE_UPSERTED', 'capability_lease_id', cap, project=project)
        decision = {key: row['request'][key] for key in
                    ('request_id', 'mission_id', 'workitem_id', 'attempt_id', 'worker_id', 'requested_capability')}
        decision.update(decision=row['rule']['decision'], reason='policy:' + row['rule']['decision'],
                        delegate_role=row['rule']['delegate_role'], capability_lease_id=row.get('capability_lease_id'),
                        decided_at=row['decided_at'])
        self._ensure('rc72_capability_decision', 'RC72_CAPABILITY_DECISION_UPSERTED', 'request_id', decision, project=project)
        return CapabilityBrokerResult(row['request_id'], CapabilityDecision(row['rule']['decision']),
            row.get('capability_lease_id'), child['lease_id'] if child else None, row['rule']['delegate_role'])

    def request(self, **values):
        from .rc72_capability_broker import CapabilityPolicyRule, CapabilityDecision, _now, _new
        for key, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise ContractError(key.upper() + '_REQUIRED')
        values['requested_capability'] = self.broker._exact_capability(values['requested_capability'])
        with ledger_lock(self.truth, busy='CAPABILITY_REQUEST_IN_PROGRESS'):
            # Another runtime/process may have appended since this projection loaded.
            self.truth.rebuild_projection()
            rows = self.truth.query(_KIND, request_id=values['request_id'])
            if rows:
                row = self._signed(self.broker._one(_KIND, request_id=values['request_id']))
                if row['release_id'] != self.broker.release_id or any(row['request'].get(k) != v for k, v in values.items()):
                    raise ContractError('CAPABILITY_REQUEST_REPLAY_CONFLICT')
                if row['state'] == 'OBSERVED':
                    return self._finish(row)
                if row['state'] == 'ISSUING':
                    raise ContractError('CAPABILITY_ISSUANCE_EFFECT_UNKNOWN')
            else:
                if self.truth.query('rc72_capability_request', request_id=values['request_id']):
                    raise ContractError('CAPABILITY_LEGACY_REQUEST_RECONCILIATION_REQUIRED')
                binding = self.broker._binding(**{key: values[key] for key in
                    ('mission_id', 'workitem_id', 'attempt_id', 'worker_id', 'parent_task_lease_id')})
                parent = self.authority.get_lease(values['parent_task_lease_id'])
                identity = self.authority.get_identity(values['worker_id'])
                self.authority._validate_lease(identity, parent, None)
                if parent.worker_id != values['worker_id']:
                    raise ContractError('CAPABILITY_REQUEST_PARENT_WORKER_MISMATCH')
                if parent.scope_ref not in {'task:' + values['workitem_id'],
                    'task:%s/attempt:%s' % (values['workitem_id'], values['attempt_id']),
                    str(binding.get('etu_id') or '')}:
                    raise ContractError('CAPABILITY_REQUEST_PARENT_SCOPE_MISMATCH')
                rule = self.broker.policies.get(values['requested_capability'], CapabilityPolicyRule(CapabilityDecision.DENY))
                row = self._persist(dict(request_id=values['request_id'], release_id=self.broker.release_id,
                    mission_id=values['mission_id'], purpose='EXACT_CAPABILITY_DECISION', state='PLANNED',
                    request=dict(values, state='REQUESTED', created_at=_now()), rule=asdict(rule), parent=asdict(parent)))
            # Revalidate current authority even after a planned-decision interruption.
            self.broker._binding(**{key: values[key] for key in
                ('mission_id', 'workitem_id', 'attempt_id', 'worker_id', 'parent_task_lease_id')})
            parent = self.authority.get_lease(values['parent_task_lease_id'])
            identity = self.authority.get_identity(values['worker_id'])
            self.authority._validate_lease(identity, parent, None)
            if json.loads(json.dumps(asdict(parent))) != json.loads(json.dumps(row['parent'])):
                raise ContractError('CAPABILITY_PARENT_CHANGED')
            child = None
            if row['rule']['decision'] == CapabilityDecision.AUTO_GRANT_TEMP_LEASE:
                ttl = min(row['rule']['max_ttl_seconds'], parent.expires_at - _now())
                if ttl < 1:
                    raise ContractError('CAPABILITY_PARENT_LEASE_EXPIRED')
                row = self._persist(row, state='ISSUING')
                child = self.authority.issue_lease(values['worker_id'], parent.scope_ref, parent.allowed_artifact_types,
                    tuple(sorted(set(parent.allowed_tools) | {values['requested_capability']})), ttl_seconds=ttl)
                if child.expires_at > parent.expires_at:
                    self.authority.revoke_lease(child.lease_id)
                    raise ContractError('CAPABILITY_CHILD_EXCEEDS_PARENT_WINDOW')
            # A journal response can be lost after its durable write. Do not
            # perform an unjournaled compensating revoke: OBSERVED may already
            # be authoritative. Without OBSERVED, ISSUING blocks reissuance.
            row = self._persist(row, state='OBSERVED', child=asdict(child) if child else None,
                                capability_lease_id=_new('CAPLEASE') if child else None, decided_at=_now())
            return self._finish(row)

    def revoke(self, capability_lease_id, reason):
        from .rc72_capability_broker import _now
        if not isinstance(reason, str) or not reason.strip():
            raise ContractError('CAPABILITY_REVOKE_REASON_REQUIRED')
        cap = self.broker._one('rc72_capability_lease', capability_lease_id=capability_lease_id)
        with ledger_lock(self.truth, busy='CAPABILITY_REQUEST_IN_PROGRESS'):
            self.truth.rebuild_projection()
            row = self._signed(self.broker._one(_KIND, request_id=cap['request_id']))
            if row.get('capability_lease_id') != capability_lease_id or not row.get('child'):
                raise ContractError('CAPABILITY_CHILD_PROOF_MISMATCH')
            if row.get('revoked_at') is None:
                row = self._persist(row, revoked_at=_now(), revoked_reason=reason)
            child_id = row['child']['lease_id']
            # A cold runtime may no longer hold the child. The signed revocation
            # is durable and prevents any subsequent restore regardless.
            if child_id in self.authority._leases and not self.authority.is_lease_revoked(child_id):
                self.authority.revoke_lease(child_id)
            cap = self.broker._one('rc72_capability_lease', capability_lease_id=capability_lease_id)
            if cap['state'] != 'REVOKED':
                self.truth.append_atomic('RC72_CAPABILITY_LEASE_UPSERTED', dict(cap,
                    state='REVOKED', revoked_at=row['revoked_at'], revoked_reason=row['revoked_reason'],
                    artifact_version=cap['artifact_version'] + 1))

    def restore_child(self, cap):
        self.truth.rebuild_projection()
        current = self.broker._one('rc72_capability_lease', capability_lease_id=cap['capability_lease_id'])
        if current['state'] != 'ACTIVE':
            raise ContractError('CAPABILITY_LEASE_NOT_ACTIVE')
        self.broker._binding(**{key: cap[key] for key in
            ('mission_id', 'workitem_id', 'attempt_id', 'worker_id', 'parent_task_lease_id')})
        row = self._signed(self.broker._one(_KIND, request_id=cap['request_id']))
        if row['state'] != 'OBSERVED' or row.get('capability_lease_id') != cap['capability_lease_id'] or not row.get('child'):
            raise ContractError('CAPABILITY_CHILD_PROOF_MISMATCH')
        self._finish(row, project=False)
        if row.get('revoked_at') is not None:
            raise ContractError('CAPABILITY_CHILD_REVOKED')
        payload = dict(row['child'])
        payload['allowed_tools'] = tuple(payload['allowed_tools'])
        payload['allowed_artifact_types'] = tuple(payload['allowed_artifact_types'])
        lease = TaskLease(**payload)
        identity = self.authority.get_identity(cap['worker_id'])
        self.authority._validate_lease(identity, lease, None)
        if self.authority.is_lease_revoked(lease.lease_id):
            raise ContractError('CAPABILITY_CHILD_REVOKED')
        if hasattr(self.authority, 'restore_signed_worker_lease'):
            self.authority.restore_signed_worker_lease(identity, lease, expected_scope=cap['scope_ref'])
        else:
            existing = self.authority._leases.get(lease.lease_id)
            if existing is not None and existing != lease:
                raise ContractError('CAPABILITY_CHILD_RESTORE_CONFLICT')
            self.authority._leases[lease.lease_id] = lease


install_rc72_capability_resolution_overlay()
