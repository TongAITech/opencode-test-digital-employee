"""Evidence-bound native coverage repair and post-repair freshness fence.

A PATH_NOT_REACHED diagnosis is not a product defect or a repair.  The repair
boundary becomes active only after the queued professional investigation and a
separate bounded repair WorkItem both have accepted Artifact/Evidence/Evaluation
proof.  Once active, the original N7/Libra epoch cannot satisfy N10 again: a
new accepted N7 gate and a new accepted Libra observation are required before
the original coverage gap may be resolved.
"""
from __future__ import annotations

import hmac
import time

from rc6_runtime import contracts, truth as registry

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Task
from .rc72_coverage_convergence import CoverageFeedbackService
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash

_KIND = 'rc72_native_coverage_repair'
_EVENT = 'RC72_NATIVE_COVERAGE_REPAIR_UPSERTED'
_CAPABILITY = 'coverage_path_repair'


def _validate(payload):
    row = dict(payload)
    for key in (
        'repair_id', 'release_id', 'source_commit', 'mission_id', 'release_batch_id',
        'application_id', 'gap_id', 'diagnosis_id', 'investigation_workitem_id',
        'repair_workitem_id', 'origin_measurement_id', 'origin_n7_gate_id',
        'repair_proof_sha256', 'signature',
    ):
        contracts._require_str(row, key)
    if row.get('purpose') != 'NATIVE_COVERAGE_POST_REPAIR_FRESHNESS':
        raise contracts.DomainValidationError('NATIVE_COVERAGE_REPAIR_PURPOSE_INVALID')
    if row.get('state') not in {'FRESH_N7_REQUIRED', 'CLOSED'}:
        raise contracts.DomainValidationError('NATIVE_COVERAGE_REPAIR_STATE_INVALID')
    if not isinstance(row.get('origin_n7_node_artifact_version'), int) or row['origin_n7_node_artifact_version'] < 1:
        raise contracts.DomainValidationError('NATIVE_COVERAGE_REPAIR_N7_VERSION_INVALID')
    if not isinstance(row.get('origin_n7_delivery_version'), int) or row['origin_n7_delivery_version'] < 1:
        raise contracts.DomainValidationError('NATIVE_COVERAGE_REPAIR_DELIVERY_VERSION_INVALID')
    for key in ('repair_artifact_refs', 'repair_evidence_refs'):
        value = row.get(key)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            raise contracts.DomainValidationError('NATIVE_COVERAGE_REPAIR_PROOF_REFS_INVALID')
    if any(key in row for key in ('product_defect', 'root_cause_proved', 'field_verified', 'bank_final', 'converged')):
        raise contracts.DomainValidationError('NATIVE_COVERAGE_REPAIR_CLAIM_FORBIDDEN')
    if row['state'] == 'CLOSED':
        for key in ('fresh_measurement_id', 'fresh_n7_gate_id', 'verification_id'):
            contracts._require_str(row, key)
        if row['fresh_n7_gate_id'] == row['origin_n7_gate_id']:
            raise contracts.DomainValidationError('NATIVE_COVERAGE_REPAIR_FRESH_N7_REQUIRED')
    row.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(row))
    return row


def install_overlay():
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'repair_id')
    registry.IDENTITY_FIELDS[_KIND] = 'repair_id'
    registry.BUCKETS[_KIND] = 'rc72_native_coverage_repairs'


def _signed(row, authority):
    raw = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
    if not hmac.compare_digest(row['signature'], authority._sign(raw)):
        raise ContractError('NATIVE_COVERAGE_REPAIR_SIGNATURE_INVALID')
    return row


def active_repair_boundaries(truth, authority, *, release_id, source_commit, release_batch_id, application_id):
    """Return validated active fences without creating or repairing anything."""
    install_overlay()
    rows = []
    for row in truth.query(_KIND, release_batch_id=release_batch_id, application_id=application_id):
        _signed(row, authority)
        if row['release_id'] != release_id or row['source_commit'] != source_commit:
            raise ContractError('NATIVE_COVERAGE_REPAIR_SOURCE_CHANGED')
        if row['state'] == 'FRESH_N7_REQUIRED':
            rows.append(row)
    return sorted(rows, key=lambda item: item['repair_id'])


