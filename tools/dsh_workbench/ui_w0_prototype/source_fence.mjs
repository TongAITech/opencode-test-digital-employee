// W0 original UI boundary experiment: never a substitute for Host/B06/R1 authorization, HTTP or Evidence checks.
// The preview intentionally has NO "PASS" state and performs NO network calls.
const queryIds = value => Array.isArray(value) ? [...new Set(value)].sort() : [];

export function scopeIdentity(scope) {
  if (!scope || !scope.project_id || !scope.batch_id) throw new Error('NO_PROJECT_BATCH_SCOPE');
  return JSON.stringify({
    project_id: scope.project_id,
    batch_id: scope.batch_id,
    release_date: scope.release_date || null,
    requirement_ids: queryIds(scope.requirement_ids),
    system_version_ids: queryIds(scope.system_version_ids),
    sst_ids: queryIds(scope.sst_ids),
    relation_revision: scope.relation_revision || null,
    access_scope_revision: scope.access_scope_revision || null,
    truth_revision: scope.truth_revision || null
  });
}

const readonlyResult = (code, message) => Object.freeze({ code, message, verified: false });
export function classifySourcePreview(response) {
  const status = response && response.http_status;
  if (status === 401) return readonlyResult('AUTH_REQUIRED','身份失效：请在真实 DSH 宿主重新鉴权；演示没有执行登录');
  if (status === 403) return readonlyResult('FORBIDDEN','无权访问该资源；不得泄露项目、批次或数据是否存在');
  if (status === 404) return readonlyResult('NOT_FOUND','有权主体请求的对象不存在；不能显示为成功或空报告');
  if (status === 409) return readonlyResult('REVISION_CONFLICT','修订冲突：应重新获取当前批次快照；不写入任何记录');
  if (status === 422) return readonlyResult('INVALID_SCOPE','关联无效：需求—版本—SST 不属于合法复合关系');
  if (status === 503) return readonlyResult('SOURCE_UNAVAILABLE','R1 或业务来源暂不可用；质量状态未知，不能显示 0 或 PASS');
  if (status !== 200) return readonlyResult('SOURCE_UNKNOWN','没有可核验的响应；质量状态未知');

  if (!response.body || typeof response.body !== 'object') {
    return readonlyResult('SOURCE_UNKNOWN','成功响应缺少权威数据，不可当作业务成功');
  }
  if (response.body.truth_status === 'STALE' || response.body.truth_status === 'UNKNOWN') {
    return readonlyResult('TRUTH_NOT_READY','R1 事实为陈旧或未知；不得显示 PASS');
  }
  if (response.body.node_gate === 'PASS' && (
    !Array.isArray(response.body.evidence_refs) || !response.body.evidence_refs.length ||
    response.body.human_review_approved !== true
  )) {
    return readonlyResult('EVIDENCE_OR_REVIEW_MISSING','来源声称 NodeGate PASS，但缺可核验证据或人工审批；保持 HOLD');
  }
  return readonlyResult('PREVIEW_ONLY','仅演示收到样本数据；未调用真实 R1/B06，不具备任何 QA_PASS 资格');
}

export class ScopeReadFence {
  constructor() {
    this.epoch = 0;
    this.active = null;
    this.latest = readonlyResult('NO_REQUEST','未请求正式业务来源');
  }
  begin(scope) {
    const key = scopeIdentity(scope);
    this.epoch += 1;
    this.active = Object.freeze({
      epoch: this.epoch, key,
      project_id: scope.project_id, batch_id: scope.batch_id,
      relation_revision: scope.relation_revision || null,
      access_scope_revision: scope.access_scope_revision || null,
      truth_revision: scope.truth_revision || null
    });
    this.latest = readonlyResult('SOURCE_UNKNOWN','当前上下文已变化，等待真实服务校验');
    return this.active;
  }
  invalidate() {
    this.epoch += 1;
    this.active = null;
    this.latest = readonlyResult('SCOPE_CLEARED','当前未选择投产日期；清除旧响应');
  }
  accept(ticket, response) {
    if (!ticket || !this.active || ticket.epoch !== this.active.epoch || ticket.key !== this.active.key) {
      return Object.freeze({accepted:false, result:readonlyResult('STALE_RESPONSE','已丢弃旧项目、批次或筛选上下文的迟到响应')});
    }
    if (!response || response.project_id !== ticket.project_id || response.batch_id !== ticket.batch_id ||
      (ticket.relation_revision !== null && response.relation_revision !== ticket.relation_revision) ||
      (ticket.access_scope_revision !== null && response.access_scope_revision !== ticket.access_scope_revision) ||
      (ticket.truth_revision !== null && response.truth_revision !== ticket.truth_revision)) {
      this.latest = readonlyResult('SOURCE_SCOPE_MISMATCH','返回内容与当前项目、批次或版本水位不符；拒绝展示');
      return Object.freeze({accepted:false,result:this.latest});
    }
    this.latest = classifySourcePreview(response);
    return Object.freeze({accepted:true,result:this.latest});
  }
}
