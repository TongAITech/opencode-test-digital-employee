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

## F224实际红例修复（不覆盖fd9失败）

完整读取F224/af9cc8ed报告及34例代码，在旧fd9实际重复执行：28过6失败、1.29s，与F结果一致。两项P1保留：缺Gap引用在lease写Task后才报错；outer economy adapter的refresh_ready/task/start/output替换被执行。首轮100个绿测试不能抵消它们。

另按A要求先实证wrong-bound风险：两个临时R1、相同Task ID，本地delegate.start绑到另一同类不同truth delegate.start，旧fd9实际令远端Scoped Task RUNNING且远端bytes改变。这个新增实证不是未经验证的推测；不将router/其他依赖上的同类假设直接命名新P1。

修复：对本次lease中READY、capability可达的REPAIR/QUALIFY_DEFECT所有Gap refs要求存在；repair PASS与实际source-reactivation的Gap足迹同样首写前完整解析。新Task注册、普通ready refresh及不触Gap的PRODUCE lease不会盲目要求未来Gap已存在；caps不匹配候选不扩大成实际Gap写目标；新Gap创建仍不要求旧row。缺失实际目标统一TARGET_UNRESOLVED，日志/投影/输入无前缀变化。

outer adapter全部已知自有和转发方法在调用前逐一校验（不只四个vars），再核delegate、planner、router的函数与真实__self__ receiver；静态方法保持原函数身份。delegate类型在任何forwarded属性读取前检查，未知Tripwire不试执行。truth/release、planner.scheduler、canonical resolver及schedule_semantics依赖关联检查阻止同类不同truth混接。合法clock仍允许，预检不调用它。没有执行plan()探路，没有改变writer/模型/reader或Scope授权。

实际复验：F原34例全部绿，联合当时新增guard为94/94、1.99s；最终仓内受影响组合**129/129、3.70s**（原68 legacy+现61 guard），包括全部outer public转发/私有查找tripwire、wrong-bound outer/delegate/planner/router零调用、同类foreign truth依赖、missing ownership Gap与repair PASS/source-reactivation/defect、未来refs/新Gap/普通PRODUCE lease/caps合法对照。diff检查通过，源码包helper必需资格保留。CI继续使用既有显式HEAD 3.8/3.11矩阵，结果交A记body/主台账；本单次修复提交后冻结不追加CI证据HEAD。raw/并发/Field-start/mtime残余没有掩盖，仍不能称全writer或生产绑定完成。

## F227实际下层依赖红例修复（保留e9拒绝结论）

完整读F227/8f3259be报告及全部脚本，旧e9实际执行其150例：148过2失败、2.28s，两个semantics.resolve/critical._assess forwarding callback均被调用并写Task lease。原F34/E61/legacy68/精确CI129绿不能抵消此P1；REGISTERED不隐式refresh的96状态/caps对照仍原样保留，没有虚构新缺陷或扩大missing refs规则。

按真实默认调用链增加静态持有对象闭包：CanonicalCriticalPathResolver.resolve→WorkScheduleSemanticsService.resolve，以及_assess→_unsafe/_cycle_node/_depends_transitively；selector.plan→BankCostWindowConfig.is_working_day也按实际源码覆盖。精确类、原类descriptor、instance/class/static接收者与既有truth/release/对象归属必须同时成立；只比对不试执行未知方法，字段shadow/错误绑定/替代对象拒绝。Semantics.record/_task_row等不在resolve调用链内的方法没有被假称为运行闭包；不引入自签verified能力。合法bank config及clock/default/base scheduler继续通过。

新增Tripwire进一步实际发现：旧getattr(resolver,'__self__')会先探测未知callable对象；扩展测试首次261过1失败。修复为先要求真实MethodType，再取receiver，未知对象零探测/零调用。静态descriptor检查也在任何getattr之前拒绝替代property。此限定检查不声称防任意raw R1后端或任意全局程序改写；原raw/跨进程/Field-start/mtime边界保留。

最终本地联合 **330/330、5.78s**：未改的F227全部150（含原148绿及2红转绿）+未改F224旧34+当前仓内78 guard（原61及新增17个闭包callback/错绑/unknown对象/property零调用）+68受影响legacy。diff检查通过，仅runtime helper/test/本证据变更；模型/reader/writer/008/08–10均未改，包归档helper必需资格保持。既有显式HEAD Python3.8/3.11 CI将运行仓内78+68=146项，外部F脚本330组合是本地实际执行，不能把CI测试数量混写。单次新提交后冻结，CI结果交A记PR body/主台账，不追加证据追HEAD；交F对新完整源独立复验。
