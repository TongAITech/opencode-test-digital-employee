# 工程缺口账本

## 当前权威状态（2026-11-11）

- 当前代码集成检查点：`d31d8ef70229942215060bd58ef3b593b1b95be1`（PR #84）；本账更新会产生新文档HEAD，实际继续前重新核对远端与同SHA checks。
- W0设计冻结源`a73ed52d`及F #121保持历史结论。已正向合入RC7.2新基线`edaf9290`，未修改主线。精确`7586a80c`的ABCD-v4完整源码/Chromium及四组Ubuntu/Windows原生资格共五job全部SUCCESS（run42847197247）；F联合报告#173。该结论不转签d31或现场Windows离线安装。
- 本轮d31本地回归：真实PostgreSQL222/222、真实PG→浏览器6/6、目录键盘/撤权3/3、Node43/43；轻量561项中269执行通过、292明确跳过。A复跑F测试不构成新独立F签署；目录修复独立F源16fe658d、报告777b8bd7（#178）已集成。
- d31远端同SHA：W0 run42859333314、真实浏览器run42859326708均SUCCESS；本次新台账HEAD另核检查，不转签旧SHA。
- 六类草稿表单、B07七kind与E02读取为组件集成；旧legacy API隔离P1、目录键盘/撤权P2已按独立报告修复。完整项目编辑、看板业务状态、日历年月日视图、正式R1资产映射及生产纵向链仍未完成，不能把只读目录当项目管理全功能。
- HTTP断连P3候选`47950777`独立PR #180：A真实socket4/4、真实PG断连提交恢复1/1通过，尚未合入，F_REVIEW_REQUIRED。F任务额度不可用，不用A自测替代独立验收。
- 正式Mission绑定生产缺口已复现：正式创建无project/batch、typed更新丢extra；PR #175初稿、B #176及D #179有required details。新协议V2 PR #181源`957874d6`仅候选，B/D/E/F复签PENDING，未改R1/冻结模型。E03仍BLOCKED_FORMAL_CONTROL_API，B08/E04–E06等依赖未齐。
- 现场统一FIELD_NEEDS_BANK_TRANSFER（用户确认行外无法访问）；真实DSH/SSO、Windows离线、实际并发/资源恢复、F01–F04与LICENSE_RELEASE_APPROVED未通过。RELEASE=NOT_APPROVED；#84保持Draft，不生成最终交付ZIP。

## 初始与历史检查点（仅追溯，以当前状态和最新同SHA证据为准）

按真实结果更新，不得把未做的任务写已完成。

| GAP | 级别 | 现状 | 下一动作 | 负责人 |
|---|---|---|---|---|
| WB-G01 | BLOCKER | naodeng/dsh-qa 为 PolyForm Noncommercial；未见银行商业授权 | 获取权利人书面授权，或保持完全独立实现 | A |
| WB-G02 | P0 | 行内 DSH 宿主与开源版兼容性未现场验证 | Windows Git Bash 宿主探测 | D |
| WB-G03 | P0 | 当前 RC7.2 SST 合同未显式建模 system_version 关联 | 增量关联结构、迁移和反例契约 | B/E |
| WB-G04 | P0 | RC7 admin 查询 API 不等于正式 Mission 控制 API | 设计权限/幂等/状态门禁接口 | E |
| WB-G05 | P0 | 六页面十个分区尚未形成实际产品验收矩阵证据 | 原型/独立实现逐项对账 | C/F |
| WB-G06 | P1 | ZSeven QA Node>=24.11，驱动需另装；银行离线兼容性未知 | 先可选化和能力探测，再决定上线 | E/D |
| WB-G07 | P0 | 同批次多需求/多版本/多 SST 真实数据未导入验证 | 通过真实样本完成 Scope 和追踪回归 | B/F |
| WB-G08 | P0 | DSH Teams 目标 32 的宿主并发/租约证明待查 | 同时核验可配置、实际并发、模型配额三层 | D/E/F |
| WB-G09 | P1 | RC8 中央数据接口与工作台语义尚未锁定 | 引入稳定 ID 与事件合同，避免未来重复开发 | A/E |

## 2026-11-09 新增施工缺口
| ID | 级别 | 当前可核查事实 | 关闭门槛 | Owner |
|---|---|---|---|---|
| WB-G10 | P0 | 原版功能对账新增 27 项，但新工作台 UI/实测未完成 | C 实现六页/十区，F 功能录像/接口/反例审查 | C/F |
| WB-G11 | P0 | 旧 rc7_admin API 不等于新 /api/workbench/v1；目前只有设计 oracle | B/E 正式 ACL/关联/命令/事件与 R1 同源验收 | B/E/F |
| WB-G12 | BLOCKER | PolyForm Noncommercial 商业授权缺失，W0 许可 Gate 尚未联入正式打包 | 权利人书面授权或可审计原创实现，F/法务检查文件清单及许可证 | A/F |
| WB-G13 | P0 | 首轮 30 PASS/1 FAIL/1 ERROR 已由 fd9e60e W0 32/32 修复、F 契约层核销；3fc09ca W0 38/38 定向通过，新 HEAD 必须另查 | 新 HEAD 同 SHA 轻量 CI 全绿 + F 独立签收 | A/F |
| WB-G14 | P1 | SSE replay/命令幂等/关联数据库仅纯函数验证，非真正产品 API | E/B 提交事件持久化/事务/ACL/断线恢复负向测试 | B/E/F |

## F 组 PR #85 审查缺口逐项核销表（A 组事实记账，不能代替 F 签署）
| F GAP | 当前实际状态 | 后续关闭门槛 | Owner |
|---|---|---|---|
| FG01 | A01 仅原子功能登记候选；PRODUCT_NOT_IMPLEMENTED | C/F 对原版入口、目标按钮、真实截图/API逐项核验 | A/C/F |
| FG02 | A03 日期迁移/HOLD 已明确合同；无运行迁移 | B/E 真迁移可逆、历史一致性、回滚证据 | B/E/F |
| FG03 | 复合 PK/FK/UNSPLIT 设计；无数据库 | B 完成事务、外键及 422 无副作用 | B/F |
| FG04 | Scope ACL/授权优先级设计；无正式 HTTP | B/E 真 join/权限/游标/负向验收 | B/E/F |
| FG05 | 追踪 R1 来源协议设计；无 API/UI | E 对齐正式 R1 Evidence、双向 trace | E/F |
| FG06 | 宿主 DSH1.18.26/Teams32 未现场实测 | D/E/F 真实 OS/宿主/并发日志 | D/E/F |
| FG07 | BLOCKED_LICENSE | 有效商业授权或原创来源链及独立合规审查 | A/F/法务 |
| FG08 | Windows Git Bash 离线整包 NOT_RUN | D/F 真实断网免安装冷启/恢复 | D/F |
| FG09 | fd9e60e 28/28 同 SHA success；3fc09ca W0 38/38 success | 新候选 HEAD 全矩阵+真实功能现场证据 | A/F |
| FG10 | R1 NodeGate/原 QA Gate 映射仅设计 | E/F N10+人审不可伪发布实测 | E/F |
| FG11 | CONTRACT_CI_PASS（F 核销 fd9e60e） | 正式 LICENSE/G14 不因此自动关闭 | A/F |
| FG12 | CONTRACT_CI_PASS（F 核销 fd9e60e） | A01 原版及 UI 功能完整度仍待 F | A/F |
| FG13 | 新增 Scope/事件纯函数 Oracle；无持久 API | B/E 真事务、重启、事件/数据库证据 | B/E/F |
| FG14 | BLOCKED_LICENSE；manifest 无独立来源证明 | 可审核独立原创 + SBOM + 打包前真实门禁 | A/F/法务 |
**WB-F00 = F_INITIAL_REVIEWED_WITH_BLOCKERS，W0_NOT_FROZEN，W1 依赖仍受控。** 原 F 初审和历史 HEAD 的 FAIL 不得被篡改；修复后状态用同 SHA 证据单独注明。

