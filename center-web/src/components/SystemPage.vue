<script setup lang="ts">
import { onMounted } from 'vue'
import { useSystemStore } from '../stores/system'

const store = useSystemStore()
onMounted(() => store.refresh())
</script>

<template>
  <section class="section-page">
    <header class="page-header page-header-actions">
      <div>
        <h1>系统信息</h1>
        <p>查看 Center、PostgreSQL、Redis 与冻结技术栈的真实状态。</p>
      </div>
      <button class="secondary-button" :disabled="store.loading" @click="store.refresh">
        {{ store.loading ? '刷新中…' : '刷新' }}
      </button>
    </header>

    <p v-if="store.error" class="error-strip">{{ store.error }}</p>

    <div class="detail-list" v-if="store.health">
      <div><span>Center</span><strong>{{ store.health.status }}</strong></div>
      <div><span>PostgreSQL</span><strong>{{ store.health.database }}</strong></div>
      <div><span>Redis</span><strong>{{ store.health.redis }}</strong></div>
      <div><span>运行时真相</span><strong>{{ store.health.runtime_truth }}</strong></div>
    </div>

    <section class="content-section" v-if="store.architecture">
      <h2>冻结技术栈</h2>
      <div class="key-value-table">
        <div v-for="(value, key) in store.architecture.technology" :key="key">
          <span>{{ key }}</span><strong>{{ value }}</strong>
        </div>
      </div>
    </section>

    <section class="content-section" v-if="store.architecture">
      <h2>真实性规则</h2>
      <div class="key-value-table">
        <div v-for="(value, key) in store.architecture.truth_rules" :key="key">
          <span>{{ key }}</span><strong>{{ value }}</strong>
        </div>
      </div>
    </section>
  </section>
</template>
