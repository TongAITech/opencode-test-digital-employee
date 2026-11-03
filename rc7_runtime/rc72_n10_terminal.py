"""Native N10 independent terminal review, exclusively from current R1 truth.

No actor can pass a boolean or omit a mandatory Obligation. The production
aggregator re-audits original accepted N7, N9, Libra, scope and repair sources
before/after the isolated reviewer. A signed process receipt, canonical
Evidence, fresh REVIEW session, NodeDelivery and NodeGate are required for PASS.
This is engineering release readiness, never in-bank BANK_FINAL permission.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from rc6_runtime import contracts, truth as registry
from rc6_runtime.process_environment import scoped_process_environment

from .models import ContractError
from .rc72_domain import AutonomousMissionNode as Node, MissionNodeState as State
from .rc72_domain import NodeDelivery, NodeGate, NodeGateDecision
from .rc72_n7_execution_admission import _hash
from .rc72_release_convergence import ReleaseConvergenceAggregator, ReleaseConvergenceSnapshot
from .rc72_state_machine import ReleaseConvergenceResult
from .rc72_worker_lifecycle import WorkerLifecycleService
from .rc72_n10_feedback import NativeN10FeedbackService

_KIND='rc72_n10_terminal_review'
_EVENT='RC72_N10_TERMINAL_REVIEW_UPSERTED'
_CRITERIA=['N10_ORIGINAL_SCOPE_DENOMINATOR','N10_ALL_REQUIRED_L1_L7',
    'N10_REAL_N7_AND_N9_ACCEPTANCE','N10_LIBRA_COVERAGE_AND_REPAIRS',
    'N10_ZERO_OPEN_DEFECT_GAP_OR_WORK','N10_CURRENT_R1_INTEGRITY',
    'N10_INDEPENDENT_PROCESS_REVIEW']


def install_overlay():
    def validate(payload):
        out=dict(payload)
        for key in ('review_result_id','release_id','source_commit','snapshot_id','snapshot_sha256',
                    'delivery_id','review_id','reviewer_worker_id','reviewer_session_id',
                    'input_ref','input_sha256','stdout_ref','stdout_sha256','stderr_ref',
                    'stderr_sha256','signature'):
            contracts._require_str(out,key)
        if out.get('purpose')!='N10_INDEPENDENT_TERMINAL_REVIEW' or out.get('verdict') not in {'PASS','BLOCKED'}:
            raise contracts.DomainValidationError('N10_TERMINAL_RECEIPT_INVALID')
        if not isinstance(out.get('pid'),int) or out['pid']<=0 or not isinstance(out.get('exit_code'),int):
            raise contracts.DomainValidationError('N10_TERMINAL_PROCESS_INVALID')
        if any(key in out for key in ('field_verified','bank_final','delivery_authorized')):
            raise contracts.DomainValidationError('N10_TERMINAL_BANK_CLAIM_FORBIDDEN')
        out.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(out))
        return out
    contracts.VALIDATORS[_KIND]=validate
    registry.EVENT_TYPES[_EVENT]=(_KIND,'review_result_id')
    registry.IDENTITY_FIELDS[_KIND]='review_result_id'
    registry.BUCKETS[_KIND]='rc72_n10_terminal_reviews'


class NativeN10TerminalReviewService:
    def __init__(self,aggregator,*,authority,source_commit,review_root,lifecycle,timeout_seconds=30):
        install_overlay()
        if (not isinstance(aggregator,ReleaseConvergenceAggregator)
                or aggregator.execution_proof is None or aggregator.expected_scope is None
                or aggregator.coverage_proof is None or aggregator.coverage_intake is None
                or not aggregator.replay_safe
                or aggregator.coverage_proof.authority is not authority
                or aggregator.execution_proof.source_commit!=source_commit
                or aggregator.expected_scope.source_commit!=source_commit
                or not isinstance(lifecycle,WorkerLifecycleService)
                or lifecycle.truth is not aggregator.truth or lifecycle.release_id!=aggregator.release_id
                or type(timeout_seconds) is not int or not 1<=timeout_seconds<=60):
            raise ContractError('N10_TERMINAL_NATIVE_PROOF_AND_FRESH_REVIEWER_REQUIRED')
        self.aggregate,self.authority,self.lifecycle=aggregator,authority,lifecycle
        self.truth,self.release_id,self.source_commit=aggregator.truth,aggregator.release_id,source_commit
        self.runtime=aggregator.runtime
        self.root=Path(review_root).resolve()
        self.timeout=timeout_seconds

    def _one(self,kind,**filters):
        rows=self.truth.query(kind,**filters)
        if len(rows)!=1:raise ContractError('N10_TERMINAL_R1_NOT_UNIQUE:'+kind)
        return rows[0]

    @staticmethod
    def _snapshot(snapshot):
        payload=asdict(snapshot)
        payload['result']=snapshot.result.value
        return payload

    def _current(self,snapshot):
        if not isinstance(snapshot,ReleaseConvergenceSnapshot):
            raise ContractError('N10_TERMINAL_NATIVE_SNAPSHOT_REQUIRED')
        batch=self._one('rc72_release_batch',release_batch_id=snapshot.release_batch_id)
        if batch['release_id']!=self.release_id or batch['mission_id']!=snapshot.mission_id:
            raise ContractError('N10_TERMINAL_BATCH_CHANGED')
        recorded=self._one('rc72_release_convergence_snapshot',snapshot_id=snapshot.snapshot_id)
        expected=self._snapshot(snapshot)
        if any(recorded.get(key)!=value for key,value in expected.items()):
            raise ContractError('N10_TERMINAL_SNAPSHOT_CHANGED')
        refreshed=self.aggregate.aggregate(mission_id=snapshot.mission_id)
        if (refreshed.snapshot_id!=snapshot.snapshot_id or refreshed.result!=ReleaseConvergenceResult.CONVERGED
                or snapshot.result!=ReleaseConvergenceResult.CONVERGED or snapshot.blockers
                or snapshot.unproven_obligation_ids
                or not snapshot.proven_obligation_ids or not snapshot.coverage_observation_ids
                or NativeN10FeedbackService(self.truth,release_id=self.release_id).derive(snapshot=snapshot)):
            raise ContractError('N10_TERMINAL_FULL_CONVERGENCE_REQUIRED')
        node=self.runtime.node_by_type(snapshot.mission_id,Node.N10_RELEASE_CONVERGENCE)
        if node['state'] not in {'RUNNING','REVIEW_PENDING','PASS'}:
            raise ContractError('N10_TERMINAL_ACTIVE_NODE_REQUIRED')
        return batch,node,expected

    def _delivery(self,snapshot,node):
        delivery_id='N10DEL-'+_hash([snapshot.snapshot_id,snapshot.manifest_id])[:24]
        evidence_refs=['r1://artifact/'+snapshot.snapshot_id]+[
            'r1://artifact/'+ref for ref in snapshot.coverage_observation_ids]
        expected=dict(mission_id=snapshot.mission_id,mission_node_id=node['mission_node_id'],
            node_type='N10_RELEASE_CONVERGENCE',
            producer_ref='runtime://audited-native-n10-release-aggregation',
            input_refs=[snapshot.manifest_id,snapshot.scope_snapshot_id],
            artifact_refs=[snapshot.snapshot_id],evidence_refs=evidence_refs,
            known_gaps=[],created_by_workitems=[])
        rows=self.truth.query('rc72_node_delivery',delivery_id=delivery_id)
        if rows:
            if len(rows)!=1 or any(rows[0].get(key)!=value for key,value in expected.items()):
                raise ContractError('N10_TERMINAL_DELIVERY_CHANGED')
            delivery=rows[0]
            if node['state']=='RUNNING':
                self.runtime._persist_node_state(node,State.REVIEW_PENDING,
                    reason='resume durable N10 convergence delivery',
                    active_delivery_version=delivery['version'],
                    delivery_refs=list(dict.fromkeys(node['delivery_refs']+[delivery_id])))
            elif (delivery_id not in node['delivery_refs']
                    or node['active_delivery_version']!=delivery['version']):
                raise ContractError('N10_TERMINAL_ACTIVE_DELIVERY_CHANGED')
        else:
            if node['state']!='RUNNING':
                raise ContractError('N10_TERMINAL_REVIEW_REQUIRES_RUNNING_NODE')
            prior=self.truth.query('rc72_node_delivery',mission_node_id=node['mission_node_id'])
            self.runtime.submit_delivery(NodeDelivery(delivery_id=delivery_id,
                node_type=Node.N10_RELEASE_CONVERGENCE,
                version=max([row['version'] for row in prior]+[0])+1,
                **{k:v for k,v in expected.items() if k!='node_type'}))
            delivery=self._one('rc72_node_delivery',delivery_id=delivery_id)
        return delivery

    def _reviewer(self,snapshot,delivery):
        node_id=delivery['mission_node_id'];delivery_id=delivery['delivery_id']
        context=dict(mission_id=snapshot.mission_id,team_id='TEAM-'+snapshot.mission_id,
            mission_node_id=node_id,delivery_id=delivery_id,
            criteria=_CRITERIA,evidence_refs=delivery['evidence_refs'])
        unrelated=self.truth.query('rc72_worker_session',mission_id=snapshot.mission_id)
        excluded={row['session_id'] for row in unrelated if row.get('delivery_id')!=delivery_id}
        workers={row['worker_id'] for row in unrelated if row.get('delivery_id')!=delivery_id}
        reviewers=self.truth.query('rc72_reviewer_assignment',delivery_id=delivery_id)
        if not reviewers:
            partial=self.truth.query('rc72_worker_session',delivery_id=delivery_id,purpose='REVIEW')
            if len(partial)>1:raise ContractError('N10_TERMINAL_REVIEWER_SESSION_NOT_UNIQUE')
            if partial:
                session=partial[0]
                if (session['state']!='ACTIVE' or session['context_bundle']!=context
                        or session['worker_id'] in workers or session['session_id'] in excluded):
                    raise ContractError('N10_TERMINAL_REVIEWER_SESSION_CHANGED')
                rid='N10REV-'+_hash([delivery_id,session['session_id']])[:24]
                self.truth.append_atomic('RC72_REVIEWER_ASSIGNMENT_UPSERTED',dict(
                    review_id=rid,release_id=self.release_id,mission_id=snapshot.mission_id,
                    worker_id=session['worker_id'],session_id=session['session_id'],
                    team_id=context['team_id'],mission_node_id=node_id,delivery_id=delivery_id,
                    criteria=_CRITERIA,evidence_refs=delivery['evidence_refs'],
                    context_bundle=context,created_at=session['created_at'],artifact_version=1))
            else:
                self.lifecycle.assign_fresh_reviewer(mission_id=snapshot.mission_id,
                    team_id=context['team_id'],mission_node_id=node_id,delivery_id=delivery_id,
                    criteria=_CRITERIA,evidence_refs=delivery['evidence_refs'],
                    excluded_session_ids=list(excluded))
            reviewers=self.truth.query('rc72_reviewer_assignment',delivery_id=delivery_id)
        if len(reviewers)!=1:raise ContractError('N10_TERMINAL_REVIEWER_NOT_UNIQUE')
        reviewer=reviewers[0];session=self._one('rc72_worker_session',session_id=reviewer['session_id'])
        if (reviewer['context_bundle']!=context or reviewer['criteria']!=_CRITERIA
                or reviewer['evidence_refs']!=delivery['evidence_refs']
                or reviewer['mission_id']!=snapshot.mission_id
                or reviewer['mission_node_id']!=node_id
                or reviewer['delivery_id']!=delivery_id
                or reviewer['team_id']!=context['team_id']
                or reviewer['worker_id'] in workers or reviewer['session_id'] in excluded
                or session['context_bundle']!=context or session['worker_id']!=reviewer['worker_id']
                or session['mission_id']!=snapshot.mission_id
                or session['mission_node_id']!=node_id
                or session['delivery_id']!=delivery_id
                or session['team_id']!=context['team_id']
                or session['purpose']!='REVIEW' or session['role']!='quality-reviewer'
                or session['state'] not in {'ACTIVE','CLOSED'}):
            raise ContractError('N10_TERMINAL_REVIEWER_CONTEXT_CHANGED')
        return reviewer,session

    def _safe_review_root(self,review_id):
        # Reviewer IDs are controlled by native Lifecycle. Never permit a
        # persisted R1 label to become a path outside the evidence root.
        if not re.fullmatch(r'(?:REV-[0-9a-f]{20}|N10REV-[0-9a-f]{24})',review_id):
            raise ContractError('N10_TERMINAL_REVIEWER_PATH_INVALID')
        root=self.root/review_id
        if root.is_symlink():
            raise ContractError('N10_TERMINAL_REVIEWER_PATH_SYMLINK')
        return root

    def _verify_receipt(self,receipt,snapshot,reviewer):
        raw={key:value for key,value in receipt.items()
             if key not in {'signature','artifact_type','artifact_version'}}
        if not hmac.compare_digest(receipt['signature'],self.authority._sign(raw)):
            raise ContractError('N10_TERMINAL_SIGNATURE_INVALID')
        if (receipt['release_id']!=self.release_id or receipt['source_commit']!=self.source_commit
                or receipt['snapshot_id']!=snapshot.snapshot_id
                or receipt['snapshot_sha256']!=_hash(self._snapshot(snapshot))
                or receipt['review_id']!=reviewer['review_id']
                or receipt['reviewer_worker_id']!=reviewer['worker_id']
                or receipt['reviewer_session_id']!=reviewer['session_id']
                or receipt['delivery_id']!=reviewer['delivery_id']):
            raise ContractError('N10_TERMINAL_REVIEW_LINEAGE_CHANGED')
        allowed_root=self._safe_review_root(reviewer['review_id']).resolve()
        for key in ('input','stdout','stderr'):
            ref=receipt[key+'_ref']
            path=Path(ref[len('file://'):]) if ref.startswith('file://') else None
            if path is None or path.is_symlink() or not path.is_file():
                raise ContractError('N10_TERMINAL_REVIEW_PROCESS_BYTES_CHANGED')
            try:
                path.resolve().relative_to(allowed_root)
            except ValueError as exc:
                raise ContractError('N10_TERMINAL_REVIEW_PROCESS_PATH_ESCAPED') from exc
            if hashlib.sha256(path.read_bytes()).hexdigest()!=receipt[key+'_sha256']:
                raise ContractError('N10_TERMINAL_REVIEW_PROCESS_BYTES_CHANGED')
        try:
            input_payload=json.loads(Path(receipt['input_ref'][len('file://'):]).read_text(encoding='utf-8'))
            output=json.loads(Path(receipt['stdout_ref'][len('file://'):]).read_text(encoding='utf-8'))
        except (UnicodeError,ValueError) as exc:
            raise ContractError('N10_TERMINAL_REVIEW_RESULT_INVALID') from exc
        expected=dict(snapshot_id=snapshot.snapshot_id,snapshot_sha256=receipt['snapshot_sha256'],
            review_id=reviewer['review_id'],reviewer_worker_id=reviewer['worker_id'],
            reviewer_session_id=reviewer['session_id'],criteria=_CRITERIA,
            accepted=(receipt['verdict']=='PASS'))
        from .rc72_n10_review_worker import review as independently_recompute
        if (input_payload.get('snapshot')!=self._snapshot(snapshot)
                or input_payload.get('snapshot_sha256')!=_hash(self._snapshot(snapshot))
                or input_payload.get('review_id')!=reviewer['review_id']
                or output!=independently_recompute(input_payload)
                or output!=expected or receipt['process_result']!=expected
                or receipt['exit_code']!=0 or receipt['verdict']!='PASS'):
            raise ContractError('N10_TERMINAL_REVIEW_NOT_ACCEPTED')
        return receipt

    def _run_review(self,snapshot,reviewer,delivery):
        data=self._snapshot(snapshot)
        payload=dict(snapshot=data,snapshot_id=snapshot.snapshot_id,
            snapshot_sha256=_hash(data),review_id=reviewer['review_id'],
            reviewer_worker_id=reviewer['worker_id'],
            reviewer_session_id=reviewer['session_id'],criteria=_CRITERIA)
        root=self._safe_review_root(reviewer['review_id'])
        root.mkdir(parents=True,exist_ok=True)
        input_path=root/'input.json'
        if input_path.is_symlink() or (root/'stdout.json').is_symlink() or (root/'stderr.log').is_symlink():
            raise ContractError('N10_TERMINAL_REVIEW_FILE_SYMLINK')
        source=json.dumps(payload,sort_keys=True,ensure_ascii=False).encode('utf-8')
        input_path.write_bytes(source)
        proc=subprocess.Popen([sys.executable,'-I',
            str(Path(__file__).with_name('rc72_n10_review_worker.py')),str(input_path)],
            cwd=str(root),env=scoped_process_environment(home=root/'process-home'),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            stdout,stderr=proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            proc.kill();proc.communicate()
            raise ContractError('N10_TERMINAL_REVIEW_TIMEOUT')
        stdout_path,stderr_path=root/'stdout.json',root/'stderr.log'
        stdout_path.write_text(stdout,encoding='utf-8')
        stderr_path.write_text(stderr,encoding='utf-8')
        try:result=json.loads(stdout)
        except (ValueError,TypeError):result=None
        expected=dict(snapshot_id=snapshot.snapshot_id,snapshot_sha256=_hash(data),
            review_id=reviewer['review_id'],reviewer_worker_id=reviewer['worker_id'],
            reviewer_session_id=reviewer['session_id'],criteria=_CRITERIA,accepted=True)
        # Recheck every original R1 input after the independent child process.
        self._current(snapshot)
        verdict='PASS' if proc.returncode==0 and result==expected else 'BLOCKED'
        raw=dict(review_result_id='N10REVIEW-'+_hash([reviewer['review_id'],snapshot.snapshot_id])[:24],
            purpose='N10_INDEPENDENT_TERMINAL_REVIEW',release_id=self.release_id,
            source_commit=self.source_commit,snapshot_id=snapshot.snapshot_id,
            snapshot_sha256=_hash(data),delivery_id=delivery['delivery_id'],
            review_id=reviewer['review_id'],reviewer_worker_id=reviewer['worker_id'],
            reviewer_session_id=reviewer['session_id'],verdict=verdict,
            pid=proc.pid,exit_code=proc.returncode,process_result=result,
            input_ref='file://'+str(input_path),input_sha256=hashlib.sha256(source).hexdigest(),
            stdout_ref='file://'+str(stdout_path),stdout_sha256=hashlib.sha256(stdout_path.read_bytes()).hexdigest(),
            stderr_ref='file://'+str(stderr_path),stderr_sha256=hashlib.sha256(stderr_path.read_bytes()).hexdigest())
        self.truth.append_atomic(_EVENT,dict(raw,signature=self.authority._sign(raw),artifact_version=1))
        if verdict!='PASS':raise ContractError('N10_TERMINAL_REVIEW_NOT_ACCEPTED')
        return self._one(_KIND,review_result_id=raw['review_result_id'])

    def finalize(self,*,snapshot):
        batch,node,_=self._current(snapshot)
        delivery=self._delivery(snapshot,node)
        reviewer,session=self._reviewer(snapshot,delivery)
        rows=self.truth.query(_KIND,snapshot_id=snapshot.snapshot_id)
        if len(rows)>1:raise ContractError('N10_TERMINAL_REVIEW_NOT_UNIQUE')
        if rows:
            receipt=rows[0]
        else:
            if session['state']!='ACTIVE':raise ContractError('N10_TERMINAL_REVIEWER_NOT_ACTIVE')
            receipt=self._run_review(snapshot,reviewer,delivery)
        self._verify_receipt(receipt,snapshot,reviewer)
        self._current(snapshot)
        evidence_id='N10EV-'+_hash([receipt['review_result_id'],receipt['stdout_sha256']])[:24]
        evidence=self.aggregate.coverage_proof.n9.pipeline.review.evidence
        evidence._ensure('rc7_evidence','RC7_EVIDENCE_UPSERTED','evidence_id',dict(
            evidence_id=evidence_id,release_id=self.release_id,mission_id=snapshot.mission_id,
            kind='N10_INDEPENDENT_PROCESS_REVIEW',
            source_ref='r1://artifact/'+receipt['review_result_id'],
            content_ref=receipt['stdout_ref'],content_hash=receipt['stdout_sha256'],
            subject_refs=[snapshot.snapshot_id],artifact_version=1))
        evidence._ensure('evidence','EVIDENCE_UPSERTED','id',dict(
            id=evidence_id,release_id=self.release_id,kind='N10_INDEPENDENT_PROCESS_REVIEW',
            ref=receipt['stdout_ref'],source_artifact_ref=receipt['review_result_id'],artifact_version=1))
        gate_id='N10GATE-'+_hash([receipt['review_result_id'],delivery['delivery_id']])[:24]
        gates=self.truth.query('rc72_node_gate',gate_id=gate_id)
        if gates and (len(gates)!=1 or gates[0]['decision']!='PASS'
                or gates[0]['delivery_id']!=delivery['delivery_id']
                or gates[0]['reviewer_worker_id']!=reviewer['worker_id']
                or gates[0]['reviewer_session_id']!=reviewer['session_id']
                or gates[0]['criteria']!=_CRITERIA or gates[0]['passed']!=_CRITERIA
                or gates[0]['evidence_refs']!=[evidence_id]):
            raise ContractError('N10_TERMINAL_GATE_CHANGED')
        node=self.runtime.node_by_type(snapshot.mission_id,Node.N10_RELEASE_CONVERGENCE)
        if node['state']=='REVIEW_PENDING':
            if gates:
                self.runtime._persist_node_state(node,State.PASS,
                    reason='resume independently accepted N10 terminal Gate',
                    gate_refs=list(dict.fromkeys(node['gate_refs']+[gate_id])),
                    bypass_direct_transition=True)
            else:
                self.runtime.apply_gate(NodeGate(gate_id=gate_id,
                    mission_id=snapshot.mission_id,mission_node_id=node['mission_node_id'],
                    node_type=Node.N10_RELEASE_CONVERGENCE,
                    delivery_id=delivery['delivery_id'],decision=NodeGateDecision.PASS,
                    reviewer_worker_id=reviewer['worker_id'],
                    reviewer_session_id=reviewer['session_id'],
                    criteria=_CRITERIA,passed=_CRITERIA,evidence_refs=[evidence_id],
                    reason='independent process review of complete current ReleaseBatch R1 facts'))
        elif node['state']!='PASS' or gate_id not in node['gate_refs']:
            raise ContractError('N10_TERMINAL_GATE_NOT_ACTIVE')
        if self._one('rc72_worker_session',session_id=reviewer['session_id'])['state']=='ACTIVE':
            self.lifecycle.checkpoint_and_close(reviewer['session_id'],
                reason='N10 complete-batch independent terminal review accepted')
        self._current(snapshot)
        return dict(status='PASS',reason='N10_INDEPENDENT_RELEASE_GATE_ACCEPTED',
            convergence_snapshot_id=snapshot.snapshot_id,
            terminal_gate_id=gate_id,terminal_review_id=receipt['review_result_id'],
            manifest_id=snapshot.manifest_id,field_verified=False,bank_final=False)


install_overlay()
