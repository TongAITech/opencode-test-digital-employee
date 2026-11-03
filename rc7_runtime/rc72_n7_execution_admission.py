"""Read-only execution preflight followed by a replay-safe R1 admission receipt.

An admission is neither an execution result nor authority to use resources.
Every consumer must call assert_current immediately before acquiring scoped
leases/dispatching. Historical N6 PASS or an old admission never bypasses a
current dependency, payload-integrity, canonical-data or expiry failure.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional

from rc6_runtime import contracts, truth as registry
from rc6_runtime.truth import TruthRuntime
from .models import ContractError
from .rc72_canonical_design import CanonicalDesignService
from .rc72_canonical_executable import approved_case_payload
from .rc72_n1_executable_binding import N1ExecutableBindingService
from .rc72_domain import AutonomousMissionNode
from .rc72_n5_data_inventory import N5DataRequirementInventoryService
from .rc72_n5_data_resolution import N5DataResolutionService
from .rc72_n6_completion import N6DeliveryGateService, _digest as contract_digest, _stable_id as contract_id_for
from .rc72_n6_executable_readiness import canonical_n5_data_ref
from .truth_overlay import install_rc7_truth_overlay

_ARTIFACT = 'rc72_n7_execution_admission'
_EVENT = 'RC72_N7_EXECUTION_ADMISSION_UPSERTED'
_UPSTREAM = tuple(AutonomousMissionNode.ordered()[:6])


class ExecutionAdmissionError(ContractError):
    pass


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionAdmissionError('N7_%s_REQUIRED' % name.upper())
    return value.strip()


def _validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise contracts.DomainValidationError('ARTIFACT_MUST_BE_OBJECT')
    out = dict(payload)
    for name in ('admission_id', 'release_id', 'source_commit', 'release_batch_id',
                 'mission_id', 'mission_node_id', 'contract_id', 'case_id',
                 'requirement_id', 'sst_id', 'obligation_id', 'input_digest'):
        out[name] = contracts._require_str(out, name)
    if out.get('status') != 'ADMITTED':
        raise contracts.DomainValidationError('N7_ADMISSION_STATUS_INVALID')
    digest = out['input_digest']
    if len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest):
        raise contracts.DomainValidationError('N7_ADMISSION_DIGEST_INVALID')
    parents = out.get('upstream_refs')
    if not isinstance(parents, list) or len(parents) != 6 or not all(isinstance(x, dict) for x in parents):
        raise contracts.DomainValidationError('N7_ADMISSION_UPSTREAM_REFS_INVALID')
    for name in ('actual_result', 'assertion_result', 'execution_result', 'data_lease_id',
                 'data_leases', 'field_verified', 'bank_final', 'n7_pass'):
        if name in out:
            raise contracts.DomainValidationError('N7_ADMISSION_PREMATURE_CLAIM:%s' % name)
    out['artifact_type'] = _ARTIFACT
    out['artifact_version'] = contracts._artifact_version(out)
    return out


def install_rc72_n7_execution_admission_overlay() -> None:
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_ARTIFACT] = _validate
    registry.EVENT_TYPES[_EVENT] = (_ARTIFACT, 'admission_id')
    registry.BUCKETS[_ARTIFACT] = 'rc72_n7_execution_admissions'
    registry.IDENTITY_FIELDS[_ARTIFACT] = 'admission_id'


class ExecutionAdmissionService:
    def __init__(self, truth: TruthRuntime, *, release_id: str, source_commit: str,
                 now: Optional[datetime] = None):
        install_rc72_n7_execution_admission_overlay()
        self.truth = truth
        self.release_id = _required(release_id, 'release_id')
        self.source_commit = _required(source_commit, 'source_commit')
        if len(self.source_commit) != 40 or any(ch not in '0123456789abcdef' for ch in self.source_commit):
            raise ExecutionAdmissionError('N7_SOURCE_COMMIT_INVALID')
        self.now = now

    def _one(self, kind: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ExecutionAdmissionError('N7_TRUTH_NOT_UNIQUE:%s:%s' % (kind, len(rows)))
        return rows[0]

    def _active_pass(self, mission_id: str, batch_id: str, node_type: AutonomousMissionNode):
        node = self._one('rc72_mission_node', mission_id=mission_id, node_type=node_type.value)
        if node.get('release_id') != self.release_id or node.get('scope_ref') != 'release-batch://' + batch_id:
            raise ExecutionAdmissionError('N7_UPSTREAM_SCOPE_MISMATCH:%s' % node_type.value)
        if node.get('state') != 'PASS' or node.get('open_gap_refs'):
            raise ExecutionAdmissionError('N7_UPSTREAM_NOT_PASS:%s' % node_type.value)
        deliveries = [row for row in self.truth.query('rc72_node_delivery', mission_node_id=node['mission_node_id'])
                      if row.get('version') == node.get('active_delivery_version')
                      and row.get('delivery_id') in node.get('delivery_refs', [])]
        if len(deliveries) != 1:
            raise ExecutionAdmissionError('N7_ACTIVE_DELIVERY_NOT_UNIQUE:%s' % node_type.value)
        delivery = deliveries[0]
        if (delivery.get('mission_id') != mission_id or delivery.get('release_id') != self.release_id
                or delivery.get('node_type') != node_type.value or delivery.get('known_gaps')):
            raise ExecutionAdmissionError('N7_UPSTREAM_DELIVERY_INVALID:%s' % node_type.value)
        gates = [row for row in self.truth.query('rc72_node_gate', mission_node_id=node['mission_node_id'])
                 if row.get('gate_id') in node.get('gate_refs', [])
                 and row.get('delivery_id') == delivery['delivery_id']]
        if len(gates) != 1:
            raise ExecutionAdmissionError('N7_ACTIVE_GATE_NOT_UNIQUE:%s' % node_type.value)
        gate = gates[0]
        if (gate.get('mission_id') != mission_id or gate.get('release_id') != self.release_id
                or gate.get('node_type') != node_type.value or gate.get('decision') != 'PASS'
                or gate.get('failed') or not gate.get('criteria')
                or set(gate.get('criteria', [])) != set(gate.get('passed', []))):
            raise ExecutionAdmissionError('N7_UPSTREAM_GATE_INVALID:%s' % node_type.value)
        return node, delivery, gate

    def _check(self, batch_id: str, contract_id: str, *, review_only=False) -> Dict[str, Any]:
        batch = self._one('rc72_release_batch', release_batch_id=batch_id)
        if batch.get('release_id') != self.release_id:
            raise ExecutionAdmissionError('N7_RELEASE_MISMATCH')
        mission_id = str(batch['mission_id'])
        n7 = self._one('rc72_mission_node', mission_id=mission_id, node_type='N7_EXECUTION')
        if (n7.get('release_id') != self.release_id or n7.get('scope_ref') != 'release-batch://' + batch_id
                or n7.get('state') not in ({'READY', 'RUNNING', 'REVIEW_PENDING', 'PASS'} if review_only else {'READY', 'RUNNING'})
                or n7.get('open_gap_refs')):
            raise ExecutionAdmissionError('N7_NODE_NOT_ADMITTED')
        upstream = [self._active_pass(mission_id, batch_id, kind) for kind in _UPSTREAM]
        n6_delivery = upstream[-1][1]
        if contract_id not in n6_delivery.get('artifact_refs', []):
            raise ExecutionAdmissionError('N7_CONTRACT_NOT_IN_ACTIVE_DELIVERY')
        if not {'n5-delivery://' + upstream[-2][1]['delivery_id'],
                'n5-gate://' + upstream[-2][2]['gate_id']}.issubset(set(n6_delivery.get('input_refs', []))):
            raise ExecutionAdmissionError('N7_N6_PARENT_BINDING_STALE')
        requirements = N5DataRequirementInventoryService(
            self.truth, source_commit=self.source_commit,
        ).current_requirements(release_batch_id=batch_id)
        contracts_in_delivery = [self._one('rc72_n6_executable_contract', contract_id=value)
                                 for value in n6_delivery.get('artifact_refs', [])]
        if (len({row['case_id'] for row in contracts_in_delivery}) != len(contracts_in_delivery)
                or {row['case_id'] for row in contracts_in_delivery} != {row['case_id'] for row in requirements}):
            raise ExecutionAdmissionError('N7_CONTRACT_DENOMINATOR_MISMATCH')
        contract = self._one('rc72_n6_executable_contract', contract_id=contract_id)
        if (contract.get('release_id') != self.release_id or contract.get('source_commit') != self.source_commit
                or contract.get('release_batch_id') != batch_id or contract.get('mission_id') != mission_id):
            raise ExecutionAdmissionError('N7_CONTRACT_LINEAGE_MISMATCH')
        if contract.get('contract_sha256') != contract_digest(contract):
            raise ExecutionAdmissionError('N7_CONTRACT_DIGEST_INVALID')
        n6 = N6DeliveryGateService(self.truth, release_id=self.release_id,
                                   source_commit=self.source_commit, now=self.now)
        if not n6._runtime_ok(contract):
            raise ExecutionAdmissionError('N7_RUNTIME_BINDINGS_UNRESOLVED')
        expected = {row['data_requirement_id']: row for row in requirements if row['case_id'] == contract['case_id']}
        refs = contract.get('data_refs') or []
        if len(refs) != len(expected) or {row.get('data_requirement_id') for row in refs} != set(expected):
            raise ExecutionAdmissionError('N7_DATA_REQUIREMENT_DENOMINATOR_MISMATCH')
        resolver = N5DataResolutionService(self.truth, release_id=self.release_id, source_commit=self.source_commit)
        bindings = []
        for ref in refs:
            requirement = expected[ref['data_requirement_id']]
            if any(contract.get(key) != requirement.get(key) for key in
                   ('release_batch_id', 'mission_id', 'requirement_id', 'sst_id', 'obligation_id', 'case_id')):
                raise ExecutionAdmissionError('N7_CASE_LINEAGE_MISMATCH')
            binding = resolver.verified_binding(data_requirement_id=requirement['data_requirement_id'])
            canonical = canonical_n5_data_ref(binding, requirement)
            if any(ref.get(key) != value for key, value in canonical.items()):
                raise ExecutionAdmissionError('N7_DATA_REF_STALE')
            if not n6._data_ref_current(contract, ref):
                raise ExecutionAdmissionError('N7_DATA_REF_EXPIRED')
            bindings.append(binding)
        design = CanonicalDesignService(self.truth, release_id=self.release_id,
                                         source_commit=self.source_commit).load(release_batch_id=batch_id)
        obligation = self._one('rc72_test_obligation', obligation_id=contract['obligation_id'])
        expected_obligation = next((item for item in design.obligations
                                    if item.obligation_id == contract['obligation_id']), None)
        if (expected_obligation is None or obligation.get('release_id') != self.release_id
                or obligation.get('mission_id') != mission_id or obligation.get('release_batch_id') != batch_id
                or obligation.get('requirement_id') != contract['requirement_id']
                or obligation.get('sst_id') != contract['sst_id']
                or obligation.get('change_refs') != expected_obligation.change_refs):
            raise ExecutionAdmissionError('N7_CANONICAL_OBLIGATION_STALE')
        case = next((item for item in design.cases if item['tc_id'] == contract['case_id']), None)
        if case is None:
            raise ExecutionAdmissionError('N7_CASE_NOT_IN_APPROVED_N4')
        approved = approved_case_payload(case, mission_id=mission_id)
        for actual, key in (('case_ref', 'case_ref'), ('preconditions', 'preconditions'),
                            ('steps', 'steps'), ('input', 'inputs'), ('oracles', 'oracles'),
                            ('evidence_required', 'evidence_requirements')):
            if contract.get(actual) != approved.get(key):
                raise ExecutionAdmissionError('N7_CASE_SEMANTICS_CHANGED:%s' % actual)
        expected_assertions = approved['assertions']
        if (contract.get('assertions') != expected_assertions
                or contract.get('request') != case['execution']['request']
                or contract.get('cleanup') != case['execution']['cleanup']):
            raise ExecutionAdmissionError('N7_CASE_SEMANTICS_CHANGED:assertion/request/cleanup')
        runtime = N1ExecutableBindingService(self.truth, source_commit=self.source_commit).canonicalize(
            release_batch_id=batch_id, binding_key=case['execution']['binding_key'], persist=False,
        )
        if any(contract.get(key) != runtime.get(key) for key in
               ('environment', 'endpoint', 'tool_route', 'capabilities', 'resources')):
            raise ExecutionAdmissionError('N7_N1_RUNTIME_BINDING_STALE')
        # The N6 delivery approved immutable content-addressed identities, not
        # just whatever payload happens to occupy that identity at query time.
        for row in contracts_in_delivery:
            if (row.get('source_commit') != self.source_commit
                    or row.get('mission_id') != mission_id
                    or row.get('release_batch_id') != batch_id
                    or row.get('release_id') != self.release_id
                    or row.get('contract_sha256') != contract_digest(row)
                    or row['contract_id'] != contract_id_for(
                        'N6CONTRACT', mission_id, row['case_id'], row['contract_sha256'])):
                raise ExecutionAdmissionError('N7_APPROVED_CONTRACT_IDENTITY_CHANGED')
        parent_refs = [dict(node_type=kind.value, node_id=node['mission_node_id'],
                            delivery_id=delivery['delivery_id'], gate_id=gate['gate_id'],
                            digest=_hash([node, delivery, gate]))
                       for kind, (node, delivery, gate) in zip(_UPSTREAM, upstream)]
        signature = _hash(dict(contract=contract, upstream=parent_refs,
                               requirements=list(expected.values()), bindings=bindings))
        return dict(release_id=self.release_id, source_commit=self.source_commit,
                    release_batch_id=batch_id, mission_id=mission_id,
                    mission_node_id=n7['mission_node_id'], contract_id=contract_id,
                    case_id=contract['case_id'], requirement_id=contract['requirement_id'],
                    sst_id=contract['sst_id'], obligation_id=contract['obligation_id'],
                    input_digest=signature, upstream_refs=parent_refs)

    def admit(self, *, release_batch_id: str, contract_id: str) -> Dict[str, Any]:
        payload = self._check(_required(release_batch_id, 'release_batch_id'),
                              _required(contract_id, 'contract_id'))
        payload.update(admission_id='N7ADM-' + _hash(payload)[:24], status='ADMITTED', artifact_version=1)
        existing = self.truth.query(_ARTIFACT, admission_id=payload['admission_id'])
        if existing:
            if len(existing) != 1 or any(existing[0].get(key) != value for key, value in payload.items()):
                raise ExecutionAdmissionError('N7_ADMISSION_REPLAY_CONFLICT')
            return existing[0]
        self.truth.append_atomic(_EVENT, payload)
        return self._one(_ARTIFACT, admission_id=payload['admission_id'])

    def _current_input(self, admission_id: str):
        # One complete current-source decision returns both the authenticated
        # receipt and its freshly reconstructed inputs. Callers must not rebuild
        # the identical whole-release inputs a second time just to obtain them.
        receipt = self._one(_ARTIFACT, admission_id=_required(admission_id, 'admission_id'))
        current = self._check(receipt['release_batch_id'], receipt['contract_id'])
        if receipt.get('status') != 'ADMITTED' or any(receipt.get(key) != value for key, value in current.items()):
            raise ExecutionAdmissionError('N7_ADMISSION_STALE')
        return receipt, current

    def assert_current(self, admission_id: str) -> Dict[str, Any]:
        receipt, _current = self._current_input(admission_id)
        return receipt

    def assert_review_current(self, admission_id: str) -> Dict[str, Any]:
        """Read-only current-source evidence check, never execution admission.

        Source/data/runtime checks remain identical. Review may be pending or
        finalized; admit/assert_current retain the live READY/RUNNING gate.
        """
        receipt = self._one(_ARTIFACT, admission_id=_required(admission_id, 'admission_id'))
        current = self._check(receipt['release_batch_id'], receipt['contract_id'], review_only=True)
        if receipt.get('status') != 'ADMITTED' or any(receipt.get(key) != value for key, value in current.items()):
            raise ExecutionAdmissionError('N7_REVIEW_ADMISSION_STALE')
        return receipt


install_rc72_n7_execution_admission_overlay()
