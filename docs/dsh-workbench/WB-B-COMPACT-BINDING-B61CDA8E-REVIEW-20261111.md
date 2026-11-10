# B：紧凑 binding 纯模块候选精确审查

被审PR #198，完整 `b61cda8e1b57d89331062abfd8ed9c196a5d8d15`；上位V3 `04ca971676509da9379ed53a29b495d2a32c325c`，B已签其设计规范。当前差异只有候选文档/调查证据，没有实现、008或冻结模型改动。

结论：**B_COMPACT_BINDING_DTO_SERIALIZER_COMPARISON_DESIGN_ACCEPTED / B_ENVELOPE_JSON_LEGACY_SCOPE_P1_PENDING**。15键紧凑结构、来源/namespace/外层一致性、detached serializer及纯不可变比较可分段准入；完整外层Mission JSON入口的“任意层float拒绝”与“未知运行字段交原模型、legacy继续”存在一处可具体复现的兼容范围P1，须先澄清。不是当前生产漏洞判定，也不因此阻断无歧义的binding值/serializer/compare纯函数。

## 15键字段来源与复合身份

| 紧凑信息 | V3拟议权威来源及B核对 |
|---|---|
| project/batch、release_date、date/relation/access三revision | 完整PG不可变snapshot，严格历史值；不能拿当前日期/revision重算旧绑定 |
| snapshot_ref、scope_digest | PG snapshot行与intent完整(project,batch,ref,digest)关联；不是本紧凑对象摘要 |
| mission_id、binding_ref、K4键、request_digest、mapping7键 | 独立durable PREPARE的immutable intent及受控身份预留；K不额外加入batch/session。mapping authority/project/batch与K/外层明确核同，runtime_release_id等于外层Mission.release_id，不猜等于PG batch |
| creation_operation_ref | 本候选明确新增的拟议永久PREPARE操作字段；**不是现有008/现有只读preview已返回的字段**。按K取旧意图、并发冲突核原分配、durable固定并由后续request wire覆盖或经审关联可作为设计细化。未来008/正式allocator/event/query仍须独立审查，纯模块不能声称它们存在 |
| schema_version=1 | 紧凑binding自身版本；不能当作完整Scope规范版本或来源证明 |

source edges/filters/canonical bytes无需重复复制进每次R1 Mission状态更新：完整数据由不可变PG snapshot恢复，再核scope_digest及date/三revision；缺失/矛盾HOLD正确。它引入对快照持久留存/备份的真实依赖，不能用紧凑字符串替代丢失业务来源。当前授权另行检查，历史access revision不改成当前值。完整snapshot版本与canonical codec从受控PG记录/已签协议读取，不从紧凑对象的schema_version猜。

复合业务身份未被扁平化丢失：typed的project/batch在mapping和flat镜像双向相等，version/SST精确关联保存在所引用的完整snapshot。authority在K和mapping明确相等；将来正式reader还必须对其配置的真实ledger authority/正式创建事实核同，纯parser不可能仅凭自报文本校验namespace的权威性。候选已要求正式creation查询在任何任务/执行/Evidence明细之前完成，不存在接口时HOLD，不以flat匹配或operation字符串放行。

## 可接受的纯分类与保留边界

LEGACY_UNBOUND仅限typed与两个flat键都缺省；serializer输出作用域片段{}，不制造null或来源。显式null、partial、未知schema、内部身份矛盾、外层mission/release冲突与flat缺失/冲突均明确拒绝。flat-only即使两个ID齐全也不提升为正式绑定，保留原日志且新写路径先HOLD/拒绝。BOUND_STRUCTURAL_ONLY仅结构成功，零/一digest示例不冒充真实快照。

serializer只返回新的作用域片段、不覆盖冲突外层；compare逐字段核完整15键及外层mission/release，不只比scope_digest。bound丢失/legacy补绑/任何不可变域变化拒绝；这不等于正式writer的并发CAS。上述规则在B职责内可签纯组件设计，不改变当前models/overlay/reader/control的实际行为，也不核销当前正式typed字段丢失缺口。

## P1：全局float token拒绝与外层兼容边界冲突

§4.1写“JSON解析拒绝任意层…浮点/指数数字token”；§4.3却规定纯模块只检查scope相关字段、未知外层运行字段由原模型负责，legacy无绑定继续。现有`truth_overlay.validate_rc7_mission`的`_base` deepcopy保留未知extra，它接受一个完全无绑定、已通过正式现有validator的payload含`diagnostic_score:0.5`。按“任意层拒绝”给json.loads配置parse_float拒绝，则这个payload在尚未进入LEGACY_UNBOUND判断前被拒绝。该差异不是对业务字段strict integer的要求，而是把scope parser扩大为未知外层运行字段validator。

本次独立内存验证：asdict(Mission(mission_id='M1',release_id='R1',goal='legacy only'))，state转现有value，再加diagnostic_score=0.5；现有validate_rc7_mission接受且没有scope_binding。对它的JSON使用parse_float拒绝会得到GLOBAL_FLOAT_REJECTED。没有PG/R1或任何正式事实副作用；这是设计兼容反例，不是已实现parser功能测试。

最小修订：浮点/指数严格限制在binding/K/mapping及作用域已定义字段，不把未知外层运行字段纳入scope校验；完整外层未知字段仍原样交原模型处理。重复键/非标准NaN/Infinity的整体JSON策略应单独明确，不能借此把合法有限浮点外层字段当非法scope。另一可选方案是把raw JSON入口声明为一种**新限定wire**，不宣称它可直接兼容旧完整Mission；旧数据必须经原正式模型与独立scope片段接口进入，不得静默丢字段。无论哪种，失败不修改输入，也不能将flat-only/partial降legacy。作者新精确SHA给出该范围后可窄复核，无需重开字段来源设计。

## 独立核查与准入限制

用stdlib解析候选示例，精确核对15/4/7键集合及authority/project/batch/mission/release相等，确认没有edges/canonical_bytes/event_hash/event_ref/receipt_ref。核V3 snapshot/intent字段和当前001–007/正式Mission，确认新字段尚未实装。`git diff --check`通过。文档示例/内存反例检查不计产品功能PASS，未重复跑无实现变化的PG/Windows产品测试。

只新增本B报告；未改候选、008、正式models、reader、writer、R1或08/09/10。纯模块不读文件/DB/网络、不分配身份、不持Host token、不产生verified/create许可。正式008/typed接入/冻结合同变更仍需完整B/D/E/F后续精确签署，真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER。B的PR199只读来源预览资格亦仅已验project-only schema；未知或漂移RLS不是本typed DTO能授予的权限。
