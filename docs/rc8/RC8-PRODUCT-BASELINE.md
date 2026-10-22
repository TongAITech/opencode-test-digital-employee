# RC8 Product Baseline v1

Status: FROZEN

## 0. Formal product technology stack
The formal RC8 Center product frontend is frozen as:
- Vue 3
- TypeScript
- Vite
- Vue Router
- Pinia

The formal product web edge is Nginx and the formal product backend API is FastAPI. The detailed binding contract is `docs/rc8/RC8-CENTER-TECHNOLOGY-STACK-CONTRACT.md`.

The current stdlib W1 HTTP server is not the formal product backend. A product capability is not PRODUCT_VERIFIED until it is exposed through the formal FastAPI projection/API and, for user-facing scope, the Vue product UI.

The UI MUST consume Center projections and MUST NOT derive PASS/SUFFICIENT/RELEASE from raw tool/execution counters.

## 1. Visual/interaction rules
- Chinese-first UI; avoid unnecessary Chinese/English mixing.
- Apple-inspired: restrained, spacious, clear hierarchy, subtle dividers, low visual noise.
- No dashboard-first design; no large decorative cards; no oversized colored navigation.
- Left navigation + right content area.
- Filter/search + list for locating objects; large detail page/modal for understanding objects.
- Complex detail surfaces use ~90% viewport width/height, fixed header/tabs, comfortable content width and internal scrolling.
- Avoid small nested dialogs and cramped multi-column long text.
- Status color is local to the status indicator; never paint whole pages/rows red/green.
- Shared design system: one table style, one filter bar, one large detail shell, one tabs pattern, one evidence viewer, one log viewer, one confirmation pattern.
- Product acceptance targets: 10 seconds understand / 30 seconds locate / 1 minute trace.

A third-party component library may provide low-level primitives, but RC8-owned wrappers/design tokens control the information architecture and visual language. A generic admin-template/dashboard look is not accepted.

## 2. Navigation
1. 投产管理
2. 版本管理
3. 需求管理
4. 代码分析
5. 业务流程
6. 测试接口
7. 测试用例
8. 测试任务
9. 测试报告
10. 缺陷管理
11. 知识库
12. 执行节点
13. 系统信息

Default landing page: 测试任务 (or last visited page). No dashboard requirement.

## 3. 投产管理
Purpose: answer “哪一天投什么”.
List/search dimensions: 投产日期/批次、需求编号、系统、版本号、应用、SST、测试状态.
Detail tabs: 需求范围、系统版本、测试进度、测试任务、缺陷.
Requirement scope is shown as a readable tree grouped by requirement -> system version -> application -> SST.

## 4. 版本管理
Supports query/create/edit/save/delete.
Core fields: 系统、版本号、版本名称、投产日期/关联投产批次、测试状态、需求数、SST数、最近测试时间、充分度/完成状态.
Detail shows associated production batches, requirements/SST, TestRuns, results and defects.

## 5. 需求管理
Requirement number is stable identity across iterations. One requirement can appear in multiple production batches and can involve multiple system versions/applications/SSTs.
List suggested fields: 需求编号、需求名称、最近投产日、涉及系统、涉及应用、SST数、投产次数、分析状态、最近执行.
Supports query/create/edit/save/delete.
Large detail tabs:
- 基本信息
- 投产实现范围
- 需求分析
- 代码分析
- 测试设计/测试用例
- 执行记录
- 缺陷
- 知识

需求分析 uses BR / SR / TR tabs, not three cramped columns.

## 6. 代码分析
Search by 投产/版本/需求/SST/应用/分析状态/时间.
Never reduce code analysis to one LLM paragraph. Structured detail includes affected application/files/classes/methods/call chains/DB objects/risks/CodeGraph evidence and snapshot/version.
Analysis is snapshot/versioned and can be compared; later analysis does not overwrite history.

## 7. 业务流程
Stores verified business operation flows, not merely API lists.
Search dimensions: 应用、页面、流程名称、需求、SST、最近验证时间、状态.
List: 流程名称、应用、起始页面、步骤数、接口数、最近验证、状态.
Detail tabs: 流程步骤、接口关系、执行记录、变更历史.
Default display is a readable vertical business timeline. Relation graph is secondary/on-demand.
Each step can expose operation, request/response, parameter source, auth dependency, assertion and evidence.

