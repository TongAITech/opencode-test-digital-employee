# RC7.2 独立验收基线与门禁判定（第 1 轮）

> 审计日期 2026-11-04；**本轮审计目标 SHA `7efb3c8aa62f22629e570e3381727969524bf598`**（`work/rc7.2`）。QA 分支基于该 SHA，另加仅 QA 测试、CI 和文档。下一轮任何生产变更，必须重新读最新分支 HEAD、同 HEAD CI、R1/Evidence；本文件中的 SHA 不应外推到未来。

## 1. 独立结论（红灯）

- **设计实现率：不发布。** `DESIGN-CLAUSE-AUDIT-BASELINE.csv` 已建立 **95 条独立核查单元**：Phase 0–10（11）、GAP 01–08（8）、CT 01–26（26）、C01–C12（12）、N1–N10（10）、Q1–Q9（9）、跨域专题（19）。**没有冻结条款权重**，既不报 96% 也不报 60%。
- 初审矩阵的 `adjudicated_status` 是**严格准入结论**：同 HEAD 未独立复核通过、未拿到 R1 或缺完整产品入口的条款标 `BLOCKED`，不是“没有代码”。`production_code` / `contract_test_candidates` 仅为路径定位，不是测试 PASS。
- Q2 独立单元具有同源成功的 Windows clean-unpack 与 R1/session/Git Bash 工程作业，允许 **ENGINEERING_VERIFIED（仅 Q2 工程范围）**。其它 94 个单元暂 HOLD / BLOCKED（含正在运行的 CI），绝不由静态文件存在上升到 COMPONENT_TESTED。
- **C01/C02 仅组件路径候选，正式产品链路不通过**；**C05/C08 P0 阻断**；**C11 未结束**；**C12 仍为工程候选，BANK_FINAL=NO**。

## 2. GitHub 同源检查快照

| 检查 | exact run | 本轮第一次检查结论 | 能证明什么 |
|---|---|---|---|
| RC7 inherited regression, Python3.8 | [41679951672](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/41679951672) | SUCCESS | 继承回归检查局部通过 |
| Phase contract, Python3.8/3.11 | [41679951672](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/41679951672) | IN_PROGRESS | **不能核销 C11** |
| Windows/Linux source platform | [41679951422](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/41679951422) | IN_PROGRESS | **不能核销 Q1**；Ubuntu 不代替目标信创 Linux |
| Windows Q2A/Q2B | [41679951380](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/41679951380) | SUCCESS | 已获 Q2A 包身份、Q2B R1/session/Git Bash 工程证据 |
| Portable physical candidate | [41679951113](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/41679951113) | SUCCESS | 仅候选构建及工程模拟，**不是 C12/BANK_FINAL** |

Portable run 生成 Artifact ID `13253451722`，GitHub Artifact 尺寸 `1,457,448,714` 字节（由 API 获取）。本轮未独立下载、逐字节散列该完整 Artifact，也未在行内机器解压启动；不能将工具日志中约定的 `status=PASS` 当成现场业务证明。Q2 日志中存在工程模拟 R1 Session A→B→C；这与真实银行 ReleaseBatch 的全链路 R1 不同。

## 3. C01/C02 逐项核销

| 原子验收 | 已核对的代码/测试 | 初审 |
|---|---|---|
| N5 对同一 DataRef 的物理修复 | `rc72_n5_existing_data_repair.py::prepare`；`test_rc72_n5_existing_data_repair.py::test_actual_physical_preparation_then_distinct_verifier_renews_whole_n5` | 真实本地 HTTP 工程场景有检查，非银行现场；同源独立复跑待完成 |
| 独立 DataVerifier 与新 N5 Gate | `rc72_n5_existing_data_repair.py::run`、`rc72_n5_completion.py`；`test_rc72_n5_reverification.py` | 代码/专用测试存在；审批证据须按真实字节复核 |
| N6 重新编译完整 Case | `rc72_n8_retry_continuation.py::reconcile/_compile`、`rc72_n6_pipeline.py`；`test_rc72_n8_retry_continuation.py` | 局部工程路径存在；缺产品入口 N8 路由 |
| 新签名 Attempt、旧失败不覆盖 | `rc72_n8_retry_continuation.py::prepare_replacement`；`test_rc72_n8_multi_round.py` | 旧失败/新代际关系已有工程测试；独立复核未通过前不核销 |
| 冷恢复不重复物理修复/业务调用 | `test_rc72_n8_multi_round.py::test_second_round_cold_roll_forward_keeps_original_member_and_no_duplicate_actions` | 组件场景候选，非完整产品重启证明 |
| 验证证据篡改/权限过期拒绝 | `test_rc72_n5_existing_data_repair.py`、`test_rc72_n8_retry_continuation.py`、本 QA `test_rc72_qa_c01_c02_independent.py` | QA 新增独立断言，待 CI |

