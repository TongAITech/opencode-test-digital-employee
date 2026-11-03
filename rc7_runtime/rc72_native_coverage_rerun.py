"""Accepted coverage repair -> real full-denominator fresh N7 execution.

This first native rerun path deliberately optimizes for truth, not speed: when
N4/N5/N6 semantics are still current it creates a new WorkItem for every
approved Case and runs the ordinary signed N7 pipeline again.  It never reuses
an old Attempt as post-repair proof.  If the canonical Case/contract denominator
changed, the existing planner refuses it; supplemental Case design belongs to a
separate N4 revision route rather than being synthesized here.
"""
from __future__ import annotations

import hmac
from copy import deepcopy

from rc6_runtime import contracts, truth as registry
from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Task
from .rc72_domain import AutonomousMissionNode as Node, MissionNodeState as State
from .rc72_n7_execution_admission import _hash
from .rc72_n7_execution_planning import ExecutionPlanningService, ExecutionPlanningError
from .rc72_n7_pipeline import N7PipelineService
from .rc72_native_coverage_repair import NativeCoverageRepairService, active_repair_boundaries, _signed as _signed_repair

_KIND='rc72_native_coverage_rerun';_EVENT='RC72_NATIVE_COVERAGE_RERUN_UPSERTED'
_ACTIVE={'PLANNED','N7_ACTIVE'}


def _validate(payload):
    row=deepcopy(payload)
    for key in ('rerun_id','release_id','source_commit','mission_id','release_batch_id','origin_n7_gate_id',
                'origin_delivery_id','origin_bundle_id','origin_plan_id','rerun_plan_id','plan_scope_sha256','signature'):
        contracts._require_str(row,key)
    contracts._require_string_list(row,'repair_ids')
    if not row['repair_ids'] or len(set(row['repair_ids']))!=len(row['repair_ids']):
        raise contracts.DomainValidationError('COVERAGE_RERUN_REPAIR_IDS_INVALID')
    if row.get('purpose')!='NATIVE_COVERAGE_FULL_N7_RERUN' or row.get('state') not in {'PLANNED','N7_ACTIVE','N7_PASS'}:
        raise contracts.DomainValidationError('COVERAGE_RERUN_STATE_INVALID')
    if not isinstance(row.get('origin_n7_delivery_version'),int) or row['origin_n7_delivery_version']<1:
        raise contracts.DomainValidationError('COVERAGE_RERUN_ORIGIN_VERSION_INVALID')
    if row['state']=='N7_PASS':
        for key in ('fresh_n7_gate_id','fresh_bundle_id'):contracts._require_str(row,key)
        contracts._require_string_list(row,'fresh_attempt_ids')
        if row['fresh_n7_gate_id']==row['origin_n7_gate_id'] or not row['fresh_attempt_ids']:
            raise contracts.DomainValidationError('COVERAGE_RERUN_FRESH_PROOF_REQUIRED')
    if any(k in row for k in ('field_verified','bank_final','converged','product_defect','root_cause_proved')):
        raise contracts.DomainValidationError('COVERAGE_RERUN_COMPLETION_CLAIM_FORBIDDEN')
    row.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(row));return row


def install_overlay():
    contracts.VALIDATORS[_KIND]=_validate
    registry.EVENT_TYPES[_EVENT]=(_KIND,'rerun_id');registry.IDENTITY_FIELDS[_KIND]='rerun_id'
    registry.BUCKETS[_KIND]='rc72_native_coverage_reruns'


class CoverageRerunPlanningService(ExecutionPlanningService):
    """Thin persisted selector around the canonical planner.

    The canonical planner still validates the original Case/N6 denominator.  A
    rerun plan may change only WorkItem identity; Case, contract, admission, ETU,
    snapshot and input digest remain exact.
    """
    def __init__(self,base,owner):
        self.base,self.owner=base,owner
        self.truth,self.release_id,self.source_commit=base.truth,base.release_id,base.source_commit
        self.authority,self.admission=base.authority,base.admission
    def plan(self,*,release_batch_id):
        rows=[row for row in self.truth.query(_KIND,release_batch_id=release_batch_id) if row['state'] in _ACTIVE]
        if rows:
            if len(rows)!=1:raise ExecutionPlanningError('COVERAGE_RERUN_ACTIVE_PLAN_NOT_UNIQUE')
            return self.owner._ensure_plan(rows[0])
        return self.base.plan(release_batch_id=release_batch_id)
    def assert_current(self,plan_id):
        rows=self.truth.query('rc72_n7_execution_plan',plan_id=plan_id)
        if len(rows)==1 and rows[0].get('coverage_rerun_id'):
            return self.owner._assert_plan(rows[0])
        return self.base.assert_current(plan_id)


