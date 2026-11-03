"""Deterministic N9 clearance of an actually accepted, discrepancy-free scope.

Does not classify a failure as a product defect or replace RCA/reproduction.
Any outstanding discrepancy/defect/regression work requires the professional
N9 route. This surface never supplies release convergence or bank acceptance.
"""
from copy import deepcopy
from dataclasses import asdict
import hmac

from rc6_runtime import contracts, truth as registry
from .models import ContractError
from .rc72_domain import AutonomousMissionNode as Node, MissionNodeState as State, NodeDelivery, NodeGate, NodeGateDecision
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash
from .rc72_obligation_execution_proof import AcceptedObligationExecutionProof
from .rc72_state_machine import RC72StateMachine

_KIND='rc72_n9_accepted_scope'
_EVENT='RC72_N9_ACCEPTED_SCOPE_UPSERTED'
_CRITERIA=['N9_NATIVE_ACCEPTED_EXECUTION_SCOPE','N9_NO_OPEN_DISCREPANCY',
           'N9_NO_OPEN_DEFECT','N9_NO_UNFINISHED_DEFECT_WORK','N9_ORIGINAL_EXECUTION_LINEAGE']
_TERMINAL_GAPS={'RESOLVED','WAIVED','DUPLICATE','SUPERSEDED'}


def _validate(payload):
    row=deepcopy(payload)
    for key in ('clearance_id','release_id','source_commit','release_batch_id','mission_id',
                'snapshot_sha256','signature'):
        contracts._require_str(row,key)
    if row.get('purpose')!='N9_ACCEPTED_SCOPE_NO_OPEN_DISCREPANCY' or not isinstance(row.get('snapshot'),dict):
        raise contracts.DomainValidationError('N9_ACCEPTED_SCOPE_INVALID')
    if any(k in row for k in ('product_defect','field_verified','bank_final','converged')):
        raise contracts.DomainValidationError('N9_ACCEPTED_SCOPE_CLAIM_FORBIDDEN')
    row.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(row))
    return row


def install_overlay():
    contracts.VALIDATORS[_KIND]=_validate
    registry.EVENT_TYPES[_EVENT]=(_KIND,'clearance_id')
    registry.IDENTITY_FIELDS[_KIND]='clearance_id'
    registry.BUCKETS[_KIND]='rc72_n9_accepted_scopes'


