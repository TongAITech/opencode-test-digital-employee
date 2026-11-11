import {scopeRequest} from './scope-client.mjs';

export const canonicalNodes=['N1_REALITY','N2_REQUIREMENT','N3_CODE_ANALYSIS','N4_TEST_DESIGN','N5_TEST_DATA','N6_EXECUTABLE_READINESS','N7_EXECUTION','N8_DIAGNOSIS_RECOVERY','N9_DEFECT','N10_RELEASE_CONVERGENCE'];
Object.freeze(canonicalNodes);
const nodeStates=new Set(['NOT_STARTED','READY','RUNNING','REVIEW_PENDING','PASS','NEEDS_REVISION','BLOCKED','HUMAN_GATE','STALE']);
const decisions=new Set(['PASS','NEEDS_REVISION','BLOCKED','HUMAN_GATE']);
const nonempty=value=>typeof value==='string'&&value.trim().length>0;
const immutable=value=>{if(value&&typeof value==='object'){Object.values(value).forEach(immutable);Object.freeze(value);}return value;};
const fail=code=>{throw Error(code);};
const strings=value=>Array.isArray(value)&&value.every(nonempty);
const unique=value=>new Set(value).size===value.length;
export function runtimeContext(state){
  if(state?.status!=='READY')fail('SCOPE_NOT_READY');
  scopeRequest(state.scope);
  if(!Number.isSafeInteger(state.relation_revision)||state.relation_revision<1||!Number.isSafeInteger(state.access_scope_revision)||state.access_scope_revision<1)fail('INVALID_SCOPE_REVISION');
  if(Object.values(state.selection||{}).some(values=>!Array.isArray(values)||values.length))fail('BATCH_SCOPE_REQUIRED');
  return {project_id:state.scope.project_id,batch_id:state.scope.batch_id,release_date:state.scope.release_date,relation_revision:state.relation_revision,access_scope_revision:state.access_scope_revision};
}
function validateEnvelope(value,context,mission){
  if(!value||Object.entries({...context,mission_id:mission}).some(([key,expected])=>value[key]!==expected))fail('RUNTIME_SCOPE_MISMATCH');
  if(!/^sha256:[a-f0-9]{64}$/.test(value.truth_revision)||!nonempty(value.as_of)||!Number.isFinite(Date.parse(value.as_of))||!strings(value.source_refs)||!value.source_refs.length||!unique(value.source_refs)||!strings(value.gap_indicators)||value.release_decision!=='HOLD')fail('INVALID_RUNTIME_SNAPSHOT');
}
function collection(value,id,mission){
  if(!Array.isArray(value)||value.length>10000)fail('INVALID_RUNTIME_COLLECTION');
  const seen=new Set();
  for(const row of value){if(!row||!nonempty(row[id])||seen.has(row[id])||row.mission_id!==mission||!nonempty(row.release_id))fail('INVALID_RUNTIME_RECORD');seen.add(row[id]);}
  return value;
}
export function validateRuntimeSnapshot(context,mission,graph,workitems,quality){
  for(const value of [graph,workitems,quality])validateEnvelope(value,context,mission);
  if(graph.truth_revision!==workitems.truth_revision||graph.truth_revision!==quality.truth_revision)fail('RUNTIME_SNAPSHOT_CHANGED');
  for(const value of [workitems,quality])if(value.source_refs.length!==graph.source_refs.length||value.source_refs.some(ref=>!graph.source_refs.includes(ref)))fail('RUNTIME_SOURCE_CHANGED');
  if(graph.human_approval!=='UNKNOWN_NOT_QUERIED'||workitems.human_approval!=='UNKNOWN_NOT_QUERIED'||quality.scope_complete!==true||quality.data_quality!=='READ_ONLY_SNAPSHOT')fail('INVALID_RUNTIME_QUALIFICATION');
  const records={},keys={rc72_mission_node:'mission_node_id',rc72_node_delivery:'delivery_id',rc72_node_gate:'gate_id',rc72_node_transition:'transition_id',rc72_back_edge:'back_edge_id',rc7_task:'task_id',rc72_etu:'etu_id',rc72_workitem_attempt_binding:'binding_id'};
  for(const [kind,id] of Object.entries(keys))records[kind]=collection((kind==='rc7_task'||kind==='rc72_etu'||kind==='rc72_workitem_attempt_binding'?workitems:graph).records?.[kind],id,mission);
  if(new Set(Object.values(records).flat().map(row=>row.release_id)).size>1)fail('RUNTIME_RELEASE_MISMATCH');
  const nodes=new Map(records.rc72_mission_node.map(row=>[row.mission_node_id,row]));
  for(const row of nodes.values())if(!canonicalNodes.includes(row.node_type)||!nodeStates.has(row.state))fail('INVALID_CANONICAL_NODE');
  const missing=canonicalNodes.filter(type=>![...nodes.values()].some(row=>row.node_type===type));
  if(!strings(graph.missing_nodes)||!unique(graph.missing_nodes)||graph.missing_nodes.length!==missing.length||graph.missing_nodes.some(type=>!missing.includes(type)))fail('INVALID_MISSING_NODES');
  const deliveries=new Map(records.rc72_node_delivery.map(row=>[row.delivery_id,row]));
  for(const row of deliveries.values())if(nodes.get(row.mission_node_id)?.node_type!==row.node_type)fail('INVALID_CANONICAL_DELIVERY');
  for(const row of records.rc72_node_gate){const delivery=deliveries.get(row.delivery_id);if(!decisions.has(row.decision)||nodes.get(row.mission_node_id)?.node_type!==row.node_type||delivery?.mission_node_id!==row.mission_node_id||delivery?.node_type!==row.node_type)fail('INVALID_CANONICAL_GATE');}
  if(!Array.isArray(quality.evidence)||quality.evidence.length>10000||quality.evidence.some(row=>!row||!nonempty(row.id)||!['HASH_VERIFIED_ONLY','HASH_MISMATCH','CONTENT_UNAVAILABLE'].includes(row.integrity))||!unique(quality.evidence.map(row=>row.id)))fail('INVALID_EVIDENCE_METADATA');
  // This display validator is not an authorization or execution gate. Server E02 owns full lineage checks.
  return immutable(structuredClone({context,mission_id:mission,truth_revision:graph.truth_revision,as_of:{graph:graph.as_of,workitems:workitems.as_of,quality:quality.as_of},source_refs:quality.source_refs,records,missing_nodes:missing,evidence:quality.evidence,gaps:[...new Set([...graph.gap_indicators,...workitems.gap_indicators,...quality.gap_indicators])],release_decision:'HOLD',human_approval:'UNKNOWN_NOT_QUERIED'}));
}

