import test from 'node:test';
import assert from 'node:assert/strict';
import {DEMO, PAGES, SECTIONS, STAGES, ScopeController} from '../tools/dsh_workbench/ui_w0_prototype/scope.mjs';

test('原版六个页面、十个项目分区、六个业务阶段固定保留',()=>{
  assert.deepEqual(PAGES,['测试首页','DSH 测试对话','项目看板','日历排期','QA Skill 安装','项目详情']);
  assert.equal(SECTIONS.length,10);assert.deepEqual(STAGES,['需求分析','用例设计','用例评审','执行中','缺陷回归','已发布']);
});
test('同需求跨两个系统版本拆三个 SST，必须按合法边过滤',()=>{
  const c=new ScopeController(DEMO);c.setBatch('B12');c.setFilter('requirement_ids','R1');
  assert.deepEqual(c.options('system_version_ids').map(x=>x.id),['V1','V2']);
  c.setFilter('system_version_ids','V2');assert.deepEqual(c.options('sst_ids').map(x=>x.id),['S3']);
  assert.equal(c.assertLegalTuple('R1','V2','S3'),true);
  assert.throws(()=>c.assertLegalTuple('R1','V2','S1'),/非法/);
});
test('共享版本不共享 SST：R2/V1 不得借用 R1/S1',()=>{
  const c=new ScopeController();c.setBatch('B12');c.setFilter('requirement_ids','R2');c.setFilter('system_version_ids','V1');
  assert.deepEqual(c.options('sst_ids').map(x=>x.id),['S4']);
  assert.throws(()=>c.setFilter('sst_ids','S1'),/关联不存在/);
});
test('同显示标签但不同系统版本，不通过标签串联',()=>{
  const c=new ScopeController();c.setBatch('B12');c.setFilter('requirement_ids','R1');
  const versions=c.options('system_version_ids');assert.equal(versions.length,2);
  assert.notEqual(versions[0].id,versions[1].id);assert.notEqual(versions[0].label,versions[1].label);
});
test('未拆 SST 显式提示，不造一个假的 SST',()=>{
  const c=new ScopeController();c.setBatch('B12');c.setFilter('requirement_ids','R3');c.setFilter('system_version_ids','V3');
  assert.deepEqual(c.options('sst_ids'),[]);assert.equal(c.status(),'待拆分 SST');
});
test('切换投产日期清除失效组合且不跨日期继承 SST',()=>{
  const c=new ScopeController();c.setBatch('B12');c.setFilter('requirement_ids','R1');c.setFilter('system_version_ids','V1');c.setFilter('sst_ids','S1');
  c.setBatch('B19');assert.deepEqual(c.query().sst_ids,[]);assert.deepEqual(c.options('sst_ids').map(x=>x.id),['S5']);
  assert.throws(()=>c.assertLegalTuple('R1','V1','S1'),/非法/);
});
test('跨项目批次不可选择，切项目清空旧范围',()=>{
  const c=new ScopeController();assert.throws(()=>c.setBatch('B2'),/不属于当前项目/);
  c.setBatch('B12');c.setFilter('requirement_ids','R1');c.setProject('P02');
  assert.equal(c.state.batch_id,null);assert.deepEqual(c.state.requirement_ids,[]);
  assert.throws(()=>c.setFilter('sst_ids','S1'),/请先选择/);
  assert.throws(()=>c.setProject('P-UNKNOWN'),/无权限/);
});
test('需求变更清除失效版本与 SST，合法关系才保留',()=>{
  const c=new ScopeController();c.setBatch('B12');c.setFilter('requirement_ids','R1');c.setFilter('system_version_ids','V2');c.setFilter('sst_ids','S3');
  c.setFilter('requirement_ids','R2');assert.deepEqual(c.state.system_version_ids,[]);assert.deepEqual(c.state.sst_ids,[]);
  c.setFilter('system_version_ids','V1');assert.deepEqual(c.options('sst_ids').map(x=>x.id),['S4']);
});
test('业务日期保持 YYYY-MM-DD 字面值，不经过 Date/UTC 换算',()=>{
  const c=new ScopeController();c.setBatch('B12');assert.equal(c.query().release_date,'2026-11-12');
});

test('一个需求可同时选多个系统版本，版本下可同时选多个合法 SST',()=>{
  const c=new ScopeController();c.setBatch('B12');
  c.setFilter('requirement_ids',['R1','R2']);
  assert.deepEqual(c.options('system_version_ids').map(x=>x.id),['V1','V2']);
  c.setFilter('system_version_ids',['V1','V2']);
  assert.deepEqual(c.options('sst_ids').map(x=>x.id),['S1','S2','S3','S4']);
  c.setFilter('sst_ids',['S1','S3','S4','S1']);
  assert.deepEqual(c.query().sst_ids,['S1','S3','S4']);
  assert.deepEqual(c.getRows().map(x=>x.sst_id),['S1','S3','S4']);
  assert.equal(c.assertLegalTuple('R1','V1','S1'),true);
  assert.equal(c.assertLegalTuple('R1','V2','S3'),true);
  assert.equal(c.assertLegalTuple('R2','V1','S4'),true);
});
test('多选非法 SST 拒绝时整次操作原子回滚，不留下部分选择',()=>{
  const c=new ScopeController();c.setBatch('B12');c.setFilter('requirement_ids',['R1']);c.setFilter('system_version_ids',['V1']);
  c.setFilter('sst_ids',['S1']);
  assert.throws(()=>c.setFilter('sst_ids',['S2','S3']),/关联不存在/);
  assert.deepEqual(c.query().sst_ids,['S1']);
});
test('需求多选缩小后，失效版本和 SST 一起级联清理',()=>{
  const c=new ScopeController();c.setBatch('B12');
  c.setFilter('requirement_ids',['R1','R2']);c.setFilter('system_version_ids',['V1','V2']);c.setFilter('sst_ids',['S1','S3','S4']);
  c.setFilter('requirement_ids',['R2']);
  assert.deepEqual(c.query().system_version_ids,['V1']);
  assert.deepEqual(c.query().sst_ids,['S4']);
});
test('清空上级筛选保留仍合法下级，切批后全部清空',()=>{
  const c=new ScopeController();c.setBatch('B12');
  c.setFilter('requirement_ids',['R1']);c.setFilter('system_version_ids',['V2']);c.setFilter('sst_ids',['S3']);
  c.setFilter('requirement_ids',[]);
  assert.deepEqual(c.query().system_version_ids,['V2']);
  assert.deepEqual(c.query().sst_ids,['S3']);
  c.setBatch('B19');
  assert.deepEqual(c.query().requirement_ids,[]);
  assert.deepEqual(c.query().system_version_ids,[]);
  assert.deepEqual(c.query().sst_ids,[]);
});
test('query 返回冻结快照，调用方不能修改共享筛选上下文',()=>{
  const c=new ScopeController();c.setBatch('B12');c.setFilter('requirement_ids',['R1','R2']);
  const snapshot=c.query();
  assert.equal(Object.isFrozen(snapshot),true);
  assert.equal(Object.isFrozen(snapshot.requirement_ids),true);
  assert.throws(()=>snapshot.requirement_ids.push('R3'),TypeError);
  assert.deepEqual(c.query().requirement_ids,['R1','R2']);
});
