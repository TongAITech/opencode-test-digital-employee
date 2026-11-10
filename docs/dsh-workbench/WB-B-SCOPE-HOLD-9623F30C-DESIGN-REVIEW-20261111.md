# B：未准入Scope首副作用前HOLD目标域设计复核

被审PR #212，**当前完整源** `9623f30c1baf81d1a78490cca373689e42ceed80`。原任务线索ce6add35的self-only P1及D/F反例保留，不把旧源转成接受。基线199a3163，两个提交均仅候选/证据文档；当前没有guard实现可验。

结论：**B_SCOPE_HOLD_BOUNDED_DESIGN_ACCEPTED_AT_9623F30C**。在本文件限定的业务Scope/兼容职责内，没有剩余B设计P1；可以在A及D/E/F所需精确签署后单独实现此负向guard。不是实现PASS、生产绑定修复、全部R1入口封闭、正式模型/PG/Host准入或最终发布批准。

## 接受的Scope和兼容规则

- 只保留Mission顶层project_id、batch_id、scope_binding三键；出现性而非truthy或结构合法性决定HOLD。null、false、空、partial、flat-only和结构完整一律不放行，不调用PG/Host/codec，不把DTO当来源或创建许可。
- 完全无三键的legacy保留原wire和有效行为；scope_ref/namespace/diagnostic_score及无关nested数据不扩入保留键。输入动态vars也检查，不能在to_payload/asdict丢字段后再检测；不删字段、不生成替代Mission或HOLD正式事实。
- 9623§2.1明确优先于原表的“当前row”简写：完整目标集T必须包含self、输入/稳定ID解析的实际拟写对象Mission、被覆盖旧对象所属Mission。先只读收集并核验整个T，再执行首个transition/输入对象修改/append/scheduler/planner/attestation；不能循环边查边写或只靠最后persist兜底。
- 覆盖task start/output、输入与旧artifact/evidence身份、evaluation/gap/defect、Gap派生任务及旧同ID对象、_sync/_persist目标Mission、source多Gap/多Task、bank及N1实际WorkItem旧所属。能力Iterable只物化一次计划/执行复用。没有当前链上的Attempt append就不虚构映射；若实施发现列内新增写，则必须在首写前纳入真实目标，解析不了HOLD回报。
- 明确新增MISSION_SCOPE_TARGET_UNRESOLVED拒绝未知/缺所属/不唯一目标，缺raw Mission例外仅合法新bootstrap；不是把无法解析当legacy。原能在首写前证明的missing/owner/identity错误优先，**有效且全unbound**的跨目标行为不被本单顺带硬化。非法/悬空目标的新HOLD是已声明的行为增量，需冻结增量签署和单列测试。

这组规则不读取或重建PG关联、不改变业务(project,batch,requirement,version,SST)事实，也不将RC72 release_batch_id猜成PG batch_id。范围是保留未准入数据并阻止其通过既有正规入口继续产生受保副作用，而不是认可保留字段代表真实业务授权。

## 独立源码核对及实际反例

已读当前Control的register/refresh/lease/start/output/evaluation/defect/converge/source恢复与私有persist/sync，TaskScheduler.start/submit/refresh/lease、GapRepairPlanner派生规则、bank.start_or_resume及N1 dispatch。当前代码确实先scheduler或evaluation/gap写，再重建旧typed Mission；_persist_mission还使用self版本行而写输入mission_id。后者的版本算法不在本单修复范围，但其**实际目标旧Scope**不能漏查。

两个独立TemporaryDirectory、真实TruthRuntime/现有Control的内存/文件实验（没有PG、生产R1或外部执行）：

1. 先bootstrap无Scope M1，另在临时日志加入带project_id/batch_id的M2 raw Mission；调用M1._persist_mission(Mission(M2))。当前旧代码成功追加，M2 project_id丢失，原R1字节变化。
2. 同样M1无Scope/M2带Scope，加入M2的合法LEASED T2及owner w；调用M1.start(T2,worker_ref=w)。当前旧代码把T2推进RUNNING并追加事实，尽管self M1没有Scope。

两项是**旧缺口characterization**，不是新guard功能测试PASS，也未制造业务缺陷/Evidence。ce6只查self不足，9623把这两项明确纳入受保入口、不能挪到raw残余，且要求用原本可成功/会写的fixture做首写前零变化测试，B认可此修订。

## 必须保留的未覆盖边界

- 仅当前可见raw投影，未封闭writer/重读CAS，跨进程新增Scope或stale projection竞态仍未解决。direct scheduler/planner/session/raw append等残余不可被这份接受核销；不得宣称全写端保护。
- bank的TruthRuntime构造touch可能改变mtime；保证限定日志原字节/hash与业务事实、任务/租约/资源状态，不把本单称完整文件metadata不变。
- N1 standalone dispatch自身首副作用前guard，不回滚其上游既已发生Field-start/driver事实；Q7/Field-start原先验必须保留，existing receipt RESUMED也要查实际目标，不用“无新写”冒充已准入。
- Scope guard只追加拒绝路径，不把HOLD转换成NodeGate/Defect/Execution FAIL，不授任何资源/动作许可。正式V3创建/读取/typed保留/PG来源/Host资格仍是独立未完成工作。

实施验收须对每条公开/私有受保入口使用有效会写参数，首写前核完整T；raw字节、所有相关projection与输入对象不变，spy零副作用；全unbound/旧wire/合法新bootstrap/原错误对照通过。对多目标最后一个Scoped、输入与旧对象不同所属、派生/恢复目标及不确定目标拒绝必须实测。此处只接受可测试规范，不声称这些新测试已经运行通过。

只新增本独立B报告，未改候选、runtime、冻结原文、008或08/09/10。源码/文档审计和两项旧行为实验已完成；没有产品guard实现测试可跑。真实DSH/Windows保持FIELD_NEEDS_BANK_TRANSFER。