export class RuntimeClient{
  #state=immutable({status:'NOT_READY',snapshot:null});#generation=0;#controller;
  constructor(fetcher=fetch,onChange=()=>{}){this.fetcher=fetcher;this.onChange=onChange;}
  get state(){return this.#state;}
  #publish(value){this.#state=immutable(structuredClone(value));this.onChange(this.#state);}
  clear(){this.#generation++;this.#controller?.abort();this.#publish({status:'NOT_READY',snapshot:null});}
  async load(input,mission){
    this.clear();const generation=this.#generation,controller=new AbortController();this.#controller=controller;
    try{
      const context=immutable(structuredClone(runtimeContext(input)));
      if(!nonempty(mission)||mission.length>200||mission!==mission.trim()||/[\u0000-\u001f\u007f]/.test(mission))fail('INVALID_MISSION_ID');
      this.#publish({status:'LOADING',snapshot:null});
      const query=new URLSearchParams({project_id:context.project_id,batch_id:context.batch_id,release_date:context.release_date});
      const paths=[`/api/workbench/v1/missions/${encodeURIComponent(mission)}/graph?${query}`,`/api/workbench/v1/missions/${encodeURIComponent(mission)}/workitems?${query}`,`/api/workbench/v1/projects/${encodeURIComponent(context.project_id)}/release-dates/${context.release_date}/quality?${new URLSearchParams({batch_id:context.batch_id,mission_id:mission})}`];
      // Call the transport as a function: native Window.fetch rejects a client receiver.
      const values=await Promise.all(paths.map(async path=>{const response=await (0,this.fetcher)(path,{method:'GET',credentials:'same-origin',redirect:'error',headers:{Accept:'application/json'},signal:controller.signal});if(!response.ok)fail('HTTP_'+response.status);return response.json();}));
      if(generation!==this.#generation)return false;
      const snapshot=validateRuntimeSnapshot(context,mission,...values);
      this.#publish({status:'READY',snapshot});return true;
    }catch(error){if(generation!==this.#generation)return false;controller.abort();this.#publish({status:'ERROR',snapshot:null,error:/^(HTTP_\d{3}|[A-Z_]+)$/.test(error.message)?error.message:'TRUTH_SOURCE_UNAVAILABLE'});return false;}
  }
}
