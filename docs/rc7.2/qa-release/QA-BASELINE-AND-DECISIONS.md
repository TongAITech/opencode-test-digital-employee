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


## 10. 同源 check-runs 独立刷新（2026-11-03 09:51 PST）

再次直接查询 GitHub 当前 branch HEAD 与 **commit SHA 精确匹配**的 check-runs（不能用不同分支或旧 run 的成功替代）：

- 主线 `work/rc7.2` = `7efb3c8aa62f22629e570e3381727969524bf598`；同 SHA `phase-contract-python-3.8` **FAILURE**、`phase-contract-python-3.11` **FAILURE**、`q1-linux-engineering-proxy-python-3.8` **FAILURE**；`q1-windows-engineering-python-3.8` **IN_PROGRESS**。
- 同 SHA `inherited-rc7-regression-python-3.8`、`q2a-windows-clean-unpack-python-3.8`、`q2b-windows-r1-session-gitbash-python-3.8`、`portable-transport` 为 **SUCCESS**，仅各自受限工程范围有效。此处更正本文件第 2 节早期快照的 IN_PROGRESS 状态；主线整体仍 **FAIL**。
- QA PR #9 的 head = `e68630d3dc3629f84cd70552255bd84b6b852026`，该 SHA 的 Windows 2022 / Ubuntu 22.04 × Python 3.8/3.11 QA checks 均 **QUEUED**；不能晋级独立 QA PASS。
- 四个未合入的候选 head：core `83cbd795d4d1ecc8b2b1483219e87fa1446deec0`；runtime `d21f5606931f8027c9b350514439d1a1cd748513`；journey `0bc08d7f8a9693609a52a9c22a60040465a03073`；economy `e6b836ec9f455a758c15c7fd61f236f24d8ba482`。其 CI 在本次读取时仍排队，不可跨 SHA 采信。
- P0 Issue #7 仍 **OPEN**；正式 N8/N10 生产接线缺口在主线仍成立。QA 不修改生产代码、不合并 PR、不消除红灯。

**本轮门禁**：C01/C02 = BLOCKED_PRODUCT_INTEGRATION；C11 = BLOCKED_SAME_SHA_CI；C12 = HOLD_FIELD_AND_FULL_PAYLOAD; Q1 = FAIL；Q2 = ENGINEERING_VERIFIED_SCOPE_ONLY；Q3–Q9 = PENDING。95 项权重未冻结，不发布百分比；BANK_FINAL = NO。

本段是同源 GitHub 检查的即时观察，不是银行现场 R1/Evidence 的新增签收。待当前 QA check-runs 完成后应按结果刷新，不得以 QUEUED 代替执行成功。

## 11. 第三轮 QA 独立防误放行验收补强（2026-11-04）

**基准仍为 work/rc7.2 @ 7efb3c8aa62f22629e570e3381727969524bf598；主线 Construction CI #41679951672 最终 FAILURE。** A/B/C/D 开发分支的新代码不是已集成主线的事实，QA CI 没有同 SHA 完成证据之前不得升级任何条款状态。

### C12 身份、路径和只读边界

本轮将完全独立于被测生产打包器的工具 tools/rc72_qa_offline_audit.py 加入严格的 RC7.2 身份核对：

1. SOURCE_COMMIT、BUILD_ID、RELEASE_FAMILY、RELEASE_STATUS、RC72_RELEASE_IDENTITY.json、PACKAGE_MANIFEST.json、FULL-CAPABILITY-INVENTORY.json 七个身份对象不得相互矛盾。Manifest 和 Release Identity 的 schema、source、build、包名、ReleaseBatch/N1–N10 控制骨架与字段 false 状态必须符合实际 RC7.2 工程候选契约。
2. BANK_FINAL、Field、real_mission_pass、delivery_pass、bank_field_pass 不允许伪造成真。畸形 JSON、Manifest 大小/hash 类型也必须报显式 FAIL。
3. 审计参数 --report 不得写进受审包或覆盖已有外部回执，否则独立“只读审计”本身会污染包的哈希。
4. --dsh-relpath **不能指向任意已列入清单的文件**；仅允许包内 runtime/dsh/dsh.exe 或 runtime/dsh/dsh 的原生可执行头及基本大小检查。这仍只是物理“可执行外观”证据，绝不构成 DSH 真启动、真实版本或银行模型接通的资格；还需另行执行、校验实际来源与运行日志。

