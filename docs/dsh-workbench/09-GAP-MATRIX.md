# W0 缺口账本
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