## WB-FG15（P0）— F 组新发现的 W0/W1 门槛环
- **原始现象**：A03 W0 设计签署要求 B 的真实数据库 422 rollback/重启、D 的真实宿主日志、E 的正式 API/R1 Evidence；但 B01 W1 依赖 A03，形成 A03→B01→A03。
- **本次整改**：WB-A03-CROSS-GROUP-SIGNOFF.md 改为 B/D/E 只对 **W0 设计合同字段、合法关系、状态/权限/幂等/事件协议与负向验收预期签 DESIGN_SIGNOFF**；真实 DB/HTTP/Host/R1 证据归 W1+ IMPLEMENTATION_QA，F01 独立 INTEGRATION_QA，F04 FIELD_QA。08 工单依赖拆分，新增静态 DAG 防回归脚本/负向测试。
- **A 当前结论**：CODE_FIX_SUBMITTED / F_DESIGN_RECHECK_PENDING；不能代签 B/D/E/F，不能宣称 F 接受、W0 冻结或产品实现。后续 F 以新 HEAD 核销 FG15，B/D/E 提交设计签署或异议。
- **授权仍阻断**：独立 `LICENSE_RELEASE_APPROVED` 为银行打包必需条件，PolyForm Noncommercial 的商业权利或可审计独立原创 SBOM 仍 BLOCKED_LICENSE。

## WB-FG16（P0）最新整改记录
F 在审查 `4349ee6` 时查出 W4 DAG 放行可以跳过 F02 六页十区原能力回归、F03 真实自主闭环及 D04 Windows 离线资格：虽有 F04+LICENSE，实际缺全部所需先驱。原 F 回归测试见 `work/dsh-wb-qa` 分支 `tests/test_dsh_workbench_release_dependencies_f.py`。
**A 代码整改已提交待新 HEAD CI/F 复核**：完善 W2/W3/W4 全量必需 Gate DAG，F04 严格依赖 F03+D04，最终 BANK_RELEASE 强制 F02 + F04 + A04 + A02 LICENSE；validator 计算传递依赖集合并校验（非仅看直接字段），新增移除/绕过任一前置的负向测试。
状态 = CODE_FIX_SUBMITTED / CI_PENDING / F_RECHECK_PENDING。真实 DB/R1/Host/Windows/授权继续 NOT_RUN/BLOCKED，不得写 RELEASE_QA_PASS。

## A01 源码入口来源整改 / FG16 后续门禁
- A01：原子清单 50 项，35 项基于 naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b 的 app.js 具名函数和 index.html DOM 固定行号建立**候选来源锚点**，另外 15 项明确为新增目标、无原版入口。仍缺 C/F 对每个 UI 按钮和行为的逐行与实际操作验证；状态 SOURCE_ANCHOR_CANDIDATE / F_REVIEW_PENDING，不可写 UI PASS。
- FG16：F 在 A 4349ee6 发现 W4 Gate 路径可绕过 F02/F03/D04；A 提交 16740b7 + 80efa1b 的发布依赖闭包与负向测试。新 HEAD W0 契约测试已有 58/58 success 历史日志，**F 独立验收和完整 CI 按最新 SHA 复核**；不能因为静态门禁完善就宣称真实自主测试/离线验收。


## B 组独立缺口登记（2026-11-09；W0 源 80efa1bfa585fe29a5939c889d5b5a08e4f742ed）
- WB-BG01：DESIGN_SPEC_SUBMITTED，来源系统命名空间、复合 PK/FK、SST 来源合法边、日期唯一/历史、Scope 关联查询、403/409/422 与迁移回滚规则详见 B 签署文档。只证明设计，不关闭 F 的 FG02–04/13 实现缺口。
- WB-BG02：W1_NOT_RUN，PostgreSQL 真实 DDL/事务/锁与 SQL 查询、HTTP/分页、重启无数据串扰缺真实证据。B01–B06 + F 真实验证才能核销。
- WB-BG03：MIGRATION_HOLD，银行 BUSINESS_TZ/原始来源租户身份/同日冲突、Legacy→batch_id 映射、双向计数及回滚演练未拿到；B08 必须 fail-closed。
- WB-BG04：DEPENDENCY_BLOCKED，D/E 签署及 A/F W0 冻结尚缺，FG16 由 A/F 独立核销，B 无权自行关闭。

- WB-BG05 / P0 / DESIGN_RED_FIXED_CI_PENDING：首次 B CI job 129170552735 = 7/8，发现 BRV 无权威需求—版本连边 FK 时可插入 R2/VB；新增 source_verified_requirement_version 复合 FK 并扩展 T1 三版本/五 SST。源提交 d0a38886048bd2183ef364295e6204eb6a742257，新 HEAD CI 结果待核实。此为 B 设计缺口，不能代替真 PostgreSQL/HTTP 验收。

- WB-BG05 DESIGN_CI_PASS：红测 8a7a116 初轮 7/8 → 修复 source_verified_requirement_version FK 后 7b916e2 同 HEAD run 42620657398 job 129171616901 **8/8 B witness + 66/66 shared contracts OK**。仅 DESIGN_SPEC 修复，真实 PostgreSQL/HTTP/F QA 依然 OPEN/NOT_RUN。F 独立接受仍待办理。


## C 组 W0 未关闭缺口（2026-11-09，增量候选）
| GAP | 级别 | 可复核现状 | 关闭证据与责任 |
|---|---|---|---|
| WB-CG01 | P0 | 六页面/十分区和按钮/表单/导航/错误、原版 50 项已形成原创设计对账，**真实正式 UI 未实现** | WB-C01/C03/C04/C05 实际实现，F02 原子 UI+API+截图回归，C/F |
| WB-CG02 | P0 | 演示 Scope 9/9 单测通过，但真实 B06 复合关系/ACL/分页、事件续传未接 | B06 真实服务与 C02 宿主/跨分区负向联调，B/C/F |
| WB-CG03 | P1 | 本地浏览器受策略阻断历史保留；同 SHA 465d GitHub W0 原型真实 Chromium+3 截图已通过并上传 artifact 13675694071；**F 尚未独立复核** | F 审查原型截图来源与正式原版功能差距，正式 F02 全功能 UI 回归仍未跑，C/F |
| WB-CG04 | BLOCKER | W0 尚未由 A/F 接受，许可 `BLOCKED_LICENSE`，跨组设计签收 PENDING | 不启动 C01/C02 正式任务，A/F/法务 |
C 组局部纯函数测试不能抵扣 FG01、FG07、FG10、FG13/14 或 F02 QA；原版受限源码不得进入银行交付。



