"""Derive gap intake from authenticated actual reports and existing lineage only."""
import hashlib,hmac,json
from collections import Counter
from pathlib import Path
from rc6_runtime import contracts,truth as registry
from .models import ContractError
from .rc72_libra_measurement import NativeLibraMeasurementService
from .rc72_n7_execution_admission import _hash
from .rc72_coverage_convergence import CoverageFeedbackService
from .rc72_ledger_lock import ledger_lock

_KIND='rc72_native_coverage_intake';_EVENT='RC72_NATIVE_COVERAGE_INTAKE_UPSERTED'
_FIELDS=('gap_id','observation_id','mission_id','release_batch_id','application_id','code_slice',
         'uncovered_units','candidate_obligation_ids','requirement_id','sst_id','obligation_id')


def _validate(payload):
    row=dict(payload)
    for key in ('intake_id','measurement_id','source_commit','release_id','release_batch_id','mission_id','body_sha256','signature'):
        contracts._require_str(row,key)
    if row.get('purpose')!='ACTUAL_COVERAGE_GAP_INTAKE' or row.get('state') not in {'BINDING','BOUND'}:
        raise contracts.DomainValidationError('NATIVE_COVERAGE_INTAKE_STATE_INVALID')
    if any(k in row for k in ('field_verified','bank_final','converged')):
        raise contracts.DomainValidationError('NATIVE_COVERAGE_INTAKE_CLAIM_FORBIDDEN')
    row.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(row));return row


def install_overlay():
    contracts.VALIDATORS[_KIND]=_validate
    registry.EVENT_TYPES[_EVENT]=(_KIND,'intake_id');registry.IDENTITY_FIELDS[_KIND]='intake_id'
    registry.BUCKETS[_KIND]='rc72_native_coverage_intakes'


