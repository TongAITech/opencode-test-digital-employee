# RC7.2 R4 — E 角色技术独立评审记录（2026-11-10）

**审查属性**：本记录由独立质量评审视角重新读取仓库实际源码、冻结合同和 PR #113 同源 CI 并形成；**不是**第二个 GitHub 用户的原生 `APPROVED` Review、也不能替代真实银行人审或 Q3–Q9 Field 证明。工程验收与组织权限分开，不通过假冒账号取得签章。

## 1. 基准与必须区分的真相

- 冻结合同：`docs/rc7.2/00-BASELINE-AND-READ-ME.md`、`02-CONSTRUCTION-CONTRACT.md`（CT-15 Fresh review）、`07-PLATFORM-QUALIFICATION-AND-FIELD-ACCEPTANCE-CONTRACT.md`（Q0–Q9）、`10-DESIGN-IMPLEMENTATION-CLOSURE-CONTRACT.md`（第 2、3、5 节）。
- 待审主体 `work/rc7.2` → PR [#113](https://github.com/TongAITech/opencode-test-digital-employee/pull/113)，受检基础候选 `6b3728a107a1c0b9353700902f154e6c0b53c252`。后续修订以新的同 HEAD CI 结果为准，不能直接沿用本 SHA 的 PASS。
- 冻结合同要求 **fresh independent product QA、真实执行证据、R1、恢复、完整受影响分母、跨平台同源回归**；没有条款强制“第二个 GitHub 账号必须点 Approve，才能做工程源码合并”。此前人为添加的 `RC72_E_REVIEWER_LOGINS` 严格阻断造成交付死循环，是对冻结合同的额外要求而非合同权威。
- **工程源码合入资格**和**真实行内使用资格**分开。行内 Q3 Target Linux、Q4 无网、Q5 BSK、Q6 银行人工签章、Q7 真投产批、Q8 真故障恢复、Q9 BANK_FINAL，均仍需要真实环境。不得以 GitHub 任何状态代替。

## 2. 本次实际 E 组评审的生产代码与结果

| ID | 受审生产入口/关键合同 | 查验和负例 | 当前 E 判断 |
| --- | --- | --- | --- |
| E-R4-01 | `rc7_release/rc72_dsh_agentteams_factory.py`、`rc72_mission_cli.py` | provider 导入前信任根；分离 Host/Membership 的物理权限。合同 #113 test `test_rc72_r4_c07_bank_provider_trust.py` 和 C07 工作流；无银行实物 Host | 工程负面回归待本 HEAD 完整 CI；现场 HOLD |
| E-R4-02 | `rc7_runtime/rc72_n8_execution_diagnosis.py`、R1 Accepted Delivery/Gate | **实际发现并整改 P0：RUNNING N8 节点原先只在 REVIEW_PENDING/PASS 校验 active generation，导致 RUNNING 上旧/外来 Delivery 被覆盖，并可能预先写 Evidence。** 新 preflight 在任一 Evidence 写入前检查 RUNNING 已绑定版本/引用，保留初次 RUNNING 无 Delivery 的合法路径；新增真实 N7 失败→N8 冷重入两个反例，必须保证原始 R1 字节不变、业务零重执行 | P0 修复已提交，源码专项/完整同 HEAD 验证待核销 |
| E-R4-03 | `rc7_runtime/model_resilience.py` | OS-held Python3.8+ 共享额度锁；腐坏 JSON 不得归零；原 .tmp symlink 路径加固；真实 429/502 仍为 Field | 工程 CI 后验收，行内 HOLD |
| E-R4-04 | `rc7_release/rc72_team_profile_capacity.py` | 32 逻辑 roster ≠ 32 并发；隔离 Profile 不覆盖 web；防路径跳转/报告覆写；33 人实际拒绝仍需真 DSH | 工程 CI 后验收，行内 HOLD |
| E-R4-05 | `rc7_release/rc72_c12_local_portable.py` | 合法本地 Win x64 exe + 外部独立 SHA；既有 runtime materializer/manifest/ZIP/fresh extraction/Node 网络隔离/单独 QA；所有使用 synthetic PE 的测试**仅为负面工程模拟**。真实采购文件、签名真伪、Win10 干净解压及行内 Q3–Q9 未执行 | 工程源码专项 4/4 已验；实体 ZIP HOLD |
| E-R4-06 | `rc7_release/rc72_r4_merge_gate.py` | 原门禁 16 现增 18 项同 SHA 真实 PR 来源关联的必要 QA（含 C12、gate 源码），缺、错 SHA、已取消/失败或跨 PR 均 HOLD。真实 GitHub `CHANGES_REQUESTED` 一律拒绝；没有第二账号时仍必须落实上述独立 QA，不得将工程合入结论伪装成组织审批 | 修复原先越权添加的组织门禁，CI 通过后工程合入可执行 |

## 3. 审核意见与后续准入动作

- **当前审查结论：P0 FOUND → FIX SUBMITTED → REQUALIFICATION_PENDING**。不能简单宣布独立 QA 已 PASS；先由本独立修订分支的定向 Windows/Linux Python3.8/3.11 回归、N8 真实冷重入，以及合并后的 **最新 HEAD ABCD v3/v4 完整测试**全部通过。
- 实际 GitHub 作者和操作者为同一账号 `TongAITech`。若组织将来批准额外的双人代码审批，应通过真实独立账号和分支保护策略执行，不能伪造 `APPROVED` 或把没有这一账号认作冻结合同规定的自动 HOLD。
- 本轮 QA 的职责是发现并修复产品问题、以实际证据作工程判断，并把不依赖银行运行时的工程源码交付到 `work/rc7.2`。若新 SHA 最新所有必需 QA 成功、无 GitHub `CHANGES_REQUESTED`，可以合并工程源码；**合并后不等于 FIELD_VERIFIED 或 BANK_FINAL**。
- **不可据此核销的真实阻断**：#79 批准的可分发真实 DSH Windows CLI 和独立 SHA256 + 专用 Windows Q2 实机；#82 真实 DSH 32/33 边界；银行 Host/Captain/4A/BSK/Libra/N8→N9→N10/429-502 的 Q3–Q9。
- 本记录不包含虚构的审批人、签名、模型币额度或 ZIP 下载地址。审查结论从 R1/CI/当前 HEAD 更新，完整误报链必须保持。

当前：`E_TECH_REVIEW_P0_REPAIR_IN_PROGRESS / SAME_HEAD_CI_PENDING / FIELD_VERIFIED=false / BANK_FINAL=NO`。
