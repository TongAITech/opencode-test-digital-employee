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
        <p>测试任务从已确认的投产批次范围创建；这里查看执行尝试、测试缺口、覆盖率和自主闭环结果。</p>
      </div>
      <button class="secondary-button" :disabled="store.loading" @click="store.load">刷新</button>
    </header>

    <div class="task-entry-strip">
      <span>新建测试任务请先确认投产日、需求、系统版本和 SST。</span>
      <RouterLink class="primary-button link-button" to="/productions">前往投产管理</RouterLink>
    </div>

    <p v-if="store.error" class="error-strip">{{ store.error }}</p>

    <div class="table-shell">
      <table>
        <thead>
          <tr><th>任务编号</th><th>投产批次</th><th>状态范围</th><th>当前状态</th><th>更新时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in store.items" :key="item.test_run_id">
            <td><strong>{{ item.test_run_id }}</strong></td>
            <td>{{ item.production_batch_id || '—' }}</td>
            <td>{{ scopeLabel(item.status_scope) }}</td>
            <td>{{ stateLabel(item.current_state) }}</td>
            <td>{{ new Date(item.updated_at * 1000).toLocaleString() }}</td>
          </tr>
          <tr v-if="!store.loading && store.items.length === 0">
            <td colspan="5" class="empty-row">暂无测试任务，请先在投产管理确认范围并开始自主测试。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>