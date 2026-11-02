"""Execute only frozen cleanup actions and recheck every owned DataRef.

An adapter's success flag is never sufficient to release resources. Verification
must return one actual observation for every leased DataRef; frozen machine
predicates are evaluated separately for each observation. This is mechanical
N7 cleanup, not independent N5 redesign or a Case/Node completion decision.
"""
from copy import deepcopy
import json
import hmac
import os
from pathlib import Path

from rc6_runtime import contracts, truth as registry
from .models import ContractError
from .oracle_runtime import DeterministicOracleRuntime
from .rc72_n7_execution_admission import _hash
from .rc72_n7_execution_evidence import ExecutionEvidenceService
from .truth_overlay import install_rc7_truth_overlay

_KIND = 'rc72_n7_cleanup_call'
_EVENT = 'RC72_N7_CLEANUP_CALL_UPSERTED'


class CleanupError(ContractError):
    pass


def frozen_cleanup_spec(contract):
    cleanup = contract['cleanup']
    verification = cleanup.get('verification')
    if not isinstance(verification, dict):
        raise CleanupError('N7_FROZEN_CLEANUP_VERIFICATION_REQUIRED')
    DeterministicOracleRuntime.validate_contract(verification)
    for spec in (cleanup, verification):
        tool = spec.get('tool')
        if not isinstance(tool, str) or not tool or '*' in tool:
            raise CleanupError('N7_FROZEN_CLEANUP_TOOL_REQUIRED')
        if (not spec.get('source_ref') or spec['source_ref'] not in contract['authoritative_sources']):
            raise CleanupError('N7_FROZEN_CLEANUP_SOURCE_UNBOUND')
    return cleanup, verification


def _validate(payload):
    out = deepcopy(payload)
    for key in ('call_id', 'preparation_id', 'release_id', 'source_commit', 'contract_id',
                'contract_sha256', 'attempt_id', 'worker_id', 'tool', 'request_sha256'):
        out[key] = contracts._require_str(out, key)
    if out.get('phase') not in {'CLEANUP', 'VERIFY'} or out.get('state') not in {'IN_FLIGHT', 'RETURNED', 'FAILED'}:
        raise contracts.DomainValidationError('N7_CLEANUP_STATE_INVALID')
    if out['state'] == 'RETURNED':
        if not isinstance(out.get('raw_result'), dict) or not out['raw_result']:
            raise contracts.DomainValidationError('N7_CLEANUP_RAW_RESULT_REQUIRED')
        if out.get('receipt_sha256') != _hash(out['raw_result']):
            raise contracts.DomainValidationError('N7_CLEANUP_RECEIPT_HASH_MISMATCH')
    if out['state'] == 'FAILED':
        contracts._require_str(out, 'error_type')
    for key in ('passed', 'field_verified', 'bank_final', 'case_pass'):
        if key in out:
            raise contracts.DomainValidationError('N7_CLEANUP_PREMATURE_CLAIM')
    out.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(out))
    return out


def install_rc72_n7_cleanup_overlay():
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'call_id')
    registry.BUCKETS[_KIND] = 'rc72_n7_cleanup_calls'
    registry.IDENTITY_FIELDS[_KIND] = 'call_id'


