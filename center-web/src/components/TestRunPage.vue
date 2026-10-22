<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useTestRunStore } from '../stores/testRuns'

const store = useTestRunStore()
const testRunId = ref('')
const productionBatchId = ref('')
const submitting = ref(false)
const submitError = ref('')

onMounted(() => store.load())

async function createRun() {
  if (!testRunId.value.trim()) return
  submitting.value = true
  submitError.value = ''
  try {
    await store.create(testRunId.value.trim(), productionBatchId.value.trim())
    testRunId.value = ''
    productionBatchId.value = ''
  } catch (error) {
    submitError.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="section-page">
    <header class="page-header page-header-actions">
      <div>
        <h1>测试任务</h1>
        <p>TestRun 是 Mission 的持久身份；执行结果、充分度和发布状态保持分离。</p>
      </div>
      <button class="secondary-button" :disabled="store.loading" @click="store.load">刷新</button>
    </header>

    <form class="inline-form" @submit.prevent="createRun">
      <input v-model="testRunId" required placeholder="任务编号，例如 TR-20261022-001" />
      <input v-model="productionBatchId" placeholder="投产批次（可选）" />
      <button class="primary-button" :disabled="submitting">{{ submitting ? '创建中…' : '创建任务' }}</button>
    </form>

    <p v-if="submitError || store.error" class="error-strip">{{ submitError || store.error }}</p>

    <div class="table-shell">
      <table>
        <thead>
          <tr><th>任务编号</th><th>投产批次</th><th>状态范围</th><th>当前状态</th><th>更新时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in store.items" :key="item.test_run_id">
            <td><strong>{{ item.test_run_id }}</strong></td>
            <td>{{ item.production_batch_id || '—' }}</td>
            <td>{{ item.status_scope }}</td>
            <td>{{ item.current_state }}</td>
            <td>{{ new Date(item.updated_at * 1000).toLocaleString() }}</td>
          </tr>
          <tr v-if="!store.loading && store.items.length === 0">
            <td colspan="5" class="empty-row">暂无测试任务</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
