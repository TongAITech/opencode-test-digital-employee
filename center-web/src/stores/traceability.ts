import { defineStore } from 'pinia'

export type TraceNodeType =
  | 'REQUIREMENT'
  | 'BUSINESS_CAPABILITY'
  | 'PAGE'
  | 'PAGE_ACTION'
  | 'API'
  | 'CONTROLLER'
  | 'METHOD'
  | 'SERVICE'
  | 'REPOSITORY'
  | 'MAPPER'
  | 'SQL'
  | 'DATABASE'
  | 'TABLE'
  | 'TEST_CASE'

export type VerificationState =
  | 'CANDIDATE'
  | 'STATIC_VERIFIED'
  | 'RUNTIME_VERIFIED'
  | 'MULTI_SOURCE_VERIFIED'
  | 'CONFLICTED'
  | 'INVALIDATED'

export interface TraceGraph {
  graph_id: string
  test_run_id: string
  test_round_id: string
  scope_revision_id: string
  code_source_snapshot_id: string
  created_at: number
  payload: Record<string, unknown>
}

export interface TraceNode {
  node_id: string
  graph_id: string
  node_type: TraceNodeType
  business_key: string
  display_name: string
  source_snapshot_id?: string | null
  scope_revision_id?: string | null
  created_at: number
  payload: Record<string, unknown>
}

export interface TraceEdge {
  edge_id: string
  graph_id: string
  from_node_id: string
  to_node_id: string
  relation_type: string
  verification_state: VerificationState
  confidence: number
  evidence_count: number
  created_at: number
  payload: Record<string, unknown>
}

export interface TraceEvidence {
  evidence_id: string
  graph_id: string
  edge_id: string
  evidence_type: string
  source: string
  artifact_id?: string | null
  test_run_id: string
  stage_id?: string | null
  work_item_id?: string | null
  attempt_id?: string | null
  code_source_snapshot_id: string
  captured_at: number
  integrity_hash: string
  payload: Record<string, unknown>
}

interface ImpactResponse {
  graph: TraceGraph
  root: TraceNode
  nodes: TraceNode[]
  edges: TraceEdge[]
  summary: {
    node_count: number
    edge_count: number
    candidate_count: number
    verified_count: number
    conflicted_count: number
    invalidated_count: number
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch {
      // Keep the HTTP status when an upstream proxy returned no JSON body.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const useTraceabilityStore = defineStore('traceability', {
  state: () => ({
    graphs: [] as TraceGraph[],
    selectedGraphId: '',
    impact: null as ImpactResponse | null,
    evidence: [] as TraceEvidence[],
    loading: false,
    evidenceLoading: false,
    error: '',
  }),
  getters: {
    selectedGraph(state): TraceGraph | undefined {
      return state.graphs.find((item) => item.graph_id === state.selectedGraphId)
    },
  },
  actions: {
    clearImpact() {
      this.impact = null
      this.evidence = []
      this.error = ''
    },
    async loadGraphsByTestRun(testRunId: string) {
      const value = testRunId.trim()
      if (!value) {
        this.graphs = []
        this.selectedGraphId = ''
        this.clearImpact()
        return
      }
      this.loading = true
      this.error = ''
      try {
        const body = await readJson<{ graphs: TraceGraph[] }>(
          await fetch(`/api/v1/test-runs/${encodeURIComponent(value)}/traceability-graphs`),
        )
        this.graphs = body.graphs
        this.selectedGraphId = body.graphs[0]?.graph_id || ''
        this.impact = null
        this.evidence = []
      } catch (error) {
        this.graphs = []
        this.selectedGraphId = ''
        this.impact = null
        this.evidence = []
        this.error = error instanceof Error ? error.message : '关系图加载失败'
      } finally {
        this.loading = false
      }
    },
    async queryImpact(nodeType: TraceNodeType, businessKey: string, direction: 'forward' | 'reverse' | 'both') {
      if (!this.selectedGraphId) {
        this.error = '请先选择分析范围'
        return
      }
      const key = businessKey.trim()
      if (!key) {
        this.error = '请输入需求、页面、接口、代码或表的标识'
        return
      }
      this.loading = true
      this.error = ''
      this.evidence = []
      try {
        const params = new URLSearchParams({
          node_type: nodeType,
          business_key: key,
          direction,
        })
        this.impact = await readJson<ImpactResponse>(
          await fetch(`/api/v1/traceability-graphs/${encodeURIComponent(this.selectedGraphId)}/impact?${params.toString()}`),
        )
      } catch (error) {
        this.impact = null
        this.error = error instanceof Error ? error.message : '影响关系查询失败'
      } finally {
        this.loading = false
      }
    },
    async loadEvidence(edgeId: string) {
      if (!this.selectedGraphId) return
      this.evidenceLoading = true
      this.error = ''
      try {
        const body = await readJson<{ evidence: TraceEvidence[] }>(
          await fetch(
            `/api/v1/traceability-graphs/${encodeURIComponent(this.selectedGraphId)}/edges/${encodeURIComponent(edgeId)}/evidence`,
          ),
        )
        this.evidence = body.evidence
      } catch (error) {
        this.evidence = []
        this.error = error instanceof Error ? error.message : '证据加载失败'
      } finally {
        this.evidenceLoading = false
      }
    },
  },
})
