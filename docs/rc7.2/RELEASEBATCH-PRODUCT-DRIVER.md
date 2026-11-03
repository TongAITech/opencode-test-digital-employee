# ReleaseBatch 原生产品推进器

状态：C08 ACTIVE / PARTIAL_NATIVE_ROUTE / DESIGN_INCOMPLETE / NO_DELIVERY。

`rc7_runtime.rc72_release_driver.ReleaseBatchDriver.run(release_batch_id=...)`
从 R1 中解析 Mission 和 release，重新核对同源 Q7 接纳，再接续原生服务。
调用方不能覆盖 Mission、release 或提交自定义 PASS 回调。
启动器和独立审查器必须是实际运行时类型，工具集必须明确且无通配符。
每个账本、每个 ReleaseBatch 通过系统文件锁排除并行控制进程；锁文件保留，
实际进程退出由操作系统释放占用，不能根据文件存在推断进程存活。

已接入的链路：

- N1：原生派发、Agent Teams 分配、严格 DSH 工作会话、原始证据锚定、
  runtime binding admission、独立节点 Gate 和正式运行时绑定。
- N2：正式需求全集派发/分配、逐需求 DSH 候选及原始证据、规范产物提交、
  独立 DSH 审查和确定性充分性检查，再执行完整分母的正式节点 Gate。
  某需求审查不通过仍处理其他独立需求，不缩减分母。修订/人工处置不自动放行。
- N3：正式应用全集源码目标发现、原始证据锚定、规范候选与独立映射审查；
  只从通过审查的目标派发代码分析，逐目标执行 Git/CodeGraph 观察记录、
  原始证据、规范产物、独立 Code 审查和实际充分性门槛，最后完整 N3 Gate。
  保留现有必需 Git/CodeGraph 工具集；不得通过调用者回调替代审查。
  发现阶段有未解决疑点时不制造可接受候选，不启动分析；代码影响范围不足
  不能靠审查文字 PASS 放行 N4。未通过的目标不减少必测分母。
- N4：从当前 N2/N3 正式父级确定 Requirement x SST 全集，原生派发/分配、
  设计工作会话、原始证据锚定、规范产物提交、独立设计审查和完整节点验收。
  `N4ParentScopedDesignEvaluator` 和 `N4ParentScopedDeliveryGateService` 是产品
  路由的强制边界，不允许通用审查器替代。每个父级来源的种类、来源 ID 和
  父产物 ID 必须完整保留在 required 义务的 source_refs 中；不同仓库中相同
  符号 ID 不得互相代替。候选 schema 增加这个明确字段，其余未声明字段继续拒绝。
  独立审查之外，复用继承的确定性断言与 SufficiencyV2 深度、密度和交互门槛。
  正式 Gate 重新计算父级完整性、断言及设计深度，不能仅依赖旧 PASS 记录。
  保持 RC7.2 Case/nested execution 契约；缺少具体执行物化仍由 N6 阻断并交回
  所属节点修复，不凭空转换成另一种旧版 Case/数据构造格式。
- N5：当前 N4 全部规范 Case 的完整数据需求清单、已验证绑定复用或正式发现
  计划、发现任务分配、DSH 发现原始证据及产物、独立验证与原生资源/绑定确认。
  发现已派发后保留完整计划；不能因部分结果已验证就重算掉未完任务。
  全部独立确认后才重算 REUSE_VERIFIED 计划并调用正式 N5 Gate。
  `N5WorkItemFinalizer` 从实际独立验证证据关闭原发现工作项；失败保留正式
  数据缺口和要求 test_data 能力的修复工作项，不越权交给 Script/执行层。
  `N5OwnedWorkItemGateService` 不允许已验证绑定掩盖未完成工作，也独立检查
  Evaluation 与验证结果、原始发现/验证字节、候选哈希的精确关系。
  完成 N5 不产生 DataLease，不代替后续实际 Case 执行。
