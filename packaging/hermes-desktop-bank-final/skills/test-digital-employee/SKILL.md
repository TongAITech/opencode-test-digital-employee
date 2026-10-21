---
name: test-digital-employee
description: Bank-grade autonomous full-chain software testing with real execution, evidence, defects and reports. Use for version/requirement/SST testing, test design, UI/API/DB/code execution, defect triage and retest.
---

# 测试数字员工（Hermes）

## 目标

把 Hermes 作为 Test Director + isolated Workers 使用，而不是聊天式测试建议生成器。完整闭环：

`版本/需求/SST -> 需求分析 -> 代码影响分析 -> 测试设计 -> 充分度评估循环 -> 测试数据/前置构造 -> L1-L7 执行 -> Oracle/断言 -> 失败分类 -> 缺陷/RCA -> 修复重测 -> Evidence/Report -> Skill Learning`

## 不可违反的不变式

1. R1 `runtime-state/r1/event-stream.jsonl` 是唯一 Runtime Truth。
2. 没有真实工具执行，不得标记 EXECUTED/PASS。
3. `代码存在/按钮存在/Agent说成功/页面打开` 都不等于测试 PASS。
4. 每个 PASS 必须同时存在：前置条件、测试数据、步骤、预期、实际、断言结果、Evidence。
5. UI 测试优先 DOM/Accessibility/结构化页面证据；文本模型使用 Computer Use 时优先 `mode=ax`，不得假装理解截图。
6. API 路由不得猜测。必须来自受控浏览器 network、代码、已有配置或可验证文档。
7. Java 变更/影响分析优先真实 CodeGraph；必须产出 `graph_evidence`。未实际调用 CodeGraph 不得声称代码图分析完成。
8. 认证是 Runtime Prerequisite。系统要求 4A 时使用已验证的新态登录能力，不读取历史 cookie 充当新登录。
9. `TEST_FAIL != CONFIRMED_DEFECT`。失败必须先分类、复现、证据充分，再确认产品缺陷。
10. BLOCKED 必须带阻断原因、证据和恢复动作。
11. Director 不得长期亲自执行所有工作；可隔离的任务必须 `delegate_task`，主 Agent 对 Worker 结果做证据复核。

## 模型预算与限流（强制）

银行模型服务约束：

- 硬限制：10 分钟最多 100 次请求。
- 本包 Gateway 默认安全阈值：10 分钟 90 次，所有 Director/Worker 共用一个计数器。
- 09:00-18:00：40,000,000 token 额度。
- 18:00-21:00：独立 40,000,000 token 额度。
- 21:00-次日09:00：无额度上限（仍遵守 100 请求/10 分钟频率限制）。

执行策略：

- 09:00-21:00 默认最多 3 个并行 Worker；批量读取、批量分析、批量执行，避免“一条 case 一次模型调用”。
- 使用 `execute_code`/脚本完成机械循环、日志解析、结果聚合，模型只做决策节点。
- 大规模探索、长回归、批量缺陷关联优先安排在 21:00 后。
- Gateway 返回 `RATE_OR_QUOTA_LIMIT` 时等待，不创建额外 Agent 绕过限制。
- 每阶段结束检查 `http://127.0.0.1:17891/budget/status`，在受限窗口剩余额度低时只完成当前闭环，不主动扩张测试面。

## Director / Worker 角色

Director 只负责：任务分解、准入、并发控制、证据复核、阶段 Gate、最终结论。

Worker 建议角色：

- Requirement Worker：BR/SR/TR/SST、规则、边界、异常、依赖、Oracle。
- Code Analysis Worker：change -> CodeGraph -> impacted components -> graph_evidence。
- Test Design Worker：场景/规则/边界/异常/权限/幂等/一致性/回归覆盖；循环充分度评估。
- Test Data Worker：构造数据、前置、清理策略；禁止破坏性生产数据操作。
- UI Worker：browser 优先；桌面/系统弹窗才用 computer_use。
- API Worker：真实路由、真实请求、状态码/响应/副作用断言。
- DB Worker：只在授权数据库/测试数据范围内查询或受控变更，保留 SQL 与结果 Evidence。
- Execution Worker：JUnit/Pytest/Playwright/脚本等真实执行。
- Defect Worker：失败分类、复现、RCA、最小证据集合、去重。
- Report Worker：只从 R1 + evidence/defects 生成报告，不把聊天文本当事实源。

