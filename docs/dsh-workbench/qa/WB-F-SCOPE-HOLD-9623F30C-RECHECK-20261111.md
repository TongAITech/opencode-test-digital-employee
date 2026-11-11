# F：Scope HOLD实际目标域设计精确窄复核

被审PR：[212](https://github.com/TongAITech/opencode-test-digital-employee/pull/212)。新完整设计源：`9623f30c1baf81d1a78490cca373689e42ceed80`；父源ce6add35。F独立worktree`f-runtime-hold-target-fix`，没有修改候选/功能、08–10、正式事实或冻结合同。本提交仅F报告。

结论：**UNADMITTED_SCOPE_HOLD_BEHAVIOR_DESIGN_ACCEPTED_EXACT_9623F30C**。旧目标选择P1已在新§2.1中明确消除，未发现阻断这份具体正式负向行为增量实施的新P0/P1。B/D/E同一精确源完成职责签署并由A记录后，可另PR实现本文件限定的runtime存在性/实际目标预检保护。不是代码验收，不准绑定创建、新模型、tools依赖、PG/Host/writer能力或全R1封闭。

## 旧失败不转签

F [#213](https://github.com/TongAITech/opencode-test-digital-employee/pull/213)的ce6设计P1与D214保持：unbound M1 Control直接persist普通M2对象可丢Scoped M2字段；M1公共start合法M2.T2可推进Scoped目标任务。两条真实R1反例仍属于列内保护，不能挪入raw/scheduler或并发残余。本新设计仅要求后续实现阻断它们，不宣称尚未存在的guard已运行通过。

## 源码逐路径复核与新规则

已读新差异及Control全部写分支、TaskScheduler、GapRepairPlanner.plan/两个产品缺陷派生任务、GapRouter、source receipt读取、runtime identity attestation、bank正式入口、N1 dispatch/Field-start顺序和JsonlEventStore构造。

| 复核项 | 新设计可准入的精确边界 |
|---|---|
| 目标域 | T含self、输入对象/稳定ID所解析实际写目标、被覆盖旧对象所属Mission；先取全T，逐个核raw Mission三键，再允许首次transition/输入原地改变/scheduler/planner/append/attestation。动态vars不能替代目标旧row |
| task/output | start/output以真实task旧row.mission_id为准；输出所有Evidence/Artifact输入与旧同ID所属也核；不能写完首个再发现第二个Scoped。register已有零副作用身份拒绝保留 |
| Mission/gap私有写 | _persist/_sync核输入真实Mission目标旧row，_sync必须早于改lists；_persist_gap含input与旧Gap双方所属；_resolve_source_gaps和reactivate必须全量收集，包括后续状态变化会激活的Task/Gap引用，不能循环边写边查 |
| evaluation/planner | Eval/Defect/input Gap与旧同ID所属、task gap_refs、source-reactivation和派生repair/repro/qualification任务及既存目标全预检。覆盖PASS/REPAIR/BLOCKED/HUMAN，不仅入口self或末尾persist |
| 未解析与兼容 | 不唯一、缺所属Mission、矛盾/不可无副作用解析全目标明确新增TARGET_UNRESOLVED HOLD；不猜self或legacy。有效完全unbound跨目标旧行为不一概硬拒绝；原本首写前可决定的missing/owner/identity错误保留 |
| 新建例外 | 仅真正计划执行旧legacy bootstrap、目标恰无row且输入无reserved的分支可创建。普通persist无此例外；bank/N1首个合法新bootstrap的完整调用链须保留正例，不能因前置规划阶段目标尚不存在而误阻合法旧新建 |
| N1/Q7/Field-start | 合法canonical batch/N1/精确Field-start先验保留；actual WorkItem旧row所属也核，首个bootstrap/register/N1 transition/receipt前全预检，existing receipt RESUMED不能漏Scoped目标 |
| bank与文件 | 读真实稳定Mission row后、graph/resume/refresh前拒绝；constructor touch可能改mtime已明确披露，承诺内容/hash/业务状态不变而非全部metadata无变化；不得借此暗改TruthRuntime或用换Mission“恢复” |

### planner/callback可实施性与不能过度承诺的部分

当前默认GapRouter只做确定性ROUTE_POLICY判断；普通repair目标ID由gap Mission/ID/route确定；产品缺陷路径先只读核terminal receipt/hash或legacy source，再由source artifact ID/gap身份确定repro与qualification两个ID。该默认图可以在Control边界只读规划或新增同runtime只读plan步骤，**无需试调用会transition/persist的plan**来探路。

实现必须把repair后Gap将变为EVIDENCE_PENDING、source-reactivation/ready后续写足迹纳入整体计划；简单按旧状态扫描再执行会遗漏后续分支。capabilities一次性iterable需物化一次复用，不改变lease选择。已有只读来源资格/receipt文件校验不能被这个guard改成PASS。

没有发现当前默认正式构造接口必须执行一个任意业务callback之后才知道写目标的正规分支；但public scheduler/planner对象可被外部替换，不能据此承诺任意替换或重入callback安全。按新稿“无法无副作用确定整个集合→UNRESOLVED”的规则，不明/不支持的依赖或callback不能先试执行再在首写后发现新目标；必须在本次首写前获得受控只读计划或拒绝。新设计不授跨进程/可变外部对象沙箱保证。实际实现对此必须给出精确边界与负例，不能只写注释声称已枚举。

## 本轮证据与限制

- 相对ce6只新增目标域30行和一份7行调查证据，无runtime实现变化；旧两反例的行为未被本次文档自动修复。
- F辅助内存探针在禁open/socket条件下，调用当前默认GapRouter的**96个已声明category/target组合**，目标与policy一致，输入Gap深相等；稳定repair/repro/qualification ID函数为可只读计算。此为目标可规划性调查，不是96项新guard测试。
- 首次辅助探针误用不存在的GapSeverity.MAJOR，构造即失败；改用实际HIGH后完成上述96项，未改被审代码，未把夹具错误计新保护的PASS。
- 没有跑不存在的HOLD产品测试，也未把原缺口characterization、旧CI或B/D报告当实现接受。读源码确认TaskScheduler/GapRepairPlanner/Session构造不append业务R1，源receipt校验是只读；这些观察不等于封闭所有底层写端。

## 代码实施后的独立验收门禁

保留#213两个实际成功反例，测试新保护同reason首写前HOLD；对照两目标都无Scope时保留旧有效行为。另测多输出/多Gap最后一个Scoped、_sync输入目标、_persist_gap输入与旧row不同所属、派生任务旧ID碰撞、source-reactivation后续状态、一次性caps、目标缺失/不唯一/不明依赖。每次拒绝原R1 bytes/hash/完整投影及输入对象不变，不能只检查最终Mission字段；legacy全回归与Q7/Field-start/N1新dispatch+RESUMED都需真正可写的正前提，而非用无效参数先失败冒充guard。

raw append/direct scheduler/planner/session、stale投影/并发查重、driver/Field-start调用之前已发生副作用仍明确不在封闭保证内。真实DSH/Windows继续FIELD_NEEDS_BANK_TRANSFER；这不阻止本负向保护施工，也不解除正式创建/reader/writer、现场或最终发布门禁。总体NOT_APPROVED。