- N6：自动从规范已验收 Case、原 N1 运行绑定、精确独立验证的 N5 DataRef
  编译并正式验收整批执行契约。不接受调用者另传契约或替代用例。
  缺少 N4 执行物化时，在编译写入前列出全部受影响 Case 与 N4 归属；
  其他确定性就绪缺口保留 Case ID 和实际归属节点。原生 request/schema
  归属 N3，不发送给明确禁止拥有这些事实的 N1。
  规范映射修复了多义务 Case：coverage_links 中的次级义务也保留正式映射，
  严查 Requirement/SST/层级且拒绝孤儿链接，不复制 Case 或删减义务。
  契约和 N6 Delivery 持久化后中断，由原规范记录接续验收，不重复上游工作。
  N6 不占用 DataLease，不生成实际执行 Attempt 或 Case PASS。
- 已提交候选的接续重查原始证据和规范候选，不重启分析工作进程。
  已验收的前缀调用原生 Gate 重新审计，不仅检查 PASS 标签。
- N7：具体 `N7PipelineService` 接入原生完整执行计划、签名工具派发、正式
  运行器的实际子进程、环境适配器清理与复核、不可变证据封存和独立进程验收。
  已持久化调用和清理回执直接复核，不重新准备已释放资源；效果不明或失败调用
  保留诊断 HOLD，不自动重放业务动作。验收提交后中断可由原 Delivery 接续。
  成功只沿真实 N7→N9 FORWARD 边推进，N8 保持未启动，不伪造 N8 PASS。
- 完成前缀后，N8 修复、N9/N10 等未接入节点明确返回 HOLD / NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED。
  全部节点标签 PASS 仍需正式发布收敛审计；推进器不自行宣布 Mission 完成。

只读状态入口不需要工作进程配置或密钥：

```text
python -m rc7_release.rc72_mission_cli status --ledger <existing-r1.jsonl> --source-commit <exact-40-char-sha> --release-batch <canonical-id>
```

状态直接重建 R1 投影，不创建任务、会话、节点或验收声明。不存在的账本会拒绝，
不会静默创建新账本。`field_verified` 和 `bank_final` 均不会由该入口提升。
工作进程启动配置工厂、完整运行命令及面向最终用户的交互仍待接入；
当前可调用推进 API 不等同于完整银行产品入口。

统一接续发现并修复 N1 历史 Gate 的下游状态约束：N2 可以已在运行、完成或修订，
N1 复核不得将它回退到 READY。必须保留原 Gate 到原 N2 的正式 FORWARD 关系；
缺失且 N2 尚 READY 时只恢复中断的关系写入，已推进但无关系则拒绝。

工程证据：`release-driver-native-regression.log`，37 passed / 5.60 s。
覆盖真正子进程协议会话、全部需求独立审查、源版本不符拒绝、只读冷状态命令、
跨进程排他、候选提交后中断接续、原始字节改动拒绝及正式推进关系改动拒绝。
启动、派发、分配、候选及严格 Gate 边界回归：
`release-driver-boundary-regression.log`，45 passed / 2.16 s。
工作进程是工程协议适配器，不能据此声称真实银行 DSH/工具调用或 Field 通过。

尚需完成：N7..N10 和 N8 回边/修复/重新执行的实际服务路由、Provider/会话接管、
生产工作进程工厂及完整运行入口、全角色实际工具调用时权限、Journey/Browser、
经济性和同源平台验证，以及 RC7.1 等价完整搬运包。C07/C08 均未完成。

N3 接续工程证据：`release-driver-n3-recovery.log`，15 passed / 10.93 s，
含 N1→N2→N3 连续推进、单应用两个经规范链路接纳的发现目标的完整逐目标分母、
发现/分析候选提交后的冷投影接续、歧义拒绝、完整影响维度缺失拒绝和
已通过 N3 正式 Gate 的只读重审。子进程仍是工程协议适配器，
不代表银行 DSH/真实 Git/CodeGraph 工具体执行已经具备 Field 证据。

