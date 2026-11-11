import test from 'node:test';import assert from 'node:assert/strict';
import {ScopeClient} from '../rc7_admin/static/workbench/scope-client.mjs';
test('F published loading scope cannot retarget validation identity',async()=>{
let done;const c=new ScopeClient(()=>new Promise(r=>done=r));
const pending=c.load({project_id:'p',batch_id:'b',release_date:'2026-11-12'});
try{c.state.scope.project_id='foreign';}catch{}
done({project_id:'foreign',batch_id:'b',release_date:'2026-11-12',relation_revision:1,access_scope_revision:1,source_refs:['rv'],records:[{requirement_id:'r',system_version_id:'v',split_state:'UNSPLIT',sst_id:null,source_verified_requirement_version:{source_link_ref:'rv',source_revision:'1'},source_verified_link:null}],warnings:[],gap_indicators:[],next_page_cursor:null});
assert.equal(await pending,false);assert.equal(c.state.status,'ERROR');
});
