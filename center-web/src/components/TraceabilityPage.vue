<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  useTraceabilityStore,
  type TraceEdge,
  type TraceNode,
  type TraceNodeType,
  type VerificationState,
} from '../stores/traceability'

const route = useRoute()
const store = useTraceabilityStore()
const testRunId = ref('')
const nodeType = ref<TraceNodeType>('REQUIREMENT')
const businessKey = ref('')
const direction = ref<'forward' | 'reverse' | 'both'>('both')
const selectedEdgeId = ref('')

const nodeTypeOptions: Array<[TraceNodeType, string]> = [
  ['REQUIREMENT', '需求'],
  ['PAGE', '页面'],
  ['API', '接口'],
  ['SERVICE', '服务代码'],
  ['METHOD', '代码方法'],
  ['TABLE', '数据库表'],
  ['TEST_CASE', '测试用例'],
]

const typeLabels: Record<string, string> = {
  REQUIREMENT: '需求',
  BUSINESS_CAPABILITY: '业务功能',
  PAGE: '页面',
  PAGE_ACTION: '页面操作',
  API: '接口',
  CONTROLLER: '控制器',
  METHOD: '代码方法',
  SERVICE: '服务',
  REPOSITORY: '数据访问',
  MAPPER: '映射器',
  SQL: 'SQL',
  DATABASE: '数据库',
  TABLE: '数据库表',
  TEST_CASE: '测试用例',
}

const relationLabels: Record<string, string> = {
  REQUIREMENT_AFFECTS: '影响',
  CAPABILITY_PRESENTED_ON: '呈现于',
  PAGE_HAS_ACTION: '包含操作',
  PAGE_CALLS_API: '调用接口',
  API_IMPLEMENTED_BY: '由代码实现',
  CALLS: '调用',
  READS_TABLE: '读取',
  WRITES_TABLE: '写入',
  EXECUTES_SQL: '执行 SQL',
  TEST_COVERS: '测试覆盖',
  TEST_VERIFIES: '测试验证',
}

const stateLabels: Record<VerificationState, string> = {
  CANDIDATE: '候选关系',
  STATIC_VERIFIED: '代码已验证',
  RUNTIME_VERIFIED: '运行已验证',
  MULTI_SOURCE_VERIFIED: '多源已验证',
  CONFLICTED: '存在冲突',
  INVALIDATED: '已失效',
}

const evidenceTypeLabels: Record<string, string> = {
  REQUIREMENT_DOCUMENT: '需求文档',
  BROWSER_NETWORK: '浏览器网络请求',
  PAGE_RUNTIME: '页面运行证据',
  SPRING_MAPPING: '接口路由映射',
  CODEGRAPH: '代码关系图',
  SOURCE_CODE: '源代码',
  MYBATIS_MAPPING: '数据映射',
  SQL: 'SQL',
  DATABASE_METADATA: '数据库元数据',
  APPLICATION_LOG: '应用日志',
  STARLINK: '日志平台',
  TEST_EXECUTION: '测试执行',
}

const columns = [
  { key: 'requirement', label: '需求', types: ['REQUIREMENT', 'BUSINESS_CAPABILITY'] },
  { key: 'page', label: '页面', types: ['PAGE', 'PAGE_ACTION'] },
  { key: 'api', label: '接口', types: ['API'] },
  { key: 'code', label: '代码', types: ['CONTROLLER', 'METHOD', 'SERVICE', 'REPOSITORY', 'MAPPER', 'SQL'] },
  { key: 'table', label: '数据库表', types: ['DATABASE', 'TABLE'] },
  { key: 'case', label: '测试用例', types: ['TEST_CASE'] },
]

const nodeById = computed(() => {
  const values = new Map<string, TraceNode>()
  for (const node of store.impact?.nodes || []) values.set(node.node_id, node)
  return values
})

function nodesFor(types: string[]) {
  return (store.impact?.nodes || []).filter((node) => types.includes(node.node_type))
}

function endpointName(nodeId: string) {
  const node = nodeById.value.get(nodeId)
  return node?.display_name || node?.business_key || '未知节点'
}

function statusClass(state: VerificationState) {
  return `trace-state trace-state-${state.toLowerCase().replaceAll('_', '-')}`
}

async function loadGraphs() {
  selectedEdgeId.value = ''
  await store.loadGraphsByTestRun(testRunId.value)
}

async function query() {
  selectedEdgeId.value = ''
  await store.queryImpact(nodeType.value, businessKey.value, direction.value)
}

async function inspectEdge(edge: TraceEdge) {
  selectedEdgeId.value = edge.edge_id
  await store.loadEvidence(edge.edge_id)
}

watch(
  () => store.selectedGraphId,
  () => {
    store.clearImpact()
    selectedEdgeId.value = ''
  },
)

onMounted(async () => {
  const initial = typeof route.query.test_run_id === 'string' ? route.query.test_run_id : ''
  if (initial) {
    testRunId.value = initial
    await loadGraphs()
  }
})
</script>