N3 与统一入口继承回归：`release-driver-n3-regression.log`，98 passed / 20.67 s。

分配前中断、发现审查前中断、代码审查前中断：
`release-driver-n3-assignment-recovery.log`，3 passed / 4.52 s。

N4 施工证据：`release-driver-n4-recovery.log`，8 passed / 16.36 s，
包括 N1→N4 全链、完整父级范围、两仓库同名符号拒绝互代、显式疑点不调用
无效审查、设计深度不足/不可执行断言拒绝、分配/审查前中断的冷接续，
以及审查角色正式产物写权限拒绝。继承回归初轮：
`release-driver-n4-regression.log`，57 passed / 35.88 s。
这些为工程协议子进程与实际原生验收服务的证据，不是银行真实工具体/Field 验收。

最终本轮源码：`release-driver-n4-final.log`，60 passed / 40.23 s。
额外三项检查通过实际继承审查器产生正面记录，再证明正式产品 Gate 会在
写入 Delivery 前分别拒绝父级来源互代、缺失确定性断言、缺失深度/交互覆盖。

N5 恢复使用同一真实工程协议工作流，依次在首项工作项验收后、第一条已验证
计划重算持久化后，以及 N5 Delivery 已写入且节点 REVIEW_PENDING 时中断。
重新建立 R1 投影后接续，其余任务继续且不重复已完成发现/验证。
通用控制面的 Evaluation/Gap/task 多次日志写入内部中断仍需 C06 完成治理，
不能把上述三个已测试边界扩大为所有中断均已证明安全。
同一 Case 的全部父级义务仍保留；N5 工程样例使用经真实 SufficiencyV2 检查的
有界多义务 Case 链接来缩短测试运行时间，没有删减数据需求分母或绕过审查。
完整银行工具体和正式 Field 验收仍由实际运行环境证明。

N5 最终本轮源码证据：`release-driver-n5-final.log`，4 passed / 134.05 s，
分别覆盖完整正向范围/原始字节改动拒绝、全部独立负面结果、旧原生确认结果
不能掩盖未完成工作项、同一流程三处持久化后冷接续。重流程分文件执行，
没有删减必验数据需求范围。`release-driver-n5-native-regression.log`，
124 passed / 137.46 s；`release-driver-n5-control-regression.log`，7 passed / 0.52 s。

平台验证时间预算：b032924 的 Linux 工程验证已通过，Windows 检查
125533816804 明确因整项任务超过 30m0s 而取消，不能记为通过。
工作流整套任务上限调整为 120 分钟，原有逐文件 180 秒及依赖安装 120 秒
保护保持不变，没有减少文件、降低断言或放宽验收标准。
`qualification-suite-budget.log`：7 passed / 0.03 s。仍需新源码同源平台结果。

N6 本轮工程证据：`release-driver-n6-regression.log`，67 passed / 40.83 s；
`release-driver-n6-recovery-final.log`，1 passed / 34.79 s，覆盖同一整批流程中
首条契约持久化后、全部契约及 Delivery 写入而 Gate 尚未执行时的两次冷接续。
`release-driver-n6-provenance.log`，1 passed / 0.37 s，验证原生请求结构缺口
归 N3 而非 N1。完整 N1→N6 正向工程链已运行，原步骤/输入/断言/来源哈希保持，
主归属以外被 Case 覆盖的义务全部保留正式记录。
N7/N10 对次级覆盖义务的证据归集仍需实现/审核，不能将当前契约编译等同于
全部义务已执行或最终发布收敛。协议子进程不构成银行真实 DSH/工具体 Field 证据。

最终本轮整批链路：`release-driver-n6-chain-final.log`，4 passed / 135.64 s，
覆盖 N5 原始证据审计、已验证绑定对应工作项验收、N5 三处恢复、缺失物化时
全量 Case 归 N4 阻断，以及完整 N1→N6 编译与只读复核。完整正向链同时确认
次级覆盖义务全部成为正式 TestObligation，且仍保持原 Case 主归属及原执行范围。
