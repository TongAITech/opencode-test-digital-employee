"""Evidence-based observed-path classification and canonical N8 work intake.

This observes missing coverage after accepted execution, not why a product path
was missed. Other classifications require their own causal evidence/service.
"""
import hashlib,hmac,json,subprocess,sys
from pathlib import Path
from rc6_runtime import contracts,truth as registry
from rc6_runtime.process_environment import scoped_process_environment
from .models import Task,Artifact,Evidence,Evaluation,EvaluationResult,ContractError
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .truth_overlay import append_entity
from .rc72_native_coverage_intake import NativeCoverageGapIntakeService
from .rc72_coverage_convergence import CoverageFeedbackService,CoverageGapReason
from .rc72_n7_execution_admission import _hash
from .rc72_libra_measurement import _capture
from .rc72_ledger_lock import ledger_lock
from .rc72_coverage_diagnosis_worker import diagnose

_KIND='rc72_native_coverage_diagnosis';_EVENT='RC72_NATIVE_COVERAGE_DIAGNOSIS_UPSERTED'


def _validate(payload):
    row=dict(payload)
    for key in ('diagnosis_id','gap_id','measurement_id','release_id','source_commit','mission_id','release_batch_id','input_sha256','signature'):
        contracts._require_str(row,key)
    if row.get('purpose')!='NATIVE_COVERAGE_PATH_DIAGNOSIS' or row.get('state') not in {'IN_FLIGHT','RETURNED'}:
        raise contracts.DomainValidationError('COVERAGE_PATH_DIAGNOSIS_STATE_INVALID')
    if any(k in row for k in ('product_defect','field_verified','bank_final','converged')):
        raise contracts.DomainValidationError('COVERAGE_PATH_DIAGNOSIS_CLAIM_FORBIDDEN')
    row.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(row));return row


def install_overlay():
    contracts.VALIDATORS[_KIND]=_validate
    registry.EVENT_TYPES[_EVENT]=(_KIND,'diagnosis_id');registry.IDENTITY_FIELDS[_KIND]='diagnosis_id'
    registry.BUCKETS[_KIND]='rc72_native_coverage_diagnoses'


