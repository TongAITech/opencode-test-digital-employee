import { DEMO, PAGES, SECTIONS, STAGES, ScopeController } from './scope.mjs';
const $ = id => document.getElementById(id);
const ctrl = new ScopeController(DEMO);
let page = '测试首页';
let section = SECTIONS[0];
const sectionMessages = {
  '项目概览': '项目、成员、阶段时间线与风险；质量摘要必须来自 R1 的同一批次快照。',
  '质量任务': '任务来源、评审、执行配置、证据、回归和诊断；不能用请求已发送替代执行成功。',
  '需求': '功能及非功能需求、验收标准；按真实需求—版本—SST 关联展开。',
  '测试用例': '优先级、前置、步骤、预期、风险、追踪、L1–L7 和测试义务。',
  '缺陷': '严重度、预期/实际、复现步骤、环境、独立复现、回归链。',
  '里程碑': '按当前业务日查看、编辑计划并关联日历；禁止跨项目编辑。',
  '报告': '测试计划、测试报告、发布说明、多版本审批、证据缺口。',
  '知识': '项目知识、代码影响、接口与数据库来源检索。',
  '会议纪要': '决议、责任人、行动项与日期/需求/版本/SST 关联。',
  '门禁': '人审申请、驳回、风险接受；原质量门禁不等于 RC7.2 NodeGate。'
};
function setNotice(text) { $('global-message').textContent = text; }
function populate(select, options, placeholder, selected = '') {
  select.replaceChildren();
  const initial = document.createElement('option'); initial.value = ''; initial.textContent = placeholder; select.append(initial);
  for (const o of options) { const node = document.createElement('option'); node.value = o.id; node.textContent = o.label; select.append(node); }
  select.value = selected || '';
}
function renderScope() {
  const s = ctrl.query();
  populate($('batch'), ctrl.batches().map(b => ({ id: b.id, label: b.release_date })), '请选择投产日期', s.batch_id);
  populate($('requirement'), ctrl.options('requirement_ids'), '全部需求', s.requirement_ids[0]);
  populate($('version'), ctrl.options('system_version_ids'), '全部系统版本', s.system_version_ids[0]);
  populate($('sst'), ctrl.options('sst_ids'), '全部 SST', s.sst_ids[0]);
  for (const id of ['requirement','version','sst']) $(id).disabled = !s.batch_id;
  $('scope-status').textContent = ctrl.status();
  $('scope-echo').textContent = `当前上下文：${s.release_date || '未选择日期'} / ${s.requirement_ids.join(',') || '全部需求'} / ${s.system_version_ids.join(',') || '全部版本'} / ${s.sst_ids.join(',') || '全部 SST'}；所有十个分区复用此上下文。`;
}
function renderPage(next) {
  if (!PAGES.includes(next)) throw new Error('未知页面');
  page = next;
  const ids = { '测试首页':'dashboard', 'DSH 测试对话':'conversation', '项目看板':'board', '日历排期':'calendar', 'QA Skill 安装':'skills', '项目详情':'detail' };
  for (const [key,id] of Object.entries(ids)) $(id).hidden = next !== key;
  for (const button of document.querySelectorAll('[data-page]')) { button.classList.toggle('active', button.dataset.page === next); button.setAttribute('aria-current', button.dataset.page === next ? 'page' : 'false'); }
  $('page-title').textContent = next;
  if (next === '项目详情') renderScope();
}
function renderSection(next) {
  if (!SECTIONS.includes(next)) throw new Error('未知项目分区');
  section = next;
  $('section-title').textContent = next;
  $('section-content').textContent = sectionMessages[next] + '（功能目标，尚未接入正式 API）';
  $('detail-error').hidden = true;
  for (const btn of $('detail-tabs').querySelectorAll('button')) btn.classList.toggle('active', btn.textContent === next);
  renderScope();
}
function showFailure(fn) { try { fn(); setNotice('演示筛选已更新；不代表已通过服务端权限校验。'); } catch(e) { setNotice(`操作已阻断：${e.message}`); } }
function boot() {
  populate($('project'), DEMO.projects.map(p => ({id:p.id,label:p.name})), '请选择项目', ctrl.state.project_id);
  $('project-card').textContent = DEMO.projects[0].name;
  for (const s of STAGES) { const tile = document.createElement('article'); tile.className='stage'; const h=document.createElement('h3'); h.textContent=s; const p=document.createElement('p'); p.textContent='演示阶段 · 无真实状态'; tile.append(h,p); $('stage-grid').append(tile); }
  for (const s of SECTIONS) { const btn=document.createElement('button');btn.type='button';btn.textContent=s;btn.addEventListener('click',()=>renderSection(s));$('detail-tabs').append(btn); }
  document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>renderPage(b.dataset.page)));
  $('open-project').addEventListener('click',()=>renderPage('项目详情'));
  $('back-board').addEventListener('click',()=>renderPage('项目看板'));
  $('project').addEventListener('change',e=>showFailure(()=>{ctrl.setProject(e.target.value);$('project-card').textContent=DEMO.projects.find(x=>x.id===ctrl.state.project_id).name;renderScope();}));
  $('batch').addEventListener('change',e=>showFailure(()=>{if(e.target.value)ctrl.setBatch(e.target.value);else ctrl.setProject(ctrl.state.project_id);renderScope();}));
  for (const [id,field] of [['requirement','requirement_ids'],['version','system_version_ids'],['sst','sst_ids']]) $(id).addEventListener('change',e=>showFailure(()=>{ctrl.setFilter(field,e.target.value);renderScope();}));
  $('detail-action').addEventListener('click',()=>{$('detail-error').hidden=false;});
  $('board-new').addEventListener('click',()=>{$('board-error').hidden=false;});
  $('chat-send').addEventListener('click',()=>{$('chat-error').textContent='未发送：缺少 DSH 宿主会话与授权。';});
  $('chat-history').addEventListener('click',()=>{$('chat-error').textContent='无法读取：本原型没有 DSH 会话历史。';});
  $('calendar-add').addEventListener('click',()=>{$('calendar-error').hidden=false;});
  $('skill-install').addEventListener('click',()=>{$('skill-error').hidden=false;});
  $('search').addEventListener('input',e=>{const v=e.target.value.trim().toLowerCase();const count=DEMO.relations.filter(x=>[x.requirement_name,x.sst_id,x.version_label].some(z=>String(z||'').toLowerCase().includes(v))).length;setNotice(v?`演示数据搜索：${count} 条关联匹配；非正式检索。`:'演示数据搜索已清空。');});
  $('skill-search').addEventListener('input',e=>{setNotice(`技能目录搜索：${e.target.value || '全部'}（真实目录尚未接入）`);});
  $('theme').addEventListener('click',()=>{const dark=document.body.classList.toggle('dark');$('theme').textContent=dark?'切换浅色主题':'切换深色主题';});
  $('collapse').addEventListener('click',()=>{const collapsed=document.querySelector('.shell').classList.toggle('collapsed');$('collapse').textContent=collapsed?'展开侧栏':'收起侧栏';});
  renderSection(section);renderPage(page);
}
boot();
