import test from 'node:test';
import assert from 'node:assert/strict';
import { ScopeReadFence, classifySourcePreview, scopeIdentity } from '../tools/dsh_workbench/ui_w0_prototype/source_fence.mjs';
import {ScopeController, DEMO} from '../tools/dsh_workbench/ui_w0_prototype/scope.mjs';

const control=()=>{const c=new ScopeController(DEMO); c.setBatch('B12');c.setFilter('requirement_ids',['R1','R2']);return c;};
const response=(ticket,http_status=200,body={})=>({
  http_status,project_id:ticket.project_id,batch_id:ticket.batch_id,
  relation_revision:ticket.relation_revision,access_scope_revision:ticket.access_scope_revision,
  truth_revision:ticket.truth_revision,body
});

test('scope identity includes project batch selected composite IDs and versions, not display labels',()=>{
  const c=control();
  c.setFilter('system_version_ids',['V1','V2']);c.setFilter('sst_ids',['S1','S3','S4']);
  const id=scopeIdentity(c.query());
  assert.match(id,/"batch_id":"B12"/);assert.match(id,/"system_version_ids":\["V1","V2"\]/);
  const switched=c.query();assert.equal(id,scopeIdentity({...switched,requirement_ids:['R2','R1']}));
  assert.notEqual(id,scopeIdentity({...switched,project_id:'P02'}));
  assert.notEqual(id,scopeIdentity({...switched,relation_revision:'rev2'}));
});
test('unknown or unset batch fails closed; invalid preview cannot infer QA PASS',()=>{
  assert.throws(()=>scopeIdentity({project_id:'P01',batch_id:null}),/NO_PROJECT_BATCH_SCOPE/);
  assert.deepEqual(classifySourcePreview({http_status:200}).code,'SOURCE_UNKNOWN');
  assert.equal(classifySourcePreview({http_status:200,body:{node_gate:'PASS',evidence_refs:['hash:1'],human_review_approved:true}}).code,'PREVIEW_ONLY');
});
test('403 must never expose project or batch identity in error text',()=>{
  const r=classifySourcePreview({http_status:403,body:{project_id:'PRIVATE',batch_id:'SECRET'}});
  assert.equal(r.code,'FORBIDDEN');assert.equal(r.verified,false);
  assert.doesNotMatch(r.message,/PRIVATE|SECRET/);
});
test('401/404/409/422/503 map to explicit denial rather than empty success',()=>{
  const codes={401:'AUTH_REQUIRED',404:'NOT_FOUND',409:'REVISION_CONFLICT',422:'INVALID_SCOPE',503:'SOURCE_UNAVAILABLE'};
  for(const [status,expected] of Object.entries(codes)){
    const r=classifySourcePreview({http_status:Number(status)});
    assert.equal(r.code,expected);assert.equal(r.verified,false);
  }
});
test('NodeGate PASS without evidence or human review must remain HOLD',()=>{
  const noEvidence=classifySourcePreview({http_status:200,body:{node_gate:'PASS',human_review_approved:true,evidence_refs:[]}});
  const noReview=classifySourcePreview({http_status:200,body:{node_gate:'PASS',human_review_approved:false,evidence_refs:['sha256:a']}});
  assert.equal(noEvidence.code,'EVIDENCE_OR_REVIEW_MISSING');
  assert.equal(noReview.code,'EVIDENCE_OR_REVIEW_MISSING');
  assert.doesNotMatch(noEvidence.message,/QA_PASS/);
});
test('stale R1 truth maps to UNKNOWN not PASS',()=>{
  for(const truth_status of ['STALE','UNKNOWN']){
    const r=classifySourcePreview({http_status:200,body:{truth_status,node_gate:'PASS'}});
    assert.equal(r.code,'TRUTH_NOT_READY'); assert.equal(r.verified,false);
  }
});
test('late response after project or batch switch cannot overwrite latest view',()=>{
  const c=control(), fence=new ScopeReadFence(),old=fence.begin(c.query());
  c.setBatch('B19');const fresh=fence.begin(c.query());
  let r=fence.accept(old,response(old,200,{node_gate:'PASS'}));
  assert.equal(r.accepted,false);assert.equal(r.result.code,'STALE_RESPONSE');
  assert.equal(fence.latest.code,'SOURCE_UNKNOWN');
  r=fence.accept(fresh,response(fresh,503));
  assert.equal(r.accepted,true);assert.equal(fence.latest.code,'SOURCE_UNAVAILABLE');
});
test('new filter selection invalidates previous response even in same batch',()=>{
  const c=control(), fence=new ScopeReadFence(),before=fence.begin(c.query());
  c.setFilter('requirement_ids',['R1']);const after=fence.begin(c.query());
  assert.equal(fence.accept(before,response(before,200,{})).accepted,false);
  assert.equal(fence.accept(after,response(after,200,{})).result.code,'PREVIEW_ONLY');
});
test('wrong response project, batch, relation or ACL revisions rejected before showing data',()=>{
  const c=control(),fence=new ScopeReadFence();
  const ticket=fence.begin({...c.query(),relation_revision:'r1',access_scope_revision:'a1',truth_revision:'t1'});
  for(const mutation of [
    {project_id:'P02'},{batch_id:'B19'},{relation_revision:'r2'},
    {access_scope_revision:'a2'},{truth_revision:'t2'}]) {
    const reply={...response(ticket,200,{node_gate:'PASS'}),...mutation};
    const r=fence.accept(ticket,reply);
    assert.equal(r.accepted,false);assert.equal(r.result.code,'SOURCE_SCOPE_MISMATCH');
  }
});
test('clearing Scope invalidates outstanding ticket and private result never becomes visible',()=>{
  const c=control(),fence=new ScopeReadFence(),old=fence.begin(c.query());
  fence.invalidate();assert.equal(fence.latest.code,'SCOPE_CLEARED');
  assert.equal(fence.accept(old,response(old,200,{node_gate:'PASS'})).accepted,false);
  assert.equal(fence.latest.code,'SCOPE_CLEARED');
});
