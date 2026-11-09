# WB-F00 / F 组对 A–E 五组本轮施工的独立验收（2026-11-09）

**role / executor:** F Independent QA（与 A/B/C/D/E 施工结论分离）  
**审查范围：** PR #84(A), #89(B), #92(C), #90(D), #91(E)，F 独立 PR #85。  
**review_time:** 2026-11-09；所有结论绑定下表源 SHA，不继承任何历史 HEAD 的绿灯。  
**result:** `FG16_DESIGN_FIX_ACCEPTED`；`A_W0_CONTRACT_CI_PASS`；`F_B_SQL_NEGATIVE_FAIL`；`F_ABCDE_PREMERGE_BLOCKED`；`A_FULL_CI_RED`；**`WB-F00 REVIEWED_WITH_BLOCKERS / W0_NOT_FROZEN / NO_BANK_PACKAGE`**。  
**known limitations:** GitHub 源文件、PR、check-runs、原始 job logs 和 F 独立 GitHub Actions。银行 DSH1.18.26、真实 PostgreSQL、B06/API、R1、AgentTeams32 同时激活、Windows Git Bash 离线和 50 原子功能正式现场回归均未测试；C 的 CI 上传 PNG 不等于 F 实际视觉逐像素独立审查。

## 1. HEAD 与同 SHA 检查登记

| 组 | PR | 精确 source_sha | 同 HEAD 事实 | F 结论 |
|---|---|---|---|---|
| A | #84 | `5dc514c50d6ae89dcd0c606cea949dda9e0e53fc` | 28 checks：27 success / 1 failure；W0 专项 58 tests OK | FG16 静态整改认可；主线集成 CI BLOCKED |
| B | #89 | `704c86aaf9b2c5a9b9b4088648ccd0c50204f2f8` | 1 check success；10 SQLite 设计测试、68 W0+B 合同测试 OK | DESIGN_SIGNOFF_SUBMITTED / F 源身份反例红 |
| C | #92 | `e9094bf5267ebc840ffae6bf3e8a707380ecaf7f` | 1 check success；9/9 Node，真实 Chromium demo probe、3 张 PNG artifact | DEMO_BROWSER_CI_PASS，正式 W1/UI/API NOT_RUN |
| D | #90 | `f0b7faeb22f9bf03d2487061a8f81a2776a5213d` | 2 checks success；13/13 Host 只读/负向合同测试 | DESIGN_SIGNOFF_SUBMITTED；银行宿主 FIELD_NOT_RUN |
| E | #91 | `bee612b2dd94a6040404db4b9a4a5fd816e136dd` | 2 checks success；19/19 R1/API 内存 Oracle 合同测试 | DESIGN_SIGNOFF_SUBMITTED_WITH_HOLDS；E01 BLOCKED_B06 |