### Q3–Q9 证据 ZIP 闭环的“反向验证”

packaging/rc7.2/QA-Q3-Q9-EVIDENCE.py 新增 --verify-archive 只读命令：
- 对 ZIP 本体、外置 .sha256 回执、ZIP 中每个 payload 的真实 SHA256/size、全覆盖成员集、Source/Build/Release 身份和非空 R1 逐一验收；
- 拒绝伪造 Q3–Q8 验收标签、Q9=BANK_FINAL、额外/重复/危险 ZIP 文件、索引欺骗；
- 负面测试直接篡改 R1 或索引并重算外层 ZIP 收据，保证校验不是只看一个 SHA。
- 成功结果仅能是 EVIDENCE_COPY_INTEGRITY_ONLY，**不自动升格 R1 业务真实性、Human Gate、Field Verified 或银行最终放行**。

### 未关闭的硬门禁

- A/core 仍需在真实 ReleaseBatchDriver.run 接入通用非 bypass N8、专业 N9 缺陷处理与最终 N10 收敛；N10 Repair/Rerun 工厂装配不能单独核销 C03/C04/C05/C08。
- Q3 目标信创 Linux、Q4 离线、Q5 CDP、Q6 真审批、Q7 全链路 ReleaseBatch、Q8 故障/冷恢复、Q9 银行现场签收全部缺实际行内 Evidence。
- **QA 验收工具新补强均为 GitHub 提交候选。GitHub Actions 排队时只能报 CI_PENDING，不能报 PASS。**


## 12. 第四轮：Q1 原始失败日志与正式 N8 产品门禁

