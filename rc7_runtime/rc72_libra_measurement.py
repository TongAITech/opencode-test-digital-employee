"""Actual leased read + captured report + separate process review for N10.

Only the normalized read-only bridge contract is supported. Its bank origin is
an operator/Field trust boundary. No model/caller supplies counts or a verdict.
"""
from dataclasses import asdict
from rc6_runtime.authority import WorkerIdentity,TaskLease
import hashlib,hmac,json,os,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.error import HTTPError

from rc6_runtime import contracts,truth as registry
from rc6_runtime.process_environment import scoped_process_environment
from .models import Artifact,Evidence,Evaluation,EvaluationResult,Task,ContractError
from .control_plane import WorkerOutput
from .closed_loop_control import ClosedLoopControlPlane
from .truth_overlay import append_entity
from .rc72_expected_scope_input import ExpectedScopeInputService
from .rc72_n9_accepted_scope import AcceptedScopeN9Service
from .rc72_n7_execution_admission import _hash
from .rc72_ledger_lock import ledger_lock
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_libra_report_review import review

_KIND='rc72_libra_measurement';_EVENT='RC72_LIBRA_MEASUREMENT_UPSERTED'
_TOOL='libra_incremental_read';_ROLE='RC72_COVERAGE_AUDITOR'


def _validate(payload):
    row=dict(payload)
    for key in ('measurement_id','release_id','source_commit','release_batch_id','mission_id','application_id',
                'workitem_id','worker_id','attempt_id','policy_input_id','policy_sha256','n7_gate_id','signature'):
        contracts._require_str(row,key)
    if row.get('purpose')!='N10_NATIVE_LIBRA_READ' or row.get('state') not in {'IN_FLIGHT','RETURNED','UNKNOWN'}:
        raise contracts.DomainValidationError('LIBRA_MEASUREMENT_STATE_INVALID')
    if any(k in row for k in ('field_verified','bank_final','converged')):raise contracts.DomainValidationError('LIBRA_MEASUREMENT_CLAIM_FORBIDDEN')
    row.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(row));return row


def install_overlay():
    contracts.VALIDATORS[_KIND]=_validate
    registry.EVENT_TYPES[_EVENT]=(_KIND,'measurement_id');registry.IDENTITY_FIELDS[_KIND]='measurement_id'
    registry.BUCKETS[_KIND]='rc72_libra_measurements'


