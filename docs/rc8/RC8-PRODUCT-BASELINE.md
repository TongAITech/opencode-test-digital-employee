# RC8 Product Baseline

Status: FROZEN FOR PRODUCT CONSTRUCTION

## Product principles

- Chinese-first user-visible language; avoid unnecessary Chinese/English mixing.
- Apple-inspired simplicity: restrained colors, generous spacing, clear hierarchy, weak borders, no dashboard-heavy visual noise.
- Left navigation + right query/list/detail flow.
- List pages answer "what exists and where is the target"; large detail pages/dialogs answer "what happened and why".
- Complex detail dialogs use about 90% viewport width/height, sticky title/tabs and a comfortable content area. Avoid nested small cards and nested dialogs.
- Runtime truth is rendered into business/test language. Users must not need DSH logs to understand testing.

## Primary navigation

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

Default entry: 测试任务 or last visited page. No mandatory dashboard.

## 1. 投产管理

Top-level object is production batch/date. List supports date, requirement, system, version, application and SST filters. Detail shows requirement scope tree and testing progress.

Scope hierarchy:
`投产批次 -> 需求 -> 系统版本 -> 应用 -> SST`.

## 2. 版本管理

List fields: version, system, production date where applicable, requirement count, SST count, testing state, latest TestRun, sufficiency state. Supports CRUD and conditional search.

## 3. 需求管理

Requirement is stable master identity; production/version participation is iterative scope, not a single version_id column.

List should summarize latest production date, involved systems/apps/SSTs and iteration count. Detail tabs:
- 基本信息
- 投产实现范围
- 需求分析 (BR/SR/TR as separate sub-tabs, not squeezed into columns)
- 代码分析
- 测试设计/用例
- 执行记录
- 缺陷
- 知识

## 4. 代码分析

Filters: production batch/date, version, requirement, SST, application, analysis state/time.

Analysis is snapshot/versioned; repeated analysis never silently overwrites history. Detail includes changed files/methods, CodeGraph chains, impacted DB/events, risks, evidence and comparison with prior snapshot.

## 5. 业务流程

Filters: application, page, flow name, requirement, SST, last verification.

Detail tabs:
- 流程步骤
- 接口关系
- 执行/重放记录
- 变更历史

Each step may show action, page context, requests, variable/auth dependencies, actual state change and evidence. Dependency diagrams are secondary views; default view remains a readable timeline.

## 6. 测试接口

Shows runtime-discovered API samples by application/page. Fields include method, route, auth requirement, source type, confidence/status, last verified time.

Source types may include browser capture, code discovery, OpenAPI/manual import and runtime learned. Request/response/auth examples are evidence-backed and versioned.

## 7. 测试用例

Filters: production batch/version/requirement/SST/layer/application/status/execution result.

List highlights title, risk/verification point and latest result. Large detail includes:
- 标题/目标
- 前置条件
- 测试数据
- 执行步骤
- 预期结果
- 关联风险/验证点
- 多次执行记录
- 证据

Attempt history is append-only from product perspective; prior FAIL/BLOCKED attempts are not hidden by a later PASS.

Case coverage type supports application, SST, system-version, requirement, cross-application, cross-system and E2E scopes.

## 8. 测试任务

Core product workbench. List: task/TestRun id, production/version/scope, owner/node, current phase, executed cases, gaps, defects, status.

Detail tabs:
- 概要
- 测试范围
- AI闭环
- 用例执行
- 缺口
- 缺陷
- 证据
- 运行轨迹（排障用）

The AI闭环 view must explicitly render attempts, evaluation, gaps, routed upstream node, invalidation/reopen and re-execution. A final status alone is insufficient.

## 9. 测试报告

Every execution TestRun produces a report record. Search by production/version/requirement/SST.

Report first answers "本次测了什么": scope, risks/verification points, verified/unverified items and why. Then each executed case shows full case content, actual result, assertions and linked logs/screenshots/videos/network/DB evidence.

## 10. 缺陷管理

Defect is first-class, linked to requirement scope, source case/attempt, expected/actual, evidence, RCA, fix verification and regression. Defect state cannot be inferred solely from a worker statement.

## 11. 知识库

Runtime knowledge types include business flow, API/route, auth behavior, data dependency, DB, test data, code, requirement/business rule, failure pattern and historical defect.

List fields: type, title, application/scope, source, status/confidence, version and last verification. Knowledge is versioned; a new model summary cannot overwrite a verified prior version without new evidence.

## 12. 执行节点

List: node name, user, OS/platform, connection state, install/package state, verified capability count, current TestRun/WorkItem, last heartbeat.

Node states are simple: 在线、空闲、执行中、维护中、异常、离线.

Node detail tabs:
- 基本信息
- 能力
- 技能
- 当前任务
- 历史任务
- 资源占用
- 运行记录

Allowed operations are controlled and safe: pause/resume new-task acquisition, maintenance, capability recheck, task release/transfer and graceful offline. Do not expose arbitrary remote command execution.

Center provides node package/upgrade downloads and tool manifest inspection.

## 13. 系统信息

Tabs: 测试环境、数据库、测试帐号、应用配置、测试资源、技能管理、系统诊断.

System diagnostics must show actual validation state and evidence for Center, PostgreSQL, Redis, artifact storage, node communication and selected node capabilities.

## Shared component rules

Use one consistent query bar, primary table, pagination, status tag, large detail shell, confirmation dialog, log viewer, JSON viewer, evidence viewer and timeline.

Use status color only on the status itself; avoid full-row red/green backgrounds.

## Product acceptance

For each key page:
- 10 seconds: user understands object and current state;
- 30 seconds: user locates the target requirement/case/task;
- 1 minute: user can trace why tested -> how tested -> actual -> assertion -> evidence.

A feature whose backend works but whose product page cannot explain the runtime truth is NOT DONE.