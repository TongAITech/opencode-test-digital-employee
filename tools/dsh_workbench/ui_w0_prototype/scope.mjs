// W0 原创可行性验证：仅消费显式合法关联，不替代 B06 权威服务端关联查询。
export const SECTIONS = Object.freeze(['项目概览', '质量任务', '需求', '测试用例', '缺陷', '里程碑', '报告', '知识', '会议纪要', '门禁']);
export const STAGES = Object.freeze(['需求分析', '用例设计', '用例评审', '执行中', '缺陷回归', '已发布']);
export const PAGES = Object.freeze(['测试首页', 'DSH 测试对话', '项目看板', '日历排期', 'QA Skill 安装', '项目详情']);

export const DEMO = Object.freeze({
  projects: [{ id: 'P01', name: '产品配置中心（演示）' }, { id: 'P02', name: '信贷集成测试（演示）' }],
  batches: [
    { id: 'B12', project_id: 'P01', release_date: '2026-11-12' },
    { id: 'B19', project_id: 'P01', release_date: '2026-11-19' },
    { id: 'B2', project_id: 'P02', release_date: '2026-11-12' }
  ],
  // 每行都来自同一条合法的 批次-需求-系统版本-SST 关联。null 仅表示待拆分，不是虚构 SST。
  relations: [
    { project_id: 'P01', batch_id: 'B12', requirement_id: 'R1', requirement_name: '登录策略', system_version_id: 'V1', system_name: '配置服务', version_label: 'PF1.2.1', sst_id: 'S1' },
    { project_id: 'P01', batch_id: 'B12', requirement_id: 'R1', requirement_name: '登录策略', system_version_id: 'V1', system_name: '配置服务', version_label: 'PF1.2.1', sst_id: 'S2' },
    { project_id: 'P01', batch_id: 'B12', requirement_id: 'R1', requirement_name: '登录策略', system_version_id: 'V2', system_name: '审批系统', version_label: 'PF1.2.1', sst_id: 'S3' },
    { project_id: 'P01', batch_id: 'B12', requirement_id: 'R2', requirement_name: '额度调整', system_version_id: 'V1', system_name: '配置服务', version_label: 'PF1.2.1', sst_id: 'S4' },
    { project_id: 'P01', batch_id: 'B12', requirement_id: 'R3', requirement_name: '通知策略', system_version_id: 'V3', system_name: '通知服务', version_label: 'PF1.2.2', sst_id: null },
    { project_id: 'P01', batch_id: 'B19', requirement_id: 'R1', requirement_name: '登录策略', system_version_id: 'V1', system_name: '配置服务', version_label: 'PF1.2.1', sst_id: 'S5' },
    { project_id: 'P02', batch_id: 'B2', requirement_id: 'R9', requirement_name: '提款审批', system_version_id: 'V9', system_name: '信贷服务', version_label: 'PF1.2.1', sst_id: 'S9' }
  ]
});
const normalizeSelection = value => {
  const values = Array.isArray(value) ? value : value ? [value] : [];
  return [...new Set(values.filter(v => typeof v === 'string' && v.length > 0))];
};
const unique = (entries, key, label) => [...new Map(entries.map(x => [x[key], { id: x[key], label: label(x) }])).values()];
const keyFor = Object.freeze({ requirement_ids: 'requirement_id', system_version_ids: 'system_version_id', sst_ids: 'sst_id' });