class NativeCoverageRepairService:
    def __init__(self, diagnosis):
        # Delayed import avoids Libra -> repair fence -> diagnosis -> Libra cycles.
        from .rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService
        if not isinstance(diagnosis, NativeCoveragePathDiagnosisService):
            raise ContractError('NATIVE_COVERAGE_DIAGNOSIS_REQUIRED')
        install_overlay()
        self.diagnosis = diagnosis
        self.intake = diagnosis.intake
        self.measurement = diagnosis.measurement
        self.truth = diagnosis.truth
        self.authority = diagnosis.authority
        self.release_id = diagnosis.release_id
        self.source_commit = diagnosis.source_commit

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError('NATIVE_COVERAGE_REPAIR_TRUTH_NOT_UNIQUE:' + kind)
        return rows[0]

    def _persist(self, row):
        raw = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
        old = self.truth.query(_KIND, repair_id=raw['repair_id'])
        self.truth.append_atomic(_EVENT, dict(
            raw,
            signature=self.authority._sign(raw),
            artifact_version=old[0]['artifact_version'] + 1 if old else 1,
        ))
        return self._one(_KIND, repair_id=raw['repair_id'])

    def _composition(self):
        if (self.diagnosis.intake is not self.intake or self.intake.measurement is not self.measurement
                or self.diagnosis.truth is not self.truth or self.measurement.truth is not self.truth
                or self.diagnosis.authority is not self.authority or self.measurement.authority is not self.authority
                or self.diagnosis.source_commit != self.source_commit or self.measurement.source_commit != self.source_commit):
            raise ContractError('NATIVE_COVERAGE_REPAIR_COMPOSITION_CHANGED')

    def _accepted_task(self, task_id, *, task_type, capability, gap_id):
        task = self._one('rc7_task', task_id=task_id)
        if (task['release_id'] != self.release_id or task['task_type'] != task_type
                or task['required_capabilities'] != [capability] or task['gap_refs'] != [gap_id]):
            raise ContractError('NATIVE_COVERAGE_REPAIR_WORKITEM_SCOPE_CHANGED')
        if task['state'] != 'PASS':
            return None
        if not task.get('evaluation_id') or not task.get('output_artifact_refs'):
            raise ContractError('NATIVE_COVERAGE_REPAIR_ACCEPTED_PROOF_REQUIRED')
        evaluation = self._one('rc7_evaluation', evaluation_id=task['evaluation_id'])
        if (evaluation['result'] != 'PASS' or evaluation['mission_id'] != task['mission_id']
                or evaluation['artifact_refs'] != task['output_artifact_refs'] or not evaluation.get('evidence_refs')):
            raise ContractError('NATIVE_COVERAGE_REPAIR_ACCEPTED_PROOF_CHANGED')
        artifacts = [self._one('rc7_artifact', artifact_id=ref) for ref in task['output_artifact_refs']]
        if any(artifact['producer_task_id'] != task_id or artifact['mission_id'] != task['mission_id']
               or artifact['state'] != 'VALID' or not artifact.get('evidence_refs') for artifact in artifacts):
            raise ContractError('NATIVE_COVERAGE_REPAIR_ACCEPTED_ARTIFACT_CHANGED')
        evidence_refs = list(dict.fromkeys(evaluation['evidence_refs'] + [ref for artifact in artifacts for ref in artifact['evidence_refs']]))
        evidences = [self._one('rc7_evidence', evidence_id=ref) for ref in evidence_refs]
        if any(evidence['mission_id'] != task['mission_id'] for evidence in evidences):
            raise ContractError('NATIVE_COVERAGE_REPAIR_ACCEPTED_EVIDENCE_CHANGED')
        return dict(task=task, evaluation=evaluation, artifacts=artifacts, evidences=evidences,
                    artifact_refs=list(task['output_artifact_refs']), evidence_refs=evidence_refs)

    def _diagnosed(self, release_batch_id, application_id, gap_id):
        self._composition()
        rows = self.truth.query('rc72_native_coverage_diagnosis', gap_id=gap_id)
        if not rows:
            return None
        if len(rows) != 1:
            raise ContractError('NATIVE_COVERAGE_REPAIR_DIAGNOSIS_NOT_UNIQUE')
        result = self.diagnosis.audit(release_batch_id=release_batch_id, application_id=application_id, gap_id=gap_id)
        if result.get('status') != 'COVERAGE_PATH_DIAGNOSIS_QUEUED':
            raise ContractError('NATIVE_COVERAGE_REPAIR_ACCEPTED_DIAGNOSIS_REQUIRED')
        receipt = self._one('rc72_native_coverage_diagnosis', diagnosis_id=result['diagnosis_id'])
        gap = self._one('rc72_coverage_gap', gap_id=gap_id)
        if (gap['status'] != 'CLASSIFIED' or gap['gap_reason'] != 'PATH_NOT_REACHED'
                or gap['responsible_nodes'] != ['N8_DIAGNOSIS_RECOVERY'] or gap['action'] != 'DIAGNOSE_PATH'
                or not gap.get('obligation_id') or len(gap.get('candidate_obligation_ids') or []) != 1
                or gap['release_batch_id'] != release_batch_id or gap['application_id'] != application_id):
            raise ContractError('NATIVE_COVERAGE_REPAIR_CLASSIFIED_PATH_REQUIRED')
        investigation = self._one('rc7_task', task_id=result['investigation_workitem_id'])
        return result, receipt, gap, investigation

    def prepare(self, *, release_batch_id, application_id, gap_id):
        diagnosed = self._diagnosed(release_batch_id, application_id, gap_id)
        if diagnosed is None:
            return dict(status='HOLD', reason='ACCEPTED_COVERAGE_PATH_DIAGNOSIS_REQUIRED', gap_id=gap_id)
        result, receipt, gap, investigation = diagnosed
        accepted = self._accepted_task(investigation['task_id'], task_type='COVERAGE_PATH_INVESTIGATION',
                                       capability='coverage_path_investigation', gap_id=gap_id)
        if accepted is None:
            return dict(status='HOLD', reason='COVERAGE_PATH_INVESTIGATION_NOT_ACCEPTED', gap_id=gap_id,
                        investigation_workitem_id=investigation['task_id'])
        repair_workitem_id = 'COV-REPAIR-WI-' + _hash([receipt['diagnosis_id'], investigation['task_id']])[:24]
        inputs = list(dict.fromkeys(accepted['artifact_refs'] + self._one('rc7_task', task_id=receipt['workitem_id'])['output_artifact_refs']))
        control = ClosedLoopControlPlane(self.truth, self.release_id, receipt['mission_id'])
        existing = self.truth.query('rc7_task', task_id=repair_workitem_id)
        if not existing:
            control.register_task(Task(
                task_id=repair_workitem_id,
                mission_id=receipt['mission_id'],
                node='DIAGNOSIS',
                task_type='COVERAGE_PATH_REPAIR_EXECUTION',
                objective='execute bounded coverage repair from independently accepted path investigation',
                required_capabilities=[_CAPABILITY],
                input_artifact_refs=inputs,
                gap_refs=[gap_id],
                acceptance_criteria=[
                    'actual bounded repair evidence is captured',
                    'repair remains bound to the original gap and accepted diagnosis',
                    'no product-defect or root-cause claim is inferred from PATH_NOT_REACHED',
                    'a fresh N7 execution is required after accepted repair',
                ],
                priority=0,
            ))
        repair_task = self._one('rc7_task', task_id=repair_workitem_id)
        if (repair_task['mission_id'] != receipt['mission_id'] or repair_task['node'] != 'DIAGNOSIS'
                or repair_task['task_type'] != 'COVERAGE_PATH_REPAIR_EXECUTION'
                or repair_task['required_capabilities'] != [_CAPABILITY]
                or repair_task['input_artifact_refs'] != inputs or repair_task['gap_refs'] != [gap_id]):
            raise ContractError('NATIVE_COVERAGE_REPAIR_WORKITEM_SCOPE_CHANGED')
        return dict(status='REPAIR_WORKITEM_READY', gap_id=gap_id, diagnosis_id=receipt['diagnosis_id'],
                    investigation_workitem_id=investigation['task_id'], repair_workitem_id=repair_workitem_id,
                    repair_workitem_state=repair_task['state'])

    def activate(self, *, release_batch_id, application_id, gap_id):
        prepared = self.prepare(release_batch_id=release_batch_id, application_id=application_id, gap_id=gap_id)
        if prepared.get('status') == 'HOLD':
            return prepared
        accepted = self._accepted_task(prepared['repair_workitem_id'], task_type='COVERAGE_PATH_REPAIR_EXECUTION',
                                       capability=_CAPABILITY, gap_id=gap_id)
        if accepted is None:
            return dict(prepared, status='HOLD', reason='COVERAGE_PATH_REPAIR_EXECUTION_NOT_ACCEPTED')
        diagnosed = self._diagnosed(release_batch_id, application_id, gap_id)
        result, receipt, gap, investigation = diagnosed
        report = self._one('rc72_libra_measurement', measurement_id=receipt['measurement_id'])
        n7 = self._one('rc72_mission_node', mission_id=receipt['mission_id'], node_type='N7_EXECUTION')
        if n7['state'] != 'PASS' or report['n7_gate_id'] not in n7['gate_refs']:
            raise ContractError('NATIVE_COVERAGE_REPAIR_ORIGIN_N7_CHANGED')
        repair_id = 'COV-REPAIR-' + _hash([receipt['diagnosis_id'], prepared['repair_workitem_id'], report['measurement_id']])[:24]
        proof_hash = _hash([accepted['task'], accepted['evaluation'], accepted['artifacts'], accepted['evidences']])
        expected = dict(
            repair_id=repair_id,
            purpose='NATIVE_COVERAGE_POST_REPAIR_FRESHNESS',
            release_id=self.release_id,
            source_commit=self.source_commit,
            mission_id=receipt['mission_id'],
            release_batch_id=release_batch_id,
            application_id=application_id,
            gap_id=gap_id,
            diagnosis_id=receipt['diagnosis_id'],
            investigation_workitem_id=investigation['task_id'],
            repair_workitem_id=prepared['repair_workitem_id'],
            origin_measurement_id=report['measurement_id'],
            origin_n7_gate_id=report['n7_gate_id'],
            origin_n7_node_artifact_version=n7['artifact_version'],
            origin_n7_delivery_version=n7['active_delivery_version'],
            repair_proof_sha256=proof_hash,
            repair_artifact_refs=accepted['artifact_refs'],
            repair_evidence_refs=accepted['evidence_refs'],
            state='FRESH_N7_REQUIRED',
        )
        epoch = self.truth.store._next_seq
        with ledger_lock(self.truth, busy='NATIVE_COVERAGE_REPAIR_LEDGER_BUSY'):
            if self.truth.store._next_seq != epoch:
                raise ContractError('NATIVE_COVERAGE_REPAIR_SOURCE_CHANGED')
            old = self.truth.query(_KIND, repair_id=repair_id)
            if old:
                row = _signed(old[0], self.authority)
                for key, value in expected.items():
                    if row.get(key) != value and not (row['state'] == 'CLOSED' and key == 'state'):
                        raise ContractError('NATIVE_COVERAGE_REPAIR_BOUNDARY_CHANGED')
                return dict(status='CLOSED' if row['state'] == 'CLOSED' else 'FRESH_N7_REQUIRED',
                            repair_id=repair_id, gap_id=gap_id, origin_n7_gate_id=row['origin_n7_gate_id'],
                            repair_workitem_id=prepared['repair_workitem_id'])
            row = self._persist(dict(expected, opened_at=int(time.time())))
        return dict(status='FRESH_N7_REQUIRED', repair_id=repair_id, gap_id=gap_id,
                    origin_n7_gate_id=row['origin_n7_gate_id'], repair_workitem_id=prepared['repair_workitem_id'])

    def reconcile_application(self, *, release_batch_id, application_id):
        self._composition()
        active = active_repair_boundaries(self.truth, self.authority, release_id=self.release_id,
                                          source_commit=self.source_commit, release_batch_id=release_batch_id,
                                          application_id=application_id)
        if not active:
            return dict(status='NO_OPEN_COVERAGE_REPAIR')
        policy, proof = self.measurement._context(release_batch_id, audit_only=True)
        if any(row['origin_n7_gate_id'] == proof['n7_gate_id'] for row in active):
            return dict(status='HOLD', reason='POST_REPAIR_FRESH_N7_REQUIRED',
                        repair_ids=[row['repair_id'] for row in active])
        n7 = self._one('rc72_mission_node', mission_id=proof['mission_id'], node_type='N7_EXECUTION')
        for row in active:
            if (n7['state'] != 'PASS' or proof['n7_gate_id'] not in n7['gate_refs']
                    or n7['artifact_version'] <= row['origin_n7_node_artifact_version']
                    or n7['active_delivery_version'] <= row['origin_n7_delivery_version']):
                raise ContractError('NATIVE_COVERAGE_REPAIR_FRESH_N7_PROVENANCE_REQUIRED')
        actual = self.measurement.audit(release_batch_id=release_batch_id, application_id=application_id)
        if actual is None:
            return dict(status='HOLD', reason='POST_REPAIR_FRESH_LIBRA_REQUIRED',
                        repair_ids=[row['repair_id'] for row in active])
        fresh = self._one('rc72_libra_measurement', measurement_id=actual['measurement_id'])
        if fresh['n7_gate_id'] != proof['n7_gate_id']:
            raise ContractError('NATIVE_COVERAGE_REPAIR_FRESH_MEASUREMENT_CHANGED')
        feedback = CoverageFeedbackService(self.truth, release_id=self.release_id)
        closed = []
        for row in active:
            gap = self._one('rc72_coverage_gap', gap_id=row['gap_id'])
            if gap['status'] == 'RESOLVED':
                raise ContractError('NATIVE_COVERAGE_REPAIR_UNATTESTED_RESOLUTION')
            if gap['status'] != 'CLASSIFIED' or gap['gap_reason'] != 'PATH_NOT_REACHED':
                raise ContractError('NATIVE_COVERAGE_REPAIR_GAP_CHANGED')
            if gap['code_slice'] in actual.get('uncovered_code_slices', []):
                return dict(status='HOLD', reason='POST_REPAIR_COVERAGE_STILL_UNCOVERED', gap_id=gap['gap_id'],
                            fresh_measurement_id=fresh['measurement_id'])
            verification_id = 'COV-REPAIR-VERIFY-' + _hash([row['repair_id'], fresh['measurement_id']])[:24]
            if not self.truth.query('rc72_coverage_gap_verification', verification_id=verification_id):
                feedback.record_gap_verification(verification_id=verification_id, gap_id=gap['gap_id'],
                    observation_id=actual['observation_id'], uncovered_units_after=0,
                    evidence_ref='r1://artifact/' + fresh['measurement_id'])
            feedback.resolve_gap(gap_id=gap['gap_id'], verification_id=verification_id,
                evidence_refs=list(dict.fromkeys(row['repair_evidence_refs'] + ['r1://artifact/' + fresh['measurement_id']])),
                rationale='fresh accepted N7 and Libra observation prove the repaired code slice has zero uncovered units')
            current = self._one(_KIND, repair_id=row['repair_id'])
            _signed(current, self.authority)
            self._persist(dict(current, state='CLOSED', fresh_measurement_id=fresh['measurement_id'],
                               fresh_n7_gate_id=fresh['n7_gate_id'], verification_id=verification_id,
                               closed_at=int(time.time())))
            closed.append(row['repair_id'])
        return dict(status='COVERAGE_REPAIRS_CLOSED', repair_ids=closed,
                    fresh_measurement_id=fresh['measurement_id'], fresh_n7_gate_id=fresh['n7_gate_id'])


install_overlay()
