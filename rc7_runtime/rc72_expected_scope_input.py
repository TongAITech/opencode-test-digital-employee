"""Freeze an expected denominator from the original, actually read N1 input.

The operator's registered ReleaseBatch input is the policy trust boundary. Its
captured bytes and accepted N1 provenance are authenticated here, not inferred
from N2 observations, Cases, successful executions or coverage percentages.
This import does not certify the bank origin of a file or grant Field approval.
"""
from dataclasses import asdict
import hmac,json
from pathlib import Path

from rc6_runtime import contracts,truth as registry
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from .models import ContractError
from .rc72_ledger_lock import ledger_lock
from .rc72_n1_strict_pipeline import N1StrictPipelineService
from .rc72_n7_execution_admission import _hash
from .rc72_native_n1_read_gate import _capture_result
from .rc72_release_scope import ReleaseScopeManifest,ReleaseScopeService

_KIND='rc72_expected_scope_input'
_EVENT='RC72_EXPECTED_SCOPE_INPUT_UPSERTED'
_SCHEMA='RC72_EXPECTED_RELEASE_SCOPE_V1'
_FIELDS={'schema','release_id','release_batch_id','mission_id','source_commit','application_ids','version_ids',
         'requirement_ssts','required_levels_by_sst','source_refs'}


def _validate(payload):
    row=dict(payload)
    for key in ('input_id','manifest_id','release_id','release_batch_id','mission_id','source_commit',
                'n1_gate_id','native_gate_id','native_call_id','input_sha256','manifest_sha256','signature'):
        contracts._require_str(row,key)
    if any(key in row for key in ('field_verified','bank_final','node_pass','converged','product_defect')):
        raise contracts.DomainValidationError('EXPECTED_SCOPE_INPUT_CLAIM_FORBIDDEN')
    contracts._require_string_list(row,'native_call_refs')
    if row.get('purpose')!='EXPECTED_SCOPE_FROM_ORIGINAL_N1_INPUT':
        raise contracts.DomainValidationError('EXPECTED_SCOPE_INPUT_PURPOSE_INVALID')
    row.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(row))
    return row


def install_overlay():
    contracts.VALIDATORS[_KIND]=_validate
    registry.EVENT_TYPES[_EVENT]=(_KIND,'input_id')
    registry.IDENTITY_FIELDS[_KIND]='input_id'
    registry.BUCKETS[_KIND]='rc72_expected_scope_inputs'


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ContractError('EXPECTED_SCOPE_DUPLICATE_JSON_KEY')
        result[key]=value
    return result


def _invalid_constant(value):
    raise ContractError('EXPECTED_SCOPE_JSON_CONSTANT_FORBIDDEN')


def _strings(items,*,allow_empty=False):
    if (not isinstance(items,list) or (not items and not allow_empty) or any(not isinstance(v,str) or not v or v!=v.strip() for v in items)
            or len(items)!=len(set(items))):
        raise ContractError('EXPECTED_SCOPE_NONEMPTY_UNIQUE_STRINGS_REQUIRED')
    return items


def parse_expected_scope(text,batch,source_commit):
    payload=json.loads(text,object_pairs_hook=_pairs,
                       parse_constant=_invalid_constant)
    if not isinstance(payload,dict) or set(payload)!=_FIELDS or payload['schema']!=_SCHEMA:
        raise ContractError('EXPECTED_SCOPE_EXACT_POLICY_INPUT_REQUIRED')
    for key in ('release_id','release_batch_id','mission_id'):
        if payload[key]!=batch[key]:raise ContractError('EXPECTED_SCOPE_RELEASE_LINEAGE_MISMATCH')
    if payload['source_commit']!=source_commit:raise ContractError('EXPECTED_SCOPE_SOURCE_MISMATCH')
    if set(_strings(payload['application_ids']))!=set(batch['application_ids']):
        raise ContractError('EXPECTED_SCOPE_APPLICATION_DENOMINATOR_MISMATCH')
    if set(_strings(payload['version_ids'],allow_empty=True))!=set(batch.get('version_ids',[])):
        raise ContractError('EXPECTED_SCOPE_VERSION_DENOMINATOR_MISMATCH')
    mapping,levels=payload['requirement_ssts'],payload['required_levels_by_sst']
    if (not isinstance(mapping,dict) or not isinstance(levels,dict)
            or set(mapping)!=set(batch['requirement_ids'])):
        raise ContractError('EXPECTED_SCOPE_REQUIREMENT_DENOMINATOR_MISMATCH')
    all_ssts=[]
    for req,values in mapping.items():all_ssts.extend(_strings(values))
    if len(all_ssts)!=len(set(all_ssts)) or set(levels)!=set(all_ssts):
        raise ContractError('EXPECTED_SCOPE_SST_DENOMINATOR_MISMATCH')
    for values in levels.values():
        if set(_strings(values))-{'L1','L2','L3','L4','L5','L6','L7'}:
            raise ContractError('EXPECTED_SCOPE_REQUIRED_LEVELS_INVALID')
    _strings(payload['source_refs'])
    return payload


