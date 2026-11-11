import { DEMO, PAGES, SECTIONS, STAGES, ScopeController } from './scope.mjs';
import { ScopeReadFence, scopeIdentity } from './source_fence.mjs';
const $ = id => document.getElementById(id);
const ctrl = new ScopeController(DEMO);
const sourceFence = new ScopeReadFence();
let sourceTicket = null;
let sourceKey = null;
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
const sectionForms = {
  '项目概览': [['project_name','项目名称','text'],['owner','项目负责人','text']],
  '质量任务': [['task_name','质量任务名称','text'],['acceptance','验收标准','textarea']],
  '需求': [['requirement_title','需求标题','text'],['acceptance','验收标准','textarea']],
  '测试用例': [['case_title','用例标题','text'],['precondition','前置条件','textarea'],['steps','测试步骤','textarea'],['expected','预期结果','textarea']],
  '缺陷': [['defect_title','缺陷标题','text'],['expected','期望结果','textarea'],['actual','实际结果','textarea'],['reproduction','复现步骤','textarea']],
  '里程碑': [['milestone_name','里程碑名称','text'],['planned_date','计划日期','date']],
  '报告': [['report_title','报告名称','text'],['summary','报告摘要','textarea']],
  '知识': [['knowledge_title','知识标题','text'],['source_ref','来源引用','text']],
  '会议纪要': [['meeting_title','会议主题','text'],['decision','会议决议','textarea'],['owner','行动负责人','text']],
  '门禁': [['review_target','审批对象','text'],['review_reason','审批理由','textarea']]
};
function setNotice(text) { $('global-message').textContent = text; }
function selectedValues(select) {
  return select.multiple ? [...select.selectedOptions].map(option => option.value).filter(Boolean) : (select.value ? [select.value] : []);
}
function populate(select, options, placeholder, selected = []) {
  select.replaceChildren();
  const values = Array.isArray(selected) ? selected : selected ? [selected] : [];
  if (!select.multiple) {
    const initial = document.createElement('option');
    initial.value = '';
    initial.textContent = placeholder;
    select.append(initial);
  }
  if (!options.length) {
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = '暂无可选项';
    empty.disabled = true;
    empty.selected = true;
    select.append(empty);
  }
  for (const option of options) {
    const node = document.createElement('option');
    node.value = option.id;
    node.textContent = option.label;
    node.selected = values.includes(option.id);
    select.append(node);
  }
  if (!select.multiple) select.value = values[0] || '';
}
function scopeText(snapshot) {
  return '共享筛选：' + (snapshot.release_date || '未选择投产日期')
    + ' / ' + (snapshot.requirement_ids.join(',') || '全部需求')
    + ' / ' + (snapshot.system_version_ids.join(',') || '全部系统版本')
    + ' / ' + (snapshot.sst_ids.join(',') || '全部 SST')
    + '；十个分区读取同一只读快照（W0 演示）。';
}
function renderScope() {
  const snapshot = ctrl.query();
  const nextKey = snapshot.batch_id ? scopeIdentity(snapshot) : null;
  if (nextKey !== sourceKey) {
    sourceKey = nextKey;
    if (nextKey) sourceTicket = sourceFence.begin(snapshot);
    else { sourceFence.invalidate(); sourceTicket = null; }
    $('source-preview-status').textContent = 'W0 演示：筛选已切换，所有旧请求与来源状态失效；实际业务结果未知。';
  }
  populate($('batch'), ctrl.batches().map(batch => ({ id: batch.id, label: batch.release_date })), '请选择投产日期', snapshot.batch_id);
  populate($('requirement'), ctrl.options('requirement_ids'), '全部需求', snapshot.requirement_ids);
  populate($('version'), ctrl.options('system_version_ids'), '全部系统版本', snapshot.system_version_ids);
  populate($('sst'), ctrl.options('sst_ids'), '全部 SST', snapshot.sst_ids);
  for (const id of ['requirement','version','sst']) $(id).disabled = !snapshot.batch_id;
  $('scope-status').textContent = ctrl.status();
  $('scope-echo').textContent = scopeText(snapshot);
  $('scope-echo').dataset.scopeSnapshot = JSON.stringify(snapshot);
  for (const button of $('detail-tabs').querySelectorAll('button')) {
    button.dataset.scopeSnapshot = JSON.stringify(snapshot);
  }
}
function renderSectionForm(name) {
  const host = $('section-form');
  host.replaceChildren();
  const form = document.createElement('form');
  form.id = 'section-demo-form';
  form.dataset.section = name;
  const heading = document.createElement('h4');
  heading.textContent = name + ' · 表单交互预览';
  form.append(heading);
  for (const [field, labelText, kind] of sectionForms[name]) {
    const label = document.createElement('label');
    label.className = 'form-field';
    const caption = document.createElement('span');
    caption.textContent = labelText;
    const input = document.createElement(kind === 'textarea' ? 'textarea' : 'input');
    input.name = field;
    input.id = 'field-' + field;
    input.required = true;
    if (kind !== 'textarea') input.type = kind;
    label.append(caption, input);
    form.append(label);
  }
  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.textContent = '提交演示表单';
  form.append(submit);
  const error = document.createElement('p');
  error.id = 'section-form-error';
  error.setAttribute('role','alert');
  error.hidden = true;
  host.append(form,error);
  form.addEventListener('submit', event => {
    event.preventDefault();
    error.textContent = '未提交：' + name + ' 尚未接入正式业务 API；没有创建、修改、执行或审批任何记录。';
    error.hidden = false;
    setNotice(error.textContent);
  });
}
function renderPage(next) {
  if (!PAGES.includes(next)) throw new Error('未知页面');
  page = next;
  const ids = { '测试首页':'dashboard', 'DSH 测试对话':'conversation', '项目看板':'board', '日历排期':'calendar', 'QA Skill 安装':'skills', '项目详情':'detail' };
  for (const [key,id] of Object.entries(ids)) $(id).hidden = next !== key;
  for (const button of document.querySelectorAll('[data-page]')) {
    button.classList.toggle('active', button.dataset.page === next);
    button.setAttribute('aria-current', button.dataset.page === next ? 'page' : 'false');
  }
  $('page-title').textContent = next;
  if (next === '项目详情') renderScope();
}
function renderSection(next) {
  if (!SECTIONS.includes(next)) throw new Error('未知项目分区');
  section = next;
  $('section-title').textContent = next;
  $('section-content').textContent = sectionMessages[next] + '（W0 原型：正式 API 未接入）';
  $('detail-error').hidden = true;
  for (const button of $('detail-tabs').querySelectorAll('button')) {
    button.classList.toggle('active', button.textContent === next);
  }
  renderSectionForm(next);
  renderScope();
}
function showFailure(fn) {
  try { fn(); setNotice('演示筛选已更新；不代表已通过服务端权限校验。'); }
  catch (error) { setNotice('操作已阻断：' + error.message); renderScope(); }
}
function boot() {
  populate($('project'), DEMO.projects.map(project => ({id:project.id,label:project.name})), '请选择项目', ctrl.state.project_id);
  $('project-card').textContent = DEMO.projects[0].name;
  for (const stage of STAGES) {
    const tile = document.createElement('article');
    tile.className = 'stage';
    const heading = document.createElement('h3');
    heading.textContent = stage;
    const note = document.createElement('p');
    note.textContent = '演示阶段 · 无真实状态';
    tile.append(heading,note);
    $('stage-grid').append(tile);
  }
  for (const name of SECTIONS) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = name;
    button.addEventListener('click', () => renderSection(name));
    $('detail-tabs').append(button);
  }
  document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => renderPage(button.dataset.page)));
  $('open-project').addEventListener('click', () => renderPage('项目详情'));
  $('back-board').addEventListener('click', () => renderPage('项目看板'));
  $('project').addEventListener('change', event => showFailure(() => {
    ctrl.setProject(event.target.value);
    $('project-card').textContent = DEMO.projects.find(project => project.id === ctrl.state.project_id).name;
    renderScope();
  }));
  $('batch').addEventListener('change', event => showFailure(() => {
    if (event.target.value) ctrl.setBatch(event.target.value);
    else ctrl.setProject(ctrl.state.project_id);
    renderScope();
  }));
  for (const [id,field] of [['requirement','requirement_ids'],['version','system_version_ids'],['sst','sst_ids']]) {
    $(id).addEventListener('change', event => showFailure(() => {
      ctrl.setFilter(field, selectedValues(event.target));
      renderScope();
    }));
  }
  $('source-preview-run').addEventListener('click', () => {
    if (!sourceTicket) {
      $('source-preview-status').textContent = 'W0 演示：请先选择投产日期；未访问任何 API。';
      return;
    }
    const ticket = sourceTicket;
    const http_status = Number($('source-preview-code').value);
    const sample = {
      http_status,project_id:ticket.project_id,batch_id:ticket.batch_id,
      relation_revision:ticket.relation_revision,
      access_scope_revision:ticket.access_scope_revision,
      truth_revision:ticket.truth_revision,
      body: {node_gate:'PASS', evidence_refs:[],human_review_approved:false}
    };
    const result = sourceFence.accept(ticket,sample);
    $('source-preview-status').textContent = 'W0 模拟响应 ' + result.result.code + '：' + result.result.message;
  });
  $('source-preview-late').addEventListener('click', () => {
    if (!sourceTicket) {
      $('source-preview-status').textContent = 'W0 演示：缺少投产日期，拒绝旧请求';
      return;
    }
    const oldTicket = sourceTicket;
    sourceTicket = sourceFence.begin(ctrl.query());
    const late = sourceFence.accept(oldTicket,{
      http_status:200,project_id:oldTicket.project_id,batch_id:oldTicket.batch_id,
      body:{node_gate:'PASS',evidence_refs:['not-real'],human_review_approved:true}
    });
    $('source-preview-status').textContent = 'W0 模拟迟到响应 ' + late.result.code + '：' + late.result.message;
  });
  $('detail-action').addEventListener('click', () => { $('detail-error').hidden = false; });
  $('board-new').addEventListener('click', () => { $('board-error').hidden = false; });
  $('chat-send').addEventListener('click', () => {
    const message = $('chat-message').value.trim();
    $('chat-error').textContent = message ? '未发送：缺少 DSH 宿主会话与授权，消息没有离开本地原型。' : '未发送：请输入消息；当前也未连接 DSH 宿主。';
  });
  $('chat-history').addEventListener('click', () => { $('chat-error').textContent = '无法读取：本原型没有 DSH 会话历史。'; });
  $('calendar-add').addEventListener('click', () => { $('calendar-error').hidden = false; });
  $('skill-install').addEventListener('click', () => { $('skill-error').hidden = false; });
  $('search').addEventListener('input', event => {
    const value = event.target.value.trim().toLowerCase();
    const count = DEMO.relations.filter(row => row.project_id === ctrl.state.project_id
      && (!ctrl.state.batch_id || row.batch_id === ctrl.state.batch_id)
      && [row.requirement_name,row.sst_id,row.version_label].some(text => String(text || '').toLowerCase().includes(value))).length;
    setNotice(value ? (count ? '演示数据搜索：' + count + ' 条关联匹配；非正式检索。' : '演示数据搜索：0 条匹配；非正式检索。') : '演示数据搜索已清空。');
  });
  $('skill-search').addEventListener('input', event => {
    setNotice('技能目录搜索：' + (event.target.value || '全部') + '（真实目录尚未接入）');
  });
  $('theme').addEventListener('click', () => {
    const dark = document.body.classList.toggle('dark');
    $('theme').textContent = dark ? '切换浅色主题' : '切换深色主题';
  });
  $('collapse').addEventListener('click', () => {
    const collapsed = document.querySelector('.shell').classList.toggle('collapsed');
    $('collapse').textContent = collapsed ? '展开侧栏' : '收起侧栏';
  });
  renderSection(section);
  renderPage(page);
}
boot();