### C 组 W0 新增反例与待核销缺口（2026-11-10）
| WB-FG23 C Browser CI trigger | C_CODE_FIXED / EXACT_HEAD_CI_PASS / F_RECHECK_PENDING | C SHA `7fa4d0c` 删除 Chromium PR 的 08/09/10 账本触发路径，保留 30 Node、浏览器、workflow_dispatch 与非 Draft；[run 42733902992](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42733902992) 三检查成功 | F 重新运行 A+B+C 同源 183/183 Python W0 CI 与路径策略负例，最终 A/F W0 签收 |
- C #97 源 15d37ec 同 SHA W0 Node 30/30、真 Chromium + PNG、B→C 30/30 已 PASS；F02 真业务仍 NOT_RUN。
| GAP | 现状 | 核销条件 |
|---|---|---|
| WB-CG05 异步响应跨 Scope | W0_PROBE_CI_PASS（SHA 15d37ec），epoch + 项目/批次/修订拒绝旧响应；正式 SSE/ACL 未接 | B06、E SSE、D Host 实际并发/撤权回归及 F02 |
| WB-CG06 业务真相不可伪 PASS | W0_PROBE_CI_PASS（SHA 15d37ec）；401/403/404/409/422/503、缺 Evidence/Human Review、STALE/UNKNOWN 不作 PASS；十项单测 CI 待新 HEAD | R1 真 Evidence/人审/控制面 HTTP + F02 |
| WB-FG22 A-owned CI admission | F #101 独立旧源曾发现错误码负向断言红，C 不代修 A CI | A 最新 HEAD 同源 L0 + F 独立复核 |

## 2026-11-09 E 组 W0 合同审查的实现 HOLD（非新功能已通过）
| E GAP | 级别 | 可复核来源与实际缺失 | 关闭门槛 | owner/status |
|---|---|---|---|---|
| E-HOLD-01 | P0 | RC7.2 ReleaseBatch 尚无项目+业务日+多版本 SST 稳定关联 | B06 真复合 join、来源迁移与端到端权限校验 | B/E：BLOCKED_DEPENDENCY_B06 |
| E-HOLD-02 | P0 | `rc7_admin/server.py` 默认旧 GET/POST 没有宿主可信 principal/项目 ACL | D 宿主绑定 + E 控制 API 401/403/404/422 反例 | D/E：NOT_IMPLEMENTED |
| E-HOLD-03 | P0 | 旧 POST 仅 test-cases，未实现命令幂等持久落库/控制面租约 | E03 正式命令、冲突无副作用、冷重启 | E：NOT_IMPLEMENTED |
| E-HOLD-04 | P0 | Evidence content_hash 可选，旧检验只覆盖特定 artifact，不验证所有 Attempt/Defect | E06/B07 真实 hash/trace/reviewer/修复回归 | B/E：NOT_IMPLEMENTED |
| E-HOLD-05 | P0 | R1 seq 不等于每批次受权 SSE 水位，缺原子快照+补放 | E04 真实项目批次隔离、断线/撤权/gap 实测 | E：NOT_IMPLEMENTED |
| E-HOLD-06 | P0 | NodeGate reviewer worker/session 不等于银行发布人审批 | E06 正式人审事件+N10 Gate 双门槛 | E/D：NOT_IMPLEMENTED |

E 对 W0 设计合同签署已记录于 `WB-E-A03-DESIGN-SIGNOFF.md`（源 W0 HEAD `5dc514c...`），可运行的 W0 Python 反例见 `tests/test_dsh_workbench_e_contract.py`。仅设计层 ACCEPTED_WITH_IMPLEMENTATION_HOLDS；FG04/05/10/13 与 B/D/F 签收状态未据此关闭；W0 NOT_FROZEN / LICENSE BLOCKED。

## F 组跨组独立审查 FG17–FG20：A 集成候选修订记录
| FG | F 原始发现及证据 | 本次 A 集成处置（未获 F 认可前不写 CLOSED） |
|---|---|---|
| FG17 P0 | A 5dc514c Chrome/CDP job #129169423859 对 POST /api/save 200 缺网络录制，2907 pass/1 fail/4 skip | CI_BLOCKER / ROOT_CAUSE_PENDING，保存失败，需对症修复并验证同 HEAD 全矩阵 |
| FG18 P0 | B 704c86a SQLite DDL 全项目 SST source_key UNIQUE，F 原始 job #129218336677 报 IntegrityError | A 候选改版本级 UNIQUE、追加反例并复制 F 原测试到联合树，待 B 复签/F 独立审查 |
| FG19 P0 | B/C/D/E 分支分别绿色但 F job #129218849736 内容合并冲突 | A 以 B/C/D/E 原始父提交组成候选统一 merge commit，08/09/10 逐增量、A03 B/D/E 签署语义合并；待验证共同 SHA 和 F 再审 |
| FG20 P1 | C 原版功能清单旧 47 与 A01 50 不一致 | C 候选文档校正为 50 / 35 O+A / 15 N；不声称 50 个行为已实测 |
| FG16 | F 上轮独立验收 38 Gate 发布依赖闭包，2/2 F 反例和 19/19 A DAG 成功 | STATIC_DESIGN_FIX_ACCEPTED，仅设计层，不代表真实 W4 发布 |
遗留：B06 真实关联、E01 HTTP/R1、C01 完整页面、D 行内 1.18.26、W2–W4 真 Evidence/FIELD QA 全部未验；A02 BLOCKED_LICENSE、W0_NOT_FROZEN、PR #84 Draft，禁止银行 ZIP 或发布。


## WB-FG18 / P0 / B 组修复提交（原独立红测不覆盖）
- F 独立复现：https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42634316547/job/129218336677，跨版本复用同一上游 SST-100 原始来源 ID 触发 B 旧 DDL 项目级唯一冲突，违反 B 设计声明。
- B 修复：UNIQUE(project_id,version_id,source_system,source_key) + UNIQUE(project_id,sst_id)，新增来源 trace 表及四组多版本关联/非法错配/重复拒绝/跨项目反例。当前=CODE_SUBMITTED / CI_PENDING / F_RECHECK_PENDING；同 SHA 真验收后才可评估关闭。
- W0 未冻结、W1 真 PostgreSQL 与 API NOT_RUN。FG17（A 全矩阵）、FG19（ABCDE 预合并）、FG20（C 清单）不属于 B 自行核销范围，保持 F 阻断。

- WB-FG18 CODE_FIXED_DESIGN_CI_PASS（历史修复 SHA eb48d161bd5c7caa29733fccfabc44654a376dd6）：B 14/14、W0+B 72/72、原 F pinned-SHA 测试 1/1；run 42637588144 job 129229772001。F 审查意见仍待，W0 NOT_FROZEN；当前提交只是追加已经成功的可审计记录。