class NativeCoverageRerunService:
    def __init__(self,repair):
        if not isinstance(repair,NativeCoverageRepairService):raise ContractError('NATIVE_COVERAGE_REPAIR_REQUIRED')
        pipeline=repair.measurement.n9.pipeline
        if not isinstance(pipeline,N7PipelineService) or pipeline.truth is not repair.truth or pipeline.source_commit!=repair.source_commit:
            raise ContractError('NATIVE_COVERAGE_RERUN_N7_PIPELINE_REQUIRED')
        install_overlay();self.repair,self.pipeline=repair,pipeline
        self.truth,self.authority=repair.truth,repair.authority
        self.release_id,self.source_commit=repair.release_id,repair.source_commit
        current=pipeline.preparation.planning
        if isinstance(current,CoverageRerunPlanningService):
            current.owner=self;self.planning=current
        else:
            self.planning=CoverageRerunPlanningService(current,self);pipeline.preparation.planning=self.planning

    def _one(self,kind,**filters):
        rows=self.truth.query(kind,**filters)
        if len(rows)!=1:raise ContractError('COVERAGE_RERUN_TRUTH_NOT_UNIQUE:'+kind)
        return rows[0]

    def _signed(self,row):
        raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        if not hmac.compare_digest(row['signature'],self.authority._sign(raw)):
            raise ContractError('COVERAGE_RERUN_SIGNATURE_INVALID')
        if row['release_id']!=self.release_id or row['source_commit']!=self.source_commit:
            raise ContractError('COVERAGE_RERUN_SOURCE_CHANGED')
        return row

    def _persist(self,row):
        raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        old=self.truth.query(_KIND,rerun_id=raw['rerun_id'])
        self.truth.append_atomic(_EVENT,dict(raw,signature=self.authority._sign(raw),artifact_version=old[0]['artifact_version']+1 if old else 1))
        return self._one(_KIND,rerun_id=raw['rerun_id'])

    def _active_repairs(self,release_batch_id):
        batch=self._one('rc72_release_batch',release_batch_id=release_batch_id)
        rows=[]
        for app in batch['application_ids']:
            rows.extend(active_repair_boundaries(self.truth,self.authority,release_id=self.release_id,
                source_commit=self.source_commit,release_batch_id=release_batch_id,application_id=app))
        return batch,sorted(rows,key=lambda row:row['repair_id'])

    def _historical_origin(self,origin_gate_id,*,audit_current=False):
        gate=self._one('rc72_node_gate',gate_id=origin_gate_id)
        if gate['decision']!='PASS' or gate['node_type']!='N7_EXECUTION':raise ContractError('COVERAGE_RERUN_ACCEPTED_ORIGIN_GATE_REQUIRED')
        delivery=self._one('rc72_node_delivery',delivery_id=gate['delivery_id'])
        bundles=[self._one('rc72_n7_evidence_bundle',bundle_id=ref) for ref in delivery['artifact_refs']
                 if self.truth.query('rc72_n7_evidence_bundle',bundle_id=ref)]
        if len(bundles)!=1:raise ContractError('COVERAGE_RERUN_ACCEPTED_ORIGIN_BUNDLE_REQUIRED')
        bundle=bundles[0]
        reviews=self.truth.query('rc72_n7_execution_review',bundle_id=bundle['bundle_id'])
        if len(reviews)!=1 or reviews[0]['verdict']!='PASS':raise ContractError('COVERAGE_RERUN_ACCEPTED_ORIGIN_REVIEW_REQUIRED')
        self.pipeline.finalization._verify(reviews[0])
        if audit_current:
            accepted=self.pipeline.finalization.audit(bundle['bundle_id'])
            if accepted['gate_id']!=origin_gate_id:raise ContractError('COVERAGE_RERUN_ORIGIN_GATE_CHANGED')
        return gate,delivery,bundle,reviews[0]

    def _record(self,release_batch_id,repairs):
        gates={row['origin_n7_gate_id'] for row in repairs}
        if len(gates)!=1:return None
        origin_gate=next(iter(gates));repair_ids=[row['repair_id'] for row in repairs]
        rid='COV-RERUN-'+_hash([release_batch_id,origin_gate,repair_ids])[:24]
        rows=self.truth.query(_KIND,rerun_id=rid)
        if len(rows)>1:raise ContractError('COVERAGE_RERUN_BOUNDARY_NOT_UNIQUE')
        # Recovery must authenticate the immutable historical origin but must not
        # require it to remain the active N7 gate after a fresh rerun succeeded.
        # Only the first durable rerun receipt is allowed to stale the then-current
        # accepted N7 epoch, so creation performs the stronger current audit.
        gate,delivery,bundle,review=self._historical_origin(origin_gate,audit_current=not bool(rows))
        origin_plan=self.planning.base.assert_current(bundle['plan_id'], review_only=True)
        plan_id='N7COVPLAN-'+_hash([rid,origin_plan['input_digest']])[:24]
        scope=_hash([origin_plan['plan_id'],origin_plan['snapshot_id'],origin_plan['input_digest'],
                     [(item['case_id'],item['contract_id'],item['admission_id'],item['etu_id'],item['input_artifact_refs']) for item in origin_plan['items']]])
        expected=dict(rerun_id=rid,purpose='NATIVE_COVERAGE_FULL_N7_RERUN',release_id=self.release_id,
            source_commit=self.source_commit,mission_id=bundle['mission_id'],release_batch_id=release_batch_id,
            repair_ids=repair_ids,origin_n7_gate_id=origin_gate,origin_delivery_id=delivery['delivery_id'],
            origin_n7_delivery_version=delivery['version'],origin_bundle_id=bundle['bundle_id'],origin_plan_id=origin_plan['plan_id'],
            rerun_plan_id=plan_id,plan_scope_sha256=scope,state='PLANNED')
        if rows:
            row=self._signed(rows[0])
            for key,value in expected.items():
                if key!='state' and row.get(key)!=value:raise ContractError('COVERAGE_RERUN_BOUNDARY_CHANGED')
            return row
        return self._persist(expected)

    def _expected_items(self,record,origin):
        return [dict(item,workitem_id='N7COVWI-'+_hash([record['rerun_id'],item['case_id']])[:24]) for item in origin['items']]

    def _assert_repairs(self,record):
        for rid in record['repair_ids']:
            row=_signed_repair(self._one('rc72_native_coverage_repair',repair_id=rid),self.authority)
            if (row['release_batch_id']!=record['release_batch_id'] or row['origin_n7_gate_id']!=record['origin_n7_gate_id']
                    or row['state'] not in {'FRESH_N7_REQUIRED','CLOSED'}):
                raise ContractError('COVERAGE_RERUN_REPAIR_BOUNDARY_CHANGED')

    def _assert_plan(self,plan):
        record=self._signed(self._one(_KIND,rerun_id=plan['coverage_rerun_id']))
        self._assert_repairs(record);self._historical_origin(record['origin_n7_gate_id'])
        origin=self.planning.base.assert_current(record['origin_plan_id'], review_only=True) if record['origin_plan_id']!=plan['plan_id'] else None
        if origin is None:raise ContractError('COVERAGE_RERUN_ORIGIN_PLAN_INVALID')
        expected=self._expected_items(record,origin)
        scope=_hash([origin['plan_id'],origin['snapshot_id'],origin['input_digest'],
                     [(item['case_id'],item['contract_id'],item['admission_id'],item['etu_id'],item['input_artifact_refs']) for item in origin['items']]])
        if (record['plan_scope_sha256']!=scope or plan['plan_id']!=record['rerun_plan_id']
                or plan['release_id']!=self.release_id or plan['source_commit']!=self.source_commit
                or plan['release_batch_id']!=record['release_batch_id'] or plan['mission_id']!=record['mission_id']
                or plan['snapshot_id']!=origin['snapshot_id'] or plan['input_digest']!=origin['input_digest']
                or plan['status']!='PLANNED' or plan['items']!=expected):
            raise ContractError('COVERAGE_RERUN_PLAN_CHANGED')
        if {item['workitem_id'] for item in plan['items']} & {item['workitem_id'] for item in origin['items']}:
            raise ContractError('COVERAGE_RERUN_OLD_WORKITEM_REUSE_FORBIDDEN')
        for index,item in enumerate(expected):
            task=self._one('rc7_task',task_id=item['workitem_id']);contract=self._one('rc72_n6_executable_contract',contract_id=item['contract_id'])
            if (task['mission_id']!=record['mission_id'] or task['node']!='EXECUTION' or task['task_type']!='RC72_CASE_EXECUTION'
                    or task['required_capabilities']!=[value['name'] for value in contract['capabilities']]
                    or task['input_artifact_refs']!=item['input_artifact_refs']):
                raise ContractError('COVERAGE_RERUN_WORKITEM_CHANGED')
        return plan

    def _ensure_plan(self,record):
        record=self._signed(record);self._assert_repairs(record)
        origin=self.planning.base.assert_current(record['origin_plan_id'], review_only=True)
        items=self._expected_items(record,origin);control=ClosedLoopControlPlane(self.truth,self.release_id,record['mission_id'])
        for index,item in enumerate(items):
            contract=self._one('rc72_n6_executable_contract',contract_id=item['contract_id'])
            rows=self.truth.query('rc7_task',task_id=item['workitem_id'])
            if not rows:
                control.register_task(Task(task_id=item['workitem_id'],mission_id=record['mission_id'],node='EXECUTION',
                    task_type='RC72_CASE_EXECUTION',objective='Re-execute approved Case '+item['case_id']+' after accepted coverage repair',
                    required_capabilities=[value['name'] for value in contract['capabilities']],input_artifact_refs=item['input_artifact_refs'],
                    acceptance_criteria=['Fresh Attempt, assertions, cleanup and canonical Evidence; no historical PASS reuse'],priority=300+index))
        payload=dict(plan_id=record['rerun_plan_id'],release_id=self.release_id,source_commit=self.source_commit,
            release_batch_id=record['release_batch_id'],mission_id=record['mission_id'],snapshot_id=origin['snapshot_id'],
            input_digest=origin['input_digest'],status='PLANNED',items=items,coverage_rerun_id=record['rerun_id'])
        rows=self.truth.query('rc72_n7_execution_plan',plan_id=record['rerun_plan_id'])
        if not rows:self.truth.append_atomic('RC72_N7_EXECUTION_PLAN_UPSERTED',dict(payload,artifact_version=1))
        elif len(rows)!=1:raise ContractError('COVERAGE_RERUN_PLAN_NOT_UNIQUE')
        return self._assert_plan(self._one('rc72_n7_execution_plan',plan_id=record['rerun_plan_id']))

    def _active_n7_gate(self,mission_id):
        node=self.repair.measurement.n9.runtime.node_by_type(mission_id,Node.N7_EXECUTION)
        deliveries=[row for row in self.truth.query('rc72_node_delivery',mission_node_id=node['mission_node_id'])
                    if row['version']==node.get('active_delivery_version') and row['delivery_id'] in node.get('delivery_refs',[])]
        if len(deliveries)!=1:return None
        gates=[self._one('rc72_node_gate',gate_id=gid) for gid in node.get('gate_refs',[])]
        gates=[gate for gate in gates if gate['delivery_id']==deliveries[0]['delivery_id'] and gate['decision']=='PASS']
        return gates[0]['gate_id'] if len(gates)==1 else None

    def _activate(self,record):
        runtime=self.repair.measurement.n9.runtime;mission=record['mission_id']
        n7=runtime.node_by_type(mission,Node.N7_EXECUTION)
        n9=runtime.node_by_type(mission,Node.N9_DEFECT);n10=runtime.node_by_type(mission,Node.N10_RELEASE_CONVERGENCE)
        if record['state']=='PLANNED':
            if n7['state']=='PASS':
                if self._active_n7_gate(mission)!=record['origin_n7_gate_id']:raise ContractError('COVERAGE_RERUN_ORIGIN_N7_CHANGED')
            elif n7['state'] not in {'STALE','READY'}:raise ContractError('COVERAGE_RERUN_N7_STATE_INVALID')
            if n10['state']!='STALE':runtime.mark_stale(n10['mission_node_id'],reason='accepted coverage repair requires fresh N7 and Libra')
            if n9['state']!='STALE':runtime.mark_stale(n9['mission_node_id'],reason='accepted coverage repair supersedes prior N9 clearance')
            n7=runtime.node_by_type(mission,Node.N7_EXECUTION)
            if n7['state']=='PASS':runtime.mark_stale(n7['mission_node_id'],reason='accepted coverage repair requires physical re-execution')
            n7=runtime.node_by_type(mission,Node.N7_EXECUTION)
            if n7['state']=='STALE':runtime.transition_state(n7['mission_node_id'],State.READY,reason='coverage repair rerun plan is frozen')
            return self._persist(dict(record,state='N7_ACTIVE'))
        return record

    def _audit_pass(self,record):
        result=self.pipeline.finalization.audit(record['fresh_bundle_id'])
        if (result['gate_id']!=record['fresh_n7_gate_id'] or result['gate_id']==record['origin_n7_gate_id']
                or result['attempt_ids']!=record['fresh_attempt_ids']):raise ContractError('COVERAGE_RERUN_FRESH_N7_CHANGED')
        bundle=self._one('rc72_n7_evidence_bundle',bundle_id=result['bundle_id'])
        if bundle['plan_id']!=record['rerun_plan_id'] or len(result['attempt_ids'])!=len(bundle['case_results']):
            raise ContractError('COVERAGE_RERUN_FULL_DENOMINATOR_REQUIRED')
        gate=self._one('rc72_node_gate',gate_id=result['gate_id']);delivery=self._one('rc72_node_delivery',delivery_id=gate['delivery_id'])
        if delivery['version']<=record['origin_n7_delivery_version']:raise ContractError('COVERAGE_RERUN_DELIVERY_VERSION_NOT_FRESH')
        return dict(state='N7_PASS',rerun_id=record['rerun_id'],plan_id=record['rerun_plan_id'],gate_id=result['gate_id'],
            bundle_id=result['bundle_id'],attempt_ids=result['attempt_ids'])

    def run(self,*,release_batch_id):
        batch,repairs=self._active_repairs(release_batch_id)
        if not repairs:
            return dict(status='HOLD',reason='ACTIVE_COVERAGE_REPAIR_REQUIRED')
        if len({row['origin_n7_gate_id'] for row in repairs})!=1:
            return dict(status='HOLD',reason='COVERAGE_REPAIR_MULTIPLE_N7_EPOCHS_REQUIRE_SEQUENTIAL_RERUN')
        record=self._record(release_batch_id,repairs);self._ensure_plan(record)
        if record['state']=='N7_PASS':return self._audit_pass(record)
        record=self._activate(record)
        result=self.pipeline.complete(release_batch_id=release_batch_id)
        if result.get('state')!='N7_PASS':return dict(status='HOLD',reason=result.get('reason','COVERAGE_RERUN_N7_NOT_ACCEPTED'),rerun_id=record['rerun_id'])
        if result['gate_id']==record['origin_n7_gate_id']:raise ContractError('COVERAGE_RERUN_OLD_N7_GATE_REUSE_FORBIDDEN')
        # The N7 finalize response intentionally does not carry a bundle ID.
        # Recover it only from the accepted canonical Gate -> Delivery, and
        # independently audit the signed full-denominator N7 proof before
        # sealing an R1 freshness receipt.  Never trust a response label.
        gate=self._one('rc72_node_gate',gate_id=result['gate_id'])
        if gate['node_type']!='N7_EXECUTION' or gate['mission_id']!=record['mission_id'] or gate['decision']!='PASS':
            raise ContractError('COVERAGE_RERUN_FRESH_GATE_INVALID')
        delivery=self._one('rc72_node_delivery',delivery_id=gate['delivery_id'])
        bundles=[self._one('rc72_n7_evidence_bundle',bundle_id=ref) for ref in delivery['artifact_refs']
                 if self.truth.query('rc72_n7_evidence_bundle',bundle_id=ref)]
        if len(bundles)!=1 or bundles[0]['plan_id']!=record['rerun_plan_id']:
            raise ContractError('COVERAGE_RERUN_FRESH_BUNDLE_NOT_UNIQUE')
        verified=self.pipeline.finalization.audit(bundles[0]['bundle_id'])
        if verified['gate_id']!=result['gate_id'] or verified['attempt_ids']!=result['attempt_ids']:
            raise ContractError('COVERAGE_RERUN_FRESH_PROOF_CHANGED')
        current=self._one(_KIND,rerun_id=record['rerun_id'])
        if current['state']!='N7_PASS':
            current=self._persist(dict(current,state='N7_PASS',fresh_n7_gate_id=verified['gate_id'],
                fresh_bundle_id=verified['bundle_id'],fresh_attempt_ids=verified['attempt_ids']))
        return self._audit_pass(current)


install_overlay()
