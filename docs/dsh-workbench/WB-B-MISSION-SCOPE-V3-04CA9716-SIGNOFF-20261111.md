# B：V3 durable PREPARE 修订窄复签

被审：PR #188，完整 `04ca971676509da9379ed53a29b495d2a32c325c`。前次报告：`b9cc568a5228a0da75e0d9da9260f3628f122789`，审32fffb21；该历史报告保留，不自动改成通过。

结论：**B_SCOPE_PROTOCOL_V3_DESIGN_ACCEPTED_AT_04CA9716 / B_PURE_COMPONENT_DESIGN_ADMISSION_ACCEPTED**。仅在B职责内接受该精确协议规范，前次唯一B正式创建P1已消除，当前无剩余B设计P1。不是008 SQL、锁定端口、正式模型/factory/writer实现验收、真实Host资格或F签署；不授权直接改写冻结模型/事实边界。A仍须收齐D/E/F所需签署与合同增量。

## 唯一B P1已消除的精确依据

- PREPARE独立PG事务先固定并durable提交原K、原authority/context、snapshot及scope/request digest和所有正式预留身份；明确确认该提交成功后才准正式R1调用。PREPARE自身不生成R1事实。
- 最终锁定事务明确禁止首次INSERT intent或重新分配身份；只重读、核验已存在不可变intent，当前完整来源/日期/双revision必须与固定快照摘要相等。权限撤销拒绝，Scope/映射/代次变化HOLD，不在原K下重算digest/换snapshot。
- PREPARE提交响应丢失时先按**原K查PG**：原intent确定则取其原身份/digest；PG结果未知HOLD，不分配新身份。只有确认无intent且从未允许正式调用，才可同K重新PREPARE。
- append前最终事务失败也不能抹除已durable intent；恢复按原K/digest向原authority查询，并重新取得当前创建许可/锁。append已发生但PG回执提交失败，则核原正式回执后只补PG引用，不回滚R1、不重分配、不把不完整图记作就绪或PASS。
- UNKNOWN、Host结果不明、日志尾部异常均先lookup/HOLD；权威NOT_FOUND本身不隐式submit，显式重交仍使用原intent与全部当前许可。故障恢复不得自动换key绕过未知结果。

因此前次“首次intent可能与R1 append后的PG事务一起回滚，导致原身份/digest丢失”的未定路径已被文本明确禁止。这里签的是可实施恢复顺序，不假称跨存储原子事务或现有API已实现。

D结果分类修订也与B恢复规则一致：COMMITTED必须带可核查的原K/request_digest/operation/event/receipt；缺少可查回执按UNKNOWN。只有DENIED_BEFORE_APPEND、EXPIRED_BEFORE_APPEND声称可靠零append证明；不把COMMITTED当零副作用。D仍需给其职责结论，B不代签Host全序。

## 当前SHA的纯组件准入边界

第1节来源tag/规范字节、第2节K与复合约束、第4节动作矩阵与32fffb21逐字相同。本次不是仅借用旧SHA的结论：已对04ca9716读取并比较，确认修订未改变B已接受的纯规范。因此B对**当前完整SHA**允许纯Scope DTO/tag验证、canonical bytes/scope_digest、K/creation-payload校验与独立域摘要纯函数的设计施工；输入只是数据，不能授verified权限、分配正式身份、写PG/R1或打开正式submit。缺能力适配只允许无副作用HOLD边界。D等依赖及独立实现QA仍按协议第7节执行。

008、受控锁函数/角色/FORCE RLS、真实两连接与崩溃恢复、正式预留器/单writer/typed模型必须各有新精确实现PR和相应审查测试；本报告不将这些待实现门禁核销，也不要求行内现场证据来阻断纯规范开发。

## 本次核查范围

只读比较32fffb21→04ca9716，差异仅新增PREPARE/恢复矩阵与D结果分类修正。独立脚本检查三段逐字未变，SHA256：第1节`3dedb41c0ed01786ff76ea83a66c65c0617528ceb0eefe0fe83d4bfd2c476183`；第2节`c2137d451e1343fd0f687a3982076172fdac460981caed0f246aedb612fc33c9`；第4节`25ffa25ffdcb9a828304f36225520a2be062354383c618fa90908412cd6ee71a`。另核六处关键顺序/分类文字均存在；这是文档审计，不计六项产品测试PASS。没有新增实现变化，因此未重复已完成的PG来源列检查或运行全量产品测试。

只新增本独立报告，未改候选、08/09/10、数据库、正式模型或R1。现场保持FIELD_NEEDS_BANK_TRANSFER，最终发布未批准。
