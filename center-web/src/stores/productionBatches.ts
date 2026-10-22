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
      const response = await fetch(`/api/v1/production-batches/${encodeURIComponent(productionBatchId)}/plan`, { cache: 'no-store' })
      if (!response.ok) throw new Error(await detail(response, '投产范围查询失败'))
      this.plan = await response.json()
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
    async startTestRun(testRunId: string) {
      if (!this.selectedId) throw new Error('请先选择投产批次')
      const response = await fetch(`/api/v1/production-batches/${encodeURIComponent(this.selectedId)}/test-runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ test_run_id: testRunId, payload: { source: 'RC8_PRODUCT_UI' } }),
      })
      if (!response.ok) throw new Error(await detail(response, '自主测试任务创建失败'))
      return response.json()
    },
  },
})
