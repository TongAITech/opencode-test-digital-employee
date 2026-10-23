<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useTestRunStore } from '../stores/testRuns'

const store = useTestRunStore()
const stateLabels: Record<string, string> = {
  PLANNED: '待开始',
  READY: '待执行',
  RUNNING: '执行中',
  ACTIVE: '进行中',
  COMPLETED: '已完成',
  FAILED: '失败',
  BLOCKED: '已阻塞',
  CANCELLED: '已取消',
}
const scopeLabels: Record<string, string> = {
  MISSION: '测试任务',
  TEST_RUN: '测试任务',
}

function stateLabel(value: string) {
  return stateLabels[value] ?? value
}

function scopeLabel(value: string) {
  return scopeLabels[value] ?? value
}

onMounted(() => store.load())
</script>

<template>
  <section class="section-page">
    <header class="page-header page-header-actions">
      <div>
        <h1>测试任务</h1>
        <p>每个投产测试任务属于一个明确测试轮次；Stage、Attempt、Evidence、Gap 和 Defect 都通过该任务追溯到所属轮次。</p>
      </div>
      <button class="secondary-button" :disabled="store.loading" @click="store.load">刷新</button>
    </header>

    <div class="task-entry-strip">
      <span>新建测试任务请先确认投产日、需求、系统版本和 SST，再新建测试轮次。</span>
      <RouterLink class="primary-button link-button" to="/productions">前往投产管理</RouterLink>
    </div>

    <p v-if="store.error" class="error-strip">{{ store.error }}</p>

    <div class="table-shell">
      <table>
        <thead>
          <tr><th>任务编号</th><th>投产批次</th><th>测试轮次</th><th>状态范围</th><th>当前状态</th><th>更新时间</th><th>影响关系</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in store.items" :key="item.test_run_id">
            <td><strong>{{ item.test_run_id }}</strong></td>
            <td>{{ item.production_batch_id || '—' }}</td>
            <td>{{ item.test_round_id || (item.production_batch_id ? '历史未绑定' : '非投产任务') }}</td>
            <td>{{ scopeLabel(item.status_scope) }}</td>
            <td>{{ stateLabel(item.current_state) }}</td>
            <td>{{ new Date(item.updated_at * 1000).toLocaleString() }}</td>
            <td>
              <RouterLink
                v-if="item.test_round_id"
                class="inline-link"
                :to="{ path: '/traceability', query: { test_run_id: item.test_run_id } }"
              >
                查看影响关系
              </RouterLink>
              <span v-else>—</span>
            </td>
          </tr>
          <tr v-if="!store.loading && store.items.length === 0">
            <td colspan="7" class="empty-row">暂无测试任务，请先在投产管理确认范围、创建测试轮次并启动自主测试。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
