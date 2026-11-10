# F 组独立审核：A/B/C/D/E 第一轮 W0 施工（2026-11-10）

**最终结论：** `ROUND1_W0_CONTRACTS_PASS_WITH_E_P1_HOLD`  
**当前 A 集成候选：** `f870ad5efb7f3eda669703291900ce49e0a1d36f`  
**F 独立审查 PR：** [#111](https://github.com/TongAITech/opencode-test-digital-employee/pull/111)  
**F 精确源 CI：** [run #42748482654](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42748482654)

本报告区分“组内分支施工完成”“A 已集成”“F 独立通过”和“正式产品/现场 QA”。不把前者替代后者。

## 1. 当前源与集成关系

### 1.1 A 当前树中已经存在的组源

F 在 A 精确 HEAD 上执行 Git ancestry 检查，以下均为 A 的祖先：
- B #95: `50bd16d9e2c321eb5eaa21e96f663e89ae377b34`
- C #97: `b2a64df65661880808510d0486f6aefc70ca23df`
- D #90: `a332e6c575cac9d2b6ef0b2038615b276dcfa602`
- E #102: `26b2deaf5485193133e418da81982291c8056d64`
- A #103: `d082e71f7eb9260afe450203bd160f8cd9e65948`
- A01 provenance #110 merge: `afcda9a5737e181a1d1d5e08f926943664c594d5`

### 1.2 本轮 B/E 增量还没有进入 A 当前树

- B #108 HEAD: `b801c25bbec361e6a791c561d5a7dd0ec9440aaf` — PR 仍 OPEN。
- E #107 HEAD: `917f597d11daa1ae0bfc0caa07066bd45ad64ffa` — PR 仍 OPEN。

F 的当前 A job 验证这两个增量 HEAD 都不是 A@f870 的祖先。F 另外在独立 CI 工作目录把 B108、E107 临时叠加到 A@f870；该临时合并**不修改 A 分支，也不代表 PR 已合并**。

临时合并两次均由 Git `ort` 策略成功，临时 HEAD：
`9d38a7c04386f564ab168f73e26a6445b684a5db`

## 2. F 同源独立测试结果

[F run #42748482654](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42748482654)：

| 被测源码 | 测试 | 结果 |
|---|---|---:|
| A@f870 | 完整 W0 Python 合同（含 A01、FG16、FG18、D/E 合同） | **225/225 PASS** |
| A@f870 | C Scope / SourceFence / 50 项对账 Node | **30/30 PASS** |
| A@f870 | A01 双语来源与许可边界静态门禁 | **PASS** |
| A@f870 | CI admission 拓扑 | **13 workflows PASS** |
| A@f870 | 真实 Playwright / Chromium 六页十区原型 | **PASS** |
| B108 精确 HEAD | B 领域设计 + F FG18 定向反例 | **30/30 PASS** |
| B108 精确 HEAD | 完整 W0 Python 合同 | **210/210 PASS** |
| E107 精确 HEAD | E 分页/只读 R1 协议夹具 | **73/73 PASS** |
| E107 精确 HEAD | 完整 W0 Python 合同 | **211/211 PASS** |
| A@f870 + B108 + E107 临时 overlay | 完整 W0 Python 合同 | **234/234 PASS** |
| 临时 overlay | C Node | **30/30 PASS** |
| 临时 overlay | A01 locale gate / CI admission | **PASS / 13 workflows PASS** |

上述均为 F-owned 工作流直接 checkout 对应 SHA 后执行；不是复制施工组 PR 描述里的 PASS。

### 2.1 当前 A HEAD 的 Chromium 证据

F 在 A@f870 精确源码上重新运行 `run_browser_evidence.py`，artifact [#13731928325](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42748482654/artifacts/13731928325)，已下载并逐张目视检查：

| PNG | SHA-256 | F 目视结果 |
|---|---|---|
| `wb-c-w0-scope-ten-sections.png` | `6e64316cad45e7d43f1827ce1d45914f0560505539edc39bfaded5232443c8ae` | 十区导航、批次日期、需求/版本/SST 多选、演示 Scope、未接业务 API 的门禁表单和错误提示均可见 |
| `wb-c-w0-six-stage-board.png` | `d850b8a2e703cd473d80d21e91b332f40bfd31f005841af93b4620050825abd1` | 六阶段完整，清楚标注演示阶段，不冒充 NodeGate/N10 |
| `wb-c-w0-mobile.png` | `e50d647e763bbe120c82544233444fcae17b20922af6bf0360443850fa93a4f7` | 390px 窄屏导航折叠、卡片可读，无明显横向溢出 |

这是 W0 原型交互/视觉证据，不是 50 项真实产品功能 QA，也不证明 B06/DB/ACL/Host/R1 已接通。

## 3. 分组审查意见

### A 组 — W0 设计与来源门禁

**结论：W0 静态来源合同通过；双语产品实现未通过。**

- PR #110 已合入 W0 候选；重复 PR #109 CLOSED_NOT_MERGED，当前只有一个 canonical `WB-A01-LOCALE-SCOPE.json`。
- F 直接核对上游固定源 `naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b`：`public/i18n.js#L700-L722` 确有 currentLang/setLang/t；`public/app.js#L2085-L2091` 确有语言 picker；`app.js#L2048-L2094` 把语言和主题作为独立控件。许可证文件确为 PolyForm Noncommercial 1.0.0。
- 新增静态门禁在 A@f870 同源 PASS；负例覆盖 theme-only 冒充 i18n、源 SHA/许可证被改写、误标 MIT、复制源码、删除 handler 锚点、W0 demo 伪装 W1 QA_PASS。
- 改动仅增加来源索引、机器合同和测试；未把上游 HTML/JS/CSS/词典/素材复制进本仓库。

**未完成：** zh-CN/en-US 的真实六页/十区、Skill 双语文案与 fallback 仍为 W1 NOT_RUN；12 条验收案例不能计为产品通过。A02 `BLOCKED_LICENSE` 仍独立有效。

### B 组 — SST 来源与拆分状态

**结论：B108 W0 设计见证通过；不是 B01/B02 实现。**

- 正确地不再信任可变的 `brv.split_state`，而从经过来源 FK 约束的 BRV/BRVS 关系推导 SPLIT/UNSPLIT。
- 对 `sst_source_trace`、`authoritative_req_version`、`authoritative_link` 增加 SQLite fixture 中的 UPDATE/DELETE fail-closed 见证，防止已验证来源被非空伪造 ref/revision 静默改写。
- 原 FG18 同 raw SST ID 在不同 system_version 合法复用语义保持；F 在 B108 精确 SHA 重新跑过 FG18。
- B PR #108 只改 B-owned 测试与 W0 设计见证文档，没有新增生产 PostgreSQL DDL、HTTP API 或 B06 服务。

**W1 必须补齐：** PostgreSQL 同一一致性快照、并发/CAS/锁、来源修订的正式 supersession/退役审批与审计、真实迁移/回滚、B06 API 和权限测试。当前 blanket append-only trigger 没有证明合法来源纠正/退役的业务流程；不得把 SQLite trigger 直接当作最终生产方案。

### C 组 — 六页面/十区 W0 原型

**结论：C W0 原型在 A@f870 复验通过。**

- 六页面（五主导航 + 项目详情入口）、十区、六阶段业务看板、四层 Scope 多选关系、fail-closed 表单和 SourceFence 负向演示保持。
- F 在当前 A HEAD 重新跑 Chromium 并逐张检查三张图；C 原有 FG23 修复仍有效。
- C01/C02 真实业务 CRUD、B06 API、持久化、SSE、DSH 对话/历史/Skill 安装、完整 50 项功能仍 NOT_RUN。

### D 组 — DSH Host 兼容与安全探针

**结论：W0 只读探针合同保留；不是现场 Host 资格。**

- 当前 A@f870 完整 W0 suite 覆盖 D 的 loopback/response-schema 负向合同。
- `wb_d_host_probe.py` 只访问明确的 127.0.0.1/::1 GET，拒绝 redirect、非 loopback、错误 session ID、超长/非 JSON 响应，并显式把 bank DSH version/field_verified 标为 UNVERIFIED/false。
- 该探针不创建会话、不发 prompt、不写配置；models/skills/commands/attachments/cancellation/history/teams/leases/quota 均未探测。

**未完成：** 行内 DSH 1.18.26 真机资格、Host trusted principal、会话隔离、Agent Teams 真实创建/并发、Windows Git Bash 离线资格均 NOT_RUN。

### E 组 — B06 多页来源修订栅栏与 R1 只读消费

**结论：E107 新增分页来源漂移反例通过；存在一个 P1 安全设计阻断，E01 不可准入。**

正向部分：
- 新增同一 `(requirement_id, system_version_id)` 的 BRV `source_link_ref + source_revision` 跨 SST 行/跨页一致性检查。
- 同父来源 ref/revision 漂移、同页矛盾均在读取 R1 前拒绝；不同 system_version 的独立来源修订仍允许。
- F 在 E107 精确 SHA 独立跑 73 个 E tests 与 211 个完整 W0 Python tests，均 PASS；A+B+E 临时 overlay 的 234 个测试也 PASS。

**P1 — R1 Mission 未授权前读取完整详情：**
- `tools/dsh_workbench/e_b06_page_consumer.py` 的 `r1_preview_after_full_b06_scope()` 在完整 B06 项目/批次 Scope 后调用 `projection.mission_overview(mission_id)`，之后才把 overview 交给 `r1_preview()` 校验 Mission 的 project_id/batch_id。
- 真实旧 `rc7_admin/projection.py::mission_overview(mission_id)` 只按 mission_id 查询 `rc7_mission`，随后按 mission_id 查询相关 tasks/evidence/executions；该查询本身没有 project_id/batch_id ACL 过滤。
- `test_old_mission_without_batch_identity_is_not_inferred` 还明确断言：缺 project/batch 的旧 Mission 被拒绝前，projection 已被调用一次。
- 因此，获准访问项目 A/B1 的调用者如果传入其他项目的 mission_id，当前适配器会先把该 Mission 及相关记录读入进程，再因 Scope 不匹配拒绝结果。当前仍是 pre-B06 原型，尚无正式 /api/workbench/v1 路由，因此 F 没有声称存在已上线的可利用接口；但若把当前调用顺序直接接入产品，就会在校验前读取跨项目数据，违反“先授权再读取”的安全边界。

**整改要求（E01 前置）：**
1. 提供在 R1 数据访问边界执行的 scope-filtered Mission read，例如按可信 principal + project_id + batch_id + mission_id 做原子授权查询；
2. 或至少先执行只返回最小 Scope 身份的受限查询，匹配成功后才读取 tasks/executions/evidence；不能先调用现有无 Scope 的 `mission_overview`；
3. 对跨项目 Mission、跨批次 Mission、缺失旧绑定、伪造 mission_id 增加负向测试，断言拒绝时相关明细查询计数为 0；
4. 保留 B06 每一页均由 Host-bound trusted principal 授权、签名 cursor、R1 不写入的约束。

在此之前，E107 可视为来源漂移的 W0 协议增量已测，但**不能签 E01 安全准入或 IMPLEMENTATION_QA_PASS**。

## 4. 文档/发布门禁审查

1. `00-PRODUCT-BASELINE.md` 及 02/03/04/05 有“W0 候选冻结”表述，而 08/09/10 明确 `W0_NOT_FROZEN / F_GLOBAL_SIGNOFF_PENDING`。建议统一为“候选基线/候选设计已整理；正式 W0 冻结尚未发生”，避免误读为 F 已冻结。
2. A01 50 项仍 50/50 NOT_RUN；中英文 W1 12 案均 NOT_RUN。
3. A02 PolyForm Noncommercial 商业授权仍 BLOCKED_LICENSE；来源只读核对不授予商业复制、修改、分发或银行打包权。
4. B01/B02 PostgreSQL、C01/C02 真实 UI/API、E01 B06/R1、D Host 1.18.26 现场资格均未通过；W2–W4 的 F02/F03/D04/F04 及银行现场证据仍未完成。
5. A PR #84 当前仍 Draft，未合并 `work/rc7.2`。其同 HEAD run #42744959613 的 `w0-contracts` 成功，但其余高成本/平台资格 jobs 为 skipped；skipped 不能算 PASS。F 本轮额外跑了当前 A@f870 的 Chromium，但没有运行 Q1/Windows/完整 RC7.2 资格矩阵。

## 5. F 最终裁决

| 项目 | F 结论 |
|---|---|
| A01 来源/许可边界静态合同 | PASS |
| B108 W0 来源/拆分设计见证 | PASS_WITH_W1_HOLDS |
| C97 W0 原型 | PASS |
| D90 W0 只读 Host 探针 | PASS_WITH_FIELD_HOLDS |
| E107 来源漂移防护 | PASS_WITH_P1_R1_SCOPE_HOLD |
| A@f870 当前 W0 L0 | PASS |
| A+B108+E107 临时联合兼容性 | PASS |
| E01 正式安全准入 | BLOCKED |
| W0 全局冻结 | NOT_ACCEPTED |
| A02 商业授权 | BLOCKED_LICENSE |
| RC7.2 主线合入 / 银行 ZIP | NOT_APPROVED |

**总体状态：** `ROUND1_W0_CONTRACTS_PASS_WITH_E_P1_HOLD` / `W0_NOT_FROZEN` / `NO_RC7.2_MERGE` / `NO_BANK_ZIP`。

F 接受 A 当前 W0 静态合同、C 原型及 B108 的 W0 设计见证；E107 的分页来源漂移修复有效，但必须先修正 R1 Mission 未授权前读取完整详情的问题。五组“施工一轮”已有可复核产物和测试，不等于五组产品实现或银行交付验收完成。