## 第二轮 B/C/D/E 精确源 SHA 统一验收候选（F 独立复核必需）
- B PR #89 `98bac426a35063a306f4eaa4b43c80cf0a0a1745`：FG18 由 B 组自行修复，SQLite 约束新增全项目内部 sst_id UNIQUE、同系统版本来源键 UNIQUE，另设 `sst_source_trace` 保留 namespace/revision/source_ref；F 原始同 raw SST ID 跨版本反例需在当前联合树重跑。B 仍为 DESIGN_SIGNOFF，仅 W0。
- C PR #92 `4394f7fef7f19035220ea2398af9ff9f19a4b865`：新增 50 个 feature_id 差异表、15 项 Node 测试、原始证据与 B→C 隔离 Git 合并成功；这不是全功能 F02。
- D PR #90 `a332e6c575cac9d2b6ef0b2038615b276dcfa602`：13/13 基线合同、宿主 allowlisted manifest 检测、真实 loopback GET 负向，近期 D 同 SHA 30/30 局部 CI；不是行内 DSH1.18.26 FIELD PASS。
- E PR #91 `8401ab85cefb2876ce4451252d3d9a6e7d14704c`：新增旧 Admin R1 的只读合成/拒绝测试、B06 source-verified 合法关系 DTO 原型；无 /api/workbench/v1、SQL、SSE 或执行。E 新共享合同改为独立 `WB-E-A03-LEDGER-MERGE-HANDOFF.md`，A 上次已保留 E 原 08/09/10 增量。
- 上述改动需要 **统一合并树同 HEAD CI 和 F 独立复核**。FG17 CDP 定向测试仍须真实通过，不可通过 W0 轻量 CI 代替完整 CI。W0 NOT_FROZEN；BLOCKED_LICENSE；不推送运行主线、不出银行 ZIP。


## C follow-up PR #97（原始 W0 对账证据保留；旧 FG 状态由下文 A 最新段覆盖）
### C 组 W0 原型深化后状态（2026-11-10）
| GAP | 当前状态 | 本轮进展 | 未关闭条件 |
|---|---|---|---|
| WB-CG01 六页面/十分区 | W0_PROTOTYPE_EXPANDED / W1_NOT_STARTED | 十区逐个增加领域字段表单与原生必填校验，提交 fail-closed；六页导航与六阶段保留 | C01 正式 Host/API 实现、全量原版交互与 F02 |
| WB-CG02 Scope | W0_MULTISELECT_PROBE / B06_BLOCKED | 多需求/多版本/多 SST 关系联动、无效组合原子拒绝、级联清理、只读快照 | B06 真实 PostgreSQL/API/ACL/分页/SSE + C02 联调 |
| WB-CG03 浏览器证据 | W0_PROBE_CI_PASS / F_VISUAL_REVIEW_PENDING | SHA `d4863ba` 同 HEAD 20/20 Node、真实 Chromium 逐区表单/多选、3 PNG artifact 13693719815；B→C 合并探针 15/15 | F 对新 SHA 视觉复核；正式 F02 UI/API/Host QA |
| WB-CG04 设计/许可门禁 | BLOCKED | F 仍 W0_NOT_FROZEN；A02 BLOCKED_LICENSE；FG17/FG21 仍 OPEN | A/F 正式 W0 冻结、授权或原创来源审计；RC7.2 merge gate |

## 2026-11-10 A/F 最新复验与未关闭 GAP（不覆盖历史原始失败）

| GAP | 新证据 | 当前判定 | 正式关闭所需 |
|---|---|---|---|
| FG17 | F #101 的 b385e04：Ubuntu Py3.8 真 C09/adapter 31/31 + 五次 1/1，Py3.11 31/31 | TARGETED_BROWSER_RECHECK_PASS；过去的 F toast flaky 仍保留 | 新联合 SHA F 独立复验、Q1 Windows/Linux Py3.8 与 L2 同 SHA 完整准入 |
| FG18 | F #94 原始跨版本 raw SST 反例 1/1；B #95 领域差量复签 | DESIGN_RECHECK_PASS / B_DESIGN_SIGNOFF_RECONFIRMED | W1 正式 PostgreSQL 迁移/来源合法 join/持久回滚/F QA |
| FG19 | A b385e04 已融入 R4 主线，B/C/D/E 旧来源在祖先链，B #95/C #97/E #96 更新中 | SOURCE_INTEGRATION_CANDIDATE | 新 HEAD CI + F 核对差量父链/三账本完整性 |
| FG20 | C 原版 50 项与原型扩展 20/20 Node+真实 Chromium 源 d4863ba | W0_PROTOTYPE_CI_PASS / F_FOLLOWUP_VISUAL_REVIEW_PENDING | F02 真原版全交互、DSH Host/API 和 Evidence |
| FG21 | PR #84 `mergeable=true`，原 dirty Git 冲突消失 | SOURCE_MERGE_CONFLICT_RESOLVED / CI_UNSTABLE | 新 HEAD 所有真实 required gates、F 独立批准、合法许可 |
| FG22 | F #101 164 项 1 FAIL；A b385e04 159 项 1 FAIL，`5bba94c` 修测试期望并添两反例 | CODE_FIX_SUBMITTED / NEW_HEAD_RECHECK_PENDING | W0 同 HEAD 完全通过 + F 独立重跑，不删真实 Q1 反例 |
| R4-32 | F #101 源码定向 100/100 | ROSTER32_SOURCE_PASS / ACTIVE4_DEFAULT | DSH1.18.26 真实 32 名册/资源并发/断线恢复/Windows Git Bash 现场 |

权限、合同门禁：B06 由 DSH Host 会话派生可信 principal；response source_refs、records、next_page_cursor 单一规范，E 仅读来源验证和 R1 拥有权。B01/B02/E01/C01/C02 **不准**以 W0 见证伪报实现 QA。BUSINESS_TZ 与真实来源映射 HOLD；A02 非商业许可与原创来源审计 BLOCKED_LICENSE；W0_NOT_FROZEN、W1–W4 NOT_RUN。


## A/F FG23 最新 Source CI 反例整改与 W0 准入差量（2026-11-10）
| GAP | 新源/真实证据 | 当前状态 | 退出条件 |
|---|---|---|---|
| FG23 C 账本触发 Chromium | F #104 A+B+C 183/1 FAIL；C #97 `b2a64df` 仅移除 08/09/10 pull_request.paths，C 同 SHA 3/3 jobs PASS | C_CODE_FIXED / F_INTEGRATED_RECHECK_REQUIRED | A 最新单源 CI 通过且 F 独立确认，不能把 C 局部绿灯当 F 全局核销 |
| FG18 SST 来源追踪 | B #95 `50bd16d` 来源复合 FK、空白/跨版本冒用负例；26/26 SQL + FG18 PASS | W0_DESIGN_PROVENANCE_CANDIDATE | F 同源负向签收；W1 真实 DB+ACL+事务资格独立核销 |
| E01 B06→R1 完整消费 | E #102 `26b2dea` Py3.8/3.11 各68/68；禁止未读完所有页就 R1/假完整 Scope | W0_PROTOCOL_CANDIDATE / E01_IMPL_NOT_RUN | B06 真 PostgreSQL/HTTP/Host ACL+R1 独立 QA |
| FG17, FG21, FG22 | F FG17 定向真实 Py3.8 PASS，PR84 R4 Git merge conflict resolved，A200 W0 180/180 Node20/20 | PREVIOUS_HEAD_CI_EVIDENCE / NEW_HEAD_RECHECK | FG17 新源资格、FG21 所有 required checks、FG22/23 F 同源核销 |
| C01/C02 50功能与source fence | C W0 原创六页十区模拟验证、30 Node、3 PNG；source fence 只验证只读 preview/失败拒绝 | W0_PROTOTYPE_ONLY / F_VISUAL_REVIEW_PENDING | 真实 DSH Host/B06、完整 50 原子 F02 UI/API/Evidence |
| A02 授权与交付 | PolyForm Noncommercial 上游源码不得商业复制；来源审计/法务尚未通过 | BLOCKED_LICENSE | LEGAL_LICENSE_RELEASE_APPROVED + F04 FIELD_QA + W1-W4 正式 QA |


