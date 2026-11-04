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


## 6. 2026-11-04 续施工：Case 谱系、动作中资源撤销、弹窗及崩溃恢复

新增真实工程闭环测试：`tests/test_rc72_journey_full_chain_engineering.py`，从教学（包含事件、网络/页面/截图真实文件引用）→非正式候选→两个分别分配 WRITE 租约的真实适配器回放 Attempt→基准结果→真人 Field 审批拒绝关口。测试使用 CI Fake CDP Browser：它验证模块之间的**调用、状态和 R1 Evidence 链路**，而非证明行内 Chromium/BSK 执行成功。基准工程通过但 `field_benchmark_verified=False`，不能制造 Official Journey。

落地约束继续收紧：

- 教学时从 WorkItemAttemptBinding 和 ETU `case_ids` 决定 Case ID；新的录制、Candidate、Official Journey、Replay/Execution 收据完整携带，并在实际工作绑定时核对。读取历史缺少 `case_id` 的资产只为向后兼容，不赋予通过新 Case Gate 的权限。
- `JourneyReplayService` 和 `OfficialJourneyExecutionService` 在**每一步业务动作之前和之后**确认 WRITE BrowserLease，不能因适配器（包括 CONTRACT_BROWSER）自报 PASS 而越过租约失效；截图也不得在所有权撤销后继续执行。
- 4A/AuthKeeper、Teaching、Replay、Official L4/L5 通过 BrowserLease `purpose` 分离，身份/Attempt 恰好相同也不能借用其他业务用途租约。
- 同一候选或正式资产如果存在 `STARTED` 且进程崩溃的回放/执行，视为副作用 `UNKNOWN`，**禁止更换 replay/execution ID 或 Attempt 偷偷重放**；交给 N8/B 组实证诊断、租约回收与新冻结契约后续执行。不能自行将中断记录改成 PASS。
- `dialog_policy_ref` 从教学保留至不可变 Journey IR；期望 Confirm/Alert 等弹窗必须经显式引用解析批准。缺少策略的弹窗被关闭并记真实失败，不能默许继续业务流程。WAIT `visible` 缺少定位信息应失败而非 PASS。
- `tests/test_rc72_journey_drift_and_failure.py` 新增中断冷恢复、Case 混绑、AuthKeeper 用途隔离以及通用模拟适配器中途撤销租约正反测试；`tests/test_rc72_journey_playwright_adapter.py` 增加弹窗/明确等待策略的可重复合同测试。

仍未解决：

1. 录制快速跨页面导航时，点击前 DOM/截图与跳转后页面可能错位。真实 BSK/Chromium 现场演练必须证明事件时间戳与截图一致，不能凭 CI FakePage 推断支持跨页动态教学。若现场不一致应标记 `JOURNEY_TEACHING_CAPTURE_INCONSISTENT` 并重新采集。
2. N7 标准 Tool Dispatch 调用和其正式 Case Oracle/清理、N8 诊断的产品接线属于 A 组；本分支提供受控 Callable，并不自行改共享 Mission Factory。
3. 行内真实 4A/BSK/CDP、Profile、弹窗、安全输入与多窗口页面控制，仍保持 `FIELD_PENDING`，需要 B 组和现场环境验证。
4. Source HEAD 同 SHA Windows/Linux/Python3.8/3.11 CI 未全绿之前，C09 不可核销为 `CODE_COMPLETE_CI_PASS`。



## 7. 2026-11-04 定向可靠性加固（续施工）

### 工程证明与核销界限

本分支完成以下真实代码改造和定向失败注入测试；**截至本条记录，最新 SHA 的 GitHub Actions 尚未获得完成结论，以下仅代表“已提交待运行”，不代表测试通过**：

1. **教学操作事件不丢失**：`JourneyCDPTeachingRecorder.poll()` 保留 Playwright binding 和 DOM 队列中的全部动作直至对应 R1 记录成功提交；每批执行前一次性验证类型、元素定位、INPUT/SELECT 引用，后续任何截图/绑定错误都不得被吞掉。 `record_assertion`、`record_wait` 和 `finish` 若检测到未消费事件或页面跳转先拒绝提交，维护真实 `CLICK→WAIT→ASSERT` 语义顺序。
2. **N7 入场前完整验证**：`SignedN7OfficialJourneyAdapter.preflight()` 在共享 `SignedToolDispatchService` 写入 `IN_FLIGHT` 前完成 BrowserLease Purpose=OFFICIAL_JOURNEY_EXECUTION 的 ACTIVE WRITE 检查、ETU/Case/WorkItem/Official Asset 线性校验、相同 Attempt 禁重入、历史 `STARTED` 副作用 UNKNOWN 的恢复阻断。
3. **正式资产不可原地篡改**：`rc72_official_journey_asset` 只允许 `artifact_version=1`；改 Oracle、Locator、Steps、审批标识，不能通过 `version=2` 伪装新审批。合法变更须再次进行 Candidate→Replay→Field Benchmark→Human Review，再铸造**新 Official Asset ID**；漂移报告独立 R1 实体，不重写既有审批资产。
4. **CI 失败注入覆盖**：包含未消费点击就完成教学、批量事件后项缺少 ValueRef、人工 ASSERT 越过点击、导航未被观测就插 WAIT、N7 错误浏览器用途/WorkItem、审批资产 Oracle 修改等测试。

