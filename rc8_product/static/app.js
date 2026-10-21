const byId = (id) => document.getElementById(id);
const state = { current: null, tab: 'basic' };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
}

function formatTime(epoch) {
  if (!epoch) return '—';
  const value = new Date(Number(epoch) * 1000);
  if (Number.isNaN(value.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  }).format(value);
}

async function api(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
  return payload;
}

async function health() {
  const target = byId('connection');
  try {
    const payload = await api('/api/health');
    target.textContent = payload.status === 'UP' ? '中央平台已连接' : '中央平台状态未知';
    target.className = 'connection ok';
  } catch (error) {
    target.textContent = '中央平台连接失败';
    target.className = 'connection error';
  }
}

function buildQuery() {
  const params = new URLSearchParams();
  for (const id of ['status', 'operator', 'capability', 'q']) {
    const value = byId(id).value.trim();
    if (value) params.set(id, value);
  }
  return params.toString();
}

function renderRows(items) {
  const rows = byId('rows');
  byId('count').textContent = `${items.length} 个节点`;
  byId('empty').hidden = items.length > 0;
  rows.innerHTML = items.map((node) => `
    <tr data-node="${escapeHtml(node.node_id)}">
      <td class="node-cell"><strong>${escapeHtml(node.display_name)}</strong><span>${escapeHtml(node.node_id)}</span></td>
      <td>${escapeHtml(node.operator || '—')}</td>
      <td>${escapeHtml(node.platform)} · ${escapeHtml(node.architecture)}</td>
      <td>${escapeHtml(node.verified_capabilities)} / ${escapeHtml(node.capability_total)}</td>
      <td>${node.current_work_item ? `<strong>${escapeHtml(node.current_work_item)}</strong>` : '<span class="muted">—</span>'}</td>
      <td>${escapeHtml(formatTime(node.heartbeat_at))}</td>
      <td><span class="status" data-state="${escapeHtml(node.status)}">${escapeHtml(node.status_label)}</span></td>
    </tr>
  `).join('');
  rows.querySelectorAll('tr').forEach((row) => {
    row.addEventListener('click', () => openDetail(row.dataset.node));
  });
}

async function loadNodes() {
  byId('error').hidden = true;
  try {
    const query = buildQuery();
    const data = await api(`/api/nodes${query ? `?${query}` : ''}`);
    renderRows(data.items || []);
  } catch (error) {
    byId('error').textContent = error.message;
    byId('error').hidden = false;
    renderRows([]);
  }
}

function field(label, value) {
  return `<div class="field"><div class="label">${escapeHtml(label)}</div><div class="value">${escapeHtml(value ?? '—')}</div></div>`;
}

function renderBasic(node) {
  return `<div class="detail-grid">
    ${field('节点名称', node.display_name)}
    ${field('节点编号', node.node_id)}
    ${field('执行人', node.operator || '—')}
    ${field('运行平台', node.platform)}
    ${field('处理器架构', node.architecture)}
    ${field('节点包版本', node.package_version || '—')}
    ${field('当前状态', node.status_label)}
    ${field('最后心跳', formatTime(node.heartbeat_at))}
    ${field('当前任务', node.current_work_item || '—')}
  </div>`;
}

function renderCapabilities(node) {
  const items = node.capabilities || [];
  if (!items.length) return '<div class="placeholder">当前节点还没有完成能力探测。节点只有完成真实执行、断言与证据保存后，能力才会进入“已验证”状态。</div>';
  return `<div class="detail-section"><h3>节点能力</h3><div class="capability-list">${items.map((item) => `
    <div class="capability-row">
      <strong>${escapeHtml(item.name)}</strong>
      <span class="status" data-state="${item.verified ? 'IDLE' : item.state === 'ERROR' ? 'ERROR' : ''}">${escapeHtml(item.state_label)}</span>
      <span>${item.last_verified_at ? escapeHtml(formatTime(item.last_verified_at)) : '<span class="muted">尚未验证</span>'}</span>
      <span class="muted">${escapeHtml((item.evidence_refs || []).join('、') || '暂无证据')}</span>
    </div>
  `).join('')}</div></div>`;
}

