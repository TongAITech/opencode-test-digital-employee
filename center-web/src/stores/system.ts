import { defineStore } from 'pinia'

export interface CenterHealth {
  status: string
  service: string
  database: string
  redis: string
  runtime_truth: string
}

export interface ArchitectureResponse {
  status: string
  technology: Record<string, string>
  truth_rules: Record<string, string | boolean>
}

export const useSystemStore = defineStore('system', {
  state: () => ({
    loading: false,
    error: '' as string,
    health: null as CenterHealth | null,
    architecture: null as ArchitectureResponse | null,
  }),
  actions: {
    async refresh() {
      this.loading = true
      this.error = ''
      try {
        const [healthResponse, architectureResponse] = await Promise.all([
          fetch('/health', { cache: 'no-store' }),
          fetch('/api/v1/system/architecture', { cache: 'no-store' }),
        ])
        if (!healthResponse.ok) throw new Error(`健康检查失败：${healthResponse.status}`)
        if (!architectureResponse.ok) throw new Error(`架构检查失败：${architectureResponse.status}`)
        this.health = await healthResponse.json()
        this.architecture = await architectureResponse.json()
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    },
  },
})