class NativeCoveragePathDiagnosisService:
    def __init__(self,intake,*,evidence_root):
        if not isinstance(intake,NativeCoverageGapIntakeService):raise ContractError('NATIVE_COVERAGE_INTAKE_REQUIRED')
        install_overlay();self.intake=intake;self.measurement=intake.measurement
        self.truth,self.authority,self.release_id,self.source_commit=intake.truth,intake.authority,intake.release_id,intake.source_commit
        self.root=Path(evidence_root).resolve()

    def _persist(self,row):
        raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        old=self.truth.query(_KIND,diagnosis_id=raw['diagnosis_id'])
        self.truth.append_atomic(_EVENT,dict(raw,signature=self.authority._sign(raw),artifact_version=old[0]['artifact_version']+1 if old else 1))
        return self.measurement._one(_KIND,diagnosis_id=raw['diagnosis_id'])

    def _facts(self,batch,app,gap_id):
        if (not isinstance(self.intake,NativeCoverageGapIntakeService) or self.intake.measurement is not self.measurement
                or self.intake.truth is not self.truth or self.intake.authority is not self.authority
                or self.intake.source_commit!=self.source_commit):raise ContractError('COVERAGE_DIAGNOSIS_COMPOSITION_CHANGED')
        admitted=self.intake.audit(release_batch_id=batch,application_id=app)
        if not admitted or gap_id not in admitted.get('gap_ids',[]):raise ContractError('COVERAGE_DIAGNOSIS_ORIGINAL_GAP_REQUIRED')
        gap=self.measurement._one('rc72_coverage_gap',gap_id=gap_id)
        if not gap['obligation_id'] or len(gap['candidate_obligation_ids'])!=1:
            return None
        policy,proof=self.measurement._context(batch,audit_only=True)
        obligation=[o for o in proof['obligations'] if o['obligation_id']==gap['obligation_id']]
        if len(obligation)!=1:raise ContractError('COVERAGE_DIAGNOSIS_ACCEPTED_OBLIGATION_REQUIRED')
        obligation=obligation[0]
        bundle=self.measurement._one('rc72_n7_evidence_bundle',bundle_id=proof['bundle_id'])
        results={c['case_id']:c for c in bundle['case_results']}
        cases=[]
        for cid in obligation['case_ids']:
            result=results[cid]
            attempt=self.measurement._one('execution_attempt',attempt_id=result['attempt_id'])
            if attempt['status']!='PASS' or result['attempt_id'] not in obligation['attempt_ids']:
                raise ContractError('COVERAGE_DIAGNOSIS_ACCEPTED_ATTEMPT_REQUIRED')
            cases.append(dict(case_id=cid,attempt_id=result['attempt_id'],status=attempt['status'],
                source_case_sha256=obligation['source_case_sha256s'][cid]))
        report=self.measurement._one('rc72_libra_measurement',measurement_id=admitted['measurement_id'])
        immutable={k:gap[k] for k in ('gap_id','code_slice','uncovered_units','requirement_id','sst_id','obligation_id','candidate_obligation_ids')}
        return dict(intake_id=admitted['intake_id'],report_request=self.measurement._request(report,proof),
            gap=immutable,accepted_cases=cases,n7_gate_id=proof['n7_gate_id'],policy_sha256=report['policy_sha256'],
            measurement_id=report['measurement_id'],mission_id=report['mission_id'],release_batch_id=batch,
            input_artifact_refs=['LIBRA-ART-'+_hash(report['measurement_id'])[:24]]+report['input_artifact_refs'])

    def _task_scope(self,row,facts,*,running=False):
        task=self.measurement._one('rc7_task',task_id=row['workitem_id'])
        if (task['release_id']!=self.release_id or task['mission_id']!=row['mission_id'] or task['node']!='DIAGNOSIS'
                or task['task_type']!='COVERAGE_PATH_ROUTING_REVIEW'
                or task['required_capabilities']!=['coverage_capture_diagnosis']
                or task['input_artifact_refs']!=facts['input_artifact_refs'] or task['gap_refs']!=[row['gap_id']]
                or running and (task['state']!='RUNNING' or task['lease_owner']!=row['worker_id'])):
            raise ContractError('COVERAGE_DIAGNOSIS_WORKITEM_SCOPE_CHANGED')
        return task

    def _process(self,request,path):
        _capture(path,json.dumps(request,sort_keys=True).encode())
        process=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('rc72_coverage_diagnosis_worker.py')),str(path)],
            cwd=str(path.parent),env=scoped_process_environment(home=path.parent/'process-home'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:out,err=process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill();process.communicate();raise ContractError('COVERAGE_DIAGNOSIS_PROCESS_TIMEOUT')
        stdout=path.with_suffix('.stdout.json');stderr=path.with_suffix('.stderr.txt')
        _capture(stdout,out.encode());_capture(stderr,err.encode())
        if process.returncode!=0:raise ContractError('COVERAGE_DIAGNOSIS_PROCESS_FAILED')
        result=json.loads(out)
        if result.get('valid') is not True:raise ContractError('COVERAGE_DIAGNOSIS_PROCESS_REJECTED')
        return result['result'],dict(pid=process.pid,exit_code=process.returncode,request_ref='file://'+str(path),request_sha256=_hash(request),
            stdout_ref='file://'+str(stdout),stdout_sha256=hashlib.sha256(stdout.read_bytes()).hexdigest(),
            stderr_ref='file://'+str(stderr),stderr_sha256=hashlib.sha256(stderr.read_bytes()).hexdigest())

    def _verify(self,row,facts):
        signed={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        if not hmac.compare_digest(row['signature'],self.authority._sign(signed)):raise ContractError('COVERAGE_DIAGNOSIS_SIGNATURE_INVALID')
        did='COV-DIAG-'+_hash([facts['measurement_id'],facts['gap']['gap_id']])[:24]
        expected=dict(diagnosis_id=did,gap_id=facts['gap']['gap_id'],measurement_id=facts['measurement_id'],
            release_id=self.release_id,source_commit=self.source_commit,mission_id=facts['mission_id'],release_batch_id=facts['release_batch_id'],
            workitem_id='COV-DIAG-WI-'+_hash(did)[:24],worker_id='COV-DIAG-W-'+_hash(did)[:24],input_sha256=_hash(facts))
        if any(row.get(k)!=v for k,v in expected.items()):raise ContractError('COVERAGE_DIAGNOSIS_INPUT_CHANGED')
        if row['state']!='RETURNED':raise ContractError('COVERAGE_DIAGNOSIS_UNKNOWN_PROCESS_NO_REPLAY')
        results=[]
        for index,key in enumerate(('diagnostic_process','review_process')):
            process=row[key]
            expected=dict(mode='DIAGNOSE' if index==0 else 'REVIEW',facts=facts)
            if index:expected['candidate']=row['result']
            if type(process['pid']) is not int or process['pid']<=0 or process['exit_code']!=0 or process['request_sha256']!=_hash(expected):
                raise ContractError('COVERAGE_DIAGNOSIS_PROCESS_BINDING_CHANGED')
            request=Path(process['request_ref'][7:])
            if request.is_symlink() or not request.is_file() or json.loads(request.read_text())!=expected:
                raise ContractError('COVERAGE_DIAGNOSIS_PROCESS_REQUEST_CHANGED')
            for stream in ('stdout','stderr'):
                path=Path(process[stream+'_ref'][7:])
                if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=process[stream+'_sha256']:
                    raise ContractError('COVERAGE_DIAGNOSIS_PROCESS_EVIDENCE_CHANGED')
            results.append(json.loads(Path(process['stdout_ref'][7:]).read_text()))
        if (row['diagnostic_process']['pid']==row['review_process']['pid']
                or any(r!=dict(valid=True,result=row['result']) for r in results)):
            raise ContractError('COVERAGE_DIAGNOSIS_INDEPENDENT_REVIEW_REQUIRED')
        result=row['result']
        if result!=diagnose(facts):raise ContractError('COVERAGE_DIAGNOSIS_RESULT_SCOPE_CHANGED')
        if (result.get('gap_id')!=facts['gap']['gap_id'] or result.get('obligation_id')!=facts['gap']['obligation_id']
                or result.get('measurement_id')!=facts['measurement_id'] or result.get('reason')!='PATH_NOT_REACHED'
                or result.get('responsible_nodes')!=['N8_DIAGNOSIS_RECOVERY'] or result.get('action')!='DIAGNOSE_PATH'
                or result.get('uncovered_units')!=facts['gap']['uncovered_units']
                or result.get('case_ids')!=[c['case_id'] for c in facts['accepted_cases']]
                or result.get('attempt_ids')!=[c['attempt_id'] for c in facts['accepted_cases']]):
            raise ContractError('COVERAGE_DIAGNOSIS_RESULT_SCOPE_CHANGED')

    def run(self,*,release_batch_id,application_id,gap_id):
        facts=self._facts(release_batch_id,application_id,gap_id)
        if facts is None:return dict(status='HOLD',reason='COVERAGE_UNIQUE_MAPPING_INVESTIGATION_REQUIRED')
        epoch=self.truth.store._next_seq
        did='COV-DIAG-'+_hash([facts['measurement_id'],gap_id])[:24]
        worker='COV-DIAG-W-'+_hash(did)[:24];wid='COV-DIAG-WI-'+_hash(did)[:24]
        with ledger_lock(self.truth,busy='COVERAGE_DIAGNOSIS_LEDGER_BUSY'):
            if self.truth.store._next_seq!=epoch:raise ContractError('COVERAGE_DIAGNOSIS_SOURCE_CHANGED')
            old=self.truth.query(_KIND,diagnosis_id=did)
            if old:row=old[0]
            else:
                gap=self.measurement._one('rc72_coverage_gap',gap_id=gap_id)
                if gap['status']!='MAPPED':raise ContractError('COVERAGE_DIAGNOSIS_UNATTESTED_CLASSIFICATION_NOT_ADOPTED')
                control=ClosedLoopControlPlane(self.truth,self.release_id,facts['mission_id'])
                if not self.truth.query('rc7_task',task_id=wid):
                    control.register_task(Task(task_id=wid,mission_id=facts['mission_id'],node='DIAGNOSIS',task_type='COVERAGE_PATH_ROUTING_REVIEW',
                        objective='independently classify observed uncovered path after accepted original Cases',
                        required_capabilities=['coverage_capture_diagnosis'],input_artifact_refs=facts['input_artifact_refs'],
                        gap_refs=[gap_id],acceptance_criteria=['independent captured report and exact original execution review'],priority=0))
                scope=dict(workitem_id=wid,worker_id=worker,mission_id=facts['mission_id'],gap_id=gap_id)
                task=self._task_scope(scope,facts)
                if task['state'] in {'REGISTERED','READY'}:
                    eligible=[t for t in control.scheduler.ready_tasks(facts['mission_id']) if set(t.required_capabilities).issubset({'coverage_capture_diagnosis'})]
                    if not eligible or eligible[0].task_id!=wid:raise ContractError('COVERAGE_DIAGNOSIS_WORKITEM_NOT_NEXT')
                    control.lease_next(worker_ref=worker,capabilities=['coverage_capture_diagnosis'])
                    task=self._task_scope(scope,facts)
                if task['state']=='LEASED':control.start(wid,worker_ref=worker)
                self._task_scope(scope,facts,running=True)
                row=self._persist(dict(diagnosis_id=did,purpose='NATIVE_COVERAGE_PATH_DIAGNOSIS',gap_id=gap_id,measurement_id=facts['measurement_id'],
                    release_id=self.release_id,source_commit=self.source_commit,mission_id=facts['mission_id'],release_batch_id=release_batch_id,
                    workitem_id=wid,worker_id=worker,input_sha256=_hash(facts),state='IN_FLIGHT'))
        if not old:
            directory=self.root/did;directory.mkdir(parents=True,exist_ok=True)
            candidate,diagnostic=self._process(dict(mode='DIAGNOSE',facts=facts),directory/'diagnose.json')
            accepted,reviewed=self._process(dict(mode='REVIEW',facts=facts,candidate=candidate),directory/'review.json')
            if candidate!=accepted:raise ContractError('COVERAGE_DIAGNOSIS_REVIEW_REJECTED')
            fresh=self._facts(release_batch_id,application_id,gap_id);epoch=self.truth.store._next_seq
            with ledger_lock(self.truth,busy='COVERAGE_DIAGNOSIS_RETURN_LEDGER_BUSY'):
                if self.truth.store._next_seq!=epoch or fresh!=facts:raise ContractError('COVERAGE_DIAGNOSIS_SOURCE_CHANGED_AFTER_PROCESS')
                self._task_scope(row,facts,running=True)
                row=self._persist(dict(row,state='RETURNED',result=candidate,diagnostic_process=diagnostic,review_process=reviewed))
        self._verify(row,facts)
        fresh=self._facts(release_batch_id,application_id,gap_id);epoch=self.truth.store._next_seq
        with ledger_lock(self.truth,busy='COVERAGE_DIAGNOSIS_ACCEPT_LEDGER_BUSY'):
            if self.truth.store._next_seq!=epoch or fresh!=facts:raise ContractError('COVERAGE_DIAGNOSIS_SOURCE_CHANGED_BEFORE_ACCEPTANCE')
            return self._accept(row,facts)

    def audit(self,*,release_batch_id,application_id,gap_id):
        facts=self._facts(release_batch_id,application_id,gap_id)
        if facts is None:raise ContractError('COVERAGE_DIAGNOSIS_UNIQUE_MAPPING_REQUIRED')
        epoch=self.truth.store._next_seq
        did='COV-DIAG-'+_hash([facts['measurement_id'],gap_id])[:24]
        row=self.measurement._one(_KIND,diagnosis_id=did);self._verify(row,facts)
        with ledger_lock(self.truth,busy='COVERAGE_DIAGNOSIS_AUDIT_LEDGER_BUSY'):
            if self.truth.store._next_seq!=epoch:raise ContractError('COVERAGE_DIAGNOSIS_SOURCE_CHANGED_DURING_AUDIT')
            aid='COV-DIAG-ART-'+_hash(did)[:24];eid='COV-DIAG-EV-'+_hash(did)[:24]
            if (self._task_scope(row,facts)['state']!='PASS'
                    or not self.truth.query('rc7_artifact',artifact_id=aid)
                    or not self.truth.query('rc7_evidence',evidence_id=eid)
                    or not self.truth.query('rc7_evaluation',evaluation_id='COV-DIAG-EVAL-'+_hash(did)[:24])
                    or self.measurement._one('rc72_coverage_gap',gap_id=gap_id)['status']!='CLASSIFIED'
                    or not self.truth.query('rc7_task',task_id='COV-PATH-WI-'+_hash(did)[:24])):
                raise ContractError('COVERAGE_DIAGNOSIS_ACCEPTED_CLOSURE_REQUIRED')
            before=self.truth.store.path.read_bytes()
            result=self._accept(row,facts)
            if self.truth.store.path.read_bytes()!=before:raise ContractError('COVERAGE_DIAGNOSIS_AUDIT_MUST_BE_READONLY')
            return result

    def _accept(self,row,facts):
        did=row['diagnosis_id'];aid='COV-DIAG-ART-'+_hash(did)[:24];eid='COV-DIAG-EV-'+_hash(did)[:24]
        control=ClosedLoopControlPlane(self.truth,self.release_id,row['mission_id'])
        task=self._task_scope(row,facts)
        if task['state']=='RUNNING':
            self._task_scope(row,facts,running=True)
            if not self.truth.query('rc7_evidence',evidence_id=eid):
                append_entity(self.truth,Evidence(evidence_id=eid,mission_id=row['mission_id'],kind='NATIVE_COVERAGE_DIAGNOSIS_REVIEW',
                    source_ref='r1://artifact/'+did,content_ref=row['review_process']['stdout_ref'],content_hash=row['review_process']['stdout_sha256'],subject_refs=[row['gap_id']]),release_id=self.release_id)
            old=self.truth.query('rc7_artifact',artifact_id=aid)
            artifact=Artifact(artifact_id=aid,mission_id=row['mission_id'],artifact_type='COVERAGE_PATH_ROUTING_DIAGNOSIS',
                producer_task_id=row['workitem_id'],content_ref='r1://artifact/'+did,content_hash=_hash(row['result']),
                parent_refs=facts['input_artifact_refs'],evidence_refs=[eid],**(dict(created_at=old[0]['created_at']) if old else {}))
            control.submit_worker_output(WorkerOutput(task_id=row['workitem_id'],worker_ref=row['worker_id'],artifacts=(artifact,)))
        evaluation_id='COV-DIAG-EVAL-'+_hash(did)[:24]
        if self.measurement._one('rc7_task',task_id=row['workitem_id'])['state']=='OUTPUT_PRODUCED':
            old=self.truth.query('rc7_evaluation',evaluation_id=evaluation_id)
            control.accept_evaluation(row['workitem_id'],evaluation=Evaluation(evaluation_id=evaluation_id,mission_id=row['mission_id'],node='DIAGNOSIS',
                artifact_refs=[aid],result=EvaluationResult.PASS,evaluator_ref='coverage-review-process://'+str(row['review_process']['pid']),
                evidence_refs=[eid],dimensions=dict(diagnosis_id=did,review_sha256=row['review_process']['stdout_sha256']),**(dict(created_at=old[0]['created_at']) if old else {})))
        task=self.measurement._one('rc7_task',task_id=row['workitem_id'])
        if task['state']!='PASS' or task.get('evaluation_id')!=evaluation_id:raise ContractError('COVERAGE_DIAGNOSIS_ACCEPTED_TASK_REQUIRED')
        artifact=self.measurement._one('rc7_artifact',artifact_id=aid)
        evidence=self.measurement._one('rc7_evidence',evidence_id=eid)
        evaluation=self.measurement._one('rc7_evaluation',evaluation_id=evaluation_id)
        expected_evaluation=dict(release_id=self.release_id,mission_id=row['mission_id'],node='DIAGNOSIS',artifact_refs=[aid],result='PASS',
            evaluator_ref='coverage-review-process://'+str(row['review_process']['pid']),evidence_refs=[eid],
            dimensions=dict(diagnosis_id=did,review_sha256=row['review_process']['stdout_sha256']))
        expected_artifact=dict(release_id=self.release_id,mission_id=row['mission_id'],artifact_type_name='COVERAGE_PATH_ROUTING_DIAGNOSIS',
            producer_task_id=row['workitem_id'],content_ref='r1://artifact/'+did,content_hash=_hash(row['result']),
            parent_refs=facts['input_artifact_refs'],evidence_refs=[eid],state='VALID')
        expected_evidence=dict(release_id=self.release_id,mission_id=row['mission_id'],kind='NATIVE_COVERAGE_DIAGNOSIS_REVIEW',
            source_ref='r1://artifact/'+did,content_ref=row['review_process']['stdout_ref'],
            content_hash=row['review_process']['stdout_sha256'],subject_refs=[row['gap_id']])
        if (task['output_artifact_refs']!=[aid] or any(evaluation.get(k)!=v for k,v in expected_evaluation.items())
                or any(artifact.get(k)!=v for k,v in expected_artifact.items())
                or any(evidence.get(k)!=v for k,v in expected_evidence.items())):
            raise ContractError('COVERAGE_DIAGNOSIS_ACCEPTED_PROOF_CHANGED')
        gap=self.measurement._one('rc72_coverage_gap',gap_id=row['gap_id'])
        evidence_ref='r1://artifact/'+did
        if gap['status']=='MAPPED':
            CoverageFeedbackService(self.truth,release_id=self.release_id).classify_gap(gap_id=row['gap_id'],gap_reason=CoverageGapReason.PATH_NOT_REACHED,
                evidence_refs=list(dict.fromkeys(gap['evidence_refs']+[evidence_ref])),rationale=row['result']['rationale'])
        gap=self.measurement._one('rc72_coverage_gap',gap_id=row['gap_id'])
        if (gap['gap_reason']!='PATH_NOT_REACHED' or gap['status']!='CLASSIFIED' or gap['responsible_nodes']!=['N8_DIAGNOSIS_RECOVERY']
                or gap['action']!='DIAGNOSE_PATH' or evidence_ref not in gap['evidence_refs'] or gap['rationale']!=row['result']['rationale']):
            raise ContractError('COVERAGE_DIAGNOSIS_CLASSIFICATION_CHANGED')
        investigation='COV-PATH-WI-'+_hash(did)[:24]
        if not self.truth.query('rc7_task',task_id=investigation):
            control.register_task(Task(task_id=investigation,mission_id=row['mission_id'],node='DIAGNOSIS',task_type='COVERAGE_PATH_INVESTIGATION',
                objective='diagnose why accepted original Cases did not reach '+facts['gap']['code_slice'],
                required_capabilities=['coverage_path_investigation'],input_artifact_refs=[aid]+facts['input_artifact_refs'],
                gap_refs=[row['gap_id']],acceptance_criteria=['causal evidence and independently reviewed bounded repair plan; no automatic product defect claim'],priority=0))
        queued=self.measurement._one('rc7_task',task_id=investigation)
        if (queued['release_id']!=self.release_id or queued['mission_id']!=row['mission_id'] or queued['node']!='DIAGNOSIS' or queued['task_type']!='COVERAGE_PATH_INVESTIGATION'
                or queued['input_artifact_refs']!=[aid]+facts['input_artifact_refs'] or queued['gap_refs']!=[row['gap_id']]
                or queued['required_capabilities']!=['coverage_path_investigation']):raise ContractError('COVERAGE_PATH_INVESTIGATION_SCOPE_CHANGED')
        return dict(status='COVERAGE_PATH_DIAGNOSIS_QUEUED',diagnosis_id=did,gap_id=row['gap_id'],investigation_workitem_id=investigation)


install_overlay()
