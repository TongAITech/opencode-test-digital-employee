# F 组独立验收 — A@200a96a / B#95 / C#97 / D 原签署 / E#96

**审查日期：** 2026-11-10（北京时区）  
**独立审核：** F 组（不得由 A/B/C/D/E 自签 `QA_PASS`）  
**A source_sha:** `200a96ac2ce3b69f2bd76a98517444699c8fbe92`，PR [#84](https://github.com/TongAITech/opencode-test-digital-employee/pull/84) OPEN/DRAFT  
**B source_sha:** `50bd16d9e2c321eb5eaa21e96f663e89ae377b34`，PR [#95](https://github.com/TongAITech/opencode-test-digital-employee/pull/95) OPEN/NOT_MERGED  
**C source_sha:** `a36421ef0ddc0f4034e4f284e8074502af7ec0eb`，PR [#97](https://github.com/TongAITech/opencode-test-digital-employee/pull/97) OPEN/NOT_MERGED  
**D source_sha:** `a332e6c575cac9d2b6ef0b2038615b276dcfa602`，PR #90 已合入 W0；本轮 D 无新的独立施工 PR  
**E source_sha:** `c70ad0da92c5a4899a72d3096fad5e46fded74d5`，PR #96 已合入 W0  
**F 审核 PR:** [#104](https://github.com/TongAITech/opencode-test-digital-employee/pull/104)，真实 CI [run #42732024122](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42732024122)

**审查结论：`FG22_DESIGN_RECHECK_PASS`、`FG21_GIT_CONFLICT_RESOLVED`、`FG23_OPEN_P1`、`B95_C97_SYNTHETIC_MERGE_OK`、`W0_NOT_FROZEN`。**

## 1. 各组同 HEAD 验证与事实边界

| 组 | 最新独立记录 | F 判定 |
|---|---|---|
| A | `200a96a` 15 check-runs: 1 success `w0-contracts` + 14 skipped；[W0 job #129542422674](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729154482/job/129542422674)：**180/180 Python、20/20 Node**，CI admission policy 13 workflows PASS。PR #84 GitHub `mergeable=true/clean` | FG22 负向错误码一致性修复在 **A 同源 L0 PASS**；非完整 L1/L2 |
| B | `50bd16d` [B job #129543167902](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729370403/job/129543167902) 26/26 B SQL witness + F FG18 原用例 1/1 + W0 183/183；E job 47/47 | SOURCE_TRACED_DESIGN_CI_PASS，仅 B01/02 方案及原始 SST source identity，不是 PostgreSQL/B06 |
| C | `a36421e` 同源 3/3 checks SUCCESS：浏览器原型和 B→C merge。C 的 14 Scope +10 source-fence +6 feature Node 合约，Chromium 与 screenshot CI 有实际运行 | W0 独立原型 / NOT_IMPLEMENTATION，见 FG23 |
| D | 原 D #90 合并入 A 的只读合同与 Host 探针 | DESIGN_SIGNOFF_ONLY；真实行内 DSH1.18.26/Agent Teams32 实测缺失 |
| E | #96 已合并，E adapter 接受 **Host 绑定** 的 B06 port、不传客户端 principal；只读 DTO 与历史 R1 为 UNKNOWN/HOLD，源 refs 和 pagination incomplete fail-closed | E01 BLOCKED_B06；真实 B06+R1 HTTP/SSE/持久真相未验 |

A 最新 CI 的 14 个 skipped check 不可解释为 14 项“成功”；Draft 阶段政策允许这些重测试不自动执行，但 W0 冻结和最终合入 RC7.2 前仍须正式同 SHA L1/L2、独立 F 签署/许可证门禁。

## 2. F 实际集成反例 — 发现 FG23

**输入：** A `200a96a` + B `50bd16d` + C `a36421e`，GitHub Actions 仅在隔离的本地分支按精确提交执行 `git merge --no-ff`（没有对 A/B/C/RC7.2 远端写入）。  
**证据：** [F 首次 synthetic job #129552134247](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42732024122/job/129552134247)。

实际：B merge **OK**，C merge **OK**；初次临时合并 HEAD `9ca05f0293924a6a186c317ac336e7086419213a`。随后运行全量 `python -m unittest discover -s tests -p 'test_dsh_workbench*.py' -v`，结果为 **183 tests, 1 FAIL**：

```text
FAIL: test_repository_policy_is_consistent
AssertionError: Lists differ:
 ['C_BROWSER_RERUN_ON_LEDGER'] != []
```

**根因源码对账：** C PR #97 新 `.github/workflows/dsh-wb-c-w0-ui.yml` 的 `on.pull_request.paths` 再次包含：
```yaml
- 'docs/dsh-workbench/08-CONSTRUCTION-PLAN.md'
- 'docs/dsh-workbench/09-GAP-MATRIX.md'
- 'docs/dsh-workbench/10-RELEASE-CHECKPOINT.md'
```
与 A 当前 `tools/dsh_workbench/ci_admission.py` 的拒绝规则 `C_BROWSER_RERUN_ON_LEDGER` 不符。C 单独 CI 的 3 checks success 并没有执行 A 的该准入契约；A 单独 W0 L0 success 也还不包含 C #97 新 workflow。因此存在**跨组 CI 配置回退**，不是主线文件合并冲突。

**GAP：`WB-FG23 P1 / CROSS_GROUP_CI_ADMISSION_REGRESSION / OPEN`**。

**整改：** C 修改 `dsh-wb-c-w0-ui.yml` 的 `on.pull_request.paths` 删除 `08/09/10`，保留真正 UI/Scope/source_fence/原子映射/工作流文件的触发以及 `workflow_dispatch`；不得删除 A 的 `C_BROWSER_RERUN_ON_LEDGER` 负向合同或把 browser QA 标 skip。A 在新 B/C 固定 SHA 合入后，同 HEAD 必须 `W0 Python contracts PASS + 30 Node PASS + Python ci_admission PASS`；F 再审其 GitHub 原始日志。

## 3. F 独立真实 Chromium 演示验证

**证据：** [F 浏览器 job #129552133945](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42732024122/job/129552133945)，[PNG artifact #13724073768](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42732024122/artifacts/13724073768)。

同样在 A+B95+C97 的临时合并源码执行真实 Playwright/Chromium `run_browser_evidence.py`：
```text
W0_BROWSER_PROBE_PASS:
six pages, ten section forms, shared multi-select Scope,
deny-by-default actions, theme and mobile
```
演示脚本逐区打开十区、验证表单必填无效、尝试提交后确认“不创建/修改/执行/审批”，包括 401/403/409/422/503 和模拟 200 来源不充分仍拒绝 PASS、旧响应迟到、390px。产出 3 张 PNG。**F 确认浏览器脚本与截图生成 job 执行成功；F 尚未逐张下载目视审查 PNG，不能标 `F_VISUAL_REVIEW_PASS`**。这些步骤都是静态 W0 原型和模拟源，不是正式业务服务/行内 DSH/Evidence 审批。

## 4. 旧 GAP 状态和许可门禁

- FG15、FG16：设计依赖 DAG 修复已完成独立合同测试。
- FG17：历史 Python3.8 toast 执行抖动真实存在；A 较新 `b385e04` 同 HEAD Py3.8 真 C09 31+5 trial、Py3.11 31 PASS，A 最新 `200a96a` 仅 W0 L0 已核；不可把历史目标 SHA 的 Chrome 结果挪作此 SHA 的完整 L2 真凭据。
- FG18：B 版本限定 raw SST source identity 的 F 反例历史已核销；B #95 加严 SST source trace，仍仅 W0 SQLite 设计。
- FG19：旧 B/C/D/E 集成冲突已解决；本轮 A+B95+C97 Git 合并 OK，但 **FG23 联合 CI 红**，因此仍未正式整体设计签收。
- FG20：50 项功能登记一致；**50/50 正式真实产品功能仍 NOT_RUN**，C W0 原型只是演示重叠。
- FG21：A PR #84 `mergeable=true/clean`，Git 层冲突消除，其他 required CI/授权仍 HOLD。
- FG22：A 新 W0 180/180 Python、20/20 Node 合同通过，CI 期望码修复成功，`FG22_DESIGN_RECHECK_PASS`。
- **FG23：P1 OPEN，A+B+C 联合 L0 准入回退**。
- **A02 `BLOCKED_LICENSE`：** naodeng/dsh-qa 使用 PolyForm Noncommercial，银行商业受限代码未取得适用授权时不得复制；不得删除原有 notice 规避。C 原创 W0 原型的源码来源与 SBOM/法务审批须单独记录，不能靠原型绿灯批准商业交付。
- W1–W4：真实 PostgreSQL/源关联、B06 REST/ACL、E01 R1/Evidence/NodeGate/SSE、D 行内 Host1.18.26、C 正式完整交互和 Windows Git Bash/32 AgentTeams 现场全部尚未验收。

**F 总裁决：`REVIEWED_WITH_BLOCKERS` / `W0_NOT_FROZEN` / `NO_RC7.2_MERGE` / `NO_BANK_ZIP`。**

本轮 F 靶向源码无商业许可结论；不以 `200`、截图或模拟 NodeGate 代替业务 Oracle。每次新 SHA 都必须独立重验，不能跨 SHA 抄 green。


## 5. F 追加独立负向实测（同固定源，不重复构建 Chromium）

**证据：** [F lightweight run #42732665548 / job #129554278918](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42732665548/job/129554278918)，在相同 A `200a96a` + B `50bd16d` + C `a36421e` 的本地临时合并源码上：

| 真执行范围 | 实际结果 |
|---|---|
| C Scope、多选、source-fence、50 原子 feature_id 设计核对 | **30/30 Node PASS** |
| B 复合来源、SST source trace、批次关系 SQL 设计 | **26/26 Python PASS** |
| F 原始 FG18 跨版本同源 SST ID 反例 | **1/1 PASS** |
| E B06 read-only/source_refs/cursor/R1 保守消费 | **47/47 Python PASS** |
| F 原始 FG16 终局 F02/F03/D04 Gate 先驱闭包 | **2/2 PASS** |

F 的 [第二次完整合并 run #42732664794](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42732664794) 仍有 **183 tests / 1 FAIL**，其原因为唯一 `C_BROWSER_RERUN_ON_LEDGER`；Chromium job 同次再验证 PASS。此独立轻量 job 不是完整联合契约的替代，**不能把上述子集全绿说成 ABCDE W0 QA_PASS**。

`FG23` 整改意见已提交 [C PR #97](https://github.com/TongAITech/opencode-test-digital-employee/pull/97#issuecomment-6755821800) 与 [A PR #84](https://github.com/TongAITech/opencode-test-digital-employee/pull/84#issuecomment-6755823252)，B #95、D #90、E #96 也分别收到范围内增量复核。F 新评审 PR [#104](https://github.com/TongAITech/opencode-test-digital-employee/pull/104) 保持 OPEN；未因独立 CI 故意的失败而绕过 gate 或伪造绿灯。

**最终状态依然 `FG23 OPEN / W0_NOT_FROZEN / BLOCKED_LICENSE`。** 新 C/A fix HEAD 必须重跑 A+B+C 合并与共同 Python/Node/admission 策略，再由 F 核销。