### FG23/FG18/E/C 最新统一树 GAP 证据（A `db1026fd`）
| 项目 | 同源核验 | 退出状态 |
|---|---|---|
| FG23 高成本 Chromium PR 路径误触发 | A 同 SHA Python 206/206、Node 30/30，CI policy 13 workflows PASS；原 F #104 183/1 FAIL 证据仍在 | A_CODE_FIXED/UNIFIED_L0_PASS；F_INDEPENDENT_RECHECK_PENDING |
| FG18 来源可信追踪/跨版本 SST | 已纳入 B #95 `50bd16d` 新 trace↔authoritative_link composite FK、原 FG18 负例；合同 Python 同源 PASS | W0_DESIGN_RECHECK_PENDING_F；PostgreSQL W1 NOT_RUN |
| B06/R1 全分页安全 | E #102 `26b2deaf` 逐页消费、游标/版本/SSE 并未建立真实 API；同源 W0 Python PASS | PROTOCOL_CONTRACT_ONLY / E01_REAL_NOT_RUN |
| FG20/ScopeReadFence | C #97 `b2a64df` W0 六页十区 30 Node 合同 PASS；浏览器已在 C SHA 用真实 Playwright+PNG 跑通，但 A 新 SHA Browser L1 尚未运行 | W0_PREVIEW_ONLY / F_VISUAL_SIGNOFF_PENDING |
| FG21/FG17/FG22 | FG21 Git 冲突已解；FG17 Py3.8 定向证据是旧 A b385e；FG22 新 A 旧源码错误码回归已修且单源再绿 | L2+F 同 SHA full qualification 仍 required |
| 许可/现场发布 | BLOCKED_LICENSE、DSH Host1.18.26/W1-W4 FIELD_QA_NOT_RUN | RELEASE_BLOCKED/NO_BANK_ZIP |


## F #106 核销与 A01 双语设计范围 GAP（2026-11-10）
| GAP | F 新结论 / A 新施工 | 当前状态 | 剩余退出门槛 |
|---|---|---|---|
| FG23 C Browser PR 账本误触发 | F #106 同 SHA `a3555b1` 独立 206 Python、30 Node、真实 Chromium+3 PNG，负向注入仍拒绝账本路径 | **FG23_CLOSED（F 签收）** | 真实 PR synchronize 仅 ledger-only 的重复 Chromium 成本仍需独立监测，不可混淆发布 L2 |
| FG20 50 项原版范围 | F #106 `FG20_DESIGN_RECONCILIATION_PASS`，35 O/A + 15 N 原版候选身份一致 | DESIGN_RECONCILIATION_PASS / PRODUCT_50_NOT_RUN | W1 完整真 UI/API/DB/Host，F02 逐项 QA |
| A01-LOCALE P05-03 / X01-01 | A `KEEP_ZH_EN_W1_REQUIRED`，默认中文且保留英文；12 项负向/许可/状态 Oracle；W0 中文仅模拟 | A_SCOPE_RECORDED / F_DESIGN_REVIEW_PENDING | F 确认 W0 设计完整，W1 C/D 实现中英文/主题/Skill，F02 正反例，许可另签 |
| W0 F00 & A02 | C W0 原型通过 **不等于 W0 总体冻结**，PolyForm NC 授权未取得 | W0_NOT_FROZEN / BLOCKED_LICENSE | F00 对 A01+A03 正式 DESIGN_ACCEPTED；法务/F 许可和 W1–W4 真证据不能预填 |

## 2026-11-10 A01 语言行为来源真实性缺口增量
| GAP | 状态 | 证据/退出条件 |
|---|---|---|
| WB-A01-LOCALE-PROVENANCE | SOURCE_ANCHOR_CORRECTION_SUBMITTED / F_RECHECK_PENDING | 上游 `i18n.js#L700-L722` 和 `app.js#L2085-L2091/#L2048-L2094` 精确入口可复核；A01 两条 feature 行补录。负向测试须证明 theme-only/错误 SHA/删除 i18n/伪许可证无法变绿；F 针对新 SHA 复核 |
| WB-A01-LOCALE-W1 | DESIGN_SCOPE_RETAINED / IMPLEMENTATION_QA_NOT_RUN | 使用 A 唯一 `WB-A01-LOCALE-SCOPE.json` 保留 zh-CN/en-US、12 条 W1 反例；C01/C02 及 D Host/QA Skill 两语真实验收未运行 |
| WB-A02 | BLOCKED_LICENSE | PolyForm Noncommercial 适用商业权利或独立原创及第三方许可证法务审核未批准，不得复制原版文件、不得打包 |
| W0_DESIGN_FROZEN | NO / F_GLOBAL_SIGNOFF_PENDING | F #106 只签 C 原型与 FG23；新 A01 原版源锚点核对不能代签 F 全局冻结或 W1 施工准入 |

## 2026-11-10 A01 来源证据 W0 merge 检查点
| GAP | 最新状态 | 验证与未关闭条件 |
|---|---|---|
| WB-A01-LOCALE-PROVENANCE | `DESIGN_NEGATIVE_CI_PASS / F_NEW_SHA_RECHECK_PENDING` | PR #110 MERGED W0 `afcda9a`；同 SHA 225 Python/30 Node/13 workflow gate PASS，原版 `i18n.js`/language-picker 关联锚点、来源 SHA、PolyForm 许可负向经机器检查；正式英文 UI、Host 和 QA Skill 双语尚未实施 |
| WB-A01-LOCALE-W1 | `12_W1_ACCEPTANCE_CASES_NOT_RUN` | 保留 zh-CN/en-US 两模式，默认中文；全六页十区、Skill 词条、无障碍、Scope 和 Human Gate 不变量须 C/D W1 真实验收 |
| WB-A02 | `BLOCKED_LICENSE` | 上游源码仍非商业许可，原始入口核查不授予银行商业复制、分发或打包权 |
| WB-F00-W0 | `F_GLOBAL_DESIGN_REVIEW_PENDING / W0_NOT_FROZEN` | F #106 仅签 C 原型及 FG23；需 F 审阅 A @afcda9a 及正式全局设计门禁后才可讨论 W0 冻结 |

## F #111 安全阻断及 B/E 最新设计差量（2026-11-10）