### 最新 C09 放行所需客观证据

- 最新 Journey HEAD 的隔离 CI Python 3.8/3.11 双绿，和 Windows/Linux RC7 继承回归在同 SHA PASS（不得使用历史 SHA 结果）。
- A 组标准产品运行器接入 `journey_playwright` 路由，使用冻结 N6 Contract+真实 N7 ToolDispatch，提供合法和越权的反向日志、正式 Case Oracle 结果与 Evidence。
- B 组真实隔离浏览器/CDP/BSK/4A、人工教学的跨页事件与截图顺序、Token 不泄漏、租约中途失效，以及 Win10/目标信创 Linux 双平台离线 smoke Evidence。
- 现场正式 Benchmark 的独立两次以上真实 PASS、真人审批签批与范围 Hash；只有这样的资产才可从 `FIELD_PENDING` 升级，不能使用 FakeBrowser/CONTRACT_BROWSER 测试身份冒充 Field。


## 2026-11-04 C09 架构修订：BrowserSkill 原生优先

用户指出：行内 RC7.2 已有 BrowserSkill（BSK），不能默认以自制 CDP/Playwright 取代浏览器主执行器。本修订不删除旧 CDP 诊断能力，但将它降为受控补充。绝不因为 BSK 操作失败就自动切 CDP 重试业务副作用。

### BSK-first 实现及来源

- rc7_runtime/rc72_journey_bsk_import.py：消费原生 BSK debug stop/export 的 DebugRecording v1，human/agent 操作按顺序导入 R1。要求录制已停止、无丢失与覆盖缺口、稳定 CSS/testid、逐操作 DOM/PNG 实物证据；请求窗口关联不是业务因果证明，不能从 HTTP 200 推断 Oracle PASS。输出 Candidate 不可直接执行。
- rc7_runtime/rc72_journey_bsk.py：BSK-native Replay/Official 适配器；B 组提供 BrowserInstance、4A 和独占 BrowserLease 已绑定的 BSK Session，逐步调用 bsk step/evaluate/screenshot 并核对实际结果。命令退出 0 仍可能带 evaluate ok=false；失败/证据丢失/结果未知一律 FAILED，禁止自动重试；CredentialRef 不可通过 CLI argv 传播，应交 DSH 原生 bsk_* 工具。
- rc7_runtime/rc72_journey_n7_adapter.py：SignedN7OfficialBSKAdapter（journey_bsk），沿用签名 N7、Human Field approval 和 ETU/Case/Attempt/Lease 门槛；A 组须将 journey_bsk 映射到正式产品工具路由，不可用测试回调代替。
- rc72_journey_playwright.py 与 rc72_journey_cdp_capture.py：仅保留明确授权的补充诊断/证据场景；不应默认作为 BSK 替代执行器。

### A / B / E 组交付契约

1. A（唯一集成负责人）：从最新 work/rc7.2 HEAD 集成 C09 BSK 收尾 PR；在真正的 N6→N7 ToolDispatch adapters 注册 journey_bsk；保留单次执行、修复回边及 R1 Gate，按最终 SHA 构建完整 Windows 离线包。
2. B（Browser/Session 负责人）：验证本地 bsk.exe、扩展及 DSH BrowserSkill 插件匹配；使用 bsk --version、bsk status、bsk doctor、DSH bsk_* 工具发现和实际 UI 调用多重实测。通过明确的 --browser 实例选择/SessionResolver 绑定 BrowserLease、4A、任务 Attempt。禁止把 bsk_endpoint 字符串当成已经授权的 Session。
3. C（本会话）：BSK DebugRecording → R1 Candidate → Compiler 和 BSK step/evaluate/screenshot → Actual/PNG 的实现、正反测试、失败证据与移交。BSK Network Oracle 对请求时间窗口的错误因果归因暂 fail-closed，需通过 BSK native debug Operation/Request + 独立业务状态核验。
4. E（独立 QA）：同 HEAD Python3.8/3.11、Windows/Linux、真 BSK + DSH 插件 / 4A / 人工审批、Case/ETU/Attempt、R1 PNG/Network/失败恢复、整包 SHA 与冷解压验收；既有 mock/Chromium/CDP 测试不得替代 BSK Field 证据。

### 行内 BSK 教学验收操作顺序（仅用现有版本支持的命令）

- 明确 BSK 浏览器实例，开启授权 Session；先做 cooperate sync，按 BSK 实际协议获得 Context/Observation；debug start 必须早于教学的导航或点击。
- 在授权标签页真人/Agent 操作；按操作收集 observe/HTML/截图的物理证据；debug operations 能标明 human/agent source，debug export 不代表 Human Field 审批。
- debug stop、debug export --output 路径，留存导出 JSON；转换器校验操作与截图，形成 Candidate；再经独立回放和 Benchmark 与真人审批后才允许正式 N7 消费。
- BSK session stop 必须由拥有 Session 生命周期的 B 组控制器执行，且不能隐式复用别的 Worker 会话。

状态仍为 ENGINEERING_CANDIDATE、PRODUCT_INTEGRATION_PENDING、FIELD_PENDING。用户要完整行内搬运包，应由 A 统一合入后构建；本 C09 PR 只交付责任范围代码与测试。