**可查证的 job：**
- A red [全继承 RC7.2 Chromium/CDP job #129169423859](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42620015620/job/129169423859)：`1 failed, 2907 passed, 4 skipped`；失败测试 `tests/test_rc72_c09_real_chromium_cdp_smoke.py::test_real_chromium_cdp_teaching_captures_dom_event_network_and_png`，`/api/save` POST 200 未被 CDP response collection 记录，断言 `assert False`，行 342。另有 TargetClosed warning，但**本次 FAIL 的直接断言为缺记录的 POST 200**；A 的 W0 变更列表不含此 RC7.2 源文件，暂不判定工作台提交是根因。当前全矩阵就是红灯，不许绕开此测试或以 W0 green 替代。
- A [W0 job #129169421428](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42620015155/job/129169421428)：`Ran 58 tests ... OK`。
- B [job #129174156870](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42621392201/job/129174156870)：`Ran 10 ... OK` 且 `Ran 68 ... OK`；SQLite 内存 witness 非 PostgreSQL。
- C [job #129177802613](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42622464425/job/129177802613)：9 Node 测试成功，Playwright Chromium 真的启动并运行 `W0_BROWSER_PROBE_PASS`，上传 [3 PNG artifact 13676629059](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42622464425/artifacts/13676629059)，只是 W0 独立静态演示。
- D [job #129174104189](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42621377607/job/129174104189)：13 测试成功；没有真实银行 Host 请求证据。
- E [job #129173968098](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42621339674/job/129173968098)：19 测试成功；没有真实 HTTP/R1 运行。

## 2. 既有 FG15/FG16 的独立复核

- **FG15:** 上一轮已接受 W0 DESIGN_SIGNOFF 与 W1 IMPLEMENTATION_QA 分开；继续有效。
- **FG16:** A 的 `W0-W1-GATE-MANIFEST.json` 已从 20 扩充 38 nodes；机器图中 `WB-F04_FIELD_QA_PASS` 前置包含 `WB-F03_AUTONOMOUS_QA_PASS` 与 `WB-D04_OFFLINE_QUALIFICATION_PASS`，最终 `WB-W4_BANK_RELEASE_APPROVED` 的祖先闭包包含 `WB-F02_FUNCTIONAL_QA_PASS`、F03、D04、F04、A04 和 LICENSE。A 的 validator 已校验闭包，增负向测试；F 的**独立 PR merge tree** [run 42634316547](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42634316547) 中 `f-w0-dag-adversarial` 原始日志 **2/2 F 独立断言 OK + 19/19 A DAG tests OK**，不是源文件只读自述。故 **FG16 `STATIC_DESIGN_FIX_ACCEPTED`**；静态 DAG 不会真的从 R1/人审/许可证系统验证 Gate 的真凭据，F01–F04 运行验收仍 NOT_RUN。

## 3. 本轮新发现的可复现 GAP 与反例

### WB-FG17 — P0 / A 全矩阵仍红

复现：打开 A 同 HEAD `5dc514c` check-run 的 [job #129169423859](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42620015620/job/129169423859)；定位 `test_rc72_c09_real_chromium_cdp_smoke.py:342` 对 POST `/api/save` 200 response 的 assert。当前 `1 failed / 2907 passed / 4 skipped`。需要 A/RC7.2 负责组提供同失败 SHA 的隔离复现、录制原始 evidence、根因、修复后的独立回归与同候选 HEAD 重新全矩阵。不得当作环境偶发直接跳过；未核清根因前不随意归咎 W0，也不认定全部 CI_PASS。

### WB-FG18 — P0 / B 系统版本作用域的 SST 源身份约束反例红

**规范性来源：** PR #89 的 `WB-B-A03-DESIGN-SIGNOFF.md` 第 2 节写明“若源 ID 被不同版本复用，生成不同内部稳定 ID、保留原始 source_ref”。其设计 witness `tests/test_dsh_workbench_b_a03_design.py` 实际 DDL 却为：

```sql
CREATE TABLE sst (
  project_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  sst_id TEXT NOT NULL,
  source_system TEXT NOT NULL,
  source_key TEXT NOT NULL,
  PRIMARY KEY(project_id, version_id, sst_id),
  UNIQUE(project_id, source_system, source_key),
  FOREIGN KEY(project_id, version_id) REFERENCES system_version(project_id, version_id)
);
```

**F 实际负向执行：** 在 [F 独立 run 42634316547 / job #129218336677](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42634316547/job/129218336677) 中，从 B HEAD `704c86a...` 的**原始 DDL**（不是复制一段自造表）执行 `tests/test_dsh_workbench_b_sst_identity_f.py`：同一 project+source_system+raw source_key `SST-100`，在两个不同系统版本 `V1/V2` 下有两个 version-scoped 内部 SST identity 的合法场景，第二次 INSERT 报：

```text
sqlite3.IntegrityError: UNIQUE constraint failed:
sst.project_id, sst.source_system, sst.source_key
```

**判定：** 现有 SQLite 设计 witness 与签署文档对于**跨版本重复来源标识**不相容，不可直接接受 B 签署无异议。请 B 明确定义 raw source ID 与内部 stable SST ID 的作用域，修改字段/UNIQUE 或规范化 mapping（确保不会将两个版本的同源 ID 错误关联），补“同 raw ID 不同 system_version 不串 SST”正反例并在新 B HEAD 测试。其他 10/10 绿色测试保留，不抹除失败。真正 PostgreSQL 及数据迁移留 W1/W2 独立资格。

### WB-FG19 — P0 / 五组独立绿灯不等于同 HEAD 可集成

**F 实际合并实验：** 使用确切 A/B/C/D/E 上表 SHAs，在 GitHub Actions 的隔离 Git 工作区以 A 为基线依次 `git merge` B/C/D/E；不执行任何远端 push。首次 [run 42634316547 / job #129218336094](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42634316547/job/129218336094)：
- B source SHA `704c86a...` 合并进 A HEAD 成功；
- 随后 C source SHA `e9094bf...` 与已有 B/A 发生**真实文件内容冲突**，具体为 `docs/dsh-workbench/08-CONSTRUCTION-PLAN.md`、`09-GAP-MATRIX.md`、`10-RELEASE-CHECKPOINT.md`；
- 原首次脚本 fail-fast，D/E **在这个旧 run 未尝试**，不得称其已冲突或已集成。F 随后修订脚本，使同一快照在 C 冲突 abort 后继续尝试 D/E 并累计冲突；只在修订 CI 真实运行后补充具体结果。
- B 与 E 还同时修改 `WB-A03-CROSS-GROUP-SIGNOFF.md` 及账本，跨组设计签署和来源约束不能靠最后写入者覆盖。当前 #89/#90/#91/#92 各自都是 Draft/Not Merged，A #84 也是 Draft；**没有可指认的 ABCDE 集成 SHA**，也没有同一合并树的 PostgreSQL/API/R1/UI/Host 合同回归。

**关闭条件：** A 以最新主线为依据明确合并次序、逐文件解决冲突、保留 B 复合来源和 D/E 权限/真相签署、C UI 十区 Scope、F 负向测试与 FG17 等原始失败；提交正式**单一 integrated SHA**，在该 SHA 运行统一契约/集成/浏览器/字段质量门禁，F 再审。单 PR “mergeable=true”不等于五组一起 mergeable。

### WB-FG20 — P1 / C 原版功能基线数量仍引用历史 47

- A 组 `WB-A01-ATOMIC-FEATURE-REGISTER.md@5dc514c` 明确 **50 项**（35 个 O/A 源函数入口候选、15 个新增目标）。
- C 组 `WB-C-W0-ORIGINAL-UI-AUDIT.md@e9094bf` 首段仍写“47 项记录”，而 C 的 PR 说明/测试证据已写 50。
- C/A 统一至 50 项固定 feature_id 与来源 SHA，形成 C 的 UI 原型覆盖 vs 原目标差异表、缺入口清单；不因 9 个 Node 单测+3 张截图声称 50 个实际交互已验收。

## 4. 五组签收状态及施工依赖

| 组/工单 | F 审查范围和决定 |
|---|---|
| A00/A01/A02/A03 | A 合同产物真实；A01 源码锚点从候选逐条完善，仍无 50 项目标实测。A02 LICENSE 仍 BLOCKED。A03 等 B/D/E 新签署的**规范性差异合入**与 F 复验。FG16 静态修复已认可；FG17/19 阻断。 |
| B A03 / B01–B08 | B 已正式提交设计签署（#89），SQLite 测试 10/10；F 发现 FG18 反例红，设计签署需修订；真实 PostgreSQL/Scope/迁移 NOT_RUN。 |
| C W0 / C01–C06 | 新增原创中文 W0 演示，真实 Chromium browser probe 与 3 张截图的**CI 执行存在**；F 尚未进行下载文件独立视觉检查，银行工作台原始 50 功能未实施；FG20 文案/功能登记落后，C02 等 B06。 |
| D A03 / D01–D04 | D 有 W0 DESIGN_SIGNOFF 和 13/13 只读契约测试；银行 DSH1.18.26 真实 Session/API/签名 Captain/32 队员并发、Git Bash 离线未验，D-G05 不能拿两个 Session GET 代替原生宿主兼容。 |
| E A03 / E01–E07 | E 有设计签署和 19/19 内存合同测试，可信主体/幂等/SSE/R1/Human Gate 语义明确；真实新 HTTP/API/持久 SSE/R1/Evidence 未实施，E01 BLOCKED_DEPENDENCY_B06。 |
| F F00/F01–F04 | F 本轮执行独立红/绿反例并发表证据；W0 设计还不能签 ACCEPTED，F01–F04 尚未进行现场/集成/全功能 QA。 |

## 5. A/B/C/D/E 下一轮具体验收请求

1. **A:** 对 FG17 失败保存原始 R1/browser/CDP 日志及根因；组织 B/C/D/E 同 HEAD 预合并、保留双方账本/签署字段；A03 编入来源验证约束；提交唯一候选集成 SHA 和同 SHA CI，不能提前 W0 FROZEN。
2. **B:** 修复 FG18 SQL 身份域与来源映射；补跨版本同原始 SST ID、跨项目、跨批次、同名系统版本和回滚等反例；新 HEAD 同 SHA SQLite CI 通过后请求 F 复验，正式生产 PostgreSQL 等 W1。
3. **C:** FG20 同步 50 项来源映射，不用静态 demo 代替 W1/C02；保留浏览器 screenshot 证据、错误提示和不提供伪发布。
4. **D:** 保持原生 Host 边界，不把公开 DSH/AgentTeams 源或 loopback 2 GET 作为行内 1.18.26 现场资格；W1 后进行实际 Host session/权限/恢复/32 并发审查。
5. **E:** 在合并 B 的 source_verified requirement-version / SST link 后确认 R1 trace/ACL 与真实业务 Scope 同源；待 B06 后推进 E01 的真实只读 API/Evidence，避免旧 rc7_admin 假成功。
6. **F:** 在新 SHA 重新跑 F 独立 release DAG、B 原始 SST 身份复用反例、ABCDE premerge / 统一集成，并核对所有原始失败的修复记录，不同 SHA 不互相继承结论。

**发布安全：** `naodeng/dsh-qa` PolyForm Noncommercial 标识不可删除规避许可。没有银行商业适用授权或经审计独立原创与正式 SBOM/法务审核，不得将受限代码复制入银行交付；`LICENSE_RELEASE_APPROVED` 仍 NOT_GRANTED。无银行 Windows 离线包，无产品 `QA_PASS`，不合入 `work/rc7.2` 运行主线。
