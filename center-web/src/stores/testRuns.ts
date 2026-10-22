import { defineStore } from 'pinia'

export interface TestRunItem {
  test_run_id: string
  production_batch_id: string | null
  status_scope: string
  current_state: string
  created_at: number
  updated_at: number
  payload: Record<string, unknown>
}

export const useTestRunStore = defineStore('testRuns', {
  state: () => ({
    loading: false,
    error: '' as string,
    items: [] as TestRunItem[],
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const response = await fetch('/api/v1/test-runs', { cache: 'no-store' })
        if (!response.ok) throw new Error(`测试任务查询失败：${response.status}`)
        this.items = await response.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    },
  },
})