# F：紧凑Mission binding纯模块精确设计审查

被审PR：[198](https://github.com/TongAITech/opencode-test-digital-employee/pull/198)。精确合同源：`b61cda8e1b57d89331062abfd8ed9c196a5d8d15`。F独立worktree`f-typed-design-exact`，未参与候选修改/被测实现，未改08/09/10、正式模型、冻结合同或R1。本提交只有F审查报告。

结论：**COMPACT_BINDING_PURE_MODULE_DESIGN_ACCEPTED_EXACT_B61CDA8E**。未发现阻断本候选P1阶段（“阶段P1”，不是缺陷级别）的真实P0/P1设计问题：在B/D/E对同一精确源完成职责签署、A记录准入后，可施工独立纯parser/serializer/不可变比较模块。它不接models/overlay/control/reader，不授正式来源或创建/执行权威，不能以本结论开放后续P2/P3。

## 核查与边界

完整读取候选与调查证据，核对V3 K/映射/PREPARE边界、当前Mission/to_payload、truth_overlay._r1_payload的release覆盖、ClosedLoopControlPlane._mission/_persist_mission及现行scoped reader；查阅原生factory/configured-binding零R1副作用合同。没有用B/D结论替代本轮独立检查。

| 规范点 | F独立判断 |
|---|---|
| 固定wire | scope_binding恰好15键，K4、mapping7，严格类型/未知键/null/schema/digest/date/正bigint规则可实现；不在R1重复PG全edges/bytes，也不允许事件hash/receipt额外键透传 |
| 紧凑身份一致 | binding.mission_id=外层mission_id；mapping.runtime_release_id=外层release_id；project/batch=typed/K/mapping及两个flat镜像；authority=K/mapping。flat缺失/错误不被parse自动补齐，serializer只从已核结构产生新片段，不覆盖调用者冲突值 |
| 历史Scope信息 | date、三revision及scope_digest属于PREPARE完整快照的历史引用，不随普通运行更新重算；纯模块只能验证类型/比较不变，真实PG快照一致性和当前授权须正式端口另核 |
| 缺省与错误分类 | 无binding且无flat键→LEGACY_UNBOUND，wire作用域片段{}；显式null不等于缺省。partial/错型/未知字段/schema、flat-only、内部身份/外层身份/镜像冲突分别拒绝，不降legacy，不修补或删除原字段 |
| 不可变比较 | 先严格解析双方，再比较绑定全部域及外层mission_id/release_id；legacy↔bound、bound→缺省或任一不可变值改变均冲突。对象键顺序无语义，ID不trim/不Unicode归一化，scope_digest不被误当紧凑对象自身摘要 |
| 原操作身份 | creation_operation_ref在PREPARE前按K查重并预分配、独立durable保存；并发冲突取原分配，重试不重分配。它不是每次网络attempt/fence，也不是事件存在证明；不嵌入尚未产生的自身hash/receipt，消除循环 |
| 结构与正式权威分离 | BOUND_STRUCTURAL_ONLY只是结构值；正式reader须在授权PG Scope之后、任何任务/执行/证据明细之前核受控creation事实及全套预留身份。字符串/DTO/flat匹配不能替代来源、PREPARE提交、正式事件或Host证明；接口缺失/UNKNOWN保持HOLD |
| 旧运行兼容 | 纯模块不接入当前正式路径，因此不改变旧无绑定legacy运行；未来legacy写回缺省应完全省略而非asdict(null)。历史flat-only不抹除/不迁移，Workbench不借reader目前接受flat而宣布正式生产接通 |
| 依赖与后续范围 | P2接model/overlay/control/reader属于冻结增量，必须另获精确签署、完整副作用前置和CAS/writer证明；P3正式创建依赖PG/Host/原子事件/回执与partial graph恢复，均未获本报告实施权 |

候选开头提及PR195 a975为调查时期的历史快照，不构成该旧codec的接受；a975的筛选失败报告#200保持。任何复用“已签纯编码原语”只可使用实际已接受8618676e或后续另验源码，不能从头部旧SHA转签。

## 本轮实证及不计产品通过的部分

1. F独立提取文档JSON示例，以stdlib核对**15/4/7精确键集合**、内外Mission/release/project/batch/authority相等、schema=1、三revision正bigint、合法ISO日期、两个64位小写digest，以及无edges/bytes/event_hash/event_ref/receipt_ref。结果相符，只是样例语法/内部结构审核，不是真实来源或新parser实现验收。示例零/一digest不能证明任何PG快照存在。
2. 精确源运行`python3 -m unittest discover -s tests -p audit_scope_binding_characterization.py -v`：3/3、0.034秒**旧缺口复现**。现正式Mission构造仍不接受业务绑定、start/resume仍无绑定、手工extra仍被refresh丢弃。此结果不计修复或生产PASS。
3. 相对b6d93e41仅2份文档共138新增行，无正式模型/overlay/control/reader或运行事实变更；F测试前后源固定b61cda8e。

## 实现验收必须明确覆盖

- 所有15/4/7键逐项缺失/多余/错类型，尤其list/dict等非hashable值应稳定分类拒绝，不泄漏原生TypeError；原始JSON重复键/数值词法/Unicode及未知schema与bool严格区分。多错输入按既定分类优先级拒绝，无副作用。
- LEGACY_UNBOUND的省略、显式null/partial/flat-only、未知外层运行字段不删除/不修改、合法serializer产生detached/immutable片段；parse缺镜像不能被serializer悄悄修复。结构合法不证明来源，未知事件/Host/PG不能凭DTO成功变成接受。
- 修改每一个绑定域、K/mapping域、date/三revision/两digest、预分配operation_ref及外层mission/release都要冲突；按§4.4，**legacy→legacy也须保持外层mission_id/release_id**，不能只看两个LEGACY标签就允许更换身份。普通可变运行字段可变与绑定不变分别验证。
- 不读文件/DB/网络、不import models/overlay/control/reader、无callback或隐式正式创建、输入不变；完整黄金向量及实际受支持Python运行时另验。纯模块实现完成后必须新完整SHA独立验收，本设计签署不直接成为其PASS。
- 当前reader无正式creation事实查询、正式writer和typed重建链尚未完成，生产接通保持HOLD；不通过更改legacy权限或绕过资源租约/人审/NodeGate来补齐。

本报告不代签B/D/E或现场资格。真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER；完整生产绑定和最终发布NOT_APPROVED，不生成最终交付包。