| GAP | 真实来源与回归证据 | 当前准确状态 | 退出条件 |
|---|---|---|---|
| E107-P1 R1 跨 Scope 预读取 | F #111 旧 `917f597` 真实调用 Mission 关联详情早于 project/batch 授权；E 新 `a04933f` 改为 scoped identity-only lookup+0 related queries on reject，E 同源 239 Python、Py3.8/3.11 各82 PASS | `E_CODE_FIX_SUBMITTED / F_NEW_SHA_SECURITY_REVIEW_PENDING`，**不能写 P1 CLOSED** | F 在新 A 联合树重跑跨项目/跨批次/legacy missing scope、unscoped fallback 禁止和查询时序，不把生产 R1/Host/Postgres ACL 当已验 |
| B108 Split/Source Audit | F #111 已签 `B108_W0_DESIGN_WITNESS_PASS`，BRV/BRVS verified relation 推导拆分态，来源审计不能静默改写，B 原同 SHA 210 Python | `W0_DESIGN_WITNESS_ACCEPTED / B01_B02_NOT_RUN` | W1 PostgreSQL 事务一致性快照、合法来源纠正 supersession 事件、CAS/回滚/HTTP/ACL 经 F 实测 |
| 旧 00/02/03/04/05/07 冻结字眼 | F #111 指出 W0 候选冻结误读风险；A 改为 W0_DESIGN_IN_PROGRESS/NOT_FROZEN，反向门禁 | `SOURCE_DOC_STATUS_CORRECTED / F_REVIEW_PENDING` | F 确认 A01+A03 整体设计合同并签 F00 后才能设正式 FROZEN |
| FG20/FG23 C 原型 | F #106 签 C W0 prototype/FG23 closed，F #111 重验 A f870 真 Chromium | `C_W0_PROTOTYPE_PASS / 50_PRODUCT_NOT_RUN` | C01/C02 正式代码 + F02 真 UI/Host/API，不得由 demo 顶替 |
| W0 总体/许可 | F #111 `ROUND1_W0_CONTRACTS_PASS_WITH_E_P1_HOLD`，法务许可未出 | `W0_NOT_FROZEN / A02_BLOCKED_LICENSE` | F00 DESIGN_ACCEPTED + 真实 W1-W4 QA + license grant/clean-room审计各自独立门禁 |

## 2026-11-10 A 同 HEAD CI 证据误判防护
| GAP | 状态 | 工程改动与关闭条件 |
|---|---|---|
| WB-A00-CHECKRUN-ATTEST | CODE_SUBMITTED / NEW_SHA_CI_PENDING / F_REVIEW_PENDING | f6aa541a 精确 GitHub 15 checks=1 success/14 skipped，不能称 ALL_GREEN；新增 w0_checkrun_evidence.py + 负向 unittest；新 HEAD GitHub W0 tests 与独立 F 审查后再调整，人工核验 required-status 保护配置 |
| E107-P1 | F_NEW_A_HEAD_RECHECK_PENDING | E 的 mission_overview_scoped 先查身份后读 details、拒绝时零关联读取，必须由 F 在最新 A 联合树独立核销，W0 合同 CI 不代替安全审查 |
| WB-A02 | BLOCKED_LICENSE | PolyForm Noncommercial 商业权利未批准，不复制受限源码到银行交付 |
| WB-W0 | NOT_FROZEN | 50 项正式功能 NOT_RUN；W1–W4/场景/现场/商业授权独立门禁，不得从 check-runs 的 skipped 或 W0 success 推导 QA_PASS |


## 2026-11-10 总控接管：精确源与 PostgreSQL 增量审查
- 远端 PR #84 接管源 `5c1a5f4e10ed9f79bb523516d340ff21f58c72f0`；RC7.2 `87f956f1388f58beabf7116c937fd6fda5fae2ca`，未修改运行主线。
- 该源 check-runs：w0-contracts SUCCESS，14 SKIPPED；跳过不是产品 PASS。F #112 仅审查 f6aa541，不转移到本源。
- F 独立复验 PR #114，报告提交 `58297959c401106c6f6f5f6221c8f91841c1a5c7`：本地 Python260/260、Node30/30、隔离 F scope-first9/9；未执行 PostgreSQL/Windows/浏览器；未签发 F00。
- PostgreSQL 正式业务库增量合同正在独立分支施工；B/D/E 技术评审 PR #115 为 REVIEW_IN_PROGRESS，不能当作原组签署。增量必须绑定实际 SHA 再审，不继承历史签署。
- BLOCKED：PostgreSQL 增量 B/E/D 审查及最新设计 HEAD 的 F00 接受；W0_NOT_FROZEN。W1 产品实现不得借本轮合同测试宣称完成。
- A02_BLOCKED_LICENSE / 50_PRODUCT_NOT_RUN / FIELD_QA_NOT_RUN / NO_RC72_MERGE / NO_BANK_ZIP。


### PostgreSQL 增量工单评审证据
- PR #116 合同源 `2343e0ff9f08f306da52b38428d7640b3409d526` 已写入02/06；真实本地 Python 合同260/260；同源 GitHub w0-contracts SUCCESS，run 42773079476/job129685163960。不是 PostgreSQL 产品验收。
- PR #115 独立技术审查更新 `1e777123`：B/D/E职责视角 ACCEPTED_FOR_DESIGN，无新增 W0 P0/P1；不冒充历史团队新签署，F 最新联合设计源接受仍待。
- PR #114/#115/#116 均为独立分支审查材料，尚未集成冻结；下一步核对并集成合同及报告，再对精确集成 HEAD 回归/F复验。W0_NOT_FROZEN，真实 PostgreSQL/Host/Windows/现场 NOT_RUN。


## 当前权威检查点：W0_DESIGN_FROZEN（2026-11-10）
- 冻结设计源：a73ed52d88425d5e60cbe07467a0ab5cbed5f708；F PR #121 / 2506b189 正式 WB-F00_DESIGN_ACCEPTED，无剩余 W0 设计 P0/P1。
- B #119/371f43f0、D #118/9e4f6c98、E #120/278a5a58 分别正式签署；00–07/A03/locale/DAG自14534d61字节未变。WB-A01_DESIGN_SIGNED / WB-A03_CONTRACT_SIGNED / WB-W0_DESIGN_FROZEN，仅设计门禁。
- 冻结源同SHA W0 CI SUCCESS：run42776373441/job129695699938；F独立263 Python/30 Node/9安全反例/33 D组件通过。14 SKIPPED不算PASS。后续账本HEAD不继承这些测试数字。
- WB-D01 COMPONENT_TESTED，现场探测GET_UNAVAILABLE，BLOCKED_FIELD；不是IMPLEMENTATION_QA_PASS。
- 下一就绪工单：B01/B02真实PostgreSQL、C01六页十区双语骨架；各组独立worktree/PR。B06未完成，C02/E01仍BLOCKED_DEPENDENCY_B06。A唯一维护08/09/10。
- 真实PostgreSQL实例准备中；50产品功能、Host/Windows/现场QA未完成。A02_BLOCKED_LICENSE / NO_RC72_MAINLINE_MERGE / NO_BANK_ZIP。W0冻结绝非最终交付。


