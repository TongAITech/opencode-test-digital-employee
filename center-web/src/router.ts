import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import ProductionPage from './components/ProductionPage.vue'
import SectionPage from './components/SectionPage.vue'
import SystemPage from './components/SystemPage.vue'
import TestRunPage from './components/TestRunPage.vue'
import TraceabilityPage from './components/TraceabilityPage.vue'

export const productRoutes: RouteRecordRaw[] = [
  { path: '/', redirect: '/productions' },
  { path: '/productions', component: ProductionPage, meta: { title: '投产管理', description: '先确定投产日，再确认需求及其系统版本、应用和SST范围。' } },
  { path: '/versions', component: SectionPage, meta: { title: '版本管理', description: '查看系统版本及其承载的需求、SST和测试充分度；系统版本不是测试任务主入口。' } },
  { path: '/requirements', component: SectionPage, meta: { title: '需求管理', description: '查看需求跨投产批次的交付历史、BR/SR/TR、分析、测试与缺陷。' } },
  { path: '/code-analysis', component: SectionPage, meta: { title: '代码分析', description: '查看快照、变更、调用链、风险、测试影响和证据。' } },
  { path: '/traceability', component: TraceabilityPage, meta: { title: '影响关系', description: '查询需求、页面、接口、代码、数据库表与测试用例的证据化正反向关系。' } },
  { path: '/business-flows', component: SectionPage, meta: { title: '业务流程', description: '查看已验证的页面、接口、状态与业务流转。' } },
  { path: '/apis', component: SectionPage, meta: { title: '测试接口', description: '查看已验证接口、认证、样例、来源和新鲜度。' } },
  { path: '/test-cases', component: SectionPage, meta: { title: '测试用例', description: '查看风险、验证点、前置、数据、步骤、Oracle与执行历史。' } },
  { path: '/test-runs', component: TestRunPage, meta: { title: '测试任务', description: '查看由投产批次范围创建的Mission、Attempt、Gap、覆盖率和AI闭环。' } },
  { path: '/reports', component: SectionPage, meta: { title: '测试报告', description: '回答测了什么、没测什么、覆盖率、缺陷与剩余风险。' } },
  { path: '/defects', component: SectionPage, meta: { title: '缺陷管理', description: '查看Expected、Actual、Evidence、RCA和回归闭环。' } },
  { path: '/knowledge', component: SectionPage, meta: { title: '知识库', description: '管理业务、接口、认证、数据、代码与失败模式知识。' } },
  { path: '/nodes', component: SectionPage, meta: { title: '执行节点', description: '查看节点、能力Reality、技能、任务和运行记录。' } },
  { path: '/system', component: SystemPage, meta: { title: '系统信息', description: '查看环境、数据库、帐号、资源、技能与系统诊断。' } },
]

export default createRouter({
  history: createWebHistory(),
  routes: productRoutes,
})
