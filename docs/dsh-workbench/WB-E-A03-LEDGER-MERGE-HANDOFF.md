# E 组 WB-A03 签署账本的无冲突集成交接（FG19）

状态：**E 组候选补丁已提交；等待 A 组写回统一 08/09/10 并让 F 复核。不是 W0 冻结或 E01 QA_PASS。**

F 的 [独立报告](https://github.com/TongAITech/opencode-test-digital-employee/pull/85) 已证实 E 对 `WB-A03-CROSS-GROUP-SIGNOFF.md` 和 `08/09/10` 的并行编辑会与 B/D 的账本冲突（FG19），所以 E 把**完整 E 组原始增量**保存在本文件，再将这四个共用账本恢复至 A W0 基线，供 A 选择在统一集成 SHA 里按组累积，不允许以一方内容覆盖另一方。E 组不直接修改 B 的 source_verified_requirement_version、source_verified_link 规范，也不合并不合格的 B FG18 DDL。

- E W0 签署与实际 RC7.2 代码 SHA：见 [WB-E-A03-DESIGN-SIGNOFF.md](WB-E-A03-DESIGN-SIGNOFF.md)。
- E pre-B06 只读 DTO 原型：`tools/dsh_workbench/e_readonly_scope_prototype.py`；测试 `tests/test_dsh_workbench_e_readonly_scope.py`；状态仅 `PROTOTYPE_UNQUALIFIED`、`BLOCKED_DEPENDENCY_B06`。
- A 集成同一 HEAD 时必须把 **B 真实来源复合身份 / D 可信宿主主体 / E 控制命令、SSE、R1 只读、人审 / C 50 原子 UI** 的状态全部并入 08/09/10 与签署表；F 再审并运行真实预合并及反例。不应将本文件视为已写回总账。
- F 的 FG18 B 跨版本同 raw SST ID 反例仍红；FG17 原始 RC7.2 全量 CI 仍红；FG19 尚未能称全部关闭。
- W0 `NOT_FROZEN`；A02 `BLOCKED_LICENSE`；不构建 ZIP。

## WB-A03-CROSS-GROUP-SIGNOFF.md 建议合入文本

E 组行的状态：`E_DESIGN_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS / IMPLEMENTATION_QA_NOT_RUN`；引用 `WB-E-A03-DESIGN-SIGNOFF.md`，验证旧 `rc7_admin` 无 `/api/workbench/v1` 新接口；E01 等待 B06。**保留 B、D、F 的现有行与签名，不替换。** 请将签署源 W0 SHA `5dc514c50d6ae89dcd0c606cea949dda9e0e53fc`、E 运行分支最新 SHA 和 same-head CI link 一并写入。

## `08-CONSTRUCTION-PLAN.md` — E 原始候选增量

## 2026-11-09 E 组 A03 设计签署增量（施工分支提议，待 A/F 审查合并）
- 工单 WB-A03/E：`E_DESIGN_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS`；签署文档 `WB-E-A03-DESIGN-SIGNOFF.md` 固定审核 W0 源 SHA `5dc514c50d6ae89dcd0c606cea949dda9e0e53fc`。该状态只接受 W0 R1 只读/权限优先/命令幂等/NodeGate、人审、SSE+水位/证据哈希设计，不要求 W1 真运行以规避 FG15 环依赖。
- 工单 WB-E01：仍 `BLOCKED_DEPENDENCY_B06`，E 仅可提交来源审查、只读映射设计与 W0 协议反例；没有真实 B06 跨 Scope join、身份授权，不得 QA_PASS。WB-E02–E06 保持受依赖约束；E07 仍 OPTIONAL_NOT_ADMITTED。
- 代码/用例：`tools/dsh_workbench/e_contract_oracle.py` + `tests/test_dsh_workbench_e_contract.py`，运行 `python -m unittest discover -s tests -p 'test_dsh_workbench_e_contract.py' -v`；它们只验证内存设计 oracle，不是 HTTP/DB/R1/SSE/执行证明。E 分支最新 SHA/同 HEAD CI 由 GitHub 检查后记入 PR，绝不预填绿灯。
- R1/NodeGate/缺陷完整性、人审、真实签名租约、证据哈希、断线补放由 E01–E06/独立 F 继续实测；A02 BLOCKED_LICENSE / W0 NOT_FROZEN / 不构建银行 ZIP。

## `09-GAP-MATRIX.md` — E 原始候选增量

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

## `10-RELEASE-CHECKPOINT.md` — E 原始候选增量

## 2026-11-09 E 组来源审计及 W0 设计签署（需 A/F 复核）
- W0 PR #84 审核来源 HEAD `5dc514c50d6ae89dcd0c606cea949dda9e0e53fc`；F PR #85 仍 REVIEWED_WITH_BLOCKERS。E 施工分支 `work/dsh-wb-runtime` 对独立控制面协议形成 `E_DESIGN_SIGNOFF_ACCEPTED_WITH_IMPLEMENTATION_HOLDS`，详见 `WB-E-A03-DESIGN-SIGNOFF.md`。E 分支实际提交 SHA/CI 必须以创建 PR 后同 HEAD API 结果更新，不借用 A 的历史 success。
- 已核对真实 `rc7_admin/server.py`, `product_server.py`, `projection.py`, `rc6_runtime/truth.py`, `rc7_runtime/rc72_domain.py`, `rc72_linkage.py`, `models.py`, `truth_overlay.py`, `derived.py` 的 blob SHA；旧 HTTP 没有可信项目 ACL、正式命令、SSE 或 `/api/workbench/v1`；R1 是 JSONL 原子事实源；Evidence content_hash 可选。对应实现 HOLD 见 09。
- E 的 W0 独立设计测试包含跨项目/跨批次越权、请求伪 principal、幂等/修订冲突、事件水位/改包/撤权、hash 篡改、人审/NodeGate 假 PASS、Attempt 缺 lease/trace。**仅 W0 内存 oracle，不是 HTTP、DB、真实 SSE、持久 R1、行内 DSH 和 Agent Teams 现场验证。**
- WB-E01 BLOCKED_DEPENDENCY_B06；E02–E06 NOT_STARTED；E07 OPTIONAL_NOT_ADMITTED。A02 BLOCKED_LICENSE，W0 NOT_FROZEN，PR DRAFT，禁止合并主线或构建银行 ZIP；F 未独立 QA_SIGNOFF。