## 8. 测试接口
Search by 应用、页面、API、方法、是否需要登录、验证状态.
Stores real observed/verified samples from Browser/OpenAPI/code/runtime/manual sources.
Fields include page, method, route, auth requirement/type, request/response sample, source type, confidence, last_verified_at and evidence.
Knowledge can become stale; historical versions remain.

## 9. 测试用例
Search by 投产/版本/需求/SST/层级L1-L7/应用/状态/最近执行结果.
List fields: Case ID、版本、需求、SST、层级、标题、风险/验证点、覆盖范围类型、最近结果、最近执行.
Coverage scope types include APPLICATION/SST/SYSTEM_VERSION/REQUIREMENT/CROSS_APPLICATION/CROSS_SYSTEM/E2E.
Large detail contains: 基本信息、前置条件、测试数据、执行步骤、预期结果、关联风险/验证点、执行记录、证据.
Execution records are append-only Attempts; do not overwrite history. Each Attempt exposes time/result/assertions/environment/duration and per-step Actual/Evidence/Failure classification.

## 10. 测试任务
First-class TestRun page; main operational product surface.
List: 任务编号、投产/版本、测试范围、执行节点/执行人、开始时间、当前阶段、已执行Case、Gap、缺陷、状态.
Detail tabs:
- 概要
- 测试范围
- AI闭环
- 用例执行
- Gap
- 缺陷
- Evidence

AI闭环 must visibly show attempts, evaluator result, gaps, route-back, invalidation/re-run and completion state. A final “完成” badge alone is insufficient.

## 11. 测试报告
Every TestRun creates one report record/snapshot.
Search by 投产/版本/需求/SST/任务/时间.
Report first answers:
- 本次测试了什么
- 哪些需求/范围/风险/验证点已验证
- 哪些未验证以及原因
Then shows every executed case with test content, Actual, Assertion and bound logs/screenshots/video/network/DB evidence.
Report is structured data first; HTML/PDF export is secondary.

## 12. 缺陷管理
Defect is first-class, linked to requirement/scope/case/attempt/evidence/RCA/regression.
List: 缺陷号、版本、需求、SST、来源Case、标题、严重级别、状态、首次发现.
Detail automatically includes Expected/Actual/assertion/log/screenshot/network/DB/code-impact/RCA and regression status.

## 13. 知识库
Not only uploaded documents. Primary purpose is AI runtime knowledge:
- 业务流程
- 接口/路由
- 认证
- 页面
- 数据库
- 测试数据
- 业务规则
- 代码
- 失败模式
- 环境
- 历史缺陷

List fields: 类型、标题、应用、适用范围、来源、置信度、最近验证、状态、版本.
New model output cannot overwrite trusted knowledge without new evidence.

## 14. 执行节点
List/search: 节点名称、执行人、状态、操作系统/架构、能力、当前任务、最后心跳、安装状态、能力状态.
Simple node states: 在线/空闲/执行中/维护中/离线/异常.
Node detail tabs: 基本信息、能力、技能、当前任务、历史任务、资源占用、运行记录.
Capabilities show reality qualification and latest verification evidence; package presence is not enough.
Allowed operations are controlled: 暂停领取、恢复领取、维护、安全下线、刷新能力、受控释放任务. Do not expose arbitrary remote shell execution.
Node page provides Center-hosted download/upgrade entry and offline-tool manifest.

## 15. 系统信息
Tabs: 测试环境、数据库、测试帐号、应用配置、测试资源、技能管理、系统诊断.
Test data sensitivity governance is not a blocking product scope for RC8; prioritize usable data discovery/build/lease/reuse/cleanup. Runtime credentials are system-security configuration, not normal shared test data.
System diagnostics show Center/PostgreSQL/Redis/artifact storage/node communication and node capability checks with latest real verification evidence.

## 16. Traceability interaction
Every recognizable entity in details/reports is navigable: requirement -> scope -> code analysis -> case -> attempt -> API/business flow -> defect -> knowledge -> evidence.
The product should feel like one connected model, not isolated CRUD screens.

## 17. Product acceptance
A critical page fails product acceptance if the user must read DSH logs to understand what happened.
For a real case, UI must answer: 为什么测、测什么、怎么测、实际是什么、为什么PASS/FAIL、证据在哪里、后续Gap回到哪里.

Product acceptance additionally requires:
- Vue 3 + TypeScript implementation of the applicable surface;
- API data coming from formal FastAPI Center projections;
- no frontend-derived sufficiency/release truth;
- same-origin Nginx deployment smoke before final product deployment closure.