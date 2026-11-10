# D Mission Scope V3 窄增量精确复签

被审：[PR #188](https://github.com/TongAITech/opencode-test-digital-employee/pull/188)，完整源 **`04ca971676509da9379ed53a29b495d2a32c325c`**。对照前审源 `32fffb2115251f2860954fe0772ec45ef433b3b7` 和 D 报告 `331a2a504fc22fc20147a33e8ba662271c691404`。独立 worktree `d-binding-v3-recheck` 从本次被审源建立；只新增本报告。

结论：**D_V3_DESIGN_COMPONENT_SIGNOFF_ACCEPTED_AT_04CA9716 / D_V3_01_RESOLVED / FORMAL_R1_IMPLEMENTATION_AND_FIELD_NOT_ACCEPTED**。

本结论只签本次精确设计中的 D 权限/恢复/Host 抽象能力及隔离组件施工边界，不签 B 的 SQL/持久化正确性、E 的正式模型/writer实现、F 独立验收或真实 Host 资格。

## 旧窄 P1 已消除

前审发现结果列表以 COMMITTED 开头却以“前两类明确未 append”处理。新源删除这一相对表述，明确：

- COMMITTED 必须带可按原 K/request_digest 查询核验的 operation_ref、event_ref、receipt_ref 和 digest，是已发生的正式原事件回执，**不是零 append**。缺可查回执按 UNKNOWN。
- 仅 DENIED_BEFORE_APPEND、EXPIRED_BEFORE_APPEND 表示可靠零 append。
- UNKNOWN 以及不能证明零副作用的 CAPABILITY_UNAVAILABLE 先原域 lookup/HOLD，绝不据此重新分配身份。

这与 durable append 线性化、已发生事实不因撤权/PG失败而消失、原主体幂等恢复一致。**D-V3-01 的设计歧义已在此精确源消除**，不保留该项为未关闭 P1。

## 新 PREPARE 增量没有退回旧授权/恢复歧义

完整读本轮第3节改写及新增3.1恢复矩阵：独立 PREPARE durable commit 先固定原 K、digest、快照与预留身份，最终锁定事务只核验既存 intent，禁止在跨 append 事务中首次分配后因回滚丢失身份。D 仅核对其与授权/恢复规则相容，不代 B 签真实PG事务/分配器实现。

| 本次核对点 | D 结论 |
|---|---|
| PREPARE 不能代替最终当前授权 | PREPARE 明确当前主体/create/mutation/can_write；已提交 intent 后继续及 append 前失败恢复仍重取全部当前权限与锁/围栏。没有把 PREPARE 时许可当后续永久许可。 |
| NOT_FOUND 不暗转 submit | 恢复矩阵明确 lookup 不暗转；只有显式再次 submit 才重新获取当前创建许可，沿用原 intent/身份/digest。第4节动作矩阵逐字未变，仍禁止只读查询升级成创建。 |
| 已提交或未知副作用 | append 后 PG/响应失败查原权威回执，只补 PG 引用；未知/Host UNKNOWN 先HOLD+lookup；不以 PG rollback、超时或日志尾损坏当 NOT_FOUND。 |
| 原主体与业务意图保持 | Bob 不可重包 Alice；K/digest/原 context 规则不变，Scope/映射/代次变化 HOLD，不在原 K 下换摘要/快照；旧 UNKNOWN 先查清，不能换新 key 绕开。 |
| 部分初始化继续 | 第4节再次 submit 明确含部分初始化继续，仍需要完整当前创建权限；第6节 INITIALIZATION_HOLD 不派发，不以结构恢复宣称执行/PASS。 |

D 未在该窄增量发现新的 P0/P1 授权或原主体恢复规范缺口。此判断是设计复签，不是声称实际 PREPARE、Host 全序或正式 writer 已实现。

## 本新 SHA 的隔离组件准入

**D 明确接受在本新精确源约束下准备/实现以下候选**：纯 canonical codec、带 tag DTO/schema 校验、K/摘要纯函数、DTO内 typed 绑定不可变保存，以及缺真实 Host 能力直接 CAPABILITY_UNAVAILABLE/HOLD 且零 PG/R1 副作用的适配器。不能返回假的 COMMITTED、创建成功或执行 PASS。B 对来源/字节/键规则的精确签署仍独立；纯函数通过不解除生产绑定缺口。

正式 Mission typed 模型/序列化/重建/普通更新保持绑定的方向，D 无新增异议，但仍按第7节要求由 E/RC72 owner、B/F 对该具体增量审查；本报告不单独授权改变冻结正式事实。新正式创建、008、allocator、writer、Host COMMITTED 路径与初始化恢复均需其独立实现 PR/实库/并发/崩溃证据，不能借纯 DTO 准入上线。

HostAdmissionFence 仍是**所需抽象能力**，不是现有 HostIdentity/mutation boolean、write-context 或某个 Captain 锁已满足它的证明。真实适配器必须证明撤权与回调 durable append 的全序、回调进行中的过期/重启/锁丢失、旧代次拒绝和未知回执恢复；不能保证时生产 HOLD。fixture 只测抽象协议，不授真实 DSH 资格。真实 DSH/Windows 继续 **FIELD_NEEDS_BANK_TRANSFER**。

## 本轮证据与精确范围

- 已核 PR188 HEAD 为04ca9716、RC7.2远端edaf9290，读取32fffb21→04ca9716完整 diff：仅一份协议文件的 PREPARE 阶段/恢复矩阵和提交结果分类，没有运行实现变更。
- 用 `git show` 抽取原/新第1节（codec）、第4节（动作矩阵）、第7节（施工准入）逐字比较，三节均未改变；新第1节 SHA256=`3dedb41c0ed01786ff76ea83a66c65c0617528ceb0eefe0fe83d4bfd2c476183`。本次重新审阅这些约束后给本新SHA签署，未转移旧测试 PASS。
- 本轮是文档窄复签，没有新增或重跑运行测试，不重复记上轮缺口3/3、PG16/16、Host夹具33/33为本次产品证据。没有真实 Host/SSO、R1 创建实现或现场 PASS。
- 只写独立报告；不改被审候选、08/09/10、正式模型、原始事实、许可证或主线；工具正常，无额度错误。