export class ScopeController {
  constructor(data = DEMO, projectId = data.projects[0]?.id) {
    this.data = data;
    if (!data.projects.some(p => p.id === projectId)) throw new Error('无权限或项目不存在');
    this.state = { project_id: projectId, batch_id: null, release_date: null, requirement_ids: [], system_version_ids: [], sst_ids: [] };
  }
  batches() { return this.data.batches.filter(b => b.project_id === this.state.project_id); }
  getRows() {
    const s = this.state;
    return this.data.relations.filter(r => r.project_id === s.project_id && r.batch_id === s.batch_id
      && (!s.requirement_ids.length || s.requirement_ids.includes(r.requirement_id))
      && (!s.system_version_ids.length || s.system_version_ids.includes(r.system_version_id))
      && (!s.sst_ids.length || s.sst_ids.includes(r.sst_id)));
  }
  options(field) {
    const s = this.state;
    const rows = this.data.relations.filter(r => r.project_id === s.project_id && r.batch_id === s.batch_id);
    if (field === 'requirement_ids') return unique(rows, 'requirement_id', r => r.requirement_name + ' (' + r.requirement_id + ')');
    if (field === 'system_version_ids') {
      const subset = rows.filter(r => !s.requirement_ids.length || s.requirement_ids.includes(r.requirement_id));
      return unique(subset, 'system_version_id', r => r.system_name + ' · ' + r.version_label);
    }
    if (field === 'sst_ids') {
      const subset = rows.filter(r => (!s.requirement_ids.length || s.requirement_ids.includes(r.requirement_id))
        && (!s.system_version_ids.length || s.system_version_ids.includes(r.system_version_id)) && r.sst_id);
      return unique(subset, 'sst_id', r => r.sst_id + ' · ' + r.system_name);
    }
    throw new Error('未知筛选字段');
  }
  setProject(id) {
    if (!this.data.projects.some(p => p.id === id)) throw new Error('无权限或项目不存在');
    this.state = { project_id: id, batch_id: null, release_date: null, requirement_ids: [], system_version_ids: [], sst_ids: [] };
  }
  setBatch(id) {
    const batch = this.batches().find(b => b.id === id);
    if (!batch) throw new Error('投产日期不属于当前项目');
    this.state = { ...this.state, batch_id: batch.id, release_date: batch.release_date,
      requirement_ids: [], system_version_ids: [], sst_ids: [] };
  }
  setFilter(field, values) {
    if (!Object.hasOwn(keyFor, field)) throw new Error('未知筛选字段');
    if (!this.state.batch_id) throw new Error('请先选择投产日期');
    const selected = normalizeSelection(values);
    const allowed = this.options(field).map(option => option.id);
    const invalid = selected.filter(id => !allowed.includes(id));
    if (invalid.length) throw new Error('关联不存在或不属于当前投产日期：' + invalid.join(','));
    // Validate first, then commit the new selection. Invalid multi-select is atomic and has no partial effect.
    this.state[field] = selected;
    if (field === 'requirement_ids') {
      const validVersions = new Set(this.options('system_version_ids').map(option => option.id));
      this.state.system_version_ids = this.state.system_version_ids.filter(id => validVersions.has(id));
    }
    if (field !== 'sst_ids') {
      const validSsts = new Set(this.options('sst_ids').map(option => option.id));
      this.state.sst_ids = this.state.sst_ids.filter(id => validSsts.has(id));
    }
  }
  assertLegalTuple(requirementId, versionId, sstId) {
    const rows = this.data.relations.filter(r => r.project_id === this.state.project_id && r.batch_id === this.state.batch_id);
    if (!rows.some(r => r.requirement_id === requirementId && r.system_version_id === versionId && r.sst_id === sstId)) {
      throw new Error('非法需求—系统版本—SST 关联');
    }
    return true;
  }
  status() {
    if (!this.state.batch_id) return '请先选择投产日期';
    const rows = this.getRows();
    if (!rows.length) return '当前筛选无合法关联';
    if (rows.every(r => r.sst_id === null)) return '待拆分 SST';
    return '合法关联 ' + rows.filter(r => r.sst_id).length + ' 条（仅演示，非真实执行结果）';
  }
  // UI 端只构建查询，不做授权决策。服务端必须重新校验主体、批次和复合关联。
  query() {
    return Object.freeze({
      ...this.state,
      requirement_ids: Object.freeze([...this.state.requirement_ids]),
      system_version_ids: Object.freeze([...this.state.system_version_ids]),
      sst_ids: Object.freeze([...this.state.sst_ids])
    });
  }
}
