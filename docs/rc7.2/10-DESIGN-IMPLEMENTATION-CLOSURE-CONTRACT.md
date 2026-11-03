# RC7.2 设计—施工对账及闭环验收增补合同

状态：FROZEN CONSTRUCTION ADDENDUM / DESIGN_INCOMPLETE / NO_FINAL_DELIVERY
首次审计基线：`8e95faacc5d9c874ac7dba27d71551fc3b48fa3f`（2026-11-04）。每轮施工必须重新读取 work/rc7.2 最新 HEAD、同 HEAD CI、R1/Evidence；不得把此 SHA 或本文件日期作为永恒的当前真相。

## 1. 合同权威与目标

本增补合同从属于 `docs/rc7.2/00..05`、`07`、`08`、`09` 及 `02-CONSTRUCTION-CONTRACT.md`，不修改冻结设计和业务分母。必须实现真实 ReleaseBatch 级自主测试数字员工：
ReleaseBatch → Requirement → SST → TestObligation → L1–L7 → Case → ETU → WorkItem → Attempt → Evidence。
Mission → MissionNode(N1–N10) → Delivery/Gate → Team Role → Fresh Worker → Tool/Skill → R1。
MissionNode≠Agent；Role≠Session；AgentTeams 是执行底座，R1/Evidence 是不可伪造的完成真相。Session/Captain 轮换不丢 Mission。

N1 环境/部署/模型/工具实测；N2 需求/BR/SR/TR/状态/正反例/边界；N3 代码影响/接口/DTO/DB/CodeGraph 真实图查询；N4 测试义务/Case/充分度；N5 数据发现、构造、验证、占用与回收；N6 冻结可执行契约；N7 真实前置/执行/业务断言/清理/证据；N8 独立故障分类、语义回退、修复与新 Attempt；N9 缺陷复现/RCA/修复/回归；N10 全投产批分母/Libra/缺陷/风险/证据收敛、独立终态 Gate。

测试充分度高于覆盖率数字；Token/模型经济优化不得削减测试义务。默认 ETU 3–8 Cases / ≤15 min，并依据 SST、代码切片、数据/Oracle/工具/权限、资源冲突及历史成功率动态拆分；细 WorkItem 不意味着每项一次完整大模型调用。

## 2. 设计验收证据分级（禁止主观百分比）

每项设计条款记：`id/source_clause/implementation_paths/product_entry/negative_tests/recovery_tests/source_sha/ci_run/r1_evidence/status/open_gap/field_boundary`。
只允许：
- NOT_IMPLEMENTED：无生产实现。
- COMPONENT_TESTED：组件和定向测试存在，未证明产品入口。
- PRODUCT_INTEGRATED：真实产品入口调用并保留 R1/失败路径。
- ENGINEERING_VERIFIED：最终同 HEAD 的相关完整链路、负面/恢复、继承回归及平台资格通过。
- FIELD_PENDING：工程已验收，真实行内能力/实机待测。
- FIELD_VERIFIED：真实行内证据、源/包身份一致且通过。
- BLOCKED：有真实阻断，必须保存原因与继续步骤。

设计实现率必须来自逐条权重及证据。没有条款总表和权重时，严禁将 96%、60% 或等权 C01–C12 估算当作正式实现率。分别报告「代码实现」「产品集成」「工程验证」「行内现场验收」四项，不把任一项冒充总体完成。

## 3. C01–C12 闭环施工矩阵

