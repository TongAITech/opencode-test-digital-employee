# RC7.2 C09 — Journey Teaching 生产接线与独立验收记录

施工分支：`work/rc7.2-journey`（来源：`work/rc7.2` HEAD `7efb3c8aa62f22629e570e3381727969524bf598`）

状态：**工程候选；FIELD_PENDING；不得标记 C09 CLOSED / BANK_FINAL。** 全量设计和最终验收以 `docs/rc7.2/01`、`02`、`05`、`10` 的冻结标准为准，本文不放宽任何前置门槛。

## 1. 本次真实改造

| 层级 | 代码路径 | 真实入口及边界 |
|---|---|---|
| 浏览器教学 | `rc7_runtime/rc72_journey_cdp_capture.py` | `JourneyCDPTeachingRecorder.begin/poll/record_assertion/finish`，只连接既有 CDP，不自建或劫持 4A Browser |
| 浏览器动作 | `rc7_runtime/rc72_journey_playwright.py` | `JourneyPlaywrightAdapter.execute_step`，Playwright/CDP + B 组 WRITE 租约；失败留下实际本地 JSON 与可获得的截图 |
| 编译 | `rc7_runtime/rc72_journey_compiler.py` | `JourneyCompiler.compile`，候选仍 `executable=False`；SELECT 也必须绑定 value_ref/credential_ref |
| 回放 | `rc7_runtime/rc72_journey_replay.py` | `JourneyReplayService.replay`，每步骤独立 Actual/Evidence；异常文件有据可查 |
| 基准 | `rc7_runtime/rc72_journey_benchmark.py` | `JourneyBenchmarkService.evaluate`：至少两次独立终态回放 |
| 人工批准 | `rc7_runtime/rc72_journey_promotion.py` | `JourneyPromotionService.review_and_promote`，依赖外部 Field 人工证明，拒绝旧失败回放绕过 |
| 正式 L4/L5 | `rc7_runtime/rc72_official_journey_execution.py` | `OfficialJourneyExecutionService.execute`；持有正式资产和资源租约，按 ETU/Case/Attempt 执行 |
| N7 接线端 | `rc7_runtime/rc72_journey_n7_adapter.py` | `SignedN7OfficialJourneyAdapter.preflight/__call__`，不改 A 共享文件，通过正式 ToolDispatch adapters 字典注入 |
| 变更后再审批 | `rc7_runtime/rc72_journey_drift.py` | `JourneyDriftService.report/assert_eligible`，真实失败文件支持漂移报告；禁止旧资产再次执行 |
| 异常留证 | `rc7_runtime/rc72_journey_failure_receipt.py` | 将真实 adapter 异常类别落盘，拒绝虚构截图和 `adapter-error://` 占位 |

## 2. 业务教学执行示例（接口非演示成功标志）

先由 B 组提供**可用且独占**的 BrowserInstance + WRITE BrowserLease，且其 `purpose=JOURNEY_TEACHING`，绑定实际 `mission_id/workitem_id/attempt_id/worker_id/session_id`。该实例的 profile、CDP endpoint、4A 会话与其他 Agent 隔离。人工在该浏览器教学，应用代码执行：

```python
from pathlib import Path
from rc7_runtime.rc72_journey_cdp_capture import JourneyCDPTeachingRecorder
from rc7_runtime.rc72_journey_teaching import JourneyTeachingService

teaching = JourneyTeachingService(truth, release_id="RC7.2", browser_pool=browser_pool)
recorder = JourneyCDPTeachingRecorder(
    teaching=teaching, evidence_root=Path("runtime-state/evidence/journey"))
recorder.begin(
    recording_id="JR-1", mission_id=mission_id,
    release_batch_id=release_batch_id, requirement_id=requirement_id,
    sst_id=sst_id, obligation_id=obligation_id,
    workitem_id=workitem_id, attempt_id=attempt_id,
    worker_id=worker_id, session_id=session_id,
    browser_lease_id=browser_lease_id, human_operator_ref=human_operator_ref,
    auth_asset_ref=auth_asset_ref)
# 教学进行时轮询 DOM 操作；输入内容只能绑定 value_ref，不能拷贝敏感明文。
recorder.poll(page_role="配置管理", bindings={
    "css:#configName": {"value_ref": "n5-value://configuration-name"},
    "css:#save": {"api_code_mapping_ref": "codegraph://verified/save-mapping"},
})
recorder.record_assertion(
    page_role="配置管理", oracle_ref="oracle://config-save-success",
    element_ref="css:#successToast")
recording = recorder.finish()  # CAPTURED / CANDIDATE_SOURCE，仍不可执行
```

同一个录制资产下一步必须经 `JourneyCompiler.compile` 形成候选；调用 `JourneyReplayService.replay` 至少两次，保存独立 Actual/Evidence；`JourneyBenchmarkService.evaluate` 检查稳定性；真实人工审核 `JourneyPromotionService.review_and_promote` 产生**独立** Official Journey。任意一步失败，不能将 Candidate 或录制文件标为正式可执行。

### 输入和断言的防误执行原则

- 所有可执行动作使用稳定 `css:/testid:` 或经独立 resolver 验证的 DOM 定位；不猜测 `dom://` 的 CSS。
- INPUT/SELECT 的值使用 N5 或保管凭证的引用；不在步骤中保存输入原值、Cookie 或 Authorization。
- ASSERT 使用可执行的确定性 Oracle（如元素可见、文本/属性匹配、URL 精确匹配），缺失则拒绝。
- 页面关联以实际页面状态、network JSON、`api_code_mapping_ref` 承载，需依赖 A 组 N3 的 CodeGraph/接口知识和现场响应事实提供**可校验映射**。没有此映射不得伪称“代码追踪验证完成”。
- 真实浏览器失败存档为 `file://` Actual/Evidence，截图无法取得时也保留异常收据，并区分“Worker/runtime 失败”和“业务断言失败”。

