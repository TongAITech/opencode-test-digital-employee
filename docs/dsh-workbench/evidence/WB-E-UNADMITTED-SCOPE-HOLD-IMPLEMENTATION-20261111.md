# E：限定未准入Scope HOLD实现候选证据

基线本机W0 `70141ff0`；批准设计 `9623f30c1baf81d1a78490cca373689e42ceed80`，B219/5660c14c、D218/8f38bc08、F217/b3e49012；新隔离worktree e-scope-hold-implementation。仅runtime内部helper与Control/bank/N1调度前置、源码包必需文件资格、测试/定向CI，不改Mission模型、正式reader/writer、008、原R1或08–10。

## 实际行为

三个Mission顶层reserved键只做存在性拒绝（含null/partial/full），理由MISSION_SCOPE_NOT_ADMITTED。目标T收集self、输入对象所属、同稳定ID旧对象所属、Task/Gap引用及ready/reactivation后续足迹；首个业务写/输入原地修改前全预检。缺Mission/无法解析目标或未知替代planner/scheduler返回MISSION_SCOPE_TARGET_UNRESOLVED，新bootstrap不存在目标仅窄legacy例外。任务跨目标公共start及私有persist两个旧设计反例现用实际guard拒绝，日志字节/投影/输入保持；批量末项有Scope不写前缀。

默认Gap planner足迹只读router+正式terminal receipt/既有及本次incoming evaluation的source artifact/task稳定ID，收集repair/repro/qualification旧覆盖目标；从未执行plan()探路或临时推进source PASS。默认RC72 economy adapter是现有正式路径，显式检查其TaskScheduler delegate/canonical resolver/selector；未知替代实现拒绝。既有clock可保留，因为preflight不调用它且全部候选Task足迹已核；其任意外部raw副作用不被包装成全writer保证。caps一次性物化后供原scheduler使用，旧合法unbound行为/已先行missing/owner/identity错误保留。

真实日志/任务资源业务不变不等于mtime不变：bank原TruthRuntime.touch保持原语义；N1仅从dispatch调用基线比较，不回滚先前Field-start。direct scheduler/planner/session/raw/外进程陈旧投影仍未封闭，测试在临时日志明确证明direct scheduler绕过残余；不授生产绑定、Scope创建/读取或执行权。

## 本轮实际失败与修复记录

- 最初用unittest发现pytest函数文件，实际0条，不计通过；改用pytest。另一次回归列表含不存在的test_rc72_economy_control_plane.py，0条退出4，不计通过。
- 初轮11项真实legacy/N1中8失败：严格TaskScheduler类型误伤默认EconomyAwareTaskSchedulerAdapter。完整读实际delegate后显式支持，11/11通过。
- 新测试首轮21失败/6通过：主要是新fixture漏Evaluation.artifact_refs/evaluator_ref及把dispatch ContractError误限定为RuntimeError；修正合法fixture和明确错误家族后27/27，未把原始TypeError当guard通过。
- 扩大旧回归43/44，PRODUCT_DEFECT bridge失败：首写前直接调用旧source资格函数要求本次稍后才发生的Task PASS；改为只读来源足迹收集，不试跑planner、不改投影，真实bridge恢复。
- 扩大98/99，既有critical-path固定clock fixture误拒；按已可证明的全候选Task足迹允许原clock，不在preflight执行该callback，其他未知planner/scheduler替换仍拒绝。原时序和选中规则不改。

## 最终本地验证与交接

最终pytest受影响组合 **100/100，2.91s**：新增32项guard（18种键/值与冷恢复、旧两反例、output/evaluation/gap、末项Scoped evidence/gap/derived planner/source reactivation零前缀、输入vars/full binding、unknown targets/callbacks、caps、旧错误、重复bank resume、真实N1有效先验两个分支、writer spy零调用及明确raw residual），加旧closed-loop/core/control/多Case缺陷桥、bank/start/autopilot/turnkey、N1 dispatch、economy scheduler/critical path、session、N2 revision、Q2b/Windows源码资格合同。git diff --check通过。

现有SOURCE_DIRS递归携带rc7_runtime；新增helper纳入REQUIRED_PRODUCT_FILES并测试其存在，避免源码包漏依赖；没有重建Windows最终包、没有现场证据。新增CI为实际Python3.8/3.11、显式checkout PR head SHA；代码/测试/证据一次提交后冻结，CI结果由A记录PR body/主台账不改候选HEAD。Draft PR交F对完整实现SHA独立验收，真实Host/Windows仍FIELD_NEEDS_BANK_TRANSFER；本实现仅防损失HOLD，不称生产绑定修复。
