# F 组独立审核：C #97 FG23 修复及 A 五组集成 HEAD a3555b1

**审核日期：** 2026-11-10  
**结论：** `C_W0_PROTOTYPE_REVIEW_PASS` / `FG23_CLOSED` / `C01_C02_NOT_IMPLEMENTED` / `W0_NOT_FROZEN`  
**A 被测 HEAD：** `a3555b187eb35d27a2d712313dd8ea7daa28915f`（A PR #84 当前 HEAD）  
**C 合并源：** `b2a64df65661880808510d0486f6aefc70ca23df`，C PR [#97](https://github.com/TongAITech/opencode-test-digital-employee/pull/97) MERGED  
**C 的 FG23 修复代码提交：** `7fa4d0c516168cde22d6d071170d449dc0ed8b77`  
**A 五组源集成提交：** `db1026fd1036d2e0b00853f56383e89b8bb0b9d0`  
**F 独立复验 PR：** [#106](https://github.com/TongAITech/opencode-test-digital-employee/pull/106)  
**F 同 SHA 实测：** [run #42740012204](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42740012204)

## 1. C 的 FG23 修复代码审查

原始失败保留：[F #104 首轮 A+B+C 精确合并 job #129552134247](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42732024122/job/129552134247)，183 Python tests /1 FAIL，错误为 `C_BROWSER_RERUN_ON_LEDGER`。

C 修复 commit `7fa4d0c` 的真实 diff **仅修改** `.github/workflows/dsh-wb-c-w0-ui.yml`，删除 3 条高成本浏览器 PR 触发路径：
- `docs/dsh-workbench/08-CONSTRUCTION-PLAN.md`
- `docs/dsh-workbench/09-GAP-MATRIX.md`
- `docs/dsh-workbench/10-RELEASE-CHECKPOINT.md`

保留 UI/Scope/SourceFence/feature reconciliation 相关源码和测试路径、非 Draft 条件、实际 Chromium job 以及 `workflow_dispatch`。未删除 A 的 `C_BROWSER_RERUN_ON_LEDGER` 准入负向断言，也没有把浏览器测试改为 skip。C 最终文档提交 `b2a64df` 只更新 08/09/10 审计记录；A 合并树中 `dsh-wb-c-w0-ui.yml` 的最终触发路径已确认没有三本账。

**F 判定：FG23 修复正确，P1 关闭。** 原 183/1 FAIL 历史不删除、不改写。

## 2. A 五组集成源父链核验

F 独立工作流从精确 `a3555b1` checkout，并以 `git merge-base --is-ancestor` 逐一验证以下源 SHA 都是 A 当前候选 HEAD 的祖先：

| 组/源 | SHA | F 验证 |
|---|---|---|
| B #95 | `50bd16d9e2c321eb5eaa21e96f663e89ae377b34` | PASS |
| C #97 | `b2a64df65661880808510d0486f6aefc70ca23df` | PASS |
| D #90 | `a332e6c575cac9d2b6ef0b2038615b276dcfa602` | PASS |
| E #102 | `26b2deaf5485193133e418da81982291c8056d64` | PASS |
| A #103 | `d082e71f7eb9260afe450203bd160f8cd9e65948` | PASS |

A 集成提交 `db1026f` 的五个 parent 精确包含 A `200a96a`、B `50bd16d`、C `b2a64df`、E `26b2dea`、A103 `d082e71`；D #90 是 A HEAD 的祖先。F 没有只凭 PR 描述认定集成成功。

## 3. F 在 A 精确 HEAD 上独立重跑的结果

[F-owned exact SHA jobs](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42740012204)：

| 检查 | 精确结果 | 说明 |
|---|---:|---|
| 完整 W0 Python `test_dsh_workbench*.py` | **206/206 PASS** | 包括 CI admission 负向、B/E 合同、Host loopback、W0 等 |
| C Scope / SourceFence / feature reconciliation Node | **30/30 PASS** | 无 skip |
| F 原生 FG18 同 raw SST ID 跨版本反例 | **1/1 PASS** | 读取 A 集成树中的 B DDL |
| F 原生 FG16 发布依赖闭包反例 | **2/2 PASS** | F04 依赖 F03+D04；BANK_RELEASE 依赖 F02 |
| CI admission policy | **13 workflows PASS** | `CI_ADMISSION_POLICY_PASS` |
| CI admission 独立负向测试 | **21/21 PASS** | `test_c_browser_does_not_rebuild_on_document_ledger` 保留；注入账本路径仍被拒绝 |
| 精确 A HEAD 真实 Playwright/Chromium | **PASS** | 非 C 独立分支，直接 checkout A `a3555b1` |

因此，**C 的 FG23 不仅 C 自己单 SHA 通过，也在 A 当前五组集成树上由 F 独立复验通过**。本轮没有沿用旧 SHA 的 PASS 代替当前 SHA。

## 4. F 对真实 Chromium 截图逐张目视检查

[F job #129578451574](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42740012204/job/129578451574) 实际执行 `run_browser_evidence.py`，生成 [artifact #13728522322](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42740012204/artifacts/13728522322) 三张 PNG；F 已下载并逐张检查：

| 图片 | 尺寸 | SHA-256 | F 目视结论 |
|---|---:|---|---|
| `wb-c-w0-scope-ten-sections.png` | 1380×1401 | `6e64316cad45e7d43f1827ce1d45914f0560505539edc39bfaded5232443c8ae` | 项目详情十区可见，投产日期/需求/版本/SST 多选及统一 Scope 回显，当前分区表单与来源异常演示可见 |
| `wb-c-w0-six-stage-board.png` | 1380×855 | `d850b8a2e703cd473d80d21e91b332f40bfd31f005841af93b4620050825abd1` | 六阶段看板完整，明确标记演示阶段，不冒充 NodeGate/N10 |
| `wb-c-w0-mobile.png` | 390×895 | `e50d647e763bbe120c82544233444fcae17b20922af6bf0360443850fa93a4f7` | 390px 窄屏导航折叠、卡片与控件可见，无明显横向溢出 |

目视检查确认原型布局和标注符合 W0 演示边界；不是完整原版功能可用性的视觉验收。截图明确说明未接入真实 API/演示数据，表单提交不创建/修改/执行/审批业务记录。Scope 与异常展示不构成服务端 ACL、B06、R1、SSE、持久化或真实质量判定。

## 5. C 完成范围与未完成范围必须区分

C PR #97 的交付是 **W0 原创 UI/Scope/SourceFence 可行性原型 + FG23 CI 修复**。本次 F 接受该 W0 交付范围，不把它扩写成正式产品功能。

- 六页面身份：五条主导航（测试首页、DSH 测试对话、项目看板、日历排期、QA Skill 安装）+ 从项目入口打开的第六页面（项目详情）。
- 项目详情十个分区：原型提供十区入口、同一只读 Scope 快照、各区表单必填校验及提交拒绝。
- 投产批次-需求-系统版本-SST：投产日期作为批次身份；需求、版本、SST 多选并按显式关系边过滤；父级变化清理下级选择；无效组合拒绝；迟到响应不覆盖当前上下文。
- 六阶段项目业务看板保留独立于 RC7.2 NodeGate 的状态含义。
- Source Fence 覆盖 401/403/404/409/422/503、缺失证据/人审、STALE/UNKNOWN、跨项目/批次/修订与迟到响应；全是本地负向原型，无真实请求。

**仍未完成：**
1. A01 50 项功能矩阵为 50 = 35 O/A + 15 N；正式产品状态仍 **50/50 NOT_RUN**。其中不少仅 `NAV_ONLY`、`STAGE_ONLY`、`FORM_DENY_ONLY`、`DENY_ONLY` 或 `ERROR_FENCE_ONLY`，不能记作业务操作实现。
2. C01/C02 W1 正式施工未启动/未通过；真实 Project/ACL/CRUD、B06 分页 API、数据库事务、跨窗口 SSE、Host 对话/会话/Skill 安装、持久化、真实缺陷/报告/人审仍未验证。
3. 双语范围需明确：当前产品正式要求为中文，W0 原型为中文；A01 的 P05-03/X01-01 英文/中文切换及 Skill 双语说明仍 `NOT_RUN`，feature delta 也标明仅 `THEME_COLLAPSE_ONLY`。若需求保留双语能力，应进入 C01/C02 正式范围；若决定仅中文，应由 A01 需求责任人正式裁剪/签署，不能静默算完成。
4. DSH Host 真实集成、R1 Evidence/NodeGate、真实 ACL 和权限撤销未运行。
5. A02 PolyForm Noncommercial 商业授权/原创来源 SBOM 法务门禁仍 `BLOCKED_LICENSE`。

## 6. F 最终结论

- `FG23_CLOSED`
- `C_W0_PROTOTYPE_REVIEW_PASS`
- `FG20_DESIGN_RECONCILIATION_PASS / PRODUCT_50_NOT_RUN`
- `C01_C02_IMPLEMENTATION_QA_NOT_RUN`
- `W0_NOT_FROZEN`
- `A02_BLOCKED_LICENSE`
- `NO_RC7.2_MAINLINE_MERGE / NO_BANK_ZIP`

**F 接受 C #97 当前 W0 原型和 FG23 修复。** 不接受“C 的 50 个产品功能已完成”或“C01/C02 已通过”。W0 总冻结和银行交付仍受 A/F 全局设计签署、真实依赖与许可证门禁约束。