def _capture(path,raw):
    # A prior or redirected capture is never overwritten during reconciliation.
    if path.parent.is_symlink():raise ContractError('LIBRA_CAPTURE_DIRECTORY_CHANGED')
    with path.open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class NativeLibraMeasurementService:
    def __init__(self,expected_scope,n9,*,capture_root):
        if (not isinstance(expected_scope,ExpectedScopeInputService) or not isinstance(n9,AcceptedScopeN9Service)
                or expected_scope.truth is not n9.truth or expected_scope.source_commit!=n9.source_commit):
            raise ContractError('LIBRA_NATIVE_SCOPE_AND_N9_REQUIRED')
        install_overlay()
        self.expected_scope,self.n9=expected_scope,n9
        self.truth,self.source_commit,self.release_id=n9.truth,n9.source_commit,n9.release_id
        self.authority=n9.authority;self.root=Path(capture_root).resolve()

    def _one(self,kind,**filters):
        rows=self.truth.query(kind,**filters)
        if len(rows)!=1:raise ContractError('LIBRA_MEASUREMENT_TRUTH_NOT_UNIQUE:'+kind)
        return rows[0]

    def _persist(self,row):
        raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        old=self.truth.query(_KIND,measurement_id=raw['measurement_id'])
        self.truth.append_atomic(_EVENT,dict(raw,signature=self.authority._sign(raw),artifact_version=old[0]['artifact_version']+1 if old else 1))
        return self._one(_KIND,measurement_id=raw['measurement_id'])

    def _signed(self,row):
        raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        if not hmac.compare_digest(row['signature'],self.authority._sign(raw)):raise ContractError('LIBRA_MEASUREMENT_SIGNATURE_INVALID')
        return row

    def _context(self,batch_id,*,audit_only=False):
        if (not isinstance(self.expected_scope,ExpectedScopeInputService) or not isinstance(self.n9,AcceptedScopeN9Service)
                or self.n9.authority is not self.authority or self.expected_scope.truth is not self.truth or self.n9.truth is not self.truth
                or self.n9.source_commit!=self.source_commit or self.expected_scope.source_commit!=self.source_commit):
            raise ContractError('LIBRA_MEASUREMENT_COMPOSITION_CHANGED')
        batch=self._one('rc72_release_batch',release_batch_id=batch_id)
        n9=self._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N9_DEFECT')
        if n9['state']!='PASS':raise ContractError('LIBRA_ACCEPTED_N9_REQUIRED')
        if audit_only:
            if (len(self.truth.query('rc72_expected_scope_input',release_batch_id=batch_id))!=1
                    or len(self.truth.query('rc72_release_scope_manifest',release_batch_id=batch_id))!=1
                    or not any(e['from_node_type']=='N9_DEFECT' and e['to_node_type']=='N10_RELEASE_CONVERGENCE'
                               and e['source_gate_id'] in n9['gate_refs'] for e in self.truth.query('rc72_node_transition',mission_id=batch['mission_id']))):
                raise ContractError('LIBRA_ACCEPTED_SOURCE_CLOSURE_REQUIRED')
        frozen=self.expected_scope.freeze(release_batch_id=batch_id)
        accepted=self.n9.complete(release_batch_id=batch_id)
        if accepted.get('state')!='N9_PASS':raise ContractError('LIBRA_ACCEPTED_N9_REQUIRED')
        policy=self._one('rc72_expected_scope_input',input_id=frozen['input_id'])
        clearance=self._one('rc72_n9_accepted_scope',clearance_id=accepted['clearance_id'])
        return policy,clearance['snapshot']['proof']

    def _inputs(self,policy,proof):
        n1_gate=self._one('rc72_node_gate',gate_id=policy['n1_gate_id'])
        n1_delivery=self._one('rc72_node_delivery',delivery_id=n1_gate['delivery_id'])
        bundle=self._one('rc72_n7_evidence_bundle',bundle_id=proof['bundle_id'])
        return list(dict.fromkeys(n1_delivery['artifact_refs']+[ref for case in bundle['case_results']
            for ref in self._one('rc7_task',task_id=case['workitem_id'])['output_artifact_refs']]))

    def _actor(self,row,identity,lease):
        task=self._one('rc7_task',task_id=row['workitem_id'])
        policy=self._one('rc72_expected_scope_input',input_id=row['policy_input_id'])
        if (_hash(policy)!=row['policy_sha256'] or task['state']!='RUNNING' or task['lease_owner']!=row['worker_id']
                or task['mission_id']!=row['mission_id'] or task['node']!='COVERAGE_AUDIT'
                or task['input_artifact_refs']!=row['input_artifact_refs']
                or self.authority.get_identity(row['worker_id'])!=identity or self.authority.get_lease(lease.lease_id)!=lease):
            raise ContractError('LIBRA_MEASUREMENT_LIVE_SCOPE_CHANGED')
        node=self._one('rc72_mission_node',mission_id=row['mission_id'],node_type='N7_EXECUTION')
        if node['state']!='PASS' or row['n7_gate_id'] not in node['gate_refs']:raise ContractError('LIBRA_MEASUREMENT_EXECUTION_CHANGED')
        n10=self._one('rc72_mission_node',mission_id=row['mission_id'],node_type='N10_RELEASE_CONVERGENCE')
        if n10['state'] not in {'READY','RUNNING'}:raise ContractError('LIBRA_MEASUREMENT_N10_NOT_ACTIVE')
        self.authority.authorize_tool(row['worker_id'],lease.lease_id,_TOOL)

    def collect(self,*,release_batch_id,application_id):
        policy,proof=self._context(release_batch_id)
        epoch=self.truth.store._next_seq
        targets=policy.get('coverage_targets',{})
        if application_id not in targets:return dict(status='HOLD',reason='NATIVE_LIBRA_TARGET_POLICY_REQUIRED')
        target=targets[application_id]
        if target['auth_mode']!='ANONYMOUS':return dict(status='HOLD',reason='NATIVE_LIBRA_WORKER_AUTH_PROVIDER_REQUIRED')
        mid='LIBRA-'+_hash([policy['input_id'],policy['input_sha256'],proof['n7_gate_id'],application_id])[:24]
        with ledger_lock(self.truth,busy='LIBRA_MEASUREMENT_LEDGER_BUSY'):
            if self.truth.store._next_seq!=epoch:raise ContractError('LIBRA_SOURCE_CHANGED_BEFORE_READ')
            existing=self.truth.query(_KIND,measurement_id=mid)
            if existing:
                row=self._signed(existing[0])
                if row['state']!='RETURNED':return dict(status='HOLD',reason='LIBRA_UNKNOWN_READ_NO_REPLAY',measurement_id=mid)
            else:
                wid='COV-WI-'+_hash(mid)[:24];worker='COV-W-'+_hash(mid)[:24];attempt='COV-ATT-'+_hash(mid)[:24]
                inputs=self._inputs(policy,proof)
                control=ClosedLoopControlPlane(self.truth,self.release_id,proof['mission_id'])
                if not self.truth.query('rc7_task',task_id=wid):
                    control.register_task(Task(task_id=wid,mission_id=proof['mission_id'],node='COVERAGE_AUDIT',task_type='LIBRA_INCREMENTAL_MEASUREMENT',
                        objective='read authoritative incremental coverage for '+application_id,required_capabilities=[_TOOL],
                        input_artifact_refs=inputs,acceptance_criteria=['captured report independently verified'],priority=0))
                task=self._one('rc7_task',task_id=wid)
                if task['state'] in {'REGISTERED','READY'}:
                    eligible=[t for t in control.scheduler.ready_tasks(proof['mission_id']) if set(t.required_capabilities).issubset({_TOOL})]
                    if not eligible or eligible[0].task_id!=wid:raise ContractError('LIBRA_OWNED_WORKITEM_NOT_NEXT')
                    control.lease_next(worker_ref=worker,capabilities=[_TOOL]);task=self._one('rc7_task',task_id=wid)
                if task['state']=='LEASED':control.start(wid,worker_ref=worker)
                identity=self.authority.adopt_identity(worker_id=worker,role=_ROLE,phase='N10_COVERAGE_READ',layer=None,generation=1,session_id='coverage-control://'+mid)
                lease=self.authority.issue_lease(worker,'task:'+wid+'/attempt:'+attempt,(),(_TOOL,),ttl_seconds=300)
                row=dict(measurement_id=mid,purpose='N10_NATIVE_LIBRA_READ',release_id=self.release_id,source_commit=self.source_commit,
                    release_batch_id=release_batch_id,mission_id=proof['mission_id'],application_id=application_id,workitem_id=wid,worker_id=worker,
                    attempt_id=attempt,input_artifact_refs=inputs,policy_input_id=policy['input_id'],policy_sha256=_hash(policy),n7_gate_id=proof['n7_gate_id'],target=target,
                    identity=asdict(identity),lease=asdict(lease),state='IN_FLIGHT',started_at=int(time.time()))
                self._actor(row,identity,lease)
                node=self._one('rc72_mission_node',mission_id=proof['mission_id'],node_type='N10_RELEASE_CONVERGENCE')
                if node['state']=='READY':self.n9.runtime.transition_state(node['mission_node_id'],MissionNodeState.RUNNING,reason='native coverage audit started')
                row=self._persist(row)
        if not existing:
            observed={}
            try:
                request=Request(target['report_url'],headers={'Accept':'application/json','X-RC72-Measurement-ID':mid},method='GET')
                opener=build_opener(ProxyHandler({}),_NoRedirect())
                try:response=opener.open(request,timeout=20)
                except HTTPError as failure:response=failure
                with response:
                    raw=response.read(2097153);status=response.status
                if len(raw)>2097152:raise ContractError('LIBRA_REPORT_SIZE_EXCEEDED')
                directory=self.root/mid;directory.mkdir(parents=True,exist_ok=True)
                path=directory/'response.json';_capture(path,raw)
                observed=dict(body_ref='file://'+str(path),body_sha256=hashlib.sha256(raw).hexdigest(),http_status=status,finished_at=int(time.time()))
                current,current_proof=self._context(release_batch_id)
                epoch=self.truth.store._next_seq
                with ledger_lock(self.truth,busy='LIBRA_MEASUREMENT_LEDGER_BUSY'):
                    if self.truth.store._next_seq!=epoch:raise ContractError('LIBRA_SOURCE_CHANGED_AFTER_READ')
                    self._actor(row,identity,lease)
                    if _hash(current)!=row['policy_sha256'] or current_proof['n7_gate_id']!=row['n7_gate_id']:
                        raise ContractError('LIBRA_MEASUREMENT_SOURCE_CHANGED_AFTER_READ')
                    row=self._persist(dict(row,state='RETURNED',**observed))
                    self.authority.revoke_worker_lease(lease.lease_id)
            except BaseException as exc:
                with ledger_lock(self.truth,busy='LIBRA_MEASUREMENT_LEDGER_BUSY'):
                    self._persist(dict(row,state='UNKNOWN',**observed,error_type=type(exc).__name__))
                    self.authority.revoke_worker_lease(lease.lease_id)
                raise
        return self._finalize(row,policy,proof)

    def audit(self,*,release_batch_id,application_id):
        policy,proof=self._context(release_batch_id,audit_only=True)
        epoch=self.truth.store._next_seq
        if application_id not in policy.get('coverage_targets',{}):return None
        mid='LIBRA-'+_hash([policy['input_id'],policy['input_sha256'],proof['n7_gate_id'],application_id])[:24]
        rows=self.truth.query(_KIND,measurement_id=mid)
        if not rows:return None
        row=rows[0];self._verify_receipt(row,policy,proof)
        expected=review(self._request(row,proof))
        path=self.root/mid/'review.json'
        if (not row.get('review_sha256') or row.get('review_exit_code')!=0 or path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest()!=row['review_sha256']
                or json.loads(path.read_text())!=dict(valid=True,result=expected)):
            raise ContractError('LIBRA_ACCEPTED_REVIEW_REQUIRED')
        self._verify_review_process(row,proof)
        with ledger_lock(self.truth,busy='LIBRA_AUDIT_LEDGER_BUSY'):
            if self.truth.store._next_seq!=epoch:raise ContractError('LIBRA_SOURCE_CHANGED_DURING_AUDIT')
            before=self.truth.store.path.read_bytes()
            # All final metadata must already exist; audit must never fill gaps.
            wid=row['workitem_id'];aid='LIBRA-ART-'+_hash(mid)[:24];eid='LIBRA-EV-'+_hash(mid)[:24]
            if (self._one('rc7_task',task_id=wid)['state']!='PASS'
                    or not self.truth.query('rc7_artifact',artifact_id=aid)
                    or not self.truth.query('rc7_evidence',evidence_id=eid)
                    or not self.truth.query('rc7_evaluation',evaluation_id='LIBRA-EVAL-'+_hash(mid)[:24])
                    or not self.truth.query('rc72_coverage_observation',observation_id='NATIVE-'+mid)):
                raise ContractError('LIBRA_ACCEPTED_WORKITEM_PROOF_REQUIRED')
            result=self._accept_locked(row,expected)
            if self.truth.store.path.read_bytes()!=before:raise ContractError('LIBRA_AUDIT_MUST_BE_READONLY')
        return result

    def _request(self,row,proof):
        gate=self._one('rc72_node_gate',gate_id=proof['n7_gate_id'])
        return dict(body_ref=row['body_ref'],body_sha256=row['body_sha256'],measurement_id=row['measurement_id'],
            application_id=row['application_id'],base_revision=row['target']['base_revision'],target_revision=row['target']['target_revision'],
            metric=row['target']['metric'],minimum_observed_at=gate['created_at'],finished_at=row['finished_at'])

    def _verify_receipt(self,row,policy,proof):
        self._signed(row)
        mid='LIBRA-'+_hash([policy['input_id'],policy['input_sha256'],proof['n7_gate_id'],row['application_id']])[:24]
        expected=dict(measurement_id=mid,release_id=self.release_id,source_commit=self.source_commit,
            release_batch_id=proof['release_batch_id'],mission_id=proof['mission_id'],
            policy_input_id=policy['input_id'],policy_sha256=_hash(policy),n7_gate_id=proof['n7_gate_id'],
            workitem_id='COV-WI-'+_hash(mid)[:24],worker_id='COV-W-'+_hash(mid)[:24],attempt_id='COV-ATT-'+_hash(mid)[:24],
            input_artifact_refs=self._inputs(policy,proof),target=policy['coverage_targets'][row['application_id']],state='RETURNED',http_status=200)
        if any(row.get(k)!=v for k,v in expected.items()):raise ContractError('LIBRA_MEASUREMENT_SCOPE_CHANGED')
        identity=WorkerIdentity(**row['identity']);data=dict(row['lease'])
        for key in ('allowed_tools','allowed_artifact_types'):data[key]=tuple(data[key])
        lease=TaskLease(**data);self.authority.validate_historical_lease(identity,lease)
        if (identity.worker_id!=row['worker_id'] or identity.role!=_ROLE or identity.phase!='N10_COVERAGE_READ'
                or identity.generation!=1 or identity.session_id!='coverage-control://'+mid
                or lease.scope_ref!='task:'+row['workitem_id']+'/attempt:'+row['attempt_id']
                or lease.allowed_tools!=(_TOOL,) or lease.allowed_artifact_types
                or not lease.issued_at<=row['started_at']<=row['finished_at']<=lease.expires_at):
            raise ContractError('LIBRA_MEASUREMENT_HISTORICAL_AUTHORITY_INVALID')

    def _verify_review_process(self,row,proof):
        request=self._request(row,proof)
        path=self.root/row['measurement_id']/'request.json'
        if (row.get('review_state')!='RETURNED' or type(row.get('review_pid')) is not int
                or row['review_pid']<=0 or row.get('review_exit_code')!=0
                or row.get('review_request_sha256')!=_hash(request)
                or path.is_symlink() or not path.is_file() or path.stat().st_size>16384
                or json.loads(path.read_text(encoding='utf-8'))!=request):
            raise ContractError('LIBRA_REVIEW_PROCESS_BINDING_CHANGED')

    def _finalize(self,row,policy,proof):
        self._verify_receipt(row,policy,proof)
        request=self._request(row,proof);expected=review(request)
        directory=self.root/row['measurement_id'];directory.mkdir(parents=True,exist_ok=True)
        review_path=directory/'review.json';request_path=directory/'request.json'
        if row.get('review_sha256'):
            if review_path.is_symlink() or not review_path.is_file() or hashlib.sha256(review_path.read_bytes()).hexdigest()!=row['review_sha256']:
                raise ContractError('LIBRA_REVIEW_EVIDENCE_CHANGED')
            result=json.loads(review_path.read_text())
        else:
            with ledger_lock(self.truth,busy='LIBRA_REVIEW_LEDGER_BUSY'):
                current=self._one(_KIND,measurement_id=row['measurement_id']);self._verify_receipt(current,policy,proof)
                if current.get('review_state') or review_path.exists():raise ContractError('LIBRA_UNKNOWN_REVIEW_NO_REPLAY')
                _capture(request_path,json.dumps(request).encode('utf-8'))
                row=self._persist(dict(current,review_state='IN_FLIGHT',review_request_sha256=_hash(request)))
            child=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('rc72_libra_report_review.py')),str(request_path)],
                cwd=str(directory),env=scoped_process_environment(home=directory/'review-home'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:stdout,stderr=child.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill();child.communicate();raise ContractError('LIBRA_REVIEW_PROCESS_TIMEOUT')
            _capture(review_path,stdout.encode('utf-8'))
            result=json.loads(stdout)
            with ledger_lock(self.truth,busy='LIBRA_REVIEW_LEDGER_BUSY'):
                row=self._persist(dict(row,review_state='RETURNED',review_pid=child.pid,review_exit_code=child.returncode,
                    review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest()))
        self._verify_review_process(row,proof)
        if row.get('review_exit_code')!=0 or result!=dict(valid=True,result=expected):raise ContractError('LIBRA_REVIEW_RESULT_MISMATCH')
        current,current_proof=self._context(row['release_batch_id'])
        epoch=self.truth.store._next_seq
        with ledger_lock(self.truth,busy='LIBRA_ACCEPTANCE_LEDGER_BUSY'):
            if self.truth.store._next_seq!=epoch:raise ContractError('LIBRA_SOURCE_CHANGED_BEFORE_ACCEPTANCE')
            self._verify_receipt(row,current,current_proof)
            return self._accept_locked(row,expected)

    def _accept_locked(self,row,expected):
        control=ClosedLoopControlPlane(self.truth,self.release_id,row['mission_id'])
        aid='LIBRA-ART-'+_hash(row['measurement_id'])[:24];eid='LIBRA-EV-'+_hash(row['measurement_id'])[:24]
        reviewer='COV-REVIEW-'+_hash([row['measurement_id'],row['review_pid']])[:24]
        task=self._one('rc7_task',task_id=row['workitem_id'])
        if task['state']=='RUNNING':
            old=self.truth.query('rc7_artifact',artifact_id=aid)
            if not self.truth.query('rc7_evidence',evidence_id=eid):
                append_entity(self.truth,Evidence(evidence_id=eid,mission_id=row['mission_id'],kind='NATIVE_LIBRA_COVERAGE_REPORT',
                    source_ref='r1://artifact/'+row['measurement_id'],content_ref=row['body_ref'],content_hash=row['body_sha256'],subject_refs=[row['measurement_id']]),release_id=self.release_id)
            artifact=Artifact(artifact_id=aid,mission_id=row['mission_id'],artifact_type='RC72_LIBRA_MEASUREMENT',producer_task_id=row['workitem_id'],
                content_ref='r1://artifact/'+row['measurement_id'],content_hash=row['body_sha256'],parent_refs=row['input_artifact_refs'],evidence_refs=[eid],**(dict(created_at=old[0]['created_at']) if old else {}))
            control.submit_worker_output(WorkerOutput(task_id=row['workitem_id'],worker_ref=row['worker_id'],artifacts=(artifact,)))
        task=self._one('rc7_task',task_id=row['workitem_id'])
        evaluation_id='LIBRA-EVAL-'+_hash(row['measurement_id'])[:24]
        if task['state']=='OUTPUT_PRODUCED':
            old=self.truth.query('rc7_evaluation',evaluation_id=evaluation_id)
            control.accept_evaluation(row['workitem_id'],evaluation=Evaluation(evaluation_id=evaluation_id,mission_id=row['mission_id'],node='COVERAGE_AUDIT',
                artifact_refs=[aid],result=EvaluationResult.PASS,evaluator_ref=reviewer,evidence_refs=[eid],
                dimensions=dict(measurement_id=row['measurement_id'],review_sha256=row['review_sha256']),**(dict(created_at=old[0]['created_at']) if old else {})))
        if self._one('rc7_task',task_id=row['workitem_id'])['state']!='PASS':raise ContractError('LIBRA_MEASUREMENT_WORKITEM_NOT_ACCEPTED')
        task=self._one('rc7_task',task_id=row['workitem_id'])
        evaluation=self._one('rc7_evaluation',evaluation_id=evaluation_id)
        artifact=self._one('rc7_artifact',artifact_id=aid);evidence=self._one('rc7_evidence',evidence_id=eid)
        if (task.get('evaluation_id')!=evaluation_id or task['output_artifact_refs']!=[aid]
                or task['mission_id']!=row['mission_id'] or task['node']!='COVERAGE_AUDIT'
                or task['task_type']!='LIBRA_INCREMENTAL_MEASUREMENT' or task['required_capabilities']!=[_TOOL]
                or task['input_artifact_refs']!=row['input_artifact_refs']
                or evaluation['mission_id']!=row['mission_id'] or evaluation['node']!='COVERAGE_AUDIT'
                or artifact['artifact_type_name']!='RC72_LIBRA_MEASUREMENT'
                or evaluation['evaluator_ref']!=reviewer or evaluation['result']!='PASS'
                or evaluation['artifact_refs']!=[aid] or evaluation['evidence_refs']!=[eid]
                or evaluation['dimensions']!=dict(measurement_id=row['measurement_id'],review_sha256=row['review_sha256'])
                or artifact['producer_task_id']!=row['workitem_id'] or artifact['content_ref']!='r1://artifact/'+row['measurement_id']
                or artifact['content_hash']!=row['body_sha256'] or artifact['evidence_refs']!=[eid]
                or artifact['parent_refs']!=row['input_artifact_refs'] or artifact['mission_id']!=row['mission_id'] or artifact['state']!='VALID'
                or evidence['content_ref']!=row['body_ref'] or evidence['content_hash']!=row['body_sha256']
                or evidence['source_ref']!='r1://artifact/'+row['measurement_id'] or evidence['subject_refs']!=[row['measurement_id']]
                or evidence['mission_id']!=row['mission_id'] or evidence['kind']!='NATIVE_LIBRA_COVERAGE_REPORT'):
            raise ContractError('LIBRA_ACCEPTED_WORKITEM_PROOF_CHANGED')
        from .rc72_coverage_convergence import CoverageFeedbackService
        observation_id='NATIVE-'+row['measurement_id']
        observation=dict(observation_id=observation_id,mission_id=row['mission_id'],release_batch_id=row['release_batch_id'],
            application_id=row['application_id'],source='LIBRA_NATIVE_ACTUAL_READ',covered_units=expected['covered_units'],
            total_units=expected['total_units'],target_ratio=row['target']['target_ratio'],evidence_ref='r1://artifact/'+row['measurement_id'],
            observed_at=expected['observed_at'])
        observed=self.truth.query('rc72_coverage_observation',observation_id=observation_id)
        if not observed:CoverageFeedbackService(self.truth,release_id=self.release_id).record_observation(**observation)
        else:
            if any(observed[0].get(k)!=v for k,v in observation.items()):raise ContractError('LIBRA_ACCEPTED_OBSERVATION_CHANGED')
        self.authority.revoke_worker_lease(row['lease']['lease_id'])
        return dict(expected,observation_id=observation_id,target_ratio=row['target']['target_ratio'],coverage_met=expected['covered_units']/expected['total_units']+1e-12>=row['target']['target_ratio'])


install_overlay()