| 切片 | 基线判断 | 完成标准（必须真实执行并有否定/恢复证据） |
| --- | --- | --- |
| C01 | CODE_COMPLETE_CI_PENDING | 原 DataRef 的受控物理修复、独立复验及新 N5 Gate；旧证据/租约不可复活；冷恢复幂等 |
| C02 | CODE_COMPLETE_CI_PENDING | 修复后 N6 重编译；保留完整 Case/ETU/WorkItem/原失败 Attempt 分母；新签名 Attempt 真正重执行 |
| C03 | PARTIAL | N8 ENV/REQUIREMENT/ANALYSIS/DESIGN/DATA/EXECUTABLE/PRODUCT/PROVIDER/CAPABILITY/RESOURCE/FLAKY/UNKNOWN 分类；N1–N6 正确回边、STALE 影响链与无副作用重试 |
| C04 | PARTIAL | 有效产品失败→独立证据/复现/RCA→真实修复→新回归 Gate；非产品失败不得造 Defect |
| C05 | PARTIAL | N10 真实全 Requirement/SST/Obligation/L1–L7/风险/覆盖/Defect/Gap/Evidence 分母，覆盖修复→新 N7→新 Libra→N9→独立最终 Gate |
| C06 | PARTIAL | Data/Browser 全局写排他、租约续期、调用时权限、孤儿/UNKNOWN 效果、跨进程竞态和崩溃恢复 |
| C07 | PARTIAL | DSH AgentTeams 专业全角色/Tool/Skill 实际调用、严格授权/临时增权/委派、Provider/Captain/Session 新 Worker 接管 |
| C08 | PARTIAL | 产品固定入口完整 N1–N10 服务组合（含 N8/N9/N10 修复及重试）；重启从 R1 接续；禁止测试专用 callback 冒充产品 |
| C09 | COMPONENT_TESTED | 真实 BSK/CDP 教学录制→编译/基准/回放→人工批准→正式 L4/L5 消费；Browser 独占与业务谱系 |
| C10 | COMPONENT_TESTED | 确定性优先、批量复用/最小上下文/重试增量、真实或 UNKNOWN 用量、上海额度时窗、软预算、浪费防护、Q7 功能与经济双结论 |
| C11 | OPEN | Phase0–10 + GAP01–08 + CT01–26 条款映射；完整同源 Python 3.8/3.11、Windows/Linux、失败注入和继承回归 |
| C12 | OPEN | RC7.1 等价完整离线载荷、包内运行时/工具/插件、校验和、Win10 Git Bash/目标 Linux bash 冷解压启动、行内 Q3–Q9 工具与证据导出 |

每个 C 项必须有真正可调用生产实现 + 对应适用的合同/失败/恢复测试 + 同源验证 + R1 Evidence；仅有模块或 CI 数量不能关闭。行内 Field 专属条款真实现场验证前保持 FIELD_PENDING，禁止伪造 BANK_FINAL。

## 4. 本次 P0 首个真实施工断点

`8e95faacc5d9c874ac7dba27d71551fc3b48fa3f` 的 Construction Qualification run `41672056689` 已确认 Python 3.11 **1405 passed / 3 failed / 3 skipped**：
1. `test_rc72_n10_control.py::test_controller_with_repair_provider_still_refuses_ambiguous_mapping_without_side_effect`：歧义覆盖映射与 R1 重入副作用。
2. `test_rc72_native_coverage_rerun.py::test_n10_runs_fresh_full_n7_then_fresh_libra_and_closes_original_gap`：`N7_NODE_NOT_ADMITTED`。
3. `test_rc72_native_coverage_rerun.py::test_cold_resume_after_fresh_n7_before_libra_never_reexecutes_business`：`N7_NODE_NOT_ADMITTED`。

施工先抓取失败 job/log、追踪 N7 准入与 Node STALE/READY 重入、N10 控制层无副作用；只修真实根因并增补成功/拒绝/冷恢复/不重复 I/O 测试。不得通过放宽 N7 fail-closed、削减原始用例分母、删除测试或人工写 PASS 达标。同 HEAD Windows Q2/Portable PASS 仅证明工程候选包，绝不自动授予设计完成/最终交付。

## 5. 后续优先级与运行规程

P0：解决上述真实红灯，重新跑同源相关链路与全量 Construction/Platform。
P1（C05/C08）：正式 `rc72_mission_factory.py` 装配 NativeCoverageRepairService/NativeCoverageRerunService，N10 原位推进 fresh N7→fresh Libra→N9；签名来源和热/冷恢复都有实测。
P2（C03/C04）：N8 所有语义回边、专业缺陷 RCA/修复/回归、真实否定用例。
P3（C06/C07）：全专业角色 DSH 实际调用、Provider/Captain/Session 接管、全局资源租约/孤儿/未知效果恢复。
P4（C09/C10）：真实 Browser/BSK/4A 边界、Journey 正式消费、全部模型/Review/Retry 的经济/上下文调用点。
P5（C11/C12）：全条款对账、同源多平台 CI、完整离线载荷、干净解压/实际启动/证据、校验和、银行验收指南。

每段施工检查新 HEAD/CI/R1/Evidence→修改生产代码及独立回归→提交推送→同源 CI→更新条款状态；已有同 SHA 有效 CI 在运行则避免重复启动。发现新缺口写入台账，不缩小标准。
施工最终可交付前必须具备完整投产批成功与失败修复循环、N10 正式终态、不因 Session 丢失中断、真实工具与业务断言、全部仓库端工程验证和开箱即用离线包；用户搬包后再取得行内真实 Q3–Q9 现场证据，BANK_FINAL 在此之前保持 NO。