**重要：**上述局部组件路径由测试本身组装，不等价于 `Mission → ReleaseBatchDriver.run` 自主调用。对用户可用功能判断要求正式入口集成。

## 4. P0：正式产品组合缺少关键路径

Issue: [#7 — N8/N10 formal product wiring absent](https://github.com/TongAITech/opencode-test-digital-employee/issues/7)。

- [`rc72_mission_factory.py#L123-L150`](https://github.com/TongAITech/opencode-test-digital-employee/blob/7efb3c8aa62f22629e570e3381727969524bf598/rc7_runtime/rc72_mission_factory.py#L123-L150) 创建 `NativeN10ControlService(expected,n9,measurement,intake,diagnosis)`，未接 `NativeCoverageRepairService`、`NativeCoverageRerunService`。
- [`rc72_release_driver.py#L251-L355`](https://github.com/TongAITech/opencode-test-digital-employee/blob/7efb3c8aa62f22629e570e3381727969524bf598/rc7_runtime/rc72_release_driver.py#L251-L355) 的正式 `run` 主循环没有非 bypass N8 的完成分支，进入 `NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED` HOLD。
- QA 新增 `test_rc72_qa_product_wiring.py` 作为**预期红灯**；仅由 A 修复正式生产连接后可以变绿。禁止 QA 修改 A 组生产入口或删除测试来求绿灯。

## 5. C12 可搬运性与现场边界

[物理库存代码](https://github.com/TongAITech/opencode-test-digital-employee/blob/7efb3c8aa62f22629e570e3381727969524bf598/rc7_release/rc72_complete_payload_inventory.py) 定义 13 个携带组：`python`、`node`、`node-execution`、`browser`、`code-intelligence`、`java`、`maven`、`maven-repository`、`allure`、`k6`、`zap`、`ripgrep`、`dsh-plugins`。当前提交的 [TRANSPORT-README](https://github.com/TongAITech/opencode-test-digital-employee/blob/7efb3c8aa62f22629e570e3381727969524bf598/packaging/rc7.2/TRANSPORT-README.md) 明确将**银行 DSH 主程序、Git Bash、模型账号及业务连接**列为现场绑定，不是完全自包含的免安装载荷。用户要求继承 RC7.1 完整能力并交付 DSH 与插件；其等价性/现场批准替代策略必须明确核销，不可把插件目录冒充 DSH 主程序。

Python/Node/Java/Maven/Chromium/BSK/CodeGraph/k6/ZAP/Allure/rg 的工程日志证据仍需绑定同一最终源 SHA、最终完整 ZIP、独立 SHA256、解压目录与启动工作记录。OCR/CV 的真实能力通过包内 Python 调用验收；不能只凭 Python 文件夹存在。Windows clean-unpack Git Bash 工程检查不代表目标信创 Linux 启动；Q3 必须独立给目标发行版/架构证据。Q4–Q9 必须有真实线下作业证据，Q9 在此之前不可承认。

## 6. 交接与停机条件

1. A：先修 #7 正式 N8 语义回边与 N10 覆盖修复/重执行组合，补同 HEAD 正向、拒绝、冷恢复真实业务 I/O 与 R1 Evidence。
2. B：回报 AgentTeams/Worker/Session/Lease 跨进程冲突与接管、失败注入、现场权限证明。
3. C：回报真 BSK/CDP 教学与回放、人工批准、正式 L4/L5 消费证据。
4. D：回报真实 provider usage/UNKNOWN，经济策略不得删 TestObligations、签名批谱系、上下文最小化实测。
5. QA：独立复跑 A–D 新 HEAD，核对完整分母/权重；验收 Q1/Q2、准备 Q3–Q9 所需验收和证据导出工具；同源全部通过之前，不宣布最终包，亦不把此 PR 当作 release authorization。

**当前决定：DESIGN_INCOMPLETE / C01_C02_NOT_CLOSED / Q9_NO / BANK_FINAL_NO / NO_FINAL_DELIVERY。**
