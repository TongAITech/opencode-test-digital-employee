import test from 'node:test';
import assert from 'node:assert/strict';
import {RuntimeClient,canonicalNodes,runtimeContext} from '../rc7_admin/static/workbench/runtime-client.mjs';

const scope=()=>({status:'READY',scope:{project_id:'P1',batch_id:'B1',release_date:'2026-11-12'},selection:{requirement:[],version:[],sst:[]},relation_revision:7,access_scope_revision:1});
function fixtures(){
 const base={project_id:'P1',batch_id:'B1',mission_id:'M1',release_date:'2026-11-12',relation_revision:7,access_scope_revision:1,truth_revision:'sha256:'+'a'.repeat(64),as_of:'2026-11-11T01:00:00+00:00',source_refs:['fixture:verified-brv','r1:mission:M1'],gap_indicators:[],release_decision:'HOLD',human_approval:'UNKNOWN_NOT_QUERIED'};
 const identity={mission_id:'M1',release_id:'CANONICAL-RUNTIME-1'},node={...identity,mission_node_id:'N1',node_type:'N1_REALITY',state:'NOT_STARTED'};
 const graph={...structuredClone(base),missing_nodes:canonicalNodes.slice(1),records:{rc72_mission_node:[node],rc72_node_delivery:[{...identity,delivery_id:'D1',mission_node_id:'N1',node_type:'N1_REALITY'}],rc72_node_gate:[{...identity,gate_id:'G1',mission_node_id:'N1',node_type:'N1_REALITY',delivery_id:'D1',decision:'PASS'}],rc72_node_transition:[],rc72_back_edge:[]}};
 const workitems={...structuredClone(base),records:{rc7_task:[{...identity,task_id:'T1',state:'READY'}],rc72_etu:[],rc72_workitem_attempt_binding:[]}};
 const quality={...structuredClone(base),scope_complete:true,data_quality:'READ_ONLY_SNAPSHOT',evidence:[{id:'E1',integrity:'HASH_VERIFIED_ONLY',content_hash:'sha256:'+'b'.repeat(64)}]};
 return [graph,workitems,quality];
}
const response=value=>({ok:true,json:async()=>structuredClone(value)});
const port=(values,calls=[])=>async(path,options)=>{calls.push({path,options});return response(values[path.includes('/graph?')?0:path.includes('/workitems?')?1:2]);};
test('three real read routes share one qualified snapshot, never infer release PASS from Gate/hash',async()=>{
 const calls=[],client=new RuntimeClient(port(fixtures(),calls));assert.equal(await client.load(scope(),'M1'),true);
 assert.equal(calls.length,3);for(const {path,options} of calls){assert.ok(path.startsWith('/api/workbench/v1/'));assert.equal(options.method,'GET');assert.equal(options.credentials,'same-origin');assert.equal(options.redirect,'error');assert.equal(options.body,undefined);assert.ok(!path.includes('principal'));assert.deepEqual(options.headers,{Accept:'application/json'});}
 assert.equal(client.state.snapshot.release_decision,'HOLD');assert.equal(client.state.snapshot.human_approval,'UNKNOWN_NOT_QUERIED');assert.equal(client.state.snapshot.records.rc72_node_gate[0].decision,'PASS');assert.equal(client.state.snapshot.evidence[0].integrity,'HASH_VERIFIED_ONLY');
 assert.throws(()=>client.state.snapshot.records.rc7_task.push({}));assert.throws(()=>client.state.snapshot.context.project_id='foreign');assert.throws(()=>client.state={});
});
for(const [name,alter] of [
 ['source drift',v=>v[2].source_refs=['different-source']],['foreign mission',v=>v[1].mission_id='M2'],['foreign project',v=>v[0].project_id='P2'],['changed date',v=>v[2].release_date='2026-11-13'],['ACL epoch',v=>v[1].access_scope_revision=2],['relation epoch',v=>v[2].relation_revision=8],['mixed R1 bytes',v=>v[2].truth_revision='sha256:'+'c'.repeat(64)],['unqualified quality',v=>v[2].scope_complete=false],['invented approval',v=>v[0].human_approval='APPROVED'],['invented release pass',v=>v[2].release_decision='PASS'],['unknown node',v=>v[0].records.rc72_mission_node[0].node_type='N11_UNKNOWN'],['invented state',v=>v[0].records.rc72_mission_node[0].state='SUCCESS'],['foreign row',v=>v[1].records.rc7_task[0].mission_id='M2'],['foreign runtime release',v=>v[1].records.rc7_task[0].release_id='OTHER'],['duplicate task',v=>v[1].records.rc7_task.push(v[1].records.rc7_task[0])],['missing node omitted',v=>v[0].missing_nodes=[]],['cross-node gate',v=>v[0].records.rc72_node_gate[0].mission_node_id='FOREIGN'],['gate without delivery',v=>v[0].records.rc72_node_gate[0].delivery_id='FOREIGN'],['unverified evidence status',v=>v[2].evidence[0].integrity='VERIFIED_PASS'],['oversize collection',v=>v[1].records.rc7_task=Array(10001).fill(v[1].records.rc7_task[0])]
])test('fail whole snapshot closed: '+name,async()=>{const values=fixtures();alter(values);const client=new RuntimeClient(port(values));assert.equal(await client.load(scope(),'M1'),false);assert.equal(client.state.status,'ERROR');assert.equal(client.state.snapshot,null);});
test('no Scope or subset filter makes zero runtime requests and preserves no old results',async()=>{
 const calls=[],client=new RuntimeClient(port(fixtures(),calls));assert.equal(await client.load(scope(),'M1'),true);calls.length=0;
 const filtered=scope();filtered.selection.sst=['SST1'];assert.equal(await client.load(filtered,'M1'),false);assert.equal(client.state.error,'BATCH_SCOPE_REQUIRED');assert.equal(calls.length,0);assert.equal(client.state.snapshot,null);
 assert.throws(()=>runtimeContext({...scope(),status:'ERROR'}));assert.equal(await client.load({...scope(),status:'ERROR'},'M1'),false);assert.equal(calls.length,0);
});
test('bad Mission inputs make zero requests',async()=>{
 let calls=0;const client=new RuntimeClient(async()=>{calls++;return response({});});
 for(const id of ['',null,1,' M1','M1\n','x'.repeat(201)])assert.equal(await client.load(scope(),id),false);
 assert.equal(calls,0);
});
test('403 after earlier success clears every old collection; next authorized read recovers',async()=>{
 let denied=false;const values=fixtures(),client=new RuntimeClient(async(...args)=>denied?{ok:false,status:403}:port(values)(...args));
 assert.equal(await client.load(scope(),'M1'),true);denied=true;assert.equal(await client.load(scope(),'M1'),false);assert.equal(client.state.error,'HTTP_403');assert.equal(client.state.snapshot,null);denied=false;assert.equal(await client.load(scope(),'M1'),true);
});
test('clear cancels requests and rejects responses that arrive anyway',async()=>{
 const resolve=[],calls=[],client=new RuntimeClient((path,options)=>{calls.push(options);return new Promise(r=>resolve.push(()=>r(response(fixtures()[path.includes('/graph?')?0:path.includes('/workitems?')?1:2]))));});
 const promise=client.load(scope(),'M1');assert.equal(client.state.status,'LOADING');client.clear();assert.ok(calls.every(call=>call.signal.aborted));resolve.forEach(done=>done());assert.equal(await promise,false);assert.equal(client.state.status,'NOT_READY');assert.equal(client.state.snapshot,null);
});
test('failure of one read cannot publish two successful partial collections or leak exception text',async()=>{
 const values=fixtures(),client=new RuntimeClient(async(path,options)=>{if(path.includes('/workitems?'))throw Error('private host filesystem or password');return port(values)(path,options);});
 assert.equal(await client.load(scope(),'M1'),false);assert.equal(client.state.snapshot,null);assert.equal(client.state.error,'TRUTH_SOURCE_UNAVAILABLE');
});

