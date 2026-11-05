# RC7.2 — B/C/D → A 实际集成审计与放行顺序

> 记录时间 2026-11-04。唯一事实来源是各 PR 最新 SHA、该 SHA CI、Git diff 与真实 R1；记录时正在并行施工，**禁止把以下 SHA 当作以后一直不变的最新状态**。本文件不授权任何 `BANK_FINAL` 或现场 Q3–Q9 放行。

## 已核实源与实际结果

| 分支/任务 | 已核实 HEAD / PR | 当前同 SHA 实证 | 向 A 交付判断 |
|---|---|---|---|
| 主线 | `work/rc7.2` `4721bb57f6a5de1fdf471000030a7b043ebe71c7` | Construction `41696111099`、Q1 `41696110996`、Q2 `41696110840`、Portable `41696110932` 均 **CANCELLED** | 未获得整线成功证明 |
| A / C03-C05 | PR #10，`56b9ec3c7816517759b72c88bb4e2e3bb6c2ab61`，DRAFT | Targeted `41777021927` **SUCCESS**，Linux Python3.8/3.11 两项均绿；Construction `41777021806` 在最近检查仍 IN_PROGRESS | 可作为核心工作树，不能宣布整线通过 |
| B / C06-C07 | PR #6，`f4ca76bcc8b1433cd96ab95f002a645b9e716393`，DRAFT | Runtime `41773853707` **SUCCESS**：Win/Linux × Python3.8/3.11 四绿；继承 RC7 `41773853978` **FAILURE**：2055 passed / 5 failed / 4 skipped | **可移交集成候选，不可单独合并后直接称验收通过** |
| C / C09 第一批 | PR #11 已 MERGED，主线已有 Journey CDP/编译/候选回放 | 已在主线 `4721bb57`，但主线综合 CI 已取消 | 不得重复合并旧 PR |
| C / BSK 收尾 | PR #13，`ea6334398ca5cdf246078fedd4ad3ce6d8e5a254`，OPEN、非 DRAFT | Isolated `41776017281` **SUCCESS**：Python3.8、3.11 和实际 Chromium/CDP 三绿；RC7 全套 `41776022247` 最近仍 IN_PROGRESS | **可立即交 A 做产品接线集成**；仍缺 B 资源授权及行内 BSK/4A 真验 |
| D / C10 | PR #8 前一候选 `69f1fda7a2c0c78f1c8d61d35bf0cc4fe81d49b7`，之后新 HEAD `c829f2c4950c82f12a52474176bcd5b9c1b871c7` | 旧候选 `41777358037` 四环境 native C10 全绿，但 Integrated **FAILURE**（36 passed / 1 failed / 1 skipped），失败于真实 Chromium 提前退出的 C09 CDP smoke；**新 HEAD 同源 CI `41777578986` 尚 QUEUED** | **允许把代码交 A 做隔离集成，禁止以旧候选 CI 给新 HEAD 盖章** |
| E / 独立 QA | PR #9，施工分支 `work/rc7.2-qa-release` | C12 `41744465642` **FAILURE**：精确 main SHA 的 Portable 已取消，拒绝用旧包代替；QA 其余 run 取消 | 审计与 Gate 必须保留，不能作为已签核凭证 |

### 切勿忽略的源冲突

对 `4721bb57` 和当前 PR head 的 GitHub commit compare：

- **B 对主线 diverged：ahead 132 / behind 4**，涉及 31 文件。先同步最新 main（或确保 A 核心树显式保留这 4 个祖先提交），禁止从旧 PR 基线盲合。
- **A + B 有两个同路径改动**：`rc7_runtime/rc72_n7_pipeline.py` 与 `.github/workflows/rc7-field-hardening.yml`。A 的 `_diagnose_failure` 调用 `NativeN9ProfessionalIntakeService.queue_reproduction`；B 的 `_prepare_governed_item` 进行 `CaptainFencedWorkItemScheduler.dispatch_etu` + `ExecutionPreparationService.prepare(fenced_admission=...)`，并要求正式 `N7PipelineService.complete` 调用该入口。**必须在同一个产品 N7 类中保留两者；不可选一边覆盖另一边。**
- **B + C #13 共享 `.github/workflows/rc7-field-hardening.yml`**，A/C 也涉及该文件；工作流应该以同 HEAD 来源与必要测试集合做完整合并，不能删套件换成“绿”。
- **D 与 A/B/C 当前变更路径零交集**，故源文件相对易集成，但正式 N7 Batch+Reviewer+Token 计费、模型额度工作日/非工作日规则、N8 Retry Delta、R1 归属与冷重启需产品接线和实证。
- **C #13 与 A 的普通生产源码零交集**，但正式 Mission Factory 仍须将 `journey_bsk` 绑定到实际 `SignedN7OfficialBSKAdapter`；原 `journey_playwright` 正式适配器也不能被泛用 HTTP runner 偷换。正式 BSK 要用 B BrowserPool 的 active WRITE BrowserLease、BSK Session/Tab 与 4A 权限事实。

### 对 A 的具体集成顺序（施工，不是放行）

1. 以最新 main + A core 为唯一集成底座，重新检查最新 HEAD 和在途 CI；不要在旧 SHA 上生成搬运包。
2. 先接入 **B C06/C07** 的底层资源/授权与 Captain-fenced N7，**人工融合 A 的 N9 triage**，在真实 ReleaseBatch 主入口与 R1 冷恢复调用它；不可仅将服务文件放进仓库。
3. 追加 **C PR #13** 的 BSK 教学/回放/字段审批与受控 `journey_bsk` 的 N6→N7 签名 ToolDispatch，并复核 C09 既有 `journey_playwright` 入口、独占 BrowserLease 与 B 组会话资源接口。
4. 接入 **D PR #8** 的模型批处理/上下文与计量：保持真实 DSH WorkerInvocation、工具调用与 Case Oracle 原始路径，每个批次子 WorkItem/Attempt 独立接受 N7 Evidence Review；非工作日模型额度规则不可误当工作日限额。旧 D 失败需要诊断及新 HEAD 同源码 CI。
5. 在最终组合 HEAD **重跑** Python3.8/3.11、Windows/Linux、继承 RC7 全套、C06/C07、C09 Chromium、C10 native/integrated、C03/N8/N9/N10、独立 QA 三套 JUnit、真实 Portable/Q2。任何失败都是 BLOCKER 而非可忽略“已有组件绿色”。
6. Q3–Q9 行内真实信创 Linux、Win10、BSK/4A、真实业务 Oracle、92% 增量覆盖、缺陷复现/定位/修复回归、真实用户审批及完整 Evidence 仍需要单独证明；`BANK_FINAL=NO`。

### QA 保护性测试

QA 已提交 `tests/test_rc72_qa_bcd_core_integration.py` 至 PR #9，在正式工厂产品路径上检查 A/B 对 `N7PipelineService` 的互相保留及 `journey_bsk` 签名 N7 适配器。它是 **必要产品接线门禁**，不是字段审批或自动验收。当前主线预计 RED，只有 A 完成接线后才应通过。

### 检查指令

- [B Runtime PR #6](https://github.com/TongAITech/opencode-test-digital-employee/pull/6) / [C BSK PR #13](https://github.com/TongAITech/opencode-test-digital-employee/pull/13) / [D Economy PR #8](https://github.com/TongAITech/opencode-test-digital-employee/pull/8)
- [A Core PR #10](https://github.com/TongAITech/opencode-test-digital-employee/pull/10) / [E QA PR #9](https://github.com/TongAITech/opencode-test-digital-employee/pull/9)
