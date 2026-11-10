# F 独立复验 R2 — A@f6aa 合入 B108/E107 后的 W0 验收

审核日期：2026-11-10  
F 独立 PR：[ #112 ](https://github.com/TongAITech/opencode-test-digital-employee/pull/112)  
原 A 精确集成 HEAD：`f6aa541a7c82b74bcd1937754637d8341111fb70`  
F-owned 测试与 Workflow 初始源码：`dc01aad9ee72fa9e634d0eb3cd5e19b437c0e4b5`  
独立 Actions：[run #42755829361](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42755829361)  
当前 A 自身 L0：[run #42754283361](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42754283361)  

## 一、最新集成源、提交关系和准入边界

与上轮 F #111 审核 A@f870 相比，当前 A 源新增四个提交，并合入：
- B 组 PR #108 `b801c25bbec361e6a791c561d5a7dd0ec9440aaf`；
- E 组 PR #107 `a04933fbe7b651c10b589b90cade5da65bdd8b81`，含上轮 F 发现的 E107-P1 修复；
- C #97 `b2a64df65661880808510d0486f6aefc70ca23df` 和 D #90 `a332e6c575cac9d2b6ef0b2038615b276dcfa602` 来源在 A 当前 HEAD 的真实 Git ancestor 链中；
- A 将 00/02/03/04/05/07 六份合同状态修正为 `W0_DESIGN_IN_PROGRESS / W0_NOT_FROZEN`，同步 08/09/10 原有阻断。

F 独立工作流从 A@f6aa 分支，新增且仅新增 F QA 测试、F QA CI 和本报告，不修改生产源码；逐项检查 A、B、C、D、E 精确 Git ancestor。

## 二、原 E107-P1 证据复验

上轮 F #111 发现的原始失败：E adapter 调用原 `mission_overview(mission_id)` 读取 Tasks/Executions/Evidence **早于** Mission project/batch 绑定校验。原失败、评论、测试均留存，不删除历史事实。

新源码：
1. `tools/dsh_workbench/e_b06_page_consumer.py` 在完整且已验证的 B06 分页链后只调用 `read_scoped_r1_mission_overview`；
2. `tools/dsh_workbench/e_readonly_scope_prototype.py` 强制 `mission_overview_scoped` 方法存在，不回退旧 `mission_overview(mission_id)`；
3. `rc7_admin/projection.py` 的新 `AdminProjection.mission_overview_scoped` 仅查询指定 `rc7_mission` 身份并校验显式 `mission_id/project_id/batch_id`，确认匹配之后才查询 Tasks/Executions/Evidence；
4. 缺失 / 跨项目 / 跨批次 Mission 一律 `R1_MISSION_SCOPE_UNRESOLVED`，拒绝时关联明细查询次数为零；重复身份同样拒绝；返回的成功 Mission 只含三项身份键，不泄露原始 Mission 的其他字段。
5. 原 `Mission` 数据模型无正式 project/batch 字段。真实 legacy Mission 仍必须 fail-closed，不能用 release_id 推断。因此这一修复不能解锁 E01 或代表旧数据可用。

F 新增 `tests/test_dsh_workbench_f_r2_r1_scope.py`：9 个独立对抗案例，使用真实 `AdminProjection` 代码和可观测的 Truth Query port。涵盖：跨项目、跨批次、缺少显式绑定、Mission 不存在、重复 Mission 身份、正确身份先验后读并收敛到最小身份字段、明细读取失败 fail-closed、E adapter 跨 Scope、禁止退化到旧 API。拒绝路径断言仅 Mission 身份查询、无 Task/Execution/Evidence 读取、无全局 R1 replay。

**F 裁决：** `E107_P1_PRE_READ_DEFECT_CLOSED_FOR_W0_DESIGN` / `E01_IMPLEMENTATION_QA_BLOCKED`。仅核销已发现的 W0 调用顺序/非授权预读缺陷，不能声称生产 ACL 与 Mission 迁移资格。

## 三、真实同源 CI

| 代码与环境 | 用例 | 结果 |
|---|---|---|
| 当前 A@f6aa（不含 F 新测试），A 同 HEAD W0 fast | Python 247 / Node 30 | **247/247、30/30 PASS** |
| F 新安全用例 + A@f6aa，Python 3.8 | 独立 F 安全负例 | **9/9 PASS** |
| F 新安全用例 + A@f6aa，Python 3.8 | E 分页 + R1 协议负例 | **82/82 PASS** |
| F 新安全用例 + A@f6aa，Python 3.11 | 独立 F 安全负例 | **9/9 PASS** |
| F 新安全用例 + A@f6aa，Python 3.11 | E 分页 + R1 协议负例 | **82/82 PASS** |
| F 新安全用例 + A@f6aa，Python 3.11 | 全量 W0 Python 含 F 新案例 | **256/256 PASS** |
| F 当前原型，Node 22 | Scope/50 原子/SourceFence | **30/30 PASS** |
| F 当前原型，真实 Chromium | 六页、十区、Scope、多选、异常拒绝、主题、移动窄屏 | **PASS** |
| A01 + CI admission | Canonical zh-CN/en-US 来源与 13 workflows | **PASS** |

F 独立 workflow 作业：Py3.8 [job 129629856745](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42755829361/job/129629856745)；Py3.11 [job 129629856385](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42755829361/job/129629856385)；Chromium [job 129629856678](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42755829361/job/129629856678)。

真实 Chromium artifact [#13735617100](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42755829361/artifacts/13735617100) 已下载、解包、核对 SHA256，并目视审查三张图：
- `wb-c-w0-scope-ten-sections.png`: `6e64316cad45e7d43f1827ce1d45914f0560505539edc39bfaded5232443c8ae`；六页入口/十区入口与 Demo Scope 关系、多选、禁止伪提交提示均可见；
- `wb-c-w0-six-stage-board.png`: `d850b8a2e703cd473d80d21e91b332f40bfd31f005841af93b4620050825abd1`；六阶段，明确仅示例，不冒充 R1 NodeGate/N10；
- `wb-c-w0-mobile.png`: `e50d647e763bbe120c82544233444fcae17b20922af6bf0360443850fa93a4f7`；移动布局在演示搜索/看板场景无明显横向溢出。

三图与上轮 f870 截图 SHA256 一致，符合 C W0 原型源码未改变的事实，不是新的六页十区正式产品实现证据。

## 四、五组独立判定

| 组 | F 验收 | 真实未完成项 |
|---|---|---|
| A | 当前 A@f6aa W0 合同、A01 双语来源及 08/09/10 一致性 **PASS** | A01 50 项真实原版操作 / W0 全局 DESIGN_ACCEPTED 未签 |
| B | B108 W0 设计见证在 A 同源回归通过 | PostgreSQL、B06、权限/事务一致性快照/迁移、合法来源 supersession |
| C | W0 六页面/十区原型 Chromium/Node 通过 | C01/C02 真 UI/API/DSH Host、W2 F02 50项真实交互 |
| D | Host read-only 安全探针 W0 合同保留 | 行内 DSH1.18.26、Agent Teams32 活跃并发、Windows Git Bash 离线 field |
| E | **E107-P1 W0 预读缺陷经 F 独立负向核销**；来源漂移防护保持 | B06 真授权/分页、R1 持久化与 canonical Scope、E01 正式 API/R1 实施及权限验收 |

## 五、剩余高风险及质量门禁

- **W0 全局冻结：** 目前 `W0_NOT_FROZEN`。A01+A03 正式设计签署、F00 决策需要独立完成，F 的定向 P1 核销不能替代全部设计准入。
- **A02 商业授权：** `BLOCKED_LICENSE`。上游 `naodeng/dsh-qa` PolyForm Noncommercial 不因源码锚点/改名/删除 notice 而自动授权；未取得正式授权不得复制受限源码进银行交付。
- **E01 产品：** 虽然 pre-B06 原型的读取顺序正确，真实 Host-bound trusted principal、数据库快照、B06 API、R1 Mission 显式 project/batch 权威绑定及迁移未实施。当前 legacy Mission 没有正式绑定，必须 HOLD。
- **旧 RC7 Admin route：** `rc7_admin/server.py` 的现有 `api/missions/{id}/overview` 仍直接调用未加 Scope 的旧 `mission_overview(mission_id)`，默认 host=127.0.0.1；该路由是旧管理面，未被本 W0 E 预适配器引用。**这不构成本轮 E P1 修复无效**，但在任何银行 Host/远程部署开放前必须独立审查实际访问控制，不能把新 scoped port 的安全性外推到旧路由。
- **CI 与现场门槛：** 当前 A PR #84 是 Draft；同 HEAD 的 Q1、V3/V4、Windows、完整 RC7.2、L1/L2 工作流大部分 `skipped`。F 已独立复测 W0 Chromium，但不意味着完整现场 qualification；F02/F03/D04/F04、真实 32 worker、银行 ZIP 均 NOT_RUN。

## 六、F 最终决议

`W0_CONTRACT_REGRESSION_PASS`、`B108_DESIGN_WITNESS_ACCEPTED`、`C_W0_PROTOTYPE_ACCEPTED`、`E107_P1_PRE_READ_DEFECT_CLOSED_FOR_W0_DESIGN`。  
仍然 `W0_GLOBAL_F00_PENDING / W0_NOT_FROZEN / W1_W4_NOT_RUN / A02_BLOCKED_LICENSE / NO_RC7.2_MERGE / NO_BANK_ZIP`。

**严格结论：本轮 A/B/E 修复的精确代码和静态设计合同通过独立 F 复验；不代表完整产品功能、商业授权和银行现场发布已验收。**
