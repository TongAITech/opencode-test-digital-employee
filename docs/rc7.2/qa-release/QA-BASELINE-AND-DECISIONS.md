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

## 7. 四施工分支新提交初审（与主分支验收严格分开）

本轮读取到的相对 `7efb3c8` 的分支专属差异：
- **A/core** `dd3da3530cb5`，领先 15 commits。已新增正式 N10 repair/rerun 装配与真实候选测试；但是 `ReleaseBatchDriver.run` 仍缺通用 N8 非 bypass 处理。A 提供的 [证据页](https://github.com/TongAITech/opencode-test-digital-employee/blob/dd3da3530cb5/docs/rc7.2/CORE-CURRENT-CONSTRUCTION-EVIDENCE.md) 明示同源 CI 待完成及 C03/C04/C05 未闭环。Issue #7 已补充独立评论；不能提前关闭。
- **B/runtime** `8bec8aac65a7`，领先 14 commits。新增 `rc72_captain_dispatch_fencing.py`、`rc72_n7_no_effect_attestation.py` 以及权限/UNKNOWN 副作用负面测试；当时同源 Windows/Linux Python3.8/3.11 CI 均 queued。
- **C/journey** `9dd17b9caa8b`，领先 30 commits。新增 CDP 采集、Playwright 真实适配、N7 Journey Adapter、漂移/失败证据；当时相关 CI queued，未获 Q5 真银行回放/批准事实。
- **D/economy** `a39448b40879`，领先 15 commits。新增 `rc72_production_economy_ingress.py`、`rc72_production_economy_wiring.py` 与正式 CLI 接入；当时同源 source regression queued，不能声称真实 token 节省。

这些是**代码变更审计**而非工程通过判决。它们尚未合入受审主分支；QA 重新评估时需以最终主分支 HEAD 复测，不得把四组各自 PASS 直接相加当作主干全绿。

## 8. 新增 QA 交付工具（仅资格与证据导出，不改变被测生产入口）

- `tools/rc72_qa_offline_audit.py`：第三方独立的物理 Manifest/Checksum/SHA256 与 13 组载荷核对；DSH 主程序未由真实包内路径+清单+校验和证明时 HOLD。即便通过也只认证 PHYSICAL_CANDIDATE_ONLY。
- `packaging/rc7.2/QA-Q3-Q9-EVIDENCE.py`：跨 Windows/Linux、Python3.8+ 的明确路径 R1 原始证据打包，所有 Q3–Q9 保持 PENDING，输出 ZIP 和 SHA256，不会产生 Field PASS。
- `tests/test_rc72_qa_offline_payload.py`、`tests/test_rc72_qa_field_evidence.py`：测试 QA 工具本身的身份、篡改、路径逃逸、缺失 R1/DSH、重复导出保护；这些是 synthetic utility tests，不代表物理最终包的验收。
- [现场操作书](C12-Q3-Q9-VERIFY-AND-EXPORT.md)：明确完整包核验与真实目标环境、失败注入、可信审批、证据导出步骤。

此处新工具及测试须等 QA 分支同源 CI 完成才能算 **QA 工具合格**。截至本次更新，多个 PR/push QA runs 仍排队，当前 QA 明确不声称绿灯。

## 9. 第二轮独立审计：实测 CI 失败与 C12 安全补强（2026-11-04）

重新读取六个分支最新 HEAD（本快照不得替代后续实时审计）：

| 分支 | 本轮观察 SHA | 判定 |
|---|---|---|
| 主线 | 7efb3c8aa62f22629e570e3381727969524bf598 | 四组候选尚未合入 |
| A/core | 8bbf7a5ed251aa49d3860cabb1a635643a40f5aa | 已组合 N10 Repair/Rerun；通用 N8、专业 N9、终态 N10 仍未闭环 |
| B/runtime | f40187568b1aae320e205e67c798b95e152aa08a | 同源 CI 尚未核销 |
| C/journey | eec3c0eca2f55f3be05d43ebd1a082d4fa595d9a | 无完整同源工程/银行回放核销 |
| D/economy | d531923f3056c1408289197dd4664c024c628971 | 同源 CI 尚未核销 |

### 主线同 SHA Construction 作业确切失败

[run 41679951672](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/41679951672) 的 Python 3.8 job 126070654139 与 Python 3.11 job 126070654398 均获得原始日志。两套环境均报告 **1406 passed / 3 failed / 3 skipped**，不能因 workflow 外层状态刷新延迟误称 PASS。

三个失败：
1. tests/test_rc72_n10_control.py::test_controller_with_repair_provider_still_refuses_ambiguous_mapping_without_side_effect：拒绝歧义覆盖映射时发生额外 R1 写入，违反无副作用契约。
2. tests/test_rc72_native_coverage_rerun.py::test_n10_runs_fresh_full_n7_then_fresh_libra_and_closes_original_gap：KeyError: 'bundle_id'。
3. tests/test_rc72_native_coverage_rerun.py::test_cold_resume_after_fresh_n7_before_libra_never_reexecutes_business：KeyError: 'bundle_id'。

A 组候选代码已尝试修复；不同 SHA 的修复不能反推失败主线 PASS。须等待 A 组同 SHA 工程 CI、合并及新主线重新验收。QA PR 被取消/排队也不视为成功。

### C12 工具补强

tools/rc72_qa_offline_audit.py：
- Manifest 文件集合与 Checksums 集合（除 Manifest 自身）严格匹配，解压目录所有普通文件也必须在校验表里；拒绝“只对一个正确子集散列”的错误。
- 13 个目录组真实文件数、真实字节数逐组与 Inventory 声明相等；拒绝未登记驱动、虚报文件数、符号链接。依据上游打包器豁免 runtime-state、state、__pycache__、pyc、pyo 运行态文件。
- 新负面测试包含未登记文件、Manifest 隐藏文件、Inventory 伪造但重新计算全部 SHA 的情况。

packaging/rc7.2/QA-Q3-Q9-EVIDENCE.py：
- 流式拷贝时同步计算文件 SHA256/size，索引必对应 ZIP 中实际写入字节，不依赖复制前的过时摘要。
- ZIP 和 SHA256 回执排他创建，只清理自己创建的输出；拒绝覆盖已有回执。
- 增加输入在预检查与复制间变化、既有回执不可覆盖的负面测试。

**门禁依旧 HOLD**：上面是 QA 分支提交候选；未获新 QA HEAD 同源全平台 CI 实跑，未逐字节独立校验 1.45GB Artifact，也未获取行内机器真实证据。DSH 主程序真实包内物理路径尚未签收；C12、Q9、BANK_FINAL 不得放行。
