import { defineStore } from 'pinia'

export interface ProductionBatchItem {
  production_batch_id: string
  production_date: string
  name: string
  state: string
  created_at: number
  payload: Record<string, unknown>
}

export interface RequirementItem {
  requirement_id: string
  title: string
  created_at: number
  payload: Record<string, unknown>
}

export interface RequirementDeliveryItem {
  delivery_id: string
  production_batch_id: string
  requirement_id: string
  state: string
  continuation_of_delivery_id: string | null
  created_at: number
  updated_at: number
  payload: Record<string, unknown>
}

export interface RequirementScopeItem {
  scope_id: string
  delivery_id: string
  system_id: string
  system_version: string
  application_id: string | null
  sst_id: string
  created_at: number
  payload: Record<string, unknown>
}

export interface BatchRequirementPlanItem {
  delivery: RequirementDeliveryItem
  requirement: RequirementItem
  scopes: RequirementScopeItem[]
}

export interface ProductionBatchPlan {
  batch: ProductionBatchItem
  requirements: BatchRequirementPlanItem[]
}

export interface TestRunItem {
  test_run_id: string
  production_batch_id: string | null
  test_round_id: string | null
  status_scope: string
  current_state: string
  created_at: number
  updated_at: number
  payload: Record<string, unknown>
}

export interface TestRoundValue {
  test_round_id: string
  production_batch_id: string
  round_no: number
  name: string
  state: string
  created_at: number
  started_at: number | null
  completed_at: number | null
  payload: Record<string, unknown>
}

export interface TestRoundItem {
  round: TestRoundValue
  deliveries: Array<{
    round_delivery_id: string
    test_round_id: string
    delivery_id: string
    included_at: number
    payload: Record<string, unknown>
  }>
  test_run: TestRunItem | null
  truth_note?: string
}

async function detail(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => ({}))
  return typeof body.detail === 'string' ? body.detail : `${fallback}：${response.status}`
}

export const useProductionBatchStore = defineStore('productionBatches', {
  state: () => ({
    loading: false,
    error: '' as string,
    items: [] as ProductionBatchItem[],
    selectedId: '' as string,
    plan: null as ProductionBatchPlan | null,
    rounds: [] as TestRoundItem[],
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const response = await fetch('/api/v1/production-batches', { cache: 'no-store' })
        if (!response.ok) throw new Error(await detail(response, '投产批次查询失败'))
        this.items = await response.json()
        if (this.selectedId && this.items.some((item) => item.production_batch_id === this.selectedId)) {
          await this.select(this.selectedId)
        }
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    },
    async createBatch(productionBatchId: string, productionDate: string, name: string) {
      const response = await fetch('/api/v1/production-batches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ production_batch_id: productionBatchId, production_date: productionDate, name }),
      })
      if (!response.ok) throw new Error(await detail(response, '投产批次创建失败'))
      this.selectedId = productionBatchId
      await this.load()
    },
    async select(productionBatchId: string) {
      this.selectedId = productionBatchId
      const [planResponse, roundsResponse] = await Promise.all([
        fetch(`/api/v1/production-batches/${encodeURIComponent(productionBatchId)}/plan`, { cache: 'no-store' }),
        fetch(`/api/v1/production-batches/${encodeURIComponent(productionBatchId)}/test-rounds`, { cache: 'no-store' }),
      ])
      if (!planResponse.ok) throw new Error(await detail(planResponse, '投产范围查询失败'))
      if (!roundsResponse.ok) throw new Error(await detail(roundsResponse, '测试轮次查询失败'))
      this.plan = await planResponse.json()
      this.rounds = await roundsResponse.json()
    },
    async addRequirement(requirementId: string, title: string, deliveryId: string) {
      if (!this.selectedId) throw new Error('请先选择投产批次')
      const createRequirement = await fetch('/api/v1/requirements', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requirement_id: requirementId, title }),
      })
      if (!createRequirement.ok) {
        const message = await detail(createRequirement, '需求创建失败')
        if (message !== 'REQUIREMENT_ALREADY_EXISTS') throw new Error(message)
      }
      const delivery = await fetch(
        `/api/v1/production-batches/${encodeURIComponent(this.selectedId)}/requirements/${encodeURIComponent(requirementId)}/deliveries`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ delivery_id: deliveryId, state: 'PLANNED' }),
        },
      )
      if (!delivery.ok) throw new Error(await detail(delivery, '需求纳入投产批次失败'))
      await this.select(this.selectedId)
    },
    async addScope(
      deliveryId: string,
      scopeId: string,
      systemId: string,
      systemVersion: string,
      applicationId: string,
      sstId: string,
    ) {
      const response = await fetch(`/api/v1/requirement-deliveries/${encodeURIComponent(deliveryId)}/scopes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scope_id: scopeId,
          system_id: systemId,
          system_version: systemVersion,
          application_id: applicationId || null,
          sst_id: sstId,
        }),
      })
      if (!response.ok) throw new Error(await detail(response, '需求实现范围保存失败'))
      await this.select(this.selectedId)
    },
    async createNextRound(name = '') {
      if (!this.selectedId || !this.plan) throw new Error('请先选择投产批次')
      const deliveryIds = this.plan.requirements.map((item) => item.delivery.delivery_id)
      if (deliveryIds.length === 0) throw new Error('当前投产批次没有需求，不能创建测试轮次')
      const response = await fetch(`/api/v1/production-batches/${encodeURIComponent(this.selectedId)}/test-rounds`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, delivery_ids: deliveryIds, payload: { source: 'RC8_PRODUCT_UI' } }),
      })
      if (!response.ok) throw new Error(await detail(response, '测试轮次创建失败'))
      const created = await response.json()
      await this.select(this.selectedId)
      return created as { round: TestRoundValue }
    },
    async startRound(testRoundId: string) {
      if (!this.selectedId) throw new Error('请先选择投产批次')
      const response = await fetch(
        `/api/v1/production-batches/${encodeURIComponent(this.selectedId)}/test-rounds/${encodeURIComponent(testRoundId)}/test-run`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ payload: { source: 'RC8_PRODUCT_UI' } }),
        },
      )
      if (!response.ok) throw new Error(await detail(response, '本轮自主测试启动失败'))
      const started = await response.json()
      await this.select(this.selectedId)
      return started as { test_run: TestRunItem }
    },
  },
})