function renderTask(node) {
  const active = (node.leases || []).find((item) => item.state === 'ACTIVE');
  if (!active) return '<div class="placeholder">当前节点没有正在执行的任务。</div>';
  return `<div class="detail-grid">
    ${field('任务编号', active.work_item_id)}
    ${field('租约编号', active.lease_id)}
    ${field('租约状态', active.state)}
    ${field('领取时间', formatTime(active.issued_at))}
    ${field('租约到期', formatTime(active.expires_at))}
    ${field('要求能力', (active.required_capabilities || []).join('、') || '—')}
  </div>`;
}

function renderHistory(node) {
  const rows = node.leases || [];
  if (!rows.length) return '<div class="placeholder">暂无历史任务记录。</div>';
  return `<div class="detail-section"><h3>任务租约历史</h3><div class="capability-list">${rows.map((item) => `
    <div class="capability-row">
      <strong>${escapeHtml(item.work_item_id)}</strong>
      <span>${escapeHtml(item.state)}</span>
      <span>${escapeHtml(formatTime(item.issued_at))}</span>
      <span class="muted">${escapeHtml((item.required_capabilities || []).join('、') || '—')}</span>
    </div>
  `).join('')}</div></div>`;
}

function renderTab() {
  const body = byId('detailBody');
  const node = state.current;
  if (!node) return;
  const renderers = {
    basic: renderBasic,
    capabilities: renderCapabilities,
    task: renderTask,
    history: renderHistory,
    resources: () => '<div class="placeholder">资源占用将在资源租约接入后展示测试帐号、测试数据和业务对象的实时占用情况；当前不使用模拟数据填充。</div>',
    runtime: () => '<div class="placeholder">运行记录将在中央 R1 投影接入后展示真实节点事件；当前不使用 DSH 对话或模拟日志替代运行事实。</div>'
  };
  body.innerHTML = (renderers[state.tab] || renderBasic)(node);
}

async function openDetail(nodeId) {
  try {
    const node = await api(`/api/nodes/${encodeURIComponent(nodeId)}`);
    state.current = node;
    state.tab = 'basic';
    byId('detailTitle').textContent = node.display_name;
    byId('detailMeta').textContent = `${node.node_id} · ${node.platform} · ${node.status_label}`;
    byId('tabs').querySelectorAll('button').forEach((button) => button.classList.toggle('active', button.dataset.tab === 'basic'));
    renderTab();
    byId('modal').hidden = false;
    document.body.style.overflow = 'hidden';
  } catch (error) {
    byId('error').textContent = error.message;
    byId('error').hidden = false;
  }
}

function closeDetail() {
  byId('modal').hidden = true;
  document.body.style.overflow = '';
  state.current = null;
}

byId('search').addEventListener('click', loadNodes);
byId('reset').addEventListener('click', () => {
  ['status', 'operator', 'capability', 'q'].forEach((id) => { byId(id).value = ''; });
  loadNodes();
});
byId('q').addEventListener('keydown', (event) => { if (event.key === 'Enter') loadNodes(); });
byId('close').addEventListener('click', closeDetail);
byId('modal').addEventListener('click', (event) => { if (event.target === byId('modal')) closeDetail(); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !byId('modal').hidden) closeDetail(); });
byId('tabs').querySelectorAll('button').forEach((button) => {
  button.addEventListener('click', () => {
    state.tab = button.dataset.tab;
    byId('tabs').querySelectorAll('button').forEach((item) => item.classList.toggle('active', item === button));
    renderTab();
  });
});

health();
loadNodes();
setInterval(health, 15000);
setInterval(loadNodes, 15000);