class AcceptedScopeN9Service:
    def __init__(self,pipeline):
        self.proof=AcceptedObligationExecutionProof(pipeline)
        self.pipeline=pipeline
        self.truth,self.release_id,self.source_commit=pipeline.truth,pipeline.release_id,pipeline.source_commit
        self.authority=pipeline.preparation.authority
        self.runtime=RC72StateMachine(self.truth,release_id=self.release_id)
        install_overlay()

    def _snapshot(self,release_batch_id):
        if (self.proof.pipeline is not self.pipeline or self.proof.truth is not self.truth
                or self.pipeline.truth is not self.truth or self.pipeline.source_commit!=self.source_commit
                or self.pipeline.release_id!=self.release_id or self.pipeline.preparation.authority is not self.authority):
            raise ContractError('N9_ACCEPTED_SCOPE_NATIVE_RUNTIME_CHANGED')
        # Caller holds the same fresh ledger gate for proof and intake inventory.
        proof=self.proof._audit_locked(release_batch_id=release_batch_id)
        mission=proof['mission_id']
        gaps=self.truth.query('rc7_gap',mission_id=mission)
        defects=self.truth.query('rc7_defect',mission_id=mission)
        tasks=[t for t in self.truth.query('rc7_task',mission_id=mission)
               if t['node'] in {'DEFECT','N9_DEFECT'} or t['task_type'] in
               {'QUALIFY_DEFECT','DEFECT_REPRODUCTION','DEFECT_RCA','DEFECT_REGRESSION','DEFECT_RESOLUTION'}]
        blockers=['gap:'+g['gap_id'] for g in gaps if g['state'] not in _TERMINAL_GAPS]
        # This deterministic route has no professional disposition executor.
        # Closed labels cannot launder a historic business discrepancy/defect.
        blockers+=['professional-gap-history:'+g['gap_id'] for g in gaps
                   if g['state'] in _TERMINAL_GAPS and (g['target_node'] in {'DEFECT','N9_DEFECT'}
                   or g['category'] in {'PRODUCT_DEFECT','VALID_TEST_FAILURE'})]
        blockers+=['professional-defect-history:'+d['defect_id'] for d in defects]
        blockers+=['professional-workitem-history:'+t['task_id'] for t in tasks]
        edges=self.truth.query('rc72_node_transition',mission_id=mission)
        if not any(e['kind']=='FORWARD' and e['from_node_type']=='N7_EXECUTION'
                   and e['to_node_type']=='N9_DEFECT' and e['source_gate_id']==proof['n7_gate_id'] for e in edges):
            raise ContractError('N9_ACCEPTED_SCOPE_N7_FORWARD_PROOF_REQUIRED')
        # Inventory is frozen to exact current canonical intake, including terminal
        # rows; no caller status/absence flag may substitute for the R1 scan.
        inventory=lambda rows,key:sorted(rows,key=lambda row:row[key])
        return dict(proof=proof,gaps=inventory(gaps,'gap_id'),defects=inventory(defects,'defect_id'),
                    defect_workitems=inventory(tasks,'task_id')),sorted(blockers)

    def _check(self,row,expected,error):
        if any(row.get(k)!=v for k,v in expected.items()):raise ContractError(error)

    def complete(self,*,release_batch_id):
        with ledger_lock(self.truth,busy='N9_ACCEPTED_SCOPE_LEDGER_BUSY'):
            snapshot,blockers=self._snapshot(release_batch_id)
            if blockers:
                return dict(status='HOLD',reason='N9_PROFESSIONAL_DISPOSITION_REQUIRED',blockers=blockers)
            proof=snapshot['proof'];mission=proof['mission_id']
            node=self.runtime.node_by_type(mission,Node.N9_DEFECT)
            if node['state'] not in {'READY','RUNNING','REVIEW_PENDING','PASS'}:
                raise ContractError('N9_ACCEPTED_SCOPE_NODE_NOT_READY')
            digest=_hash(snapshot)
            cid='N9CLEAR-'+_hash([release_batch_id,proof['n7_gate_id']])[:24]
            expected=dict(clearance_id=cid,purpose='N9_ACCEPTED_SCOPE_NO_OPEN_DISCREPANCY',
                release_id=self.release_id,source_commit=self.source_commit,release_batch_id=release_batch_id,
                mission_id=mission,snapshot_sha256=digest,snapshot=snapshot)
            rows=self.truth.query(_KIND,clearance_id=cid)
            if rows:
                if len(rows)!=1:raise ContractError('N9_ACCEPTED_SCOPE_CLEARANCE_NOT_UNIQUE')
                raw={k:v for k,v in rows[0].items() if k not in {'signature','artifact_version','artifact_type'}}
                if not hmac.compare_digest(rows[0]['signature'],self.authority._sign(raw)):
                    raise ContractError('N9_ACCEPTED_SCOPE_SIGNATURE_INVALID')
                self._check(rows[0],expected,'N9_ACCEPTED_SCOPE_CHANGED')
            else:
                if node['state'] not in {'READY','RUNNING'}:raise ContractError('N9_ACCEPTED_SCOPE_RECEIPT_REQUIRED')
                self.truth.append_atomic(_EVENT,dict(expected,signature=self.authority._sign(expected),artifact_version=1))
            did='N9DEL-'+_hash(cid)[:24];gid='N9GATE-'+_hash(cid)[:24]
            delivery=NodeDelivery(delivery_id=did,mission_id=mission,mission_node_id=node['mission_node_id'],
                node_type=Node.N9_DEFECT,version=1,producer_ref='rc72-native-accepted-scope-auditor',
                input_refs=[proof['n7_gate_id'],proof['bundle_id']],artifact_refs=[cid],
                evidence_refs=[proof['review_result_id']])
            d={k:v for k,v in asdict(delivery).items() if k!='created_at'};d['node_type']=Node.N9_DEFECT.value
            deliveries=self.truth.query('rc72_node_delivery',delivery_id=did)
            if deliveries:self._check(deliveries[0],d,'N9_ACCEPTED_SCOPE_DELIVERY_CHANGED')
            if node['state']=='READY':
                self.runtime.transition_state(node['mission_node_id'],State.RUNNING,reason='audit accepted N7 discrepancy inventory')
                node=self.runtime.node(node['mission_node_id'])
            if node['state']=='RUNNING':
                if not deliveries:self.runtime.submit_delivery(delivery)
                else:
                    self.runtime._persist_node_state(node,State.REVIEW_PENDING,reason='resume native N9 delivery',
                        active_delivery_version=1,delivery_refs=list(dict.fromkeys(node['delivery_refs']+[did])))
                node=self.runtime.node(node['mission_node_id'])
            if node['active_delivery_version']!=1 or did not in node['delivery_refs']:
                raise ContractError('N9_ACCEPTED_SCOPE_ACTIVE_DELIVERY_CHANGED')
            # Recompute instead of trusting the producer's absence claim.
            checked,pending=self._snapshot(release_batch_id)
            if pending or checked!=snapshot:raise ContractError('N9_ACCEPTED_SCOPE_CHANGED_DURING_REVIEW')
            gate=NodeGate(gate_id=gid,mission_id=mission,mission_node_id=node['mission_node_id'],node_type=Node.N9_DEFECT,
                delivery_id=did,decision=NodeGateDecision.PASS,reviewer_worker_id='rc72-native-n9-deterministic-checker',
                reviewer_session_id='runtime://rc72/n9-check/'+cid,criteria=list(_CRITERIA),passed=list(_CRITERIA),
                evidence_refs=[cid,proof['review_result_id']],reason='accepted execution scope has no open discrepancy or defect work')
            g={k:v for k,v in asdict(gate).items() if k!='created_at'}
            g.update(node_type=Node.N9_DEFECT.value,decision='PASS')
            gates=self.truth.query('rc72_node_gate',gate_id=gid)
            if gates:self._check(gates[0],g,'N9_ACCEPTED_SCOPE_GATE_CHANGED')
            if node['state']=='REVIEW_PENDING':
                if not gates:self.runtime.apply_gate(gate)
                else:self.runtime._persist_node_state(node,State.PASS,reason='resume native N9 gate',
                    gate_refs=list(dict.fromkeys(node['gate_refs']+[gid])),exited_at=gates[0]['created_at'],bypass_direct_transition=True)
            elif node['state']!='PASS' or not gates or gid not in node['gate_refs']:
                raise ContractError('N9_ACCEPTED_SCOPE_GATE_REQUIRED')
            transitions=self.truth.query('rc72_node_transition',source_gate_id=gid)
            if transitions:
                if len(transitions)!=1 or any(transitions[0].get(k)!=v for k,v in dict(kind='FORWARD',
                    mission_id=mission,from_node_type='N9_DEFECT',to_node_type='N10_RELEASE_CONVERGENCE').items()):
                    raise ContractError('N9_ACCEPTED_SCOPE_FORWARD_CHANGED')
            else:self.runtime.forward(Node.N9_DEFECT,Node.N10_RELEASE_CONVERGENCE,source_gate_id=gid,mission_id=mission)
            return dict(state='N9_PASS',gate_id=gid,clearance_id=cid,next_node='N10_RELEASE_CONVERGENCE',
                        field_verified=False,bank_final=False)


install_overlay()