test('N10 PASS and a PASS Gate with verified hash remain HOLD and Human unknown; missing N10 stays explicit',async()=>{
 const values=fixtures();
 const client=new RuntimeClient(port(values));await client.load(scope(),'M1');
 assert.ok(client.state.snapshot.missing_nodes.includes('N10_RELEASE_CONVERGENCE'));
 const identity={mission_id:'M1',release_id:'CANONICAL-RUNTIME-1'};
 values[0].records.rc72_mission_node.push({...identity,mission_node_id:'N10',node_type:'N10_RELEASE_CONVERGENCE',state:'PASS'});
 values[0].records.rc72_node_delivery.push({...identity,delivery_id:'D10',mission_node_id:'N10',node_type:'N10_RELEASE_CONVERGENCE'});
 values[0].records.rc72_node_gate.push({...identity,gate_id:'G10',mission_node_id:'N10',node_type:'N10_RELEASE_CONVERGENCE',delivery_id:'D10',decision:'PASS'});
 values[0].missing_nodes=values[0].missing_nodes.filter(type=>type!=='N10_RELEASE_CONVERGENCE');
 assert.equal(await client.load(scope(),'M1'),true);
 assert.equal(client.state.snapshot.release_decision,'HOLD');
 assert.equal(client.state.snapshot.human_approval,'UNKNOWN_NOT_QUERIED');
 assert.equal(client.state.snapshot.records.rc72_mission_node[1].state,'PASS');
 assert.ok(!client.state.snapshot.missing_nodes.includes('N10_RELEASE_CONVERGENCE'));
});

test('transport is called as a function, never with RuntimeClient as native fetch receiver',async()=>{
 const values=fixtures(),receivers=[];
 const client=new RuntimeClient(async function(path,options){receivers.push(this);return port(values)(path,options);});
 assert.equal(await client.load(scope(),'M1'),true);assert.deepEqual(receivers,[undefined,undefined,undefined]);
});