## 3. N7 标准入口——请求 A 组集成，不改共享文件

A 组只需把 `SignedN7OfficialJourneyAdapter(official_execution_service)` 注入现有 `SignedToolDispatchService(adapters=...)` 的 `journey_playwright` 工具入口。该入口必须由 N6 签名、N7 Admission/Preparation 后真实触发，禁止直接通过 Agent 文本调用它冒充标准 N7。

N6 的 `tool_route.tool` 必须为 `journey_playwright`；`request` 最少包含：

```json
{
  "schema_ref": "n6://journey-official-v1",
  "source_ref": "official-journey://OJ-1",
  "official_asset_id": "OJ-1",
  "approval_scope_digest": "sha256:<exact-approved-candidate-benchmark-digest>"
}
```

冻结 ExecutableContract 同时携带 `mission_id/release_batch_id/requirement_id/sst_id/obligation_id/case_id`，WorkItemAttemptBinding/ETU/TestCase 必须完全同源。N7 只认**一个 active WRITE BrowserLease**；普通 AuthKeeper、教学、其他 L4/L5 Worker 的 BrowserInstance 不可共享写所有权。N7 仍必须由 A 组的正式 Oracle/cleanup/independent review/N8/N9/N10 完成闭环。工具返回 `journey.state` 只是实际结果，不是 Case PASS。

**A 组待集成接口：**
1. N6 编译器允许 `journey_playwright` 的明确 schema/source/verified tool route 和可解引用 Official Journey；仍按现有 fail-closed 规则验证输入。
2. 正式 Case/ETU WorkItem 从 Requirement→SST→TestObligation→TestCase 取得 Approved Asset 引用，而非人工在测试代码直接 UPsert Official Asset。
3. N7 标准调度时注入上面的 Callable + B 组独立 BrowserPool；运行前调用 preflight；N7 Intent 必须先落 R1，以免冷重启重复副作用。
4. 新增 `journey.state` 与业务 Oracle 的确认型映射，清理/独立结果审核、N8 诊断与修复不得根据 adapter 自报 PASS；失败和页面漂移要产生新的 Attempt，不允许旧 Attempt 原位重放。

**B 组待确认接口：**
1. BrowserInstance 必须具备单独 profile/CDP 端点、可访问的 BSK Session、真实 browser process 健康状态。
2. BrowserLease 的实际 WRITE 排他、租约续期、取消/失效时强制 fencing，异常和崩溃后的 custody 恢复；Adapter 执行前后均检查。
3. AuthKeeper 的独立 BrowserInstance/4A AuthAsset 导入策略；设备绑定无法导入时由相应 Worker 自己登录。
4. 行内办公 PC 的 Playwright 1.62.1 + 匹配 Chromium 离线包，以及 BSK/CDP 真实握手、Windows Git Bash/信创 Linux 环境验证。

## 4. 正反例与冷恢复

`tests/test_rc72_journey_playwright_adapter.py`：真实 `file://` JSON/截图收据、成功/断言失败、被撤租约、动作中撤租约、教学采集、R1 冷重启不重复执行。

`tests/test_rc72_journey_n7_adapter.py`：正式 Case/Attempt 谱系、N7 RAW receipt、错误 Requirement/SST/Obligation/Case 拒绝、审批摘要冲突、BrowserLease 数量拒绝、冷启动旧 Attempt 禁止重复业务 I/O。

`tests/test_rc72_journey_drift_and_failure.py`：页面改变所致正式失败需实际证据才允许报告漂移、漂移后冷恢复仍隔离旧资产、adapter 异常留真实文件、不可信旧基准推广拦截。

旧 `tests/test_rc72_phase9_*.py` 保留，独立 CI：`.github/workflows/rc7.2-journey-ci.yml` 用 Python 3.8/3.11 全跑旧组件和新边界。这些测试的 FakePage 是工程可复验浏览器协议模拟，**不是行内 Playwright/BSK/4A 实体测试**。

## 5. 未核销 / 现场边界

| 缺口 | 责任 / 当前状态 |
|---|---|
| Playwright/Chromium 实机附着、BSK 录制握手、4A 登录及 Session 生命周期 | B 组 + 行内：`FIELD_PENDING` |
| 真实网络→业务 API→Java 代码映射的 CodeGraph 查询及可签名证明 | A/N3 + 现场：`FIELD_PENDING` |
| N6 标准 Case 可执行契约正式生成 + N7 Mission Factory 工具路由 | A 组：`INTEGRATION_PENDING` |
| 弹窗、多页、新标签页、页面动态路由及会话恢复的完整实机覆盖 | C09 + B + 行内：`PARTIAL / FIELD_PENDING` |
| Actual/Evidence 证据索引、敏感内容安全策略、跨平台文件 URI 路径 | A/B/现场：`FIELD_PENDING` |
| 实际业务回放的两次稳定基准 + 真人审核信任源 | 行内：`FIELD_PENDING` |
| C09 当前 HEAD Linux/Windows Python 和实际浏览器回归 | 见同 HEAD GitHub Actions，不允许由历史 CI SUCCESS 代替 |
| 完整 RC7.2 + N1–N10 工程设计对账 / 现场验收 | QA 组独立判定，不能由 C09 自行宣告 |

禁止将 Fake Browser 成功回放当成真实业务 L4/L5，通过 `FIELD_VERIFIED` 或 `BANK_FINAL`。没有已经过 A/B 标准调度接线的生产真实 Case、真实截图/网络/断言和现场审批，C09 最多是工程候选。
