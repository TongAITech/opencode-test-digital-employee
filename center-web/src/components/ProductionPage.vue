<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useProductionBatchStore } from '../stores/productionBatches'

const store = useProductionBatchStore()
const router = useRouter()

const productionBatchId = ref('')
const productionDate = ref('')
const productionName = ref('')
const requirementId = ref('')
const requirementTitle = ref('')
const deliveryId = ref('')
const scopeDeliveryId = ref('')
const scopeId = ref('')
const systemId = ref('')
const systemVersion = ref('')
const applicationId = ref('')
const sstId = ref('')
const actionError = ref('')
const actionMessage = ref('')
const submitting = ref(false)

const stateLabels: Record<string, string> = {
  PLANNED: '待开始',
  ACTIVE: '进行中',
  IN_PROGRESS: '进行中',
  PARTIAL: '部分完成',
  COMPLETED: '已完成',
  CANCELLED: '已取消',
}

const scopeReady = computed(() => {
  const requirements = store.plan?.requirements ?? []
  return requirements.length > 0 && requirements.every((item) => item.scopes.length > 0)
})

function stateLabel(value: string) {
  return stateLabels[value] ?? value
}

onMounted(() => store.load())

async function run(action: () => Promise<unknown>, success: string) {
  submitting.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    await action()
    actionMessage.value = success
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function createBatch() {
  await run(async () => {
    await store.createBatch(productionBatchId.value.trim(), productionDate.value, productionName.value.trim())
    productionBatchId.value = ''
    productionDate.value = ''
    productionName.value = ''
  }, '投产批次已创建，请继续确认本批次需求。')
}

async function addRequirement() {
  await run(async () => {
    await store.addRequirement(requirementId.value.trim(), requirementTitle.value.trim(), deliveryId.value.trim())
    requirementId.value = ''
    requirementTitle.value = ''
    deliveryId.value = ''
  }, '需求已纳入当前投产批次，请继续补充系统版本和 SST。')
}

async function addScope() {
  await run(async () => {
    await store.addScope(
      scopeDeliveryId.value,
      scopeId.value.trim(),
      systemId.value.trim(),
      systemVersion.value.trim(),
      applicationId.value.trim(),
      sstId.value.trim(),
    )
    scopeId.value = ''
    systemId.value = ''
    systemVersion.value = ''
    applicationId.value = ''
    sstId.value = ''
  }, '系统版本和 SST 范围已保存。')
}

async function createNextRound() {
  await run(async () => {
    await store.createNextRound()
  }, '下一轮测试已创建。轮次编号由系统自动生成。')
}

async function startRound(testRoundId: string) {
  await run(async () => {
    await store.startRound(testRoundId)
    await router.push('/test-runs')
  }, '本轮自主测试已启动。')
}
</script>

<template>
  <section class="section-page">
    <header class="page-header page-header-actions">
      <div>
        <h1>投产管理</h1>
        <p>先确定投产日，再确认需求、系统版本和 SST；同一投产日可以连续开展多轮测试。</p>
      </div>
      <button class="secondary-button" :disabled="store.loading" @click="store.load">刷新</button>
    </header>

    <form class="production-form" @submit.prevent="createBatch">
      <input v-model="productionBatchId" required placeholder="投产批次编号" />
      <input v-model="productionDate" required type="date" aria-label="计划投产日" />
      <input v-model="productionName" required placeholder="批次名称，例如 11月15日投产" />
      <button class="primary-button" :disabled="submitting">新建投产批次</button>
    </form>

    <p v-if="actionError || store.error" class="error-strip">{{ actionError || store.error }}</p>
    <p v-if="actionMessage" class="success-strip">{{ actionMessage }}</p>
    <p v-if="store.legacyUnboundRuns.length" class="error-strip">
      发现 {{ store.legacyUnboundRuns.length }} 个历史测试任务未绑定测试轮次。它们仅作为升级审计记录保留，不会被计入当前轮次事实或充分度判断。
    </p>

    <div class="table-shell">
      <table>
        <thead><tr><th>投产日</th><th>投产批次</th><th>名称</th><th>状态</th><th></th></tr></thead>
        <tbody>
          <tr v-for="item in store.items" :key="item.production_batch_id">
            <td>{{ item.production_date }}</td>
            <td><strong>{{ item.production_batch_id }}</strong></td>
            <td>{{ item.name }}</td>
            <td>{{ stateLabel(item.state) }}</td>
            <td><button class="text-button" @click="store.select(item.production_batch_id)">查看范围</button></td>
          </tr>
          <tr v-if="!store.loading && store.items.length === 0"><td colspan="5" class="empty-row">暂无投产批次</td></tr>
        </tbody>
      </table>
    </div>

    <template v-if="store.plan">
      <section class="content-section">
        <h2>{{ store.plan.batch.production_date }} · {{ store.plan.batch.name }}</h2>
        <p class="section-hint">当前投产范围：{{ store.plan.batch.production_batch_id }}。多轮测试不会自动产生新的需求迭代；只有进入新的投产日才属于跨批次持续交付。</p>

        <form class="production-form requirement-form" @submit.prevent="addRequirement">
          <input v-model="requirementId" required placeholder="需求编号" />
          <input v-model="requirementTitle" required placeholder="需求名称" />
          <input v-model="deliveryId" required placeholder="本批次需求交付编号" />
          <button class="secondary-button" :disabled="submitting">纳入本批次</button>
        </form>

        <div class="requirement-list">
          <article v-for="item in store.plan.requirements" :key="item.delivery.delivery_id" class="requirement-row">
            <div class="requirement-heading">
              <div>
                <strong>{{ item.requirement.requirement_id }}</strong>
                <span>{{ item.requirement.title }}</span>
              </div>
              <small>{{ stateLabel(item.delivery.state) }} · {{ item.delivery.delivery_id }}</small>
            </div>
            <div class="table-shell compact-table">
              <table>
                <thead><tr><th>系统</th><th>系统版本</th><th>应用</th><th>SST</th></tr></thead>
                <tbody>
                  <tr v-for="scope in item.scopes" :key="scope.scope_id">
                    <td>{{ scope.system_id }}</td><td>{{ scope.system_version }}</td><td>{{ scope.application_id || '—' }}</td><td>{{ scope.sst_id }}</td>
                  </tr>
                  <tr v-if="item.scopes.length === 0"><td colspan="4" class="empty-row">尚未确认系统版本 / SST，不能启动测试轮次</td></tr>
                </tbody>
              </table>
            </div>
          </article>
        </div>
      </section>

      <section v-if="store.plan.requirements.length" class="content-section">
        <h2>补充需求实现范围</h2>
        <form class="scope-form" @submit.prevent="addScope">
          <select v-model="scopeDeliveryId" required>
            <option value="" disabled>选择需求</option>
            <option v-for="item in store.plan.requirements" :key="item.delivery.delivery_id" :value="item.delivery.delivery_id">
              {{ item.requirement.requirement_id }} · {{ item.requirement.title }}
            </option>
          </select>
          <input v-model="scopeId" required placeholder="范围编号" />
          <input v-model="systemId" required placeholder="系统" />
          <input v-model="systemVersion" required placeholder="系统版本" />
          <input v-model="applicationId" placeholder="应用（可选）" />
          <input v-model="sstId" required placeholder="SST" />
          <button class="secondary-button" :disabled="submitting">保存范围</button>
        </form>
      </section>

      <section class="content-section">
        <div class="page-header-actions">
          <div>
            <h2>测试轮次</h2>
            <p class="section-hint">每一轮拥有独立 TestRun、Stage、Attempt 和 Evidence；上一轮事实不会被下一轮覆盖。</p>
          </div>
          <button class="secondary-button" :disabled="submitting || !scopeReady" @click="createNextRound">新建下一轮</button>
        </div>

        <div class="table-shell compact-table">
          <table>
            <thead><tr><th>轮次</th><th>名称</th><th>状态</th><th>纳入需求</th><th>测试任务</th><th></th></tr></thead>
            <tbody>
              <tr v-for="item in store.rounds" :key="item.round.test_round_id">
                <td><strong>第 {{ item.round.round_no }} 轮</strong></td>
                <td>{{ item.round.name }}</td>
                <td>{{ stateLabel(item.round.state) }}</td>
                <td>{{ item.deliveries.length }}</td>
                <td>{{ item.test_run?.test_run_id || '尚未启动' }}</td>
                <td>
                  <button
                    v-if="!item.test_run && item.round.state !== 'COMPLETED' && item.round.state !== 'CANCELLED'"
                    class="text-button"
                    :disabled="submitting || !scopeReady"
                    @click="startRound(item.round.test_round_id)"
                  >开始本轮自主测试</button>
                  <button v-else-if="item.test_run" class="text-button" @click="router.push('/test-runs')">查看测试任务</button>
                </td>
              </tr>
              <tr v-if="store.rounds.length === 0"><td colspan="6" class="empty-row">尚未创建测试轮次。范围确认完成后，新建第 1 轮。</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </section>
</template>