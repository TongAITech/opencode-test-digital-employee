<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'

const nav = [
  ['投产管理', '/productions'],
  ['版本管理', '/versions'],
  ['需求管理', '/requirements'],
  ['代码分析', '/code-analysis'],
  ['影响关系', '/traceability'],
  ['业务流程', '/business-flows'],
  ['测试接口', '/apis'],
  ['测试用例', '/test-cases'],
  ['测试任务', '/test-runs'],
  ['测试报告', '/reports'],
  ['缺陷管理', '/defects'],
  ['知识库', '/knowledge'],
  ['执行节点', '/nodes'],
  ['系统信息', '/system'],
]
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">RC8</span>
        <div>
          <strong>测试数字员工</strong>
          <small>中央测试平台</small>
        </div>
      </div>

      <nav aria-label="主导航">
        <RouterLink v-for="item in nav" :key="item[1]" :to="item[1]" class="nav-item">
          {{ item[0] }}
        </RouterLink>
      </nav>
    </aside>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>
