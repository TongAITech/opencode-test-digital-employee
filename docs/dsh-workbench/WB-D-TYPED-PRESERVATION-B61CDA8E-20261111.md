# D 紧凑 typed 绑定纯结构阶段独立审查

被审：[PR #198](https://github.com/TongAITech/opencode-test-digital-employee/pull/198)，精确冻结源 **`b61cda8e1b57d89331062abfd8ed9c196a5d8d15`**。独立 worktree `d-typed-preservation-review` 从该源建立；参照已审 V3 `04ca9716` 与 D 复签 `cf74b3d3`。本报告只审本次结构阶段，不把 V3 许可转移为正式模型或 Host 实现批准。

结论：**D_COMPACT_PURE_PARSER_DESIGN_ACCEPTED_AT_B61CDA8E / NO_D_P0_P1_FOR_THIS_ISOLATED_PHASE / FORMAL_MODEL_READER_WRITER_HOST_NOT_ADMITTED**。

D 接受按本新精确候选先实施纯 parse、typed DTO、detached serialize、不可变比较；模块不接正式 models/overlay/control/replay/reader/writer，不读PG/网络/文件、不处理Host凭据、不自行验证业务来源或事件。现场不可访问不是这一纯结构阶段的施工阻断。实际模块实现仍须精确代码审阅与对应负向测试，本报告不是实现 QA_PASS 或 F 签署。

## 字段、原主体与权威边界

- 绑定恰好15键，K恰好4键，mapping恰好7键；mapping/formal_authority、project、batch及外层 mission/release/flat 镜像的相等关系明确。原 actor_ref/formal_authority_ref/creation_key 作为不可变数据保存，**不由这些字符串推导当前 Host 主体、角色、动作或执行许可**。parser成功只能返回 BOUND_STRUCTURAL_ONLY；看起来合法的伪造 K/digest/op 也不能升级成正式事实。
- `original_context_ref` 不属于这个紧凑 wire；它仍在上位 V3 的 durable PREPARE intent/当前授权与原主体恢复域中校验。这里不需要为了结构阶段复制 Host session、fence token 或上下文凭据进 R1，不把省去这些字段解释为取消恢复授权。以后 submit/reconcile 仍按原 K/intent/context 及当次可信 Host 动作核验；不是拿 parser 的 actor 字符串与当前登录名自行拼成授权。
- 当前 can_write、Host mission.create/lookup、mutation/CSRF 或审核的原生证明、资源/人审/NodeGate 等均不由 parser验证或授予。合法用户读取既有 Mission 的授权与“原创建者的幂等恢复权”继续分开；不能因 K 内 actor_ref 是 Alice 就认为 Bob 没有既有授权读取权，也不能因 Bob 有同项目写权就重放 Alice 原意图。

## 保留、拒绝与永久身份

| 要求 | 本次候选的 D 核对 |
|---|---|
| 完整/缺省分类 | 整体缺省且无flat才是LEGACY_UNBOUND；序列化作用域片段为{}，不生成scope_binding:null。 |
| partial/null/flat-only | 显式null、部分/畸形/未知schema、flat单边或双边无typed均稳定拒绝或未具正式来源HOLD；不默默降legacy、不删除原字段、不补造typed来源。 |
| 镜像一致 | 完整typed必须与外层mission_id/release_id和两个flat镜像精确相等。serializer由typed生成新镜像，但不得覆盖传入冲突来“修复”；parse也不得自动补缺镜像。 |
| 不可变域 | 绑定所有字段、外层mission_id/release_id均在不变域，含actor/authority/K、mapping、snapshot/date/三revision/digest、creation_operation_ref。比较前双方先严格解析；非法输入先拒绝，任何字段变化、bound/legacy转换均不得产补丁。legacy→legacy的可保留规则不能被实现为忽略外层ID变化。 |
| 永久 operation_ref | §4.2明确PREPARE先查原K，再为确无原intent的新意图分配；唯一冲突取原分配核验。同K重试不换creation_operation_ref；它不是网络attempt_ref或可变Host fence_ref，也不是已commit证明。 |
| 无事件自引用 | 不存完整edges/canonical_bytes、自己尚未生成的event_hash/event_ref/receipt_ref；这些额外键明确拒绝。永久op由PREPARE固定，后生成的事件/外部回执引用它，避免把绑定本身摘要当事件认证。 |
| 不变比较不授写权 | 纯结构相等不是CAS；正式writer仍须持锁重读旧事实/artifact_version并验证所有权。全局同K唯一、分配器和request digest最终wire不是本parser的隐含功能。 |

## 身份与正式事实必须先于明细

§4.2明确：先经当前PG Scope授权，再由受控正式creation事实查询核对operation_ref/K/request_digest及mission/release/binding/mapping/Scope引用，才允许tasks/executions/evidence明细。查不到、UNKNOWN、重复、身份冲突或完整快照与引用/date/三revision/digest不合都HOLD；查询端口不存在时也不因parser成功放行。

实际 `rc7_admin/projection.py:159` 的既有guard目前只先读Mission flat身份，再读明细；`models.Mission` 无typed字段，control `_mission()` 仍会丢extra。候选已明确这些当前缺口，且本阶段**不修改此reader或正式模型**。因此 D 接受纯parser并不表示现有flat-only生产链已经升级，手工extra fixture也不成为正式创建事实。未来接入reader必须有spy/真实入口测试证明拒绝发生在tasks/executions/evidence零查询前，HTTP仍用不泄漏存在性的拒绝，不把内部详细错误码直接回显给未授权者。

request_digest 对永久op的完整编码覆盖、正式creation事实/回执索引、008持久化和所有writer封闭仍待相应独立增量。此处仅保留合法格式的引用和摘要，不重算一个“看起来通过”的值替代权威校验，不给Mission、Attempt、Evidence或NodeGate增加执行资格。

## 本次证据与实现阶段退出项

- PR198完整HEAD、远端被审分支均核对为b61cda8e；RC7.2远端edaf9290。`gh pr diff 198 --name-only`仅候选及只读调查证据两份文档，没有运行实现。已读完整候选/调查证据和实际Mission、control重建、scoped reader、write-context调用边界。
- 用stdlib仅解析文档JSON示例，逐项核15/4/7键集合、authority/project/batch/mission/release镜像及禁用额外字段；示例自洽。**这只核对文档结构向量，不是未来parser测试、真实来源或Host资格通过。** 零/一digest只是格式示例，不能当实库/事件摘要。
- 本次未重跑旧缺口复现或旧PG/Host用例，未将旧数字转签为新实现证据；没有访问真实行内Host或改原始R1。初次定位文档使用了不存在的文件名，随后按commit真实路径读取；该定位失败不计验证通过。

实现后必须独立测：全部字段逐一删/加/null/错类型/Unicode/重复键/整数token边界，K/mapping/外层与镜像各冲突；原输入嵌套mutation不改变返回值、序列化返回值mutation不改内部；序列化legacy完全省略；同K不同permanent-op/actor/authority/mapping/digest及outer ID变化拒绝；对象键乱序等价但字符原样不归一化；禁止IO/Host/model/reader/writer副作用。不能以字段测试通过取消正式来源、当前授权、writer/CAS或行内现场门禁。

只新增本独立报告，不改候选/实现、08/09/10、冻结合同、许可证或主线。无本轮D侧真实P0/P1需要阻断这项纯结构施工；正式模型/Host/事件的未完成工作按各自增量推进，不代签B/E/F。