class ExpectedScopeInputService:
    def __init__(self,pipeline):
        if not isinstance(pipeline,N1StrictPipelineService):raise ContractError('EXPECTED_SCOPE_NATIVE_N1_PIPELINE_REQUIRED')
        install_overlay()
        self.pipeline,self.truth=pipeline,pipeline.truth
        self.source_commit=pipeline.source_commit
        self.authority=pipeline.handoff_service.launcher.authority
        pipeline.handoff_service.expected_scope_input_schema=_SCHEMA

    def freeze(self,*,release_batch_id):
        with ledger_lock(self.truth,busy='EXPECTED_SCOPE_INPUT_LEDGER_BUSY'):
            if (self.pipeline.truth is not self.truth or self.pipeline.source_commit!=self.source_commit
                    or self.pipeline.handoff_service.truth is not self.truth
                    or self.pipeline.gate_service.truth is not self.truth
                    or self.pipeline.handoff_service.launcher.truth is not self.truth
                    or self.pipeline.handoff_service.launcher.authority is not self.authority):
                raise ContractError('EXPECTED_SCOPE_NATIVE_PIPELINE_CHANGED')
            batch=self.pipeline.handoff_service._one('rc72_release_batch',release_batch_id=release_batch_id)
            node=self.pipeline.handoff_service._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N1_REALITY')
            if node['state']!='PASS':raise ContractError('EXPECTED_SCOPE_ACCEPTED_N1_REQUIRED')
            # Semantic N1 gate plus signed raw/tool proof, without another worker.
            accepted=self.pipeline.complete(release_batch_id=release_batch_id)
            node=self.pipeline.handoff_service._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N1_REALITY')
            if node['state']!='PASS' or accepted.get('completion',{}).get('gate',{}).get('decision')!='PASS':
                raise ContractError('EXPECTED_SCOPE_CURRENT_N1_ACCEPTANCE_REQUIRED')
            service=self.pipeline.handoff_service
            assignments=self.truth.query('rc72_mission_node_worker_assignment',release_batch_id=release_batch_id,
                                         source_commit=self.source_commit,node_type='N1_REALITY')
            if len(assignments)!=1:raise ContractError('EXPECTED_SCOPE_ORIGINAL_ASSIGNMENT_REQUIRED')
            assignment=assignments[0]
            events=service._handoff_events(batch['mission_id'],service._runtime_assignment_id(assignment['assignment_id']))
            if len(events)!=1 or not events[0].get('native_n1_read_gate_id'):
                raise ContractError('EXPECTED_SCOPE_ACTUAL_NATIVE_READ_REQUIRED')
            event=events[0];service._audit_native_read(assignment,event)
            source_ref='release-batch://'+release_batch_id
            calls=self.truth.query('rc72_n1_native_read',gate_id=event['native_n1_read_gate_id'],kind='CALL',source_ref=source_ref)
            if not calls:raise ContractError('EXPECTED_SCOPE_EXACT_ORIGINAL_INPUT_READ_REQUIRED')
            calls=sorted(calls,key=lambda row:row['record_id'])
            observations=[_capture_result(row) for row in calls]
            if len({row['sha256'] for row in observations})!=1:
                raise ContractError('EXPECTED_SCOPE_ORIGINAL_INPUT_CHANGED_DURING_N1')
            call=calls[0];result=observations[0]
            payload=parse_expected_scope(result['text'],batch,self.source_commit)
            mapping,levels=payload['requirement_ssts'],payload['required_levels_by_sst']
            # Bind the selected input to the actual returned N1 candidate, so a
            # read of an unrelated document cannot become an expected policy.
            raw_ref=next(ref for ref in event['evidence_refs'] if ref.startswith('file://'))
            raw_events=tuple(DshHeadlessWorkerLauncher._parse_json_lines(Path(raw_ref[7:]).read_text(encoding='utf-8')))
            output=DshHeadlessWorkerLauncher._final_json(raw_events)
            if output.get('facts',{}).get('expected_scope_input')!=dict(source_ref=source_ref,sha256=result['sha256']):
                raise ContractError('EXPECTED_SCOPE_N1_INPUT_PROVENANCE_REQUIRED')
            manifest_id='EXPECTED-SCOPE-'+_hash([release_batch_id,self.source_commit])[:24]
            manifest=ReleaseScopeManifest(manifest_id=manifest_id,mission_id=batch['mission_id'],release_batch_id=release_batch_id,
                requirement_ssts=mapping,required_levels_by_sst=levels,
                source_refs=list(dict.fromkeys([source_ref]+payload['source_refs'])))
            manifest_payload={k:v for k,v in asdict(manifest).items() if k!='created_at'}
            deliveries=[d for d in self.truth.query('rc72_node_delivery',mission_node_id=node['mission_node_id'])
                        if d['version']==node['active_delivery_version'] and d['delivery_id'] in node['delivery_refs']]
            gates=[g for g in self.truth.query('rc72_node_gate',mission_node_id=node['mission_node_id'])
                   if g['gate_id'] in node['gate_refs'] and g['decision']=='PASS' and len(deliveries)==1 and g['delivery_id']==deliveries[0]['delivery_id']]
            if len(gates)!=1:raise ContractError('EXPECTED_SCOPE_CURRENT_N1_GATE_REQUIRED')
            record=dict(input_id='SCOPE-INPUT-'+_hash(manifest_id)[:24],purpose='EXPECTED_SCOPE_FROM_ORIGINAL_N1_INPUT',
                manifest_id=manifest_id,release_id=batch['release_id'],release_batch_id=release_batch_id,mission_id=batch['mission_id'],
                source_commit=self.source_commit,batch_scope={key:sorted(batch.get(key,[])) for key in
                    ('version_ids','application_ids','requirement_ids')},n1_gate_id=gates[0]['gate_id'],native_gate_id=event['native_n1_read_gate_id'],
                native_call_id=call['record_id'],native_call_refs=[row['record_id'] for row in calls],input_sha256=result['sha256'],manifest_sha256=_hash(manifest_payload),manifest=manifest_payload)
            existing=self.truth.query(_KIND,input_id=record['input_id'])
            if existing:
                row=existing[0];raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
                if not hmac.compare_digest(row['signature'],self.authority._sign(raw)) or raw!=record:
                    raise ContractError('EXPECTED_SCOPE_INPUT_RECEIPT_CHANGED')
            elif self.truth.query('rc72_release_scope_manifest',release_batch_id=release_batch_id):
                raise ContractError('EXPECTED_SCOPE_UNATTESTED_MANIFEST_CONFLICT')
            else:self.truth.append_atomic(_EVENT,dict(record,signature=self.authority._sign(record),artifact_version=1))
            manifests=self.truth.query('rc72_release_scope_manifest',release_batch_id=release_batch_id)
            if manifests:
                if len(manifests)!=1 or any(manifests[0].get(k)!=v for k,v in manifest_payload.items()):
                    raise ContractError('EXPECTED_SCOPE_FROZEN_MANIFEST_CHANGED')
            else:ReleaseScopeService(self.truth,release_id=batch['release_id']).persist_manifest(manifest)
            return dict(manifest_id=manifest_id,input_id=record['input_id'],input_sha256=result['sha256'],
                        field_verified=False,bank_final=False)


install_overlay()
