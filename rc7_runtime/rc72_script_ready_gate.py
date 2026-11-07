"""GAP-01 formal SCRIPT_READY producer: signed native N6 provenance, never an RC6 string Gate.

This is not a second Mission state machine. Real N6 creates the canonical
Delivery/NodeGate; the approved Host countersigns its independently re-audited
Case denominator and current executable contracts before N7 may use it.
Legacy mission_gate_commit cannot mint or substitute this admission.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

from rc6_runtime import contracts, truth as registry
from rc6_runtime.truth import TruthRuntime
from .models import ContractError
from .rc72_authority import RC72AuthorityRuntime
from .rc72_canonical_design import CanonicalDesignService
from .rc72_n7_execution_admission import ExecutionAdmissionService
from .rc72_n6_pipeline import N6PipelineService
from .rc72_captain_dispatch_fencing import install_captain_dispatch_overlay
from .rc72_mission_factory import MissionCaptainBinding
from .truth_overlay import install_rc7_truth_overlay

_KIND = 'rc72_script_ready_admission'
_EVENT = 'RC72_SCRIPT_READY_ADMISSION_UPSERTED'
_PURPOSE = 'RC72_SIGNED_NATIVE_N6_SCRIPT_READY_V1'


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode('utf-8')).hexdigest()


def _validate(value):
    if not isinstance(value, dict):
        raise contracts.DomainValidationError('SCRIPT_READY_PAYLOAD_INVALID')
    row = dict(value)
    for key in ('admission_id', 'purpose', 'release_id', 'mission_id',
                'release_batch_id', 'source_commit', 'n6_delivery_id',
                'n6_gate_id', 'contract_digest', 'captain_lease_id',
                'captain_session_id', 'team_id', 'signature', 'status'):
        contracts._require_str(row, key)
    if row['purpose'] != _PURPOSE or row['status'] != 'ADMITTED':
        raise contracts.DomainValidationError('SCRIPT_READY_ADMISSION_PURPOSE_OR_STATUS_INVALID')
    contracts._require_string_list(row, 'case_ids', nonempty=True)
    contracts._require_string_list(row, 'contract_ids', nonempty=True)
    if (row['case_ids'] != sorted(set(row['case_ids']))
            or row['contract_ids'] != sorted(set(row['contract_ids']))
            or row.get('case_count') != len(row['case_ids'])
            or type(row.get('captain_generation')) is not int
            or row['captain_generation'] < 1
            or len(row['contract_digest']) != 64
            or any(ch not in '0123456789abcdef' for ch in row['contract_digest'])):
        raise contracts.DomainValidationError('SCRIPT_READY_ADMISSION_DENOMINATOR_INVALID')
    for forbidden in ('bank_final', 'field_verified', 'case_pass', 'execution_result', 'assertion_result'):
        if forbidden in row:
            raise contracts.DomainValidationError('SCRIPT_READY_PREMATURE_CLAIM_FORBIDDEN')
    row['artifact_type'] = _KIND
    row['artifact_version'] = contracts._artifact_version(row)
    return row


def install_script_ready_admission_overlay():
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'admission_id')
    registry.BUCKETS[_KIND] = 'rc72_script_ready_admissions'
    registry.IDENTITY_FIELDS[_KIND] = 'admission_id'


class NativeScriptReadyGateProducer:
    """Only an approved Host Captain + independent native N6 producer can write.

    Both inspect and issue use live R1, not a model's narrative or a user
    selected evidence_ref. Repeating issue is idempotent with zero new writes.
    """

    def __init__(self, truth, *, release_id, source_commit, authority=None):
        install_script_ready_admission_overlay()
        self.truth = truth
        self.release_id = release_id
        self.source_commit = source_commit
        self.authority = authority

    @staticmethod
    def _hold(reason, **facts):
        return dict(status='HOLD', reason=reason, field_verified=False,
                    bank_final=False, **facts)

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError('SCRIPT_READY_TRUTH_NOT_UNIQUE:%s:%d' % (kind, len(rows)))
        return rows[0]

    def _native(self, release_batch_id):
        batch = self._one('rc72_release_batch', release_batch_id=release_batch_id)
        if batch['release_id'] != self.release_id:
            raise ContractError('SCRIPT_READY_RELEASE_SCOPE_MISMATCH')
        mission = batch['mission_id']
        n6 = self._one('rc72_mission_node', mission_id=mission,
                       node_type='N6_EXECUTABLE_READINESS')
        n7 = self._one('rc72_mission_node', mission_id=mission,
                       node_type='N7_EXECUTION')
        if (n6['state'] != 'PASS' or n7['state'] not in
                {'READY', 'RUNNING', 'REVIEW_PENDING', 'PASS'}):
            raise ContractError('SCRIPT_READY_NATIVE_N6_N7_NOT_ADMITTED')
        active = [row for row in self.truth.query('rc72_node_delivery',
                                                  mission_node_id=n6['mission_node_id'])
                  if row.get('delivery_id') in n6.get('delivery_refs', [])
                  and row.get('version') == n6.get('active_delivery_version')]
        if len(active) != 1:
            raise ContractError('SCRIPT_READY_ACTIVE_DELIVERY_NOT_UNIQUE')
        delivery = active[0]
        gates = [row for row in self.truth.query('rc72_node_gate',
                                                 mission_node_id=n6['mission_node_id'])
                 if row.get('gate_id') in n6.get('gate_refs', [])
                 and row.get('delivery_id') == delivery['delivery_id']
                 and row.get('decision') == 'PASS']
        if (len(gates) != 1 or delivery.get('mission_id') != mission
                or delivery.get('node_type') != 'N6_EXECUTABLE_READINESS'
                or delivery.get('known_gaps')
                or not gates[0].get('criteria')
                or set(gates[0]['criteria']) != set(gates[0].get('passed', []))
                or gates[0].get('failed')
                or gates[0].get('mission_id') != mission):
            raise ContractError('SCRIPT_READY_NATIVE_N6_GATE_NOT_TRUSTED')
        design = CanonicalDesignService(self.truth, release_id=self.release_id,
                                        source_commit=self.source_commit).load(
                                            release_batch_id=release_batch_id)
        cases = sorted(case['tc_id'] for case in design.cases)
        if not cases or len(cases) != len(set(cases)):
            raise ContractError('SCRIPT_READY_FROZEN_CASE_DENOMINATOR_INVALID')
        contract_ids = sorted(delivery.get('artifact_refs', []))
        if len(contract_ids) != len(cases) or len(set(contract_ids)) != len(contract_ids):
            raise ContractError('SCRIPT_READY_N6_CONTRACT_DENOMINATOR_MISMATCH')
        admission = ExecutionAdmissionService(
            self.truth, release_id=self.release_id, source_commit=self.source_commit)
        inputs = []
        for contract_id in contract_ids:
            inputs.append(admission._check(release_batch_id, contract_id))
        if sorted(row['case_id'] for row in inputs) != cases:
            raise ContractError('SCRIPT_READY_N6_FROZEN_CASE_LINEAGE_MISMATCH')
        return dict(release_id=self.release_id, source_commit=self.source_commit,
                    release_batch_id=release_batch_id, mission_id=mission,
                    n6_delivery_id=delivery['delivery_id'],
                    n6_gate_id=gates[0]['gate_id'],
                    contract_digest=_hash(inputs), case_ids=cases,
                    contract_ids=contract_ids, case_count=len(cases))

    def inspect(self, *, release_batch_id):
        try:
            facts = self._native(release_batch_id)
        except (ContractError, ValueError, KeyError) as exc:
            return self._hold(str(exc))
        receipts = self.truth.query(_KIND, release_batch_id=release_batch_id,
                                    source_commit=self.source_commit)
        if not receipts:
            return self._hold('SCRIPT_READY_TRUSTED_HOST_ADMISSION_REQUIRED',
                              n6_gate_id=facts['n6_gate_id'], case_count=facts['case_count'])
        if len(receipts) != 1 or type(self.authority) is not RC72AuthorityRuntime:
            return self._hold('SCRIPT_READY_TRUSTED_SIGNER_OR_RECEIPT_REQUIRED')
        row = receipts[0]
        signed = {key: value for key, value in row.items()
                  if key not in ('signature', 'artifact_type', 'artifact_version')}
        if (not isinstance(row.get('signature'), str)
                or not hmac.compare_digest(row['signature'],
                                           self.authority._sign(signed))
                or any(row.get(key) != value for key, value in facts.items())
                or row.get('purpose') != _PURPOSE
                or row.get('status') != 'ADMITTED'):
            return self._hold('SCRIPT_READY_TRUSTED_SIGNATURE_OR_LINEAGE_INVALID')
        return dict(status='ADMITTED', admission_id=row['admission_id'],
                    n6_gate_id=row['n6_gate_id'], case_count=row['case_count'],
                    mission_id=row['mission_id'], field_verified=False, bank_final=False)

    def issue(self, *, release_batch_id, captain_binding):
        if type(self.authority) is not RC72AuthorityRuntime:
            raise ContractError('SCRIPT_READY_TRUSTED_SIGNER_REQUIRED')
        if type(captain_binding) is not MissionCaptainBinding:
            raise ContractError('SCRIPT_READY_REAL_CAPTAIN_BINDING_REQUIRED')
        governed = captain_binding.scheduler
        if (governed.truth is not self.truth
                or governed.release_id != self.release_id):
            raise ContractError('SCRIPT_READY_CAPTAIN_RUNTIME_SCOPE_MISMATCH')
        batch = self._one('rc72_release_batch', release_batch_id=release_batch_id)
        mission = batch['mission_id']
        owner = governed.fencer.assert_owner(
            mission_id=mission, lease_id=captain_binding.captain_lease_id,
            captain_session_id=captain_binding.captain_session_id)
        if owner.get('team_id') != captain_binding.team_id:
            raise ContractError('SCRIPT_READY_CAPTAIN_TEAM_SCOPE_MISMATCH')
        n6 = self._one('rc72_mission_node', mission_id=mission,
                       node_type='N6_EXECUTABLE_READINESS')
        if n6['state'] != 'PASS':
            if n6['state'] not in {'READY', 'RUNNING', 'REVIEW_PENDING'}:
                return self._hold('SCRIPT_READY_UPSTREAM_NODE_NOT_READY')
            result = N6PipelineService(self.truth, release_id=self.release_id,
                                       source_commit=self.source_commit).complete(
                                           release_batch_id=release_batch_id)
            if result.get('status') == 'HOLD':
                return self._hold(result.get('reason', 'SCRIPT_READY_N6_NOT_READY'))
        facts = self._native(release_batch_id)
        governed.fencer.assert_owner(
            mission_id=mission, lease_id=captain_binding.captain_lease_id,
            captain_session_id=captain_binding.captain_session_id)
        payload = dict(facts, purpose=_PURPOSE, status='ADMITTED',
                       captain_lease_id=owner['lease_id'],
                       captain_session_id=owner['captain_session_id'],
                       team_id=owner['team_id'],
                       captain_generation=owner['generation'])
        payload['admission_id'] = 'SCRIPTREADY-' + _hash(payload)[:24]
        signed = dict(payload)
        payload['signature'] = self.authority._sign(signed)
        existing = self.truth.query(_KIND, release_batch_id=release_batch_id,
                                    source_commit=self.source_commit)
        if existing:
            if (len(existing) != 1
                    or any(existing[0].get(k) != v for k, v in payload.items())
                    or existing[0].get('artifact_version') != 1):
                raise ContractError('SCRIPT_READY_ADMISSION_REPLAY_CONFLICT')
            return self.inspect(release_batch_id=release_batch_id)
        self.truth.append_atomic(_EVENT, dict(payload, artifact_version=1))
        return self.inspect(release_batch_id=release_batch_id)


install_script_ready_admission_overlay()