## W1 首轮真实实现验收（2026-11-10）
- WB-C01 PR #122 原源98292caf：Node3/3、Chromium1/1自测通过但F #123/ac5774a6独立发现P1无尾斜杠入口空白、P2键盘重绘丢焦点。保留真实红灯；修复源c699965f46276db30fcf1e11b4aa5e834b5dfcbd已补双入口/焦点反例，F复验中，未记QA_PASS。
- WB-B01/B02 PR #124 源617636424877f24a582d1c55e374553131c3d85a：真实PG本地12/12自测，远端同SHA w0-contracts PASS但postgres-identity FAIL（run42781440846/job129712176958）。状态CODE_COMPLETE/CI_BLOCKED，B正修复，F独立验收中；本地绿不能覆盖远端红。
- W0冻结源a73ed52d的设计签署保持；本轮实现尚未通过集成门禁，不能转移旧设计PASS。B06未实施，C02/E01 BLOCKED_DEPENDENCY_B06；D01 BLOCKED_FIELD；50功能/F01-F04/Windows/现场/许可证发布门禁未完成。
- 下一步：核销两组真实失败→F精确源接受→A唯一集成→同HEAD回归；不合RC7.2，不出银行ZIP。


## W1 B01/B02+C01 联合集成回归检查点（2026-11-10）
- 精确联合源cf11501866d7538167463f2c9e9c2951b67f57e0，真实父源B175efda6、C785c5a3c及F128/0ec59f7b独立复验报告已集成。F接受B01/B02数据库组件与C01导航骨架组件，不代表整个C01实施资格、50功能或F01/F02/现场通过。
- 原C路由/焦点缺陷已F复验关闭；B原外层BEGIN身份残留P1经真实PG反例关闭。旧CI认证与浏览器依赖失败保留，未删除反例。
- 本联合HEAD真实本地PG13/13、Node C01 3/3、Chromium1/1通过；通用合同276发现/263执行/13无DSN明确跳过，单独PG结果不得与skip混计。
- 同源远端：postgres-identity SUCCESS run42784572619/job129722479349；w0-contracts SUCCESS run42784572885/job129722480157；手动正式浏览器 SUCCESS run42784606902，headSha精确cf115018。不是历史源PASS转移。
- B01/B02 COMPONENT_QA_ACCEPTED / MERGED；C01 NAVIGATION_COMPONENT_ACCEPTED / MERGED。B03/B04依赖已满足启动真实关联施工，B05/B06顺序依赖；C02/E01仍BLOCKED_B06。C03/C04需业务资产HTTP合同/API，先补接口评审，禁止占位数据冒充实现。
- D01 BLOCKED_FIELD；真实DSH1.18.26、Windows/离线/实际AgentTeams并发/恢复、F01-F04、A02许可证发布门禁仍未满足。NO_RC72_MAINLINE_MERGE / NO_BANK_ZIP。


## B03/B04 与 Scope 准备组件集成（2026-11-10）
- B03/B04源c94a045da61683347999ed32619db7796766c07e获F130/6359121d独立组件接受：真实PG45/45、F攻击回归20/20，旧缺驱动导入红灯保留并修复。
- A联合源6dc36e2fd92919a469003d97662f5c72ace02b19真实PG45/45，远端PG SUCCESS run42789747684/job129739856195、W0 SUCCESS run42789747479/job129739851635。B03/B04 COMPONENT_QA_ACCEPTED/MERGED，B05已启动，B06尚未实施。
- C准备组件源46006d31由F132发现共享可变Scope引用P1；修复65f7d139109ff0080a910cd9441ac5f02bb0ceaa获F133/483f2026复验关闭，仅客户端状态机准备组件接受。当前A集成422d9433ea1b3438978a94b334b39c89389cc7fa，Node24+F负例1共25通过，远端新联合检查仍须同源核验。
- Scope组件未接UI或不存在的B06；C02/E01保持BLOCKED_DEPENDENCY_B06，不能宣称服务端权限或十区真联动已验收。后续B05接受→B06真实HTTP/DB→C02/E01纵向接入。
- 50项完整产品、真实DSH/Windows/离线/AgentTeams现场、F01-F04及许可证发布门禁仍未满足；不合RC7.2、不出银行ZIP。


## B05 正式组件验收与 B06 启动（2026-11-10）
- B05精确c8972dbdbd136f7da03061ee0463a47d68de6cb9获F135/a5343617独立接受，真实PG68/68、F新增攻击2/2；SST版本限定来源/内部身份唯一/BRVS可信连边/权限审计恢复组件通过，非完整产品验收。
- A联合111bc4806bb39f7bb44d857610d3b17878b23eac真实PG68/68通过；同源远端PG SUCCESS run42795365470/job129759080212，W0 SUCCESS run42795365782/job129759085711。B05 COMPONENT_QA_ACCEPTED/MERGED。
- B06正式启动真实PG Scope HTTP/授权/完整分页/签名游标/修订权限失效；尚未验收。C02与E01仍依赖B06验收，准备组件不能视为真实纵向链路完成。
- DSH现场/Windows离线/正式命令/AgentTeams真实并发及恢复/F01-F04/许可发布门禁继续未满足，不合RC7.2、不出银行ZIP。


## B06 组件集成与 C02/E01 准入（2026-11-10）
- B06精确f144f1a1492d457f0121dd77e23fdd8c474e4268获F138/20aa0068独立组件接受，真实PG/HTTP100/100、F新增攻击2/2；同源PG SUCCESS42796663148/job129763472502、W0 SUCCESS42796663127/job129763472380。
- A联合e901b2d8bda2e53f12a3c90028deeb54071f6741本地真实PG/HTTP100/100通过并推送，远端联合检查须另核；B06 COMPONENT_QA_ACCEPTED/MERGED，仅PG/HTTP Scope组件，不代表真实DSH认证或W1整体通过。
- C02正式日期/需求/版本/SST十区Scope联动与E01 R1只读适配已按组件依赖准入，隔离worktree/PR施工中。Host provider缺失默认503；测试provider明确fixture，不可替真实宿主现场。
- R1 Mission/Attempt/Evidence/NodeGate仍唯一运行事实，E01必须最小Mission身份校验先于明细，不可回写正式事实。50完整产品、F01-F04、DSH现场、Windows离线及许可发布门禁仍未满足，不合RC7.2、不出银行ZIP。


## C02/E01 与统一产品入口集成（2026-11-10）
- C139/cdfeb458获F141/3619b2e2组件接受：真PG/HTTP/Chromium1/1+Node24；E140/c00ca464获F142/b5e6f747组件接受：真PG/HTTP/持久R1 35/35+旧E82+F2。不改正式R1，Evidence只读校验，NodeGate UNKNOWN/发布HOLD。
- A联合574b54e1754c2c7b6de876ce4feb3c0f2870a12c本地E35/35、真浏览器1/1，远端PG/W0 PASS及专属E01 run42807484469、浏览器run42807492097精确同SHA均SUCCESS。首次PG venv缺playwright未执行保留，复用有效环境后重跑通过，未作产品失败或假PASS。
- 统一入口144/66a57fab获F148/905d036b接受：同源真PG/HTTP/Chromium1、E35、路由隔离攻击1通过，同源5CI成功。product_server静态界面与B/E校验handler同源，缺Host provider默认503、无旧API回退；旧admin兼容。
- A最新联合97917526bb875c276ee5541d0fb377c11f0d9580同源真PG/HTTP/Chromium1/1、通用合同398发现/264执行/134未配置PG明确skip；远端联合检查另核，不继承旧源数字。
- B07增量合同143/22fc88ff及D39e7bccd/E44828bf0职责签署已集成，里程碑真库/HTTP首slice独立施工中，尚无CRUD通过声明。
- C02/E01/统一入口仅COMPONENT_QA_ACCEPTED/MERGED，F01整体、真实Host认证/DSH1.18.26、Windows/离线、实际并发恢复、50完整产品及许可发布门禁未完成，不合RC7.2、不出银行ZIP。