2026-11-04 从 **同一主线提交 `7efb3c8aa62f22629e570e3381727969524bf598`** 重新检索 [Q1 run #41679951422](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/41679951422) 的 `q1-linux-engineering-proxy-python-3.8` 作业 `126071464041` 原始日志。Linux 最后明确 `RC72_BOUNDED_PYTEST_RESULT::FAIL::count=2`：`tests/test_rc72_n10_control.py` 有 1 failed/4 passed，`tests/test_rc72_native_coverage_rerun.py` 有 2 failed/1 passed（计 2 个失败测试文件、3 个失败用例）。Q1 Windows 作业 `126071463528` 在核查时仍 IN_PROGRESS；不可合并推算出全平台通过。

同 SHA [Construction run #41679951672](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/41679951672) 已确认为 FAILURE，两组 Python3.8/3.11 均为 1406 passed、3 failed、3 skipped。Q1 Linux 与 Construction 原始失败相互佐证；这仍只是当前老主线，不替代 A 组不同 SHA 候选后续同源 CI。

### C03/N8 产品入口新增必要回归门禁

QA 的 `tests/test_rc72_qa_product_wiring.py` 新增 **必要条件性质**的 `test_qa_release_driver_has_an_owned_non_bypass_n8_product_execution_route`：校验正式 `ReleaseBatchDriver.run` 是否在非 bypass N8 路径执行 `complete/run/dispatch/resume/reconcile` 的实际服务调用，而不是仅对已通过 N7 的 N8 进行跳过，也不能默认 `NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED`。此测试在受审主线**预期为 RED**，用于持续阻止 C03 仅凭模块存在被提前核销。它是静态入口门禁，不是端到端执行成功证据；修复后仍需新 HTTP SUT/真实 provider 的错误分类、人工 Gate、R1 签名、冷恢复以及原业务副作用断言。

### Q3–Q9 导出反向校验新增一致性

独立 `--verify-archive` 现同时解析 ZIP 内 `PACKAGE_MANIFEST.json` 和 `FULL-CAPABILITY-INVENTORY.json` 的限长 JSON，要求 source/build/release/status 与 ZIP 收据、索引、SOURCE_COMMIT 完全一致；虚假 `BANK_FINAL`、`real_mission_pass`、`delivery_pass`、`bank_field_pass` 必须被拒绝。增加 ZIP SHA 正确但内嵌 Manifest/Inventory 伪造源提交、状态的负面测试。该验证仍仅说明**拷贝字节与身份互相一致**，不等于 Field Gate 或 R1 业务真值成立。

**当前验收判定不变：Q1=FAIL，C01/C02/C03/C11/C12=HOLD，Q3–Q9=NO FIELD EVIDENCE，BANK_FINAL=NO。** QA 本轮新增测试/工具仍需最新 QA HEAD CI 真正运行后逐项核销。

## 13. 第五轮核查：Q1 双平台最终失败及证据回执必备身份（2026-11-04）

独立复读 [主线 Q1 同 SHA 41679951422](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/41679951422) 的最终 check-runs：`q1-windows-engineering-python-3.8` 作业 `126071463528` **FAILURE**、`q1-linux-engineering-proxy-python-3.8` 作业 `126071464041` **FAILURE**；总 workflow 为 FAILURE，Q1 总结作业 SKIPPED。两端日志均出现 `test_rc72_n10_control.py` 1 failed / 4 passed，`test_rc72_native_coverage_rerun.py` 2 failed / 1 passed，即两个相同的失败测试文件、各三条失败测试。不能把 Q2 Windows package pass、主线独立 package 准备 PASS 当作 Q1 平台验收通过。两端都是 GitHub 工程 runner，**目标信创 Linux 仍未实测**。

Q3–Q9 QA 证据导出器做了更强的**必备来源集合**与 **canonical R1** 校验：

1. 新增 `RELEASE_STATUS`、`RC72_RELEASE_IDENTITY.json` 为强制出口文件，并由复核端从 ZIP 内解析；须对应同一 SHA/Build ID、固定 RC7.2 包名、ReleaseBatch 业务根、N1–N10 语义骨架，且 `field_verified=false`、`bank_final=false`。
2. `--r1-relpath` 不得以现场附件冒充 R1；索引 `r1_event_stream` 必须等于 `runtime-state/r1/event-stream.jsonl`。R1 的连续事件序号与 JSONL 结构仍只是结构门禁，不能等价为业务真实性。
3. 验证 INDEX 中 `R1_EVENT_STREAM`、`PACKAGE_IDENTITY`、`EXPLICIT_FIELD_ATTACHMENT` 与实际文件类别一致；对篡改后重算整个 ZIP SHA256 的负面用例同样拒绝。
4. QA GitHub workflow 的 C12 工具套件与 C01/C02 产品测试套件现在不会因其中一个测试失败而跳过另一个测试，分别上传 JUnit 结果；明确 FAIL 的真实内容比错误的整体 PASS 重要。

**当前结论：Q1=FAIL（Windows+Linux 工程代理均 FAIL），QA HEAD CI=AWAITING COMPLETION，C03/正式 N8 仍 BLOCKED_PRODUCT_INTEGRATION；Q3–Q9=FIELD_PENDING；BANK_FINAL=NO。** 不更新已冻结的 95 条权重成虚构百分比。

## 14. 第六轮：证据身份完整集合、R1 防替换与 CI 去重

最新 QA 施工收窄了 Q3–Q9 原始 Evidence 的导出边界，全部限定为 **证据拷贝/结构审计**，不改变被测产品代码：

- 现场证据必须包含 `SOURCE_COMMIT`、`BUILD_ID`、`RELEASE_FAMILY`、`RELEASE_STATUS`、`RC72_RELEASE_IDENTITY.json`、`PACKAGE_MANIFEST.json`、`CHECKSUMS.sha256`、`FULL-CAPABILITY-INVENTORY.json` 和真正的 canonical `runtime-state/r1/event-stream.jsonl`；若包身份、业务根、R1 索引、Manifest 或 Inventory 不一致，反向验证必须失败。
- ZIP INDEX 的 `kind` 必须与 R1/包身份/现场附件真实类别一致；即使有人修改 ZIP 并生成一张新 SHA256 回执，也不能使被重新标记的附件自动成为 R1。
- 独立 QA 产品入口增加 **N10 全 PASS 后不可无条件返回 `RELEASE_CONVERGENCE_AUDIT_REQUIRED` HOLD** 的必要条件测试；同时保留非 bypass N8 真实服务入口测试。二者只是阻止缺口被误报完成的静态门禁，并非端到端执行合格证明。
- CI 优化：原先 QA 分支每个提交同时创建 `push` 与 `pull_request` 两个相同四平台矩阵，易造成重复排队与持续取消。QA 分支已有 draft PR #9，现统一使用 `pull_request` + 按需 `workflow_dispatch`，**每 SHA 只需一套 Windows/Ubuntu × Python3.8/3.11 的正式 QA 矩阵**，不减少测试维度。C12 工具测试与 C01/C02 产品测试分别执行和留存 JUnit，任何一组失败均阻断最终放行。

实际 R1 业务断言、DSH 主程序启动、目标信创 Linux、真实 Q3–Q9 现场批准未核销，`BANK_FINAL=NO`。**QA CI 当前仍在排队，任何新增测试不能自行被标记 PASS**。

## 15. 新主线精确同源 QA 同步与 N8 二阶段独立检查（2026-11-04）

本节是**新快照**，不覆盖第 1–14 节针对旧 `7efb3c8a` 主线所记录的原始失败日志；旧失败无法自动推定新主线同 SHA 也失败，也不能自动判定修复成功。

- 主线 `work/rc7.2` 更新到 `af701d69eb4111cb2b11ce915af845c07521a1f8`，相对旧基线 3 个提交，仅修改 `rc7_runtime/rc72_native_coverage_rerun.py`、`tests/test_rc72_n10_control.py`、`tests/test_rc72_native_coverage_rerun.py`；新主线 Construction/Q1 作业在初审时均 **QUEUED**，尚无同 SHA 合格报告。
- 通过 GitHub Git Tree 的 3 个实际主线 blob SHA 重建了**无冲突合并树**，新增双父提交 `445c5d8b440f5eb58c6dd53f850cb105e9097287`，父提交依次为 QA `df5d461263b3fb8d3d0c0af38d7dd68ec6c30bc6` 与主线 `af701d69eb4111cb2b11ce915af845c07521a1f8`。通过 `update_ref(expected_sha=旧 QA HEAD, force=false)` CAS 方式前进 QA 分支，未强制推送、未覆盖 QA 文件。合并后的三个源/测试文件 Blob SHA 已与新主线逐字节对应，QA workflow/产品验收测试/证据出口文件仍保持旧 QA Blob SHA。
- GitHub PR 的 `pull_request` 事件默认 checkout 可能落在临时 merge ref，而不是 PR head。QA 工作流现显式 checkout `github.event.pull_request.head.sha`，执行 `git rev-parse HEAD` 相等性断言，输出 `qa-source-identity.txt` 记录准确 QA HEAD 与触发时的 PR Base SHA，随分平台 JUnit 上传。**验证源一定要由真实 checkout 得出，不以 PR 可合并或 Actions RUN 有编号作为执行成功证明**。
- A/core 在本轮先新增 `rc72_n8_product_recovery.py` 而未接入正式入口；随后其候选分支已将 `NativeN8ProductRecoveryService(n7)` 装入工厂，并在 `ReleaseBatchDriver.run` 增设 N8 非 bypass 路径。QA 添加两个必要检查：正式工厂必须拥有**具体原生 N8 类型**且与 N7、诊断、修复、R1 共享身份；正式 Driver 在 N8 不走 bypass 时必须调用原生服务。这是 **A 分支候选接线改善**，不等于主线集成、错误分类完整、真实 SUT 操作正确或 Q7/Q9 Field 通过。

**本轮门禁：主线新 HEAD 工程 CI=QUEUED（不能用旧 `7efb3c8` 的 FAIL 或 Q2 PASS 冒名）；QA HEAD CI=QUEUED；C03=BRANCH_CANDIDATE_UNVERIFIED；C11/C12=HOLD；Q3–Q9=FIELD_PENDING；BANK_FINAL=NO。** 需要等独立 QA、A/B/C/D 产品 CI 同一源码及现场实证后再逐条对账。

## 16. 第七轮：C09 首次合入后独立产品入口复核与真实 Git 源祖先门禁（2026-11-04）

### 基线变化与无覆盖 QA 同步

本轮核实主线新 HEAD `4721bb57f6a5de1fdf471000030a7b043ebe71c7`：从 `af701d69` 前进 1 个合入提交，新增/修改 23 个 Journey 模块、C09 测试、文档与独立 CI 文件。新 C09 提交与 QA 的 13 个专属改动路径 **零交集**。使用主线 23 个真实 Git Blob 合并至 QA 原树，创建双父合并提交 `2876d3a02125b253db3041a04741934995c010db`，父提交为原 QA `e33f8008d2a511ba499dcf6f7a4527c138b0347e` 与新主线 `4721bb57...`，通过 `update_ref(expected_sha=旧QA,force=false)` 前进，**未强制推送、未覆盖 QA 文件**。最新 QA HEAD 每次再查，不沿用这份文字里的旧 SHA。

### QA 同源资格：不再将旧设计表当作当前 HEAD

新增 `tools/rc72_qa_source_provenance.py` + `tests/test_rc72_qa_source_provenance.py`，实质验证：
1. `git rev-parse HEAD` 等于 PR 明确声明的 QA Head SHA（不接受 GitHub PR 临时合并 SHA）；
2. `git merge-base --is-ancestor <目标main SHA> HEAD` 为真，证明 QA 包含当前拟验收的目标主线；
3. 历史 95 条设计分母 CSV 仅允许一个冻结来源 SHA，且其源码提交必须是**目标主线的祖先**，不能把历史快照误写成最新主线绿灯；
4. 负面测试用本地临时 Git 仓库真实构造“伪造 HEAD、不同支线、台账旧基线不属于主线、分母丢失”等，全部必须拒绝。
5. QA GitHub workflow 检出完整 Git 历史，并在跑产品或工具测试之前执行祖先门禁；每个 Windows/Ubuntu × Python3.8/3.11 作业将 `qa-source-identity.txt` 与 `qa-source-provenance.json` 和不同 JUnit 一起归档。手动运行须明确输入目标主线的 40 位 SHA。通过结果只表示 `SOURCE_SCOPE_VERIFIED_NOT_TEST_PASS`，**不等于任何 C01–C12 或 Q3–Q9 的 PASS**。

### C09：文件合入不是 L4/L5 产品闭环

C09 已合入主线 `rc72_journey_cdp_capture.py`、`rc72_journey_n7_adapter.py`、`rc72_official_journey_execution.py` 及真实 Chromium/CDP 工程测试，但现场 BSK/4A/BrowserLease 和真人审批仍缺。源码审计还确认：**正式 `rc72_mission_factory.py` + `rc72_n7_pipeline.py` 只将 `tool_registry` 的工具统一映射为 `FormalN7RunnerAdapter`；当前未将 `journey_playwright` 路由绑定到 `SignedN7OfficialJourneyAdapter`。** C09 自身施工文档第 3/5 节也把该接线列为 A 组待集成。

QA 新增 `tests/test_rc72_qa_c09_product_dispatch.py`，使用正式 `create_mission_driver` 注入 `journey_playwright`，要求 N7 `dispatch.adapters` 中是实际 `SignedN7OfficialJourneyAdapter`，共享同一 Release/R1，不得通过通用 HTTP runner 或文本结果伪造 L4/L5 正式执行。**当前主线该门禁预期 RED**，并不否认 C09 已合入组件代码。修复后仍必须通过真实 N6 冻结契约、N7 Intent、Business Oracle、BrowserLease/人工审批、截图网络证据及 N8 冷恢复。

### 独立矩阵拆分

同一四环境 QA 作业拆成三套独立 JUnit，任何一套失败不遮蔽其他结果：
- `qa-c12-tools.xml`：包字节审计、证据 ZIP 反向验证、95 条冻结台账和 Git 源祖先负面测试；
- `qa-c01-c02.xml`：真实 local HTTP SUT N5 数据补偿、N6 再编译、新 N7 Attempt、故障证据/回滚；
- `qa-product-wiring.xml`：正式 N8/N10 及新增 C09 L4/L5 Journey 产品入口；缺接线应保留真实 RED。

截至写入检查，主线 C09 合入后的 Construction/Q1/Q2/portable workflows 均 **QUEUED**；最新 QA HEAD 的四环境 CI 也 **QUEUED**。A/B/C/D 未完成整体合入、行内 Q3–Q9 证据未获取，**C09=COMPONENT_MERGED_PRODUCT_DISPATCH_BLOCKED；C11/C12=HOLD；BANK_FINAL=NO**。


## 17. 第八轮：N8 防假接线、R1 重放身份与真实大制品验收（2026-11-04）

### N8 独立门禁防假阳性

原有 QA 静态断言只确认某个 N8 条件块内存在任意 complete/run 调用，可能错误接受 N7 bypass、其他服务或模拟回调。新增 tools/rc72_qa_product_route_ast.py，只有活跃节点类型确切为 N8_DIAGNOSIS_RECOVERY 的正式分支调用 self.n8_pipeline.complete/run/resume/reconcile 才算满足入口必要条件；通过 tests/test_rc72_qa_product_route_ast.py 的绕过、伪造服务和真实调用正负例保护这项检查本身。形式入口通过并不代表实际 N8 诊断和 N7 新 Attempt 成功。

### Q3–Q9 原始 R1 事件复核

独立 ZIP 复核进一步拒绝重复 event_id、entity_type 与 payload.artifact_type 冲突、entity_version 与实际 payload 版本不一致。test_case 使用原生 case_version，而不是误把 artifact_version 当成版本事实。对应测试必须在 ZIP 字节和外部 SHA256 本身完全有效的情况下拒绝伪造事件。结构完整不等于业务 Oracle、Human Gate 或 Field 真实性。

### C12 真实主线 Artifact 物理资格作业

新增 .github/workflows/rc7.2-qa-physical-transport.yml，使用独立 Windows runner 检查 QA HEAD 包含目标主线 SHA 与冻结设计祖先，只从 GitHub Actions 的精确目标主线 SHA 选择已成功的 Portable Transport push 构建及未过期的唯一同源 Artifact。随后真实下载 Artifact 字节，要求内层 ZIP 与其 .sha256 侧车一致，干净解包，调用 QA 独立只读工具检查 Manifest、全部 13 个实物能力组及真实携带的 DSH 主程序。无成功构建、旧 SHA、未匹配 Artifact、源字节不一致、缺少 DSH 均拒绝放行。上传源码关系、Artifact 元数据和独立物理审计 JSON 留证；就算全部成功，结果至多 PHYSICAL_CANDIDATE_ONLY，仍非 BANK_FINAL。

**历史证据与当前边界：** 旧主线 7efb3c8 的 Portable run #41679951113 曾显示成功，Artifact #13253451722 元数据标称大小 1,457,448,714 字节，但没有在此前完成独立真实字节下载验证；它不能替代新主线 4721bb57 的包。新主线当时的 portable run #41696110932 仍在排队，新 C12 实物 QA run #41698987310 也排队。所有工程能力必须等待同源实际 CI 和真实文件之后才能签收；Q3–Q9 现场证明缺失，BANK_FINAL=NO。


## 18. 第九轮：CI 堆积抑制与 C12 不可信 ZIP 解包前安全检查（2026-11-04）

### 已定位的继承回归运行资源问题

GitHub Actions 近期 100 条运行中观察到 52 条 QUEUED、48 条 COMPLETED；另一次独立查询发现 16 条 IN_PROGRESS。进一步逐一核对至少四个旧提交的 RC7 Field Hardening run（例如 41686265053、41685956103、41685896067、41685841050）：Windows 与 Ubuntu source regression 已 success，但 RC7 source suite 仍 in_progress，卡在 Run RC7-focused source tests。原 .github/workflows/rc7-field-hardening.yml 的该套件未配置 timeout，整个 workflow 也缺少按 PR 取消过期提交的并发治理。该问题可能加重队列，不把它未经证明地宣告为唯一原因。

QA CI-only 改动：为 RC7 Field Hardening 加入按 PR/branch 区分的 concurrency/cancel-in-progress，保证新 SHA 启动时后续重复旧 run 可被取消；为完整 RC7 source suite 加入 60 分钟明确超时。**没有删除、缩减或跳过任何原测试。** 超时必须以 FAILURE 形式留证，不能变成 PASS。新的配置不保证自动取消该配置生效前的老 run，也不代表所有排队都会立刻消失。

### 真实 C12 ZIP 的安全前置检查

新增 tools/rc72_qa_zip_preflight.py 与 tests/test_rc72_qa_zip_preflight.py；QA C12 物理 GitHub Artifact 工作流在实际 PowerShell Expand-Archive 之前先执行：

- ZIP 中仅允许 PFC-AITest-DSH-Turnkey-RC7.2-BANK-WIN10 为唯一正确的相对根；拒绝父目录、绝对路径、Windows 路径、ADS 冒号、点段与重复路径写法；
- 禁止符号链接、重复 ZIP Entry、根目录冒充普通文件、空包、不合理大文件与累计超过 20 GiB 的解包体积；
- 结构审计结果为 STRUCTURAL_PREFLIGHT_ONLY，单独存入 qa-c12-zip-preflight.json；必须再经真实内层 ZIP SHA、全部包内 Manifest/Checksum、DSH 主程序、真实冷启动，才能考虑更高级别资格；
- 负例用真正 zipfile 构造恶意成员、符号链接与重复文件名，不依赖文档层提示。Windows/Ubuntu × Python3.8/3.11 均编译/运行相同 QA 工具合同，不以本地假包替代真实包。

**当前仍为工程变更已提交、CI 结果未取得**。主线仍缺 C03/N8、C09 正式 L4/L5 工厂入口等完整验收，真实行内 Q3–Q9 未完成；BANK_FINAL=NO。
