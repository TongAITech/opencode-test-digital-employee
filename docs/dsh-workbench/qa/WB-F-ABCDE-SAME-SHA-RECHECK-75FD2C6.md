# WB-F 独立复验记录 — ABCDE 最新集成 A@75fd2c6 / F@8a4bf7f

**审查时间：** 2026-11-10（北京时区）  
**主源 SHA：** `work/dsh-wb-w0@75fd2c64159db863cfd1319d41a887785b556d40`  
**F 复验 SHA：** `work/dsh-wb-qa-f-recheck-20261110@8a4bf7f092426b7681d75092b11d0da3308722e9`（仅新增 F workflow；其父提交是上述 A 源 SHA）  
**F 复验 PR：** [#94](https://github.com/TongAITech/opencode-test-digital-employee/pull/94)  
**A 施工 PR：** [#84](https://github.com/TongAITech/opencode-test-digital-employee/pull/84)  
**已有 F 历史审查：** [#85](https://github.com/TongAITech/opencode-test-digital-employee/pull/85)  
**result:** `FG18_DESIGN_CI_PASS`、`FG20_DESIGN_RECONCILED`、`ABCDE_W0_CONTRACT_CI_PASS`、`FG17_NONDETERMINISTIC_FAIL_AND_PASS`、`W0_NOT_FROZEN / F_REVIEWED_WITH_BLOCKERS`。

## 1. 五组 PR 与版本状态

| 组 | PR | 提交源 SHA（审查快照） | 状态 | F 阶段结论 |
|---|---|---|---|---|
| A | #84 | 75fd2c64159db863cfd1319d41a887785b556d40 | Draft/Open，未合并 RC7.2，mergeable=false / dirty | W0 合同代码合并提交存在；仅 L0 自测绿；F 对最新 HEAD 重新触发独立 CI |
| B | #89 | 98bac426a35063a306f4eaa4b43c80cf0a0a1745 | MERGED into A W0 | FG18 修复见证 SQL 与 F 原反例在 A+F 树可执行；生产 PostgreSQL 仍未运行 |
| C | #92 | e4588ee6e14409323b7da483b7b158e25728b1a3 | MERGED into A W0 | FG20 50 条与 Node 15 tests 已纳入；Demo Chromium≠正式 C01/C02/F02 |
| D | #90 | a332e6c575cac9d2b6ef0b2038615b276dcfa602 | MERGED into A W0 | 13+12+5 Host 合同/本机只读测试；真实行内 Host NOT_RUN |
| E | #91 | b4065b52f5adf68f25c4ebd7892912d1a94d862c | MERGED into A W0 | 40 项 R1/Scope 原型合同；E01 BLOCKED_B06、真实 API/R1 NOT_RUN |

这些 B/C/D/E 的“MERGED”指 GitHub PR 合入 `work/dsh-wb-w0`，**不是**合入 `work/rc7.2`、不是 W0 冻结或真实产品 QA_PASS。

## 2. F 独立执行：合同与前次 FG18/FG20

**证据：** [F 组独立 Actions run #42655897274 / job 129294170362](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42655897274/job/129294170362)。

```text
F_INDEPENDENT_SOURCE_SHA=8a4bf7f092426b7681d75092b11d0da3308722e9
F_BASE_SOURCE_A=75fd2c64159db863cfd1319d41a887785b556d40
python -m unittest discover -s tests -p 'test_dsh_workbench*.py' -v
Ran 156 tests ... OK
python -m unittest discover -s tests -p 'test_dsh_workbench_b_sst_identity_f.py' -v
... OK
python -m unittest discover -s tests -p 'test_dsh_workbench_release_dependencies_f.py' -v
Ran 2 tests ... OK
node --test tests/test_dsh_workbench_ui_w0.mjs tests/test_dsh_workbench_c_feature_reconciliation.mjs
# tests 15
# pass 15
# fail 0
CI_ADMISSION_POLICY_PASS workflow_count=10; NO_QA_PASS_CLAIM
```

源 SQL 合同已把 `sst` 来源原始 ID 唯一域限定在 project+system_version+source_system+source_key，同时保留稳定内部 SST ID 及 source_trace。F 原始同 raw ID 跨版本反例已在最新合并源树通过，**FG18 = DESIGN_CI_RECHECK_PASS**；W1 真实源系统字段映射、PostgreSQL DDL/迁移/查询授权、回滚和持续持久性不在此范围。

C 原版功能基线现在 A01 与 C 差异登记一致为 **50 条（35 O/A 候选，15 新目标）**，15 项 Node 合同通过；**FG20 = DESIGN_REGISTER_RECONCILED**，不是 50 项正式操作已经实测。

## 3. F 独立执行：FG17 新 HEAD Python3.8 真 Chromium 仍红

**证据：** [F 独立 Actions run #42655897274 / job 129294169646](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42655897274/job/129294169646)，CI 证据 [artifact ID 13692021395](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42655897274/artifacts/13692021395)。

**环境：** Ubuntu 22.04，Python 3.8，pytest 8.3.5，Playwright 1.48.0，真实安装的 Playwright Chromium；与 RC7.2 Q1 Python3.8 兼容栈一致。  
**source:** F HEAD `8a4bf7f...` 仅新增 workflow，待测 `tests/test_rc72_c09_real_chromium_cdp_smoke.py` 与 A `75fd2c6` 完全相同。  
**command：**
```bash
python -m pytest -q -ra tests/test_rc72_c09_real_chromium_cdp_smoke.py --junitxml=f-fg17-py38.xml
```
**actual:** `1 failed, 2 passed in 7.20s`。失败 `test_real_chromium_cdp_teaching_captures_dom_event_network_and_png`，`tests/test_rc72_c09_real_chromium_cdp_smoke.py:327`：

```text
AssertionError: FG17_SUT_TOAST_ORACLE_NOT_MET
assert 'Before save' == 'Saved on server'
```

关键区别：在 `expect_response` 见到 SUT POST 200 后，`wait_for_load_state("networkidle")` **并未保证 SPA 已完成 toast DOM 更新**。可能是 Playwright1.48/Chrome 旧栈时序差异，**尚未有根因证据，不能擅自归类为偶发/产品缺陷或删除断言**。继续检查 recorder 产生的 network refs 与 DOM/PNG 是否可复核，不能凭 HTTP 200 就宣称业务 Oracle PASS。测试原始 artifact、前次 Q1 Linux Python3.8 红与本轮新 HEAD 同一类失败；后续 A 应在不删除任何真实断言的条件下提供可靠的 DOM Oracle 收敛/事件归属诊断，F 再复验。

**历史对照：** 旧 A `f8de595...` [V4 5 job 全绿](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42639771154)，Linux Chromium 全继承 `2908 passed, 4 skipped`，而 [Q1 Ubuntu Python3.8 专项](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42639770756/job/129237438065) 仍 1 failed；这些历史结果**不能代替** A 最新 `75fd2c6` 的最终 L2。

**F decision：FG17 P0 OPEN / PY38_REAL_BROWSER_QA_FAIL，禁止 L2 完整资格宣称。**

## 3A. 同一 A 产品源下再次 F 执行 3/3 PASS — FG17 是未收敛的不稳定问题

前次记录的真红灯必须保留，不得因复验绿灯涂改。F 在同一 A 产品源 SHA `75fd2c6` 的新 F 审查提交 `89d31e29ef735150cafe8b3acc454a12506e26ca` 上再次触发实际工作流；与第一次 `8a4bf7f` 相比，**只新增本审查 Markdown，无任何 A/B/C/D/E 产品/测试代码变化**。

- [F 第二次真实 Chromium job #129296053535](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42656439120/job/129296053535)：**3 passed in 4.84s**。
- [同 HEAD F 合同 job #129296054091](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42656439120/job/129296054091)：**156/156 Python W0、F FG18 1/1、FG16 2/2、C Node 15/15**。
- [首次同源 F 真红灯 job #129294169646](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42655897274/job/129294169646)：**2 passed, 1 failed**（toast 仍 Before save）。

**独立结论：`FG17 FLAKY_UNRESOLVED`，而不是简单“固定红灯”或“稳定修复”**。原断言绝不降级；异步 HTTP response vs SPA toast 观察结果存在执行不确定性，必须做多次独立重复、分析响应网络 Evidence、DOM 轮询与 CDP recorder 关联后再签资格。F workflow 已改为同一次 provision 下连续执行 5 轮真 Chrome 测试，任何 1 次失败都 fail-closed、保留每次 XML；这是新的施工验证，不代表已经通过。

## 4. 当前集成、CI 和许可门禁

- A 最新 `75fd2c6` [L0 job 129288577089](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42654306689/job/129288577089) 为 W0 **156/156**、CI policy 10 workflows 通过；由于 CI 进行了 L0/L1/L2 admission 优化，**该 source SHA 自动只执行一项 L0 check**。其余完整继承 QA/Windows Python3.8/真实浏览器不得借旧 SHA 绿灯或 L0 替代。
- C source `e4588ee...` 中旧 `c-b-premerge` 工作流 [job 129233205908](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42638571177/job/129233205908) 仍有 08/09/10 与 C audit 冲突；其做法是再拉取最新 origin A/B/C 并顺序 merge，已经不匹配签署后 A 合入四组的单源流程。C 原型校验 job 129233204908 独立成功（15 Node、真 Chromium demo）。作为历史分支检查红保留；A 统一 W0 源代码确实已有 B/C/D/E，需最终 F 对合法性/来源/状态再审。
- A [PR #84](https://github.com/TongAITech/opencode-test-digital-employee/pull/84) 对 work/rc7.2 当前 GitHub `mergeable=false / mergeable_state=dirty`。**新增 FG21 P0 — 主线合并阻断**：必须由 A 提交不损失现有 RC7.2 R1/Agent Teams/Source 与工作台的冲突解决单一 HEAD、同 SHA CI，在此之前不得合入。
- `naodeng/dsh-qa` PolyForm Noncommercial 1.0.0 仍是商业许可红线。没有适用银行商业授权或可审计原创来源批准，不能复制受限代码/删除标识，`LICENSE_RELEASE_APPROVED` 仍 NOT_GRANTED；`A02 BLOCKED_LICENSE` 保持不变。
- 真实 W1–W4 业务数据库/API、DSH Host1.18.26、AgentTeams32 实际并发、N1–N10/R1 Evidence、Windows Git Bash 无网安装及 F01–F04 真验收均未实施，不使用任何 W0 mock/Oracle 充当 QA_PASS。

## 5. F 退出条件与 A/B/C/D/E 接单

**WB-F00：`REVIEWED_WITH_BLOCKERS`；W0：`NOT_FROZEN`。**

A 必须在 08/09/10 记录本次 source SHA、F PR #94、FG17 Python3.8 独立红灯/原始证据、FG18/F20 设计层成功和 FG21 RC7.2 主线合并阻断；核实 L1（同一个 source HEAD）和有现场意义的 L2 验收触发/权限。B/D/E 要对合并后 A03 新契约源 SHA 再确认，而非仅依赖旧合并前分支的设计签署。

A/RC7.2 责任方修复 FG17 时必须保留 HTTP POST 200、DOM 业务 Oracle、CDP 已记录 response、R1/PNG 等断言及失败 Evidence；F 再针对 Python3.8 + Python3.11 真 Chromium、历史负例和同 SHA 的 L1/L2 重跑。A 整体工作台功能仍仅设计，F 不签实际产品 QA_PASS。

**known limitations：** 本轮 F 的 GitHub CI 在 GitHub Ubuntu runner 上运行，非行内 Windows、非生产 DB/Host/R1；虽然 GH CI 上传了 artifact，但未逐项人工开包分析 PNG 与 R1 真原始字节，故对 CDP 数据包完整性的结论仅来自此测试在断言处失败，不能推断测试后续编译/回放成功。


## 6. F 五轮真实浏览器稳定性复验（增量结果）

**源版本：** A 产品 `75fd2c64159db863cfd1319d41a887785b556d40`，F test workflow `76128293eb9eea3c7a420af121235c9a89ade502`（仅 F workflow/文档，没有任何 ABCDE 产品源码或原 C09 断言改变）。  
**命令：** Ubuntu 22.04 / Python 3.8 / Playwright1.48.0 / 真 Chromium，在同一 provision 下 **连续 5 次**各运行未删减的 `tests/test_rc72_c09_real_chromium_cdp_smoke.py` 三个测试，用独立 JUnit XML 归档；任何尝试失败即整 job FAIL。  
**证据：** [F run #42656920332 / job #129297760533](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42656920332/job/129297760533)；同源合同 [job #129297760873](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42656920332/job/129297760873) success。

| 实际尝试 | 结果 | 耗时 |
|---|---|---|
| 1 | 3/3 PASS | 6.10s |
| 2 | 3/3 PASS | 7.94s |
| 3 | 3/3 PASS | 4.24s |
| 4 | 3/3 PASS | 4.18s |
| 5 | 3/3 PASS | 4.22s |

输出：`FG17_FIVE_TRIAL_FAILURES=0`，此次重复验证通过。注意**此前同一 A 产品源码的独立 CI 1 FAIL（真实 toast Before save）不可因这五次成功而删除或改写**；准确状态仍为 `FLAKY_OBSERVED / SHORT_REPEAT_PASS / ROOT_CAUSE_PENDING`，并非稳定性已根因解决或行内正式 Q1/FIELD_QA_PASS。下一步由 A/RC7.2 排查 SPA toast DOM 收敛和旧 Playwright 时序，保留原 HTTP/DOM/CDP/R1/PNG 强断言；F 在新修复 SHA 与 Q1 跨平台独立重验。

**本轮最后裁决：** `FG18_DESIGN_RECHECK_PASS`、`FG20_REGISTER_RECHECK_PASS`、`ABCDE_W0_CONTRACT_CI_PASS`、`FG17_FLAKY_OBSERVED`、`FG21_MAINLINE_MERGE_DIRTY`。W0_NOT_FROZEN、A02_BLOCKED_LICENSE、W1–W4 产品/行内 QA_PASS=0。
