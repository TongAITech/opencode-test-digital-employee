import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const a01=readFileSync(new URL('../docs/dsh-workbench/WB-A01-ATOMIC-FEATURE-REGISTER.md',import.meta.url),'utf8');
const c=readFileSync(new URL('../docs/dsh-workbench/WB-C-W0-50-FEATURE-DELTA.md',import.meta.url),'utf8');
const idPattern=/^(?:P0[1-6]|D(?:0[1-9]|10)|X0[1-3])-\d{2}$/;
const allowed=new Set(['NAV_ONLY','STAGE_ONLY','SCOPE_MULTI_ONLY','FORM_DENY_ONLY','DENY_ONLY','ERROR_FENCE_ONLY','TEXT_HINT_ONLY','THEME_COLLAPSE_ONLY','NO_INTERACTION']);
const tableRows=doc=>doc.split('\n').filter(line=>/^\|\s*(?:P0[1-6]|D(?:0[1-9]|10)|X0[1-3])-\d{2}\s*\|/.test(line)).map(line=>line.split('|').slice(1,-1).map(cell=>cell.trim()));
export function verifyInventory(source,delta) {
  const target=tableRows(source),actual=tableRows(delta);
  assert.equal(target.length,50,'A01 baseline must remain 50 until explicitly reconciled');
  assert.equal(actual.length,50,'C must reconcile all 50 features');
  const byId=new Map(actual.map(row=>[row[0],row]));
  assert.equal(byId.size,50,'duplicate C feature_id not allowed');
  const categories={O:0,A:0,N:0};
  for(const [id,kind,sourceRef,action] of target) {
    assert.match(id,idPattern);
    assert.ok(['O','A','N'].includes(kind));
    categories[kind]++;
    if(kind==='N')assert.match(sourceRef,/N\/A/,id+': N cannot claim upstream UI');
    else assert.match(sourceRef,/app\.js:L\d+/,id+': missing upstream candidate anchor');
    const row=byId.get(id);
    assert.ok(row,'missing '+id);
    assert.equal(row.length,5,id+': C row must have five columns');
    assert.equal(row[1],kind,id+': A01 category mismatch');
    assert.equal(row[2],action,id+': A01 action drift');
    assert.ok(allowed.has(row[3]),id+': unknown demo scope');
    assert.equal(row[4],'NOT_RUN',id+': W0 demo is NOT product QA');
  }
  assert.equal(categories.O+categories.A,35);
  assert.equal(categories.N,15);
  assert.deepEqual([...byId.keys()],target.map(row=>row[0]),'source order drift');
  return {total:target.length,original:categories.O+categories.A,newTarget:categories.N};
}
test('FG20 A01 50 ID/category/action synchronized, 35 original/source candidates and 15 new',()=>assert.deepEqual(verifyInventory(a01,c),{total:50,original:35,newTarget:15}));
test('FG20 deleted mapping cannot pass',()=>assert.throws(()=>verifyInventory(a01,c.replace(/^\| P01-01 \|.*\n/m,'')),/50 features/));
test('FG20 reused ID cannot pass',()=>assert.throws(()=>verifyInventory(a01,c.replace('| P01-02 | O |','| P01-01 | O |')),/duplicate C feature_id/));
test('FG20 incorrect O/N category cannot pass',()=>assert.throws(()=>verifyInventory(a01,c.replace('| P01-01 | O |','| P01-01 | N |')),/category mismatch/));
test('FG20 fake QA_PASS cannot pass',()=>assert.throws(()=>verifyInventory(a01,c.replace('| NOT_RUN |','| QA_PASS |')),/NOT product QA/));
test('FG20 missing upstream source anchor cannot pass',()=>assert.throws(()=>verifyInventory(a01.replace('app.js:L503','app.js:MISSING'),c),/missing upstream candidate anchor/));
