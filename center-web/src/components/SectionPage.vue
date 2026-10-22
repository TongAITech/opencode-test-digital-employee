<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => String(route.meta.title ?? 'RC8'))
const description = computed(() => String(route.meta.description ?? ''))
</script>

<template>
  <section class="section-page">
    <header class="page-header">
      <div>
        <h1>{{ title }}</h1>
        <p>{{ description }}</p>
      </div>
    </header>

    <div class="empty-state">
      <strong>产品投影尚未接入</strong>
      <span>此页面骨架已冻结，但在真实 Center Projection/API 接入前不会展示模拟业务数据。</span>
    </div>
  </section>
</template>