## 现场环境访问约束（用户确认，2026-11-10）

用户确认行外无法访问真实DSH/Windows，必须搬运行内。现场状态统一 FIELD_NEEDS_BANK_TRANSFER；停止行外尝试真实现场访问，fixture仍只是组件测试。接续操作和证据字段见 BANK-TRANSFER-ACCEPTANCE.md。只在集中回归候选点准备搬运材料，不提前生成最终银行交付ZIP，不跳过D01/D04/F04或许可证门禁。


## 里程碑 API 与正式 Mission 图联合集成（2026-11-10）
- B07首milestone PR152/49063661获F153/072694aa接受：真实PG/HTTP141/141+F2。初源历史Scope可追加连边缺陷已加不可变link_count/延迟约束并复验；其余六kind尚在独立施工，B07整体不关闭。
- E02旧72dd3f9f由F150真实发现同批次跨Mission NodeGate引用P1；新1136bea2完整node/delivery/gate/ETU/workitem/attempt谱系校验，获F154/161398b4复验关闭，真PG/HTTP/R1 35/35及谱系攻击通过，原失败保留。
- A精确联合76d6d9c8583df1ed74e44a40b16b4f0d6351a1b5解决business_http共同路由冲突，保留资产与Mission查询：本地真PG141/141、E02 35/35、同源浏览器1/1、Node24；轻量475发现/265执行/210明确未配置PGskip，不混作真库结果。
- 同联合源远端：PG SUCCESS42815706578/job129828136986、W0 SUCCESS42815706397/job129828135567、专属E01/E02 SUCCESS42815837222、正式浏览器 SUCCESS42815845374。SHA均核实76d6d9c8。
- C里程碑UI PR156/a7fd0827正在F独立验收，未集成或记C03/C04整体通过。E03调查确认缺通用正式控制面，BLOCKED_FORMAL_CONTROL_API；依赖提案PR155，未写R1或伪accepted。E04–E06继续按正式依赖受控。
- 新增第三方实物审计THIRD-PARTY-WORKBENCH-AUDIT.json：Psycopg3.2.13安装元数据为LGPL-3.0-only（纠正旧or-later表述），依赖固定本次已验版本并记录许可证哈希；不是最终Windows包SBOM或LICENSE_RELEASE_APPROVED。
- 真实宿主与Windows FIELD_NEEDS_BANK_TRANSFER，接续见BANK-TRANSFER-ACCEPTANCE.md；不合RC7.2、不出最终银行ZIP。


## 草稿资产扩展与界面恢复缺陷（2026-11-10）
- 六kind后端4c3c30a1获F160/47574ed4独立组件接受：真实PG/HTTP190/190、F2；A联合d0ee15ad9f97ad1990a8eba43dcccab18d3071b3本地190/190，远端PG SUCCESS42822241991/job129850419532、W0 SUCCESS42822241919/job129850418701，精确同SHA。R1引用保持UNRESOLVED，未实现可信正式映射或B07整体关闭。
- C156/a7fd0827由F157发现未知提交刷新丢request_id；修复da1a7e82后原问题关闭，但F159/884d132f实际发现Alice旧pending在合法Bob会话重放产生新资产。当前C156不接受/不集成，必须B/D/C主体绑定context修复后新SHA复验。
- 最小context增量D/C6661e80d、B确认仅恢复主体域绑定；不授权限、不替代CSRF/ACL/真实SSO。后端和界面分支修复中，token缺失/换key/换主体保持HOLD，不以当前Bob context替换原请求。
- E03依赖提案0e8259cd已集成仅作DESIGN_REVIEW_PENDING；独立设计复核任务被平台内容检查中断，未产生F设计接受。E03仍BLOCKED_FORMAL_CONTROL_API，不新增伪accepted或第二状态机。
- FIELD_NEEDS_BANK_TRANSFER；正式Host、Windows、F01-F04及发布门禁未通过，不构建最终银行交付包。


## 主体绑定恢复修复集成与集中回归（2026-11-10）
- B161/3fc3c1a4与C162/37a025fa获独立F本地报告1728c731接受。A仅代推F原提交并建PR164，未代写结论；F本地16PG/HTTP、四browser、Node24、原F159主体切换反例通过。F157未知刷新与F159主体切换两P1关闭，旧失败记录保留。
- 每资产写入先验证可信Host/mutation及原opaque write-context，再进入业务连接；context不授权限，CSRF/ACL仍独立。未知pending固定原context/request_id，不以Bob或新key的context替换；Alice恢复同key原回执无重复。
- A联合d0fbd1ee9164b05d0516f24b44807a211bd2b860本地PG/HTTP206/206、真实browser4/4+原F1591/1、Node24；轻量540发现/265执行/275明确PGskip。该源远端PG SUCCESS42826010909/job129863371353、W0 SUCCESS42826011099/job129863372191、专属E SUCCESS42826008090与browser SUCCESS42826017673，headSha均独立核对d0fbd1ee。
- 首milestone详情/日历同资产生命周期与主体恢复COMPONENT_QA_ACCEPTED/MERGED；六kind界面在独立分支，不代表C03/C04完整完成。B07可信R1引用映射仍UNRESOLVED，未授全B07完成。
- E03提案B审查163/4c02b8af已集成，要求精确幂等/FK/CAS/fencing及丢权威回执的恢复查询。E03仍BLOCKED_FORMAL_CONTROL_API；正式writer跨进程原子准入尚待设计，不以实例锁或PG本地journal冒正式控制事实。
- FIELD_NEEDS_BANK_TRANSFER；最终交付/真实宿主/Windows/实际并发及F01-F04/许可证门禁未通过。


## A 发现同源挂载后的遗留私有路由缺口（2026-11-10）
- A在ebce951e本地临时R1/loopback真实复现：显式workbench_handler的Host provider返回None，新workbench Scope为403，但旧/api/missions/M_FOREIGN/overview仍200且含fixture Mission。没有访问银行网络或生产R1。
- 状态P1_FIX_IN_PROGRESS，E独立分支修复显式工作台模式的遗留私有读写默认拒绝，保留独立legacy模式及非敏感meta兼容。safe CLI不能因缺失R1而创建空文件；固定源后须F独立验证。当前尚未签署此缺口关闭。
- 六kind表单与只读项目目录仍在独立验收/施工，FIELD_NEEDS_BANK_TRANSFER及正式命令阻断不变。
