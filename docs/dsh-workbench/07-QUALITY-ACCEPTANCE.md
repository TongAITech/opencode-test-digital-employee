# 独立质量验收合同
状态：W0_DESIGN_IN_PROGRESS / W0_NOT_FROZEN；W0 候选合同待 A01/A03/F00 正式签署；W1–W4 实现与现场 QA 未运行；A02 BLOCKED_LICENSE

## 证据优先级
同提交 HEAD 的实际测试、R1 正式 Evidence、真实宿主操作及截图 > 代码/PR > 施工账本 > 聊天自述。任何一个按钮能点击不能证明业务闭环。

## 核心验收包
QA-01：六页面、十个分区与原始交互逐项对账，缺一个即不完整。
QA-02：多需求/多版本/多 SST 关联 T1–T10 正反向测试。
QA-03：同一个 Scope 在需求→代码→用例→质量任务→缺陷→报告中保持一致。
QA-04：跨批次/跨项目数据访问拒绝；错误关联不会污染资产。
QA-05：看板可拖动但不能绕过 N10 人工审批；未执行结果不会显示 PASS。
QA-06：DSH 模型、附件、历史、Skills、命令、会话恢复、原生 QA。
QA-07：Agent Teams 断线接管、Worker 签名租约、资源冲突、模型截断、幂等重试。
QA-08：L1–L7 至少针对已接入的能力真实执行，检查前置、步骤、Oracle、Evidence；未装工具的级别必须明确 BLOCKED。
QA-09：BSK 与可选 QA Replay 浏览器互斥，拒绝未知结果伪绿。
QA-10：Windows Git Bash 免安装离线完整包、SHA256、依赖版本、启动/重启/卸载/恢复验证。
QA-11：R1 的 mission/evidence/defect/NodeGate 与 UI 同源，报告数值可逐项重算。
QA-12：商业授权门禁与第三方许可证清单符合最终交付规定。

## 状态定义
NOT_STARTED、IN_PROGRESS、CODE_COMPLETE、CI_PASS、QA_PASS、MERGED、CLOSED、BLOCKED；禁止从 CODE_COMPLETE 跳成 CLOSED。
验收证据字段：task_id、source_sha、test_command、result、evidence_ref、date、executor、known_limitations；每条失败必须有重现步骤和分级。
F 组负责独立验收；A 组只在跨模块质量门禁通过后合入，未经 F 组实际确认不得宣称现场 PASS。