class ExecutionCleanupService:
    def __init__(self, preparation, *, adapters, recovery_authorizer=None):
        install_rc72_n7_cleanup_overlay()
        self.preparation = preparation
        self.truth = preparation.truth
        self.adapters = dict(adapters)
        if recovery_authorizer is not None:
            from .rc72_n8_repair_boundary import RepairBoundaryService
            if not isinstance(recovery_authorizer, RepairBoundaryService) or recovery_authorizer.preparation is not preparation:
                raise CleanupError('N7_TRUSTED_REPAIR_BOUNDARY_REQUIRED')
        self.recovery_authorizer = recovery_authorizer
        self.evidence = ExecutionEvidenceService(preparation)

    def _spec(self, contract):
        cleanup, verification = frozen_cleanup_spec(contract)
        for spec in (cleanup, verification):
            if not callable(self.adapters.get(spec['tool'])):
                raise CleanupError('N7_FROZEN_CLEANUP_TOOL_REQUIRED')
        return cleanup, verification

    def _call(self, p, c, phase, tool, cleanup_ref=None):
        call_id = 'N7CLEAN-' + _hash([p['preparation_id'], c['contract_sha256'], phase, tool])[:24]
        context = {key: deepcopy(p[key]) for key in ('workitem_id', 'attempt_id', 'worker_id',
                    'session_id', 'data_lease_ids', 'browser_lease_ids')}
        context.update(phase=phase, cleanup_receipt_ref=cleanup_ref)
        digest = _hash({'contract': c, 'context': context})
        existing = self.truth.query(_KIND, call_id=call_id)
        if existing:
            if (len(existing) != 1 or existing[0]['request_sha256'] != digest
                    or existing[0]['attempt_id'] != p['attempt_id']
                    or existing[0]['worker_id'] != p['worker_id']
                    or existing[0]['phase'] != phase or existing[0]['tool'] != tool
                    or existing[0]['contract_sha256'] != c['contract_sha256']
                    or existing[0]['preparation_id'] != p['preparation_id']
                    or existing[0]['release_id'] != p['release_id']
                    or existing[0]['source_commit'] != p['source_commit']):
                raise CleanupError('N7_CLEANUP_REPLAY_CONFLICT')
            if existing[0]['state'] == 'IN_FLIGHT':
                raise CleanupError('N7_CLEANUP_SIDE_EFFECTS_UNKNOWN_DIAGNOSIS_REQUIRED')
            signature = existing[0].get('runtime_signature')
            if signature is not None:
                signed = {key: value for key, value in existing[0].items()
                          if key not in {'runtime_signature', 'artifact_type', 'artifact_version'}}
                if not hmac.compare_digest(signature, self.preparation.authority._sign(signed)):
                    raise CleanupError('N7_CLEANUP_RUNTIME_SIGNATURE_INVALID')
            return existing[0]
        # Only new external I/O requires current admission, TTL and all leases.
        # Resuming persisted cleanup receipts below cannot authorize another call.
        if self.recovery_authorizer is None:
            self.preparation.assert_current(p['preparation_id'])
            self.preparation.authority.authorize_tool(p['worker_id'], p['task_lease']['lease_id'], tool)
            recovery_grant = None
        else:
            recovery_grant = self.recovery_authorizer.authorize_cleanup(p, c, phase, tool)

        row = dict(call_id=call_id, preparation_id=p['preparation_id'], release_id=p['release_id'],
            source_commit=p['source_commit'], contract_id=c['contract_id'], contract_sha256=c['contract_sha256'],
            attempt_id=p['attempt_id'], worker_id=p['worker_id'], tool=tool, phase=phase,
            request_sha256=digest, state='IN_FLIGHT', artifact_version=1)
        if recovery_grant is not None:
            row['recovery_grant_ref'] = recovery_grant
        directory = Path(str(self.truth.store.path) + '.n7-dispatch-claims')
        directory.mkdir(parents=True, exist_ok=True)
        try:
            claim = os.open(str(directory / call_id), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise CleanupError('N7_CLEANUP_ALREADY_CLAIMED_DIAGNOSIS_REQUIRED') from exc
        os.close(claim)
        self.truth.append_atomic(_EVENT, row)
        try:
            result = self.adapters[tool](contract=deepcopy(c), context=deepcopy(context))
            if not isinstance(result, dict) or not result:
                raise CleanupError('N7_CLEANUP_RAW_RESULT_REQUIRED')
            result = json.loads(json.dumps(result, allow_nan=False))
        except Exception as exc:
            updated = dict(row, state='FAILED', error_type=type(exc).__name__, artifact_version=2)
        else:
            updated = dict(row, state='RETURNED', raw_result=result,
                           receipt_sha256=_hash(result), artifact_version=2)
        updated['runtime_signature'] = self.preparation.authority._sign(
            {key: value for key, value in updated.items() if key not in {'artifact_type', 'artifact_version'}})
        self.truth.append_atomic(_EVENT, updated)
        return self.preparation._one(_KIND, call_id=call_id)

    def run(self, preparation_id):
        p, c, binding, admission, execution, oracle = self.evidence.observation(preparation_id)
        cleanup, verification = self._spec(c)
        allowed = p['task_lease']['allowed_tools']
        if cleanup['tool'] not in allowed or verification['tool'] not in allowed:
            raise CleanupError('N7_CLEANUP_TOOL_OUTSIDE_SIGNED_SCOPE')
        if execution['state'] == 'IN_FLIGHT':
            raise CleanupError('N7_EXECUTION_SIDE_EFFECTS_UNKNOWN_DIAGNOSIS_REQUIRED')
        self.evidence.record(preparation_id)
        action = self._call(p, c, 'CLEANUP', cleanup['tool'])
        if action['state'] != 'RETURNED':
            return dict(state='CLEANUP_FAILED', call_ref=action['call_id'], resources_released=False)
        observed = self._call(p, c, 'VERIFY', verification['tool'], action['call_id'])
        if observed['state'] != 'RETURNED':
            return dict(state='VERIFICATION_FAILED', call_ref=observed['call_id'], resources_released=False)
        for row in (action, observed):
            if row.get('receipt_sha256') != _hash(row['raw_result']):
                raise CleanupError('N7_CLEANUP_RECEIPT_HASH_MISMATCH')
        refs = sorted(ref['data_ref'] for ref in c['data_refs'])
        actual = observed['raw_result'].get('data_results')
        if not isinstance(actual, dict) or set(actual) != set(refs):
            raise CleanupError('N7_CLEANUP_DATA_DENOMINATOR_MISMATCH')
        results = {ref: DeterministicOracleRuntime().evaluate(verification, actual[ref],
            {'attempt_id': p['attempt_id'], 'data_ref': ref, 'cleanup_call_ref': action['call_id'],
             'verification_call_ref': observed['call_id'], 'receipt_sha256': observed['receipt_sha256']}) for ref in refs}
        if not all(result['passed'] for result in results.values()):
            return dict(state='VERIFICATION_FAILED', call_ref=observed['call_id'],
                        data_assertions=results, resources_released=False)
        evidence_id = 'N7CLEANEV-' + _hash([p['attempt_id'], action['receipt_sha256'],
            observed['receipt_sha256'], results])[:24]
        evidence_ref = 'r1://artifact/' + observed['call_id']
        # Validate the complete ownership tuple before releasing the first item.
        reason = 'verified N7 cleanup evidence ' + evidence_id
        resources = []
        expected_data = dict(zip(p['data_lease_ids'], sorted(c['data_refs'], key=lambda ref: ref['data_ref'])))
        for kind, key, ids in (('rc72_data_lease', 'data_lease_id', p['data_lease_ids']),
                               ('rc72_browser_lease', 'browser_lease_id', p['browser_lease_ids'])):
            for lease_id in ids:
                resource = self.preparation._one(kind, **{key: lease_id})
                if (any(resource.get(k) != p[k] for k in ('mission_id', 'workitem_id', 'attempt_id', 'worker_id'))
                        or (kind == 'rc72_data_lease' and resource.get('data_ref') != expected_data[lease_id]['data_ref'])
                        or resource['state'] not in ({'ACTIVE', 'EXPIRED', 'RELEASED'} if self.recovery_authorizer else {'ACTIVE', 'RELEASED'})
                        or (resource['state'] == 'RELEASED' and resource.get('release_reason') != reason)):
                    raise CleanupError('N7_CLEANUP_RESOURCE_OWNER_OR_STATE_MISMATCH')
                resources.append((kind, lease_id, resource['state']))
        self.evidence._ensure('rc7_evidence', 'RC7_EVIDENCE_UPSERTED', 'evidence_id', dict(
            evidence_id=evidence_id, release_id=p['release_id'], mission_id=p['mission_id'],
            kind='N7_CLEANUP_DATA_REVERIFIED', source_ref=evidence_ref, content_ref=evidence_ref,
            content_hash=_hash(results), subject_refs=[p['workitem_id'], p['attempt_id']] + refs,
            data_assertions=results, cleanup_call_ref=action['call_id'], verification_call_ref=observed['call_id'],
            artifact_version=1))
        self.evidence._ensure('evidence', 'EVIDENCE_UPSERTED', 'id', dict(
            id=evidence_id, release_id=p['release_id'], kind='N7_CLEANUP_DATA_REVERIFIED',
            ref=evidence_ref, source_artifact_ref=observed['call_id'], requirement_id=c['requirement_id'],
            tc_id=p['case_id'], attempt_id=p['attempt_id'], artifact_version=1))
        if self.recovery_authorizer is not None:
            # Check all expired release authority before relinquishing the first
            # resource. Each manager rechecks under its ledger gate as well.
            import time
            for kind, lease_id, state in resources:
                if state == 'RELEASED':
                    continue
                key = 'data_lease_id' if kind == 'rc72_data_lease' else 'browser_lease_id'
                resource = self.preparation._one(kind, **{key: lease_id})
                if state == 'EXPIRED' or time.time() > int(resource['expires_at']):
                    self.recovery_authorizer.authorize_expired_release(resource, evidence_id)
        for kind, lease_id, state in resources:
            if state == 'RELEASED':
                continue
            if kind == 'rc72_data_lease':
                self.preparation.data.release(lease_id, cleanup_evidence_ref=evidence_id, reason=reason,
                    recovery_authorizer=self.recovery_authorizer)
            else:
                self.preparation.browser.release(lease_id, reason=reason, cleanup_evidence_ref=evidence_id,
                    recovery_authorizer=self.recovery_authorizer)
        return dict(state='CLEANUP_VERIFIED', evidence_ref=evidence_id, data_assertions=results,
                    resources_released=True)


    def begin_failure_diagnosis(self, preparation_id):
        """Derive cleanup failure from durable calls; never accept a success flag."""
        from .rc72_diagnosis_orchestration import DiagnosisOrchestrator
        from .rc72_state_machine import RC72StateMachine
        p, c, binding, admission, execution, oracle = self.evidence.observation(preparation_id)
        cleanup, verification = self._spec(c)
        calls = self.truth.query(_KIND, preparation_id=preparation_id)
        reason, failed = None, None
        by_phase = {row['phase']: row for row in calls}
        if len(by_phase) != len(calls):
            raise CleanupError('N7_CLEANUP_CALL_NOT_UNIQUE')
        for phase in ('CLEANUP', 'VERIFY'):
            row = by_phase.get(phase)
            if row is None:
                continue
            if (row['attempt_id'] != p['attempt_id'] or row['worker_id'] != p['worker_id']
                    or row['contract_sha256'] != c['contract_sha256']):
                raise CleanupError('N7_CLEANUP_CALL_OWNER_MISMATCH')
            if row['state'] in {'IN_FLIGHT', 'FAILED'}:
                failed, reason = row, 'CLEANUP_SIDE_EFFECTS_UNKNOWN' if row['state'] == 'IN_FLIGHT' else 'CLEANUP_TOOL_FAILED'
                break
            if row['receipt_sha256'] != _hash(row['raw_result']):
                raise CleanupError('N7_CLEANUP_RECEIPT_HASH_MISMATCH')
        if reason is None and 'VERIFY' in by_phase:
            observed = by_phase['VERIFY']
            actual = observed['raw_result'].get('data_results')
            refs = {ref['data_ref'] for ref in c['data_refs']}
            if not isinstance(actual, dict) or set(actual) != refs:
                failed, reason = observed, 'CLEANUP_DATA_DENOMINATOR_MISMATCH'
            else:
                for ref in sorted(refs):
                    try:
                        result = DeterministicOracleRuntime().evaluate(verification, actual[ref], {})
                        passed = result['passed']
                    except (ValueError, RuntimeError, TypeError):
                        passed = False
                    if not passed:
                        failed, reason = observed, 'CLEANUP_DATA_VERIFICATION_FAILED'
                        break
        if reason is None:
            raise CleanupError('N7_CLEANUP_FAILURE_REQUIRED')
        self.evidence.record(preparation_id)
        evidence_id = 'N7CLEANFAIL-' + _hash([failed['call_id'], reason, failed.get('receipt_sha256')])[:24]
        ref = 'r1://artifact/' + failed['call_id']
        self.evidence._ensure('rc7_evidence', 'RC7_EVIDENCE_UPSERTED', 'evidence_id', dict(
            evidence_id=evidence_id, release_id=p['release_id'], mission_id=p['mission_id'],
            kind='N7_CLEANUP_FAILURE', source_ref=ref, content_ref=ref,
            content_hash=_hash(failed), subject_refs=[p['workitem_id'], p['attempt_id']],
            failure_reason=reason, artifact_version=1))
        self.evidence._ensure('evidence', 'EVIDENCE_UPSERTED', 'id', dict(
            id=evidence_id, release_id=p['release_id'], kind='N7_CLEANUP_FAILURE', ref=ref,
            source_artifact_ref=failed['call_id'], requirement_id=c['requirement_id'],
            tc_id=p['case_id'], attempt_id=p['attempt_id'], artifact_version=1))
        return DiagnosisOrchestrator(self.truth, release_id=p['release_id'],
            state_machine=RC72StateMachine(self.truth, release_id=p['release_id']),
            worker_lifecycle=self.preparation.lifecycle).begin_failure_diagnosis(
                mission_id=p['mission_id'], team_id='TEAM-' + p['mission_id'],
                source_binding_id=p['binding_id'], failure_evidence_refs=[evidence_id],
                executable_contract_refs=[p['contract_id']], reason=reason)


install_rc72_n7_cleanup_overlay()
