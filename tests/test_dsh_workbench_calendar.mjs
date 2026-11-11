import test from 'node:test';
import assert from 'node:assert/strict';
import {parseDate,formatDate,daysInMonth,shiftDate,monthCells,visibleMilestones} from '../rc7_admin/static/workbench/calendar-model.mjs';

test('Gregorian leap boundaries and exact business DATE encoding',()=>{
  assert.equal(daysInMonth(2000,2),29);assert.equal(daysInMonth(1900,2),28);assert.equal(daysInMonth(2100,2),28);
  assert.deepEqual(parseDate('0001-01-01'),{year:1,month:1,day:1});assert.equal(formatDate(99,2,28),'0099-02-28');
  assert.deepEqual(parseDate('9999-12-31'),{year:9999,month:12,day:31});
});
for(const value of ['2026-02-29','2024-02-30','0000-01-01','10000-01-01','2026-13-01','2026-00-01','2026-01-00','2026-1-01','2026-01-01T00:00:00Z',null])test('reject invalid date '+value,()=>assert.throws(()=>parseDate(value),/INVALID_CALENDAR_DATE/));
test('month/year navigation clamps days without spilling into another month',()=>{
  assert.equal(shiftDate('2024-01-31','month',1),'2024-02-29');assert.equal(shiftDate('2024-03-31','month',-1),'2024-02-29');
  assert.equal(shiftDate('2024-02-29','year',1),'2025-02-28');assert.equal(shiftDate('2026-12-31','month',1),'2027-01-31');
  assert.equal(shiftDate('2027-01-31','month',-1),'2026-12-31');
});
test('day navigation crosses leap day, year and two-digit year correctly',()=>{
  assert.equal(shiftDate('2024-02-28','day',1),'2024-02-29');assert.equal(shiftDate('2024-03-01','day',-1),'2024-02-29');
  assert.equal(shiftDate('2026-12-31','day',1),'2027-01-01');assert.equal(shiftDate('0100-01-01','day',-1),'0099-12-31');
});
test('calendar bounds return no target and invalid mode/step rejects',()=>{
  for(const mode of ['year','month','day']){assert.equal(shiftDate('0001-01-01',mode,-1),null);assert.equal(shiftDate('9999-12-31',mode,1),null);}
  assert.throws(()=>shiftDate('2026-01-01','week',1));assert.throws(()=>shiftDate('2026-01-01','day',2));
});
test('Monday-first month has real days exactly once and blank padding only',()=>{
  const january=monthCells('2000-01-10');assert.deepEqual(january.slice(0,6),[null,null,null,null,null,'2000-01-01']);assert.equal(january.filter(Boolean).length,31);assert.equal(january.length%7,0);
  const february=monthCells('2024-02-01');assert.equal(february.filter(Boolean).length,29);assert.equal(february.filter(Boolean).at(-1),'2024-02-29');
  assert.equal(monthCells('0001-01-01')[0],'0001-01-01');assert.equal(monthCells('9999-12-31').filter(Boolean).at(-1),'9999-12-31');
});
test('month day mapping is independent of viewer timezone including date-line and DST zones',()=>{
  const previous=process.env.TZ;
  try{const results=['Pacific/Kiritimati','America/Los_Angeles','Asia/Shanghai'].map(zone=>{process.env.TZ=zone;return JSON.stringify([monthCells('2024-03-01'),shiftDate('2024-03-10','day',1),monthCells('0099-02-01')]);});assert.equal(new Set(results).size,1);}finally{if(previous===undefined)delete process.env.TZ;else process.env.TZ=previous;}
});
const record=(id,date,state='ACTIVE')=>({kind:'milestone',asset_id:id,state,title:'same title',payload:{due_date:date}});
test('year/month/day projection uses exact date and stable identity rather than event title',()=>{
  const records=[record('z','2024-03-01'),record('b','2024-02-29'),record('a','2024-02-29','RETIRED'),record('outside','2025-02-28')],before=JSON.stringify(records);
  assert.deepEqual(visibleMilestones(records,'2024-02-01','year').map(r=>r.asset_id),['a','b','z']);
  assert.deepEqual(visibleMilestones(records,'2024-02-01','month').map(r=>r.asset_id),['a','b']);
  assert.deepEqual(visibleMilestones(records,'2024-02-29','day').map(r=>r.asset_id),['a','b']);
  assert.deepEqual(visibleMilestones(records,'2024-02-28','day'),[]);assert.equal(JSON.stringify(records),before);
});
test('malformed or duplicate asset fails the whole projection instead of hiding a bad date',()=>{
  for(const invalid of [record('bad','2026-02-30'),{...record('bad','2024-02-29'),kind:'case_draft'},{...record('bad','2024-02-29'),state:'PASS'}])assert.throws(()=>visibleMilestones([record('ok','2024-02-29'),invalid],'2024-02-29','day'));
  assert.throws(()=>visibleMilestones([record('a','2024-02-29'),record('a','2024-03-01')],'2024-02-29','month'));
});