<template>
  <section class="section-page trace-page">
    <header class="page-header">
      <div>
        <h1>影响关系</h1>
        <p>从需求、页面、接口、代码或数据库表双向追溯真实影响链；候选关系不会被当成已验证事实。</p>
      </div>
    </header>

    <div class="trace-toolbar">
      <label>
        <span>测试任务</span>
        <input v-model="testRunId" placeholder="输入测试任务编号" @keyup.enter="loadGraphs" />
      </label>
      <button class="secondary-button" :disabled="store.loading || !testRunId.trim()" @click="loadGraphs">
        {{ store.loading ? '加载中…' : '加载分析范围' }}
      </button>
      <label class="trace-scope-field">
        <span>分析范围</span>
        <select v-model="store.selectedGraphId" :disabled="store.graphs.length === 0">
          <option value="">请选择</option>
          <option v-for="graph in store.graphs" :key="graph.graph_id" :value="graph.graph_id">
            {{ graph.scope_revision_id }} · 代码 {{ graph.code_source_snapshot_id }}
          </option>
        </select>
      </label>
    </div>

    <div class="trace-query-bar">
      <label>
        <span>查询对象</span>
        <select v-model="nodeType">
          <option v-for="option in nodeTypeOptions" :key="option[0]" :value="option[0]">{{ option[1] }}</option>
        </select>
      </label>
      <label class="trace-key-field">
        <span>业务标识</span>
        <input v-model="businessKey" placeholder="如 STBB19-320、POST /credit/limit/adjust、credit_limit" @keyup.enter="query" />
      </label>
      <label>
        <span>追溯方向</span>
        <select v-model="direction">
          <option value="both">上下游</option>
          <option value="forward">向下游</option>
          <option value="reverse">向上游</option>
        </select>
      </label>
      <button class="primary-button" :disabled="store.loading || !store.selectedGraphId" @click="query">
        查询影响关系
      </button>
    </div>

    <p v-if="store.error" class="error-strip">{{ store.error }}</p>

    <template v-if="store.impact">
      <div class="trace-context-strip">
        <div><span>测试轮次</span><strong>{{ store.impact.graph.test_round_id }}</strong></div>
        <div><span>范围版本</span><strong>{{ store.impact.graph.scope_revision_id }}</strong></div>
        <div><span>代码快照</span><strong>{{ store.impact.graph.code_source_snapshot_id }}</strong></div>
        <div><span>关系</span><strong>{{ store.impact.summary.edge_count }}</strong></div>
        <div><span>已验证</span><strong>{{ store.impact.summary.verified_count }}</strong></div>
        <div><span>待验证</span><strong>{{ store.impact.summary.candidate_count }}</strong></div>
      </div>

      <div class="trace-chain" aria-label="需求到测试用例影响链">
        <template v-for="(column, index) in columns" :key="column.key">
          <div class="trace-column">
            <div class="trace-column-title">{{ column.label }}</div>
            <div v-if="nodesFor(column.types).length" class="trace-node-list">
              <article v-for="node in nodesFor(column.types)" :key="node.node_id" class="trace-node-card">
                <small>{{ typeLabels[node.node_type] || node.node_type }}</small>
                <strong>{{ node.display_name }}</strong>
                <span v-if="node.business_key !== node.display_name">{{ node.business_key }}</span>
              </article>
            </div>
            <p v-else class="trace-empty">未发现</p>
          </div>
          <div v-if="index < columns.length - 1" class="trace-arrow" aria-hidden="true">→</div>
        </template>
      </div>

      <div class="trace-detail-grid">
        <div class="table-shell">
          <table>
            <thead>
              <tr><th>起点</th><th>关系</th><th>终点</th><th>验证状态</th><th>证据</th></tr>
            </thead>
            <tbody>
              <tr v-for="edge in store.impact.edges" :key="edge.edge_id" :class="{ 'selected-row': selectedEdgeId === edge.edge_id }">
                <td>{{ endpointName(edge.from_node_id) }}</td>
                <td>{{ relationLabels[edge.relation_type] || edge.relation_type }}</td>
                <td>{{ endpointName(edge.to_node_id) }}</td>
                <td><span :class="statusClass(edge.verification_state)">{{ stateLabels[edge.verification_state] }}</span></td>
                <td>
                  <button class="text-button" :disabled="edge.evidence_count === 0" @click="inspectEdge(edge)">
                    {{ edge.evidence_count ? `查看 ${edge.evidence_count} 条` : '无证据' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <aside class="trace-evidence-panel">
          <div class="trace-panel-heading">
            <div>
              <small>关系证据</small>
              <strong>{{ selectedEdgeId ? '证据详情' : '选择一条关系查看证据' }}</strong>
            </div>
          </div>
          <p v-if="store.evidenceLoading" class="muted">正在加载证据…</p>
          <div v-else-if="store.evidence.length" class="trace-evidence-list">
            <article v-for="item in store.evidence" :key="item.evidence_id" class="trace-evidence-item">
              <div class="trace-evidence-title">
                <strong>{{ evidenceTypeLabels[item.evidence_type] || item.evidence_type }}</strong>
                <span>{{ new Date(item.captured_at * 1000).toLocaleString() }}</span>
              </div>
              <dl>
                <dt>来源</dt><dd>{{ item.source }}</dd>
                <dt>代码快照</dt><dd>{{ item.code_source_snapshot_id }}</dd>
                <dt>完整性</dt><dd>{{ item.integrity_hash }}</dd>
              </dl>
            </article>
          </div>
          <p v-else class="muted">候选关系没有真实证据时不会显示为“已验证”。</p>
        </aside>
      </div>
    </template>

    <div v-else-if="!store.loading" class="trace-placeholder">
      <strong>从业务对象开始查询</strong>
      <p>例如输入需求 STBB19-320，可查看页面、接口、代码、数据库表和测试用例；输入表名可反向追溯到需求。</p>
    </div>
  </section>
</template>

<style scoped>
.trace-page { max-width: 1500px; }
.trace-toolbar, .trace-query-bar { display: flex; align-items: end; gap: 12px; padding: 14px 0; border-bottom: 1px solid var(--border, #e5e5ea); }
.trace-query-bar { margin-bottom: 16px; }
.trace-toolbar label, .trace-query-bar label { display: grid; gap: 6px; min-width: 180px; }
.trace-toolbar label span, .trace-query-bar label span { font-size: 12px; color: #6e6e73; }
.trace-toolbar input, .trace-toolbar select, .trace-query-bar input, .trace-query-bar select { min-height: 38px; border: 1px solid #d2d2d7; border-radius: 9px; padding: 0 11px; background: #fff; font: inherit; }
.trace-scope-field, .trace-key-field { flex: 1; }
.trace-context-strip { display: flex; flex-wrap: wrap; gap: 22px; padding: 12px 0 18px; }
.trace-context-strip div { display: grid; gap: 2px; }
.trace-context-strip span { font-size: 11px; color: #86868b; }
.trace-context-strip strong { font-size: 13px; font-weight: 600; }
.trace-chain { display: grid; grid-template-columns: minmax(140px,1fr) 22px minmax(140px,1fr) 22px minmax(140px,1fr) 22px minmax(160px,1.2fr) 22px minmax(140px,1fr) 22px minmax(140px,1fr); align-items: stretch; gap: 0; padding: 16px 0 24px; overflow-x: auto; }
.trace-column { min-width: 140px; border-top: 2px solid #1d1d1f; padding-top: 9px; }
.trace-column-title { font-size: 12px; font-weight: 700; margin-bottom: 8px; }
.trace-node-list { display: grid; gap: 7px; }
.trace-node-card { border: 1px solid #e5e5ea; border-radius: 10px; padding: 10px; background: #fff; display: grid; gap: 3px; box-shadow: 0 1px 2px rgba(0,0,0,.03); }
.trace-node-card small, .trace-node-card span { color: #86868b; font-size: 11px; overflow-wrap: anywhere; }
.trace-node-card strong { font-size: 13px; overflow-wrap: anywhere; }
.trace-arrow { display: grid; place-items: center; color: #86868b; font-size: 17px; }
.trace-empty { color: #aeaeb2; font-size: 12px; margin: 12px 0; }
.trace-detail-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(280px, .8fr); gap: 16px; align-items: start; }
.trace-evidence-panel { border: 1px solid #e5e5ea; border-radius: 12px; padding: 14px; background: #fff; min-height: 180px; }
.trace-panel-heading div { display: grid; gap: 3px; }
.trace-panel-heading small { color: #86868b; }
.trace-evidence-list { display: grid; gap: 10px; margin-top: 12px; }
.trace-evidence-item { border-top: 1px solid #f0f0f2; padding-top: 10px; }
.trace-evidence-title { display: flex; justify-content: space-between; gap: 8px; }
.trace-evidence-title span { color: #86868b; font-size: 11px; }
.trace-evidence-item dl { display: grid; grid-template-columns: 64px minmax(0,1fr); gap: 5px 8px; margin: 9px 0 0; font-size: 12px; }
.trace-evidence-item dt { color: #86868b; }
.trace-evidence-item dd { margin: 0; overflow-wrap: anywhere; }
.trace-state { display: inline-flex; padding: 3px 7px; border-radius: 999px; font-size: 11px; background: #f2f2f7; }
.trace-state-static-verified, .trace-state-runtime-verified, .trace-state-multi-source-verified { background: #edf7ef; }
.trace-state-conflicted { background: #fff2e8; }
.trace-state-invalidated { text-decoration: line-through; color: #86868b; }
.text-button { border: 0; background: transparent; padding: 0; font: inherit; color: #0066cc; cursor: pointer; }
.text-button:disabled { color: #aeaeb2; cursor: default; }
.selected-row { background: #f7f7fa; }
.trace-placeholder { padding: 36px 0; color: #6e6e73; }
.trace-placeholder strong { color: #1d1d1f; }
.muted { color: #86868b; font-size: 12px; }
@media (max-width: 1100px) { .trace-detail-grid { grid-template-columns: 1fr; } .trace-toolbar, .trace-query-bar { flex-wrap: wrap; } }
</style>