class NativeCoverageGapIntakeService:
    def __init__(self,measurement):
        if not isinstance(measurement,NativeLibraMeasurementService):raise ContractError('NATIVE_COVERAGE_MEASUREMENT_REQUIRED')
        install_overlay();self.measurement=measurement
        self.truth,self.authority=measurement.truth,measurement.authority
        self.release_id,self.source_commit=measurement.release_id,measurement.source_commit

    def _persist(self,row):
        raw={k:v for k,v in row.items() if k not in {'artifact_type','artifact_version','signature'}}
        old=self.truth.query(_KIND,intake_id=raw['intake_id'])
        self.truth.append_atomic(_EVENT,dict(raw,signature=self.authority._sign(raw),artifact_version=old[0]['artifact_version']+1 if old else 1))
        return self.truth.query(_KIND,intake_id=raw['intake_id'])[0]

    def intake(self,*,release_batch_id,application_id):
        return self._run(release_batch_id,application_id,audit_only=False)

    def audit(self,*,release_batch_id,application_id):
        return self._run(release_batch_id,application_id,audit_only=True)

    def _run(self,release_batch_id,application_id,*,audit_only):
        if (not isinstance(self.measurement,NativeLibraMeasurementService) or self.measurement.truth is not self.truth
                or self.measurement.authority is not self.authority or self.measurement.source_commit!=self.source_commit):
            raise ContractError('NATIVE_COVERAGE_INTAKE_COMPOSITION_CHANGED')
        actual=self.measurement.audit(release_batch_id=release_batch_id,application_id=application_id)
        if actual is None:return dict(status='HOLD',reason='ACTUAL_MEASUREMENT_REQUIRED')
        epoch=self.truth.store._next_seq
        with ledger_lock(self.truth,busy='NATIVE_COVERAGE_INTAKE_LEDGER_BUSY'):
            if self.truth.store._next_seq!=epoch:raise ContractError('NATIVE_COVERAGE_INTAKE_SOURCE_CHANGED')
            report=self.measurement._one('rc72_libra_measurement',measurement_id=actual['measurement_id'])
            self.measurement._signed(report)
            path=Path(report['body_ref'][7:])
            if path.is_symlink() or not path.is_file() or path.stat().st_size>2097152:raise ContractError('NATIVE_COVERAGE_CAPTURE_REQUIRED')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=report['body_sha256']:raise ContractError('NATIVE_COVERAGE_CAPTURE_CHANGED')
            counts=Counter(unit['code_slice'] for unit in json.loads(raw.decode('utf-8-sig'))['units'] if not unit['covered'])
            if sorted(counts)!=actual['uncovered_code_slices'] or sum(counts.values())!=actual['total_units']-actual['covered_units']:
                raise ContractError('NATIVE_COVERAGE_ACTUAL_DENOMINATOR_CHANGED')
            feedback=CoverageFeedbackService(self.truth,release_id=self.release_id)
            observation=self.measurement._one('rc72_coverage_observation',observation_id=actual['observation_id'])
            mappings=[]
            for code_slice,count in sorted(counts.items()):
                matches=feedback._matching_obligations(observation,code_slice)
                unique=matches[0] if len(matches)==1 else {}
                mappings.append(dict(gap_id='NATIVE-CG-'+_hash([actual['measurement_id'],code_slice])[:24],
                    observation_id=actual['observation_id'],mission_id=report['mission_id'],release_batch_id=release_batch_id,
                    application_id=application_id,code_slice=code_slice,uncovered_units=count,
                    candidate_obligation_ids=[r['obligation_id'] for r in matches],
                    requirement_id=unique.get('requirement_id'),sst_id=unique.get('sst_id'),obligation_id=unique.get('obligation_id')))
            iid='COV-INTAKE-'+_hash(actual['measurement_id'])[:24]
            expected=dict(intake_id=iid,purpose='ACTUAL_COVERAGE_GAP_INTAKE',measurement_id=actual['measurement_id'],
                release_id=self.release_id,source_commit=self.source_commit,release_batch_id=release_batch_id,
                mission_id=report['mission_id'],body_sha256=report['body_sha256'],policy_sha256=report['policy_sha256'],
                n7_gate_id=report['n7_gate_id'],evidence_ref='r1://artifact/'+actual['measurement_id'],mappings=mappings)
            old=self.truth.query(_KIND,intake_id=iid)
            if old:
                receipt=old[0];signed={k:v for k,v in receipt.items() if k not in {'signature','artifact_type','artifact_version'}}
                if not hmac.compare_digest(receipt['signature'],self.authority._sign(signed)):
                    raise ContractError('NATIVE_COVERAGE_INTAKE_SIGNATURE_INVALID')
                if any(receipt.get(k)!=v for k,v in expected.items()):raise ContractError('NATIVE_COVERAGE_INTAKE_SCOPE_CHANGED')
            else:
                if audit_only:raise ContractError('NATIVE_COVERAGE_ACCEPTED_INTAKE_REQUIRED')
                if any(self.truth.query('rc72_coverage_gap',gap_id=m['gap_id']) for m in mappings):
                    raise ContractError('NATIVE_COVERAGE_UNATTESTED_GAP_NOT_ADOPTED')
                receipt=self._persist(dict(expected,state='BINDING'))
            if audit_only and receipt['state']!='BOUND':raise ContractError('NATIVE_COVERAGE_ACCEPTED_INTAKE_REQUIRED')
            for mapping in mappings:
                rows=self.truth.query('rc72_coverage_gap',gap_id=mapping['gap_id'])
                if not rows:
                    if receipt['state']=='BOUND':raise ContractError('NATIVE_COVERAGE_ACCEPTED_GAP_MISSING')
                    feedback.map_gap(gap_id=mapping['gap_id'],observation_id=actual['observation_id'],
                        code_slice=mapping['code_slice'],uncovered_units=mapping['uncovered_units'])
                gap=self.measurement._one('rc72_coverage_gap',gap_id=mapping['gap_id'])
                if any(gap.get(k)!=mapping[k] for k in _FIELDS):raise ContractError('NATIVE_COVERAGE_GAP_LINEAGE_CHANGED')
                if expected['evidence_ref'] not in gap['evidence_refs']:
                    if receipt['state']=='BOUND':raise ContractError('NATIVE_COVERAGE_GAP_EVIDENCE_CHANGED')
                    self.truth.append_atomic('RC72_COVERAGE_GAP_UPSERTED',dict(gap,
                        evidence_refs=gap['evidence_refs']+[expected['evidence_ref']],artifact_version=gap['artifact_version']+1))
            if receipt['state']!='BOUND':self._persist(dict(expected,state='BOUND'))
            return dict(status='COVERAGE_GAPS_BOUND',intake_id=iid,measurement_id=actual['measurement_id'],
                gap_ids=[m['gap_id'] for m in mappings],uncovered_units=sum(counts.values()))


install_overlay()