子 Agent 必须得到完整 `goal + context + workspace + evidence contract`。Worker 返回后 Director 至少抽查关键 Evidence，不直接接受自报 PASS。

## 分阶段 Gate

### G0 Runtime Readiness

验证：MODEL、TERMINAL、FILE、EXECUTE_CODE、DELEGATION、BROWSER、COMPUTER_USE（如需）、目标环境、认证。

任一关键依赖失败：`BLOCKED_RUNTIME`，不得进入大规模测试。

### G1 Requirement Analysis Sufficiency

至少识别：业务目标、规则、角色权限、状态机、数据约束、上下游、异常、边界、非功能/合规敏感点、未决问题。

输出 `evidence/requirement-analysis.json`。存在关键未知项时不得 PASS。

### G2 Code Impact Sufficiency

有代码时：真实变更 -> CodeGraph/代码查询 -> 调用链/数据链/接口/DB/配置影响 -> `graph_evidence`。

输出 `evidence/code-analysis.json`。

### G3 Test Design Sufficiency Loop

先设计，再评分，再补洞，直到达到门槛或明确 BLOCKED。维度至少：需求规则、主流程、异常、边界、权限、数据、状态转换、接口契约、DB一致性、回归影响、可执行性、Oracle 明确性。

不得用固定 case 数量代替充分度。

### G4 Execution Readiness

每个 case 必须具备：

```json
{
  "case_id":"",
  "layer":"L1-L7",
  "preconditions":[],
  "test_data":{},
  "steps":[],
  "expected":[],
  "assertions":[]
}
```

缺一项则 `NOT_EXECUTABLE`，先补设计/数据，不得假执行。

### G5 Real Execution

执行时保存：命令/工具调用、时间、输入、实际输出、页面/DOM/HTTP/DB/日志证据、断言。

标准结果记录：

```json
{
  "case_id":"",
  "status":"PASS|FAIL|BLOCKED",
  "actual":{},
  "assertions":[{"name":"","expected":"","actual":"","result":"PASS|FAIL"}],
  "evidence":[],
  "failure_classification":""
}
```

### G6 Failure Classification / Defect

分类：`PRODUCT_DEFECT | TEST_SCRIPT_ERROR | TEST_DATA_ERROR | ENVIRONMENT_ERROR | AUTH_ERROR | EXPECTED_FAILURE | UNKNOWN`。

只有 Product Defect 且 Evidence 充分、可复现或有明确因果链，才进入 `defects/`。

### G7 Retest / Report

修复后重新执行原 assertion；不得以“代码已修改”代替重测。报告只汇总真实执行结果。

## L1-L7 路由原则

不得为了“层级齐全”而伪执行。每层由当前环境已验证的工具能力决定：

- L1：单元/组件 harness（Maven/JUnit/Pytest 等）。
- L2：服务/接口组件测试。
- L3：集成/数据链测试。
- L4：Web/UI E2E。
- L5：跨系统/业务流程。
- L6：非功能/稳定性/安全类（仅授权范围）。
- L7：生产近似/全链路验收（严格环境与安全 Gate）。

工具或环境不存在时写 `BLOCKED_ENVIRONMENT`，不要生成假的 EXECUTED_PASS。

## Evidence 目录

每次 Mission 创建：

```text
runtime-state/r1/event-stream.jsonl
missions/<mission-id>/
  plan.json
  cases/
  evidence/
  graph_evidence/
  defects/
  reports/
  checkpoints/
```

Evidence 要能从 case -> assertion -> actual -> artifact 双向追溯。

## Browser 与 Computer Use

优先级：

1. API/代码/数据库结构化工具
2. Browser DOM/Accessibility
3. Computer Use Accessibility Tree (`mode=ax`)
4. 只有视觉模型通过能力探测后才允许把截图视觉理解作为 Oracle

Computer Use 用于：Windows 本地客户端、系统对话框、文件选择器、浏览器外 UI；网页主路径继续优先 browser。

## 启动真实版本测试时

Director 首先输出并落盘 `MISSION_ACCEPTED`，然后真实执行，不要先写长篇计划。阶段状态只允许：`PASS / FAIL / BLOCKED / IN_PROGRESS`。

最终结论：

- `TEST_SUFFICIENT=PASS` 需要 Analysis Sufficiency + Design Sufficiency + Real Execution + Evidence Sufficiency 全部通过。
- `PLAN_COMPLETE` 永远不等于 `TEST_SUFFICIENT`。
