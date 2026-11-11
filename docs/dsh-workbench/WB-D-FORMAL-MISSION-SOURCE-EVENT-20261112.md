# 正式 Scope Mission 创建源事件候选

审查基线 `c397d016`。输入 A #288 精确 `b0711004`、E #289、D #293、B #292 和 A #275 / D #285。范围为正式源事件、冷回放和原回执。现有跨存储、Host、writer 和部署门禁继续适用。

## 现有 R1 的真实行为

在一次性目录中使用现有 `JsonlEventStore`、`TruthRuntime` 与 overlay 进行探针。

| 探针 | 观察 |
|---|---|
| 两次旧 `RC7_MISSION_UPSERTED`，相同 payload 含附加标记和 Scope | 两个不同原始 event_id，冷回放历史只有一个版本。 |
| 原包 entity_id 为 BAD，payload mission_id 为 ` M1 `、goal 为 ` goal ` | 回放返回 entity_id M1 和 goal。原包元数据与原文本差异被归一化。 |
| 原包事件类型改为未注册的新创建事件 | 现有冷回放报 UNSUPPORTED_EVENT_TYPE。 |
| 仅在探针内将新类型注册为 rc7_mission 别名 | 旧字段验证器仍接受原包附加标记。给新类型 payload 增加 `cases: []` 后，默认回放将其当旧批量容器消费，返回零事件单元。 |

对应路径为 `rc6_runtime/truth.py` 的 `_canonical_payload`、`expand_for_replay`、`_legacy_children` 与 `Projection._apply_validated`，以及 `rc7_runtime/truth_overlay.py` 的 `validate_rc7_mission`。单靠类型注册、附加标记和当前投影无法证明正式创建。

## 事件与回放

- 推荐独立类型 `RC7_SCOPED_MISSION_CREATED_V1`。它是唯一正式创建载体。兼容读法是新程序同时识别旧 upsert 与新类型，投影到已有 `rc7_mission` 和全局 mission_id。不得双写或把旧 upsert 标记重解释为正式创建。旧程序对含新类型的同一物理账本会 fail closed，因而必须在首条正式事件前升级所有受支持读写端、冷恢复端和离线包，并撤掉旧写入者。降级到旧版本只允许在已验证账本无该类型时进行。备份与恢复保存原字节和新 reader，禁止重写新事件类型或删除事件来恢复旧工具兼容。
- 外层精确 6 键为 `seq,event_id,event_type,entity_type,entity_id,entity_version`，另有 `payload`，合计 7 键。seq 为受控账本分配的正 bigint 且拒布尔，event_id 为原权威中唯一、稳定且满足正式引用域的文本。event_type 固定上述字面值，entity_type 固定 `rc7_mission`，entity_id 与 payload.mission_id 逐字相等，entity_version 固定整数 1。
- payload 精确键为 `artifact_type,artifact_version,mission_id,release_id,goal,state,sufficiency_state,artifact_refs,open_gap_ids,active_task_ids,residual_risk_ids,latest_evaluation_id,revision,created_at,updated_at,project_id,batch_id,scope_binding,runtime_batch_mapping,receipt_ref`。artifact_type 固定 `rc7_mission`。两类版本均为整数 1。四个引用列表均为空，最近评估为 null，状态为 REGISTERED，sufficiency 为 UNKNOWN。两个时间均为同一次采样的非负整数 Unix 秒。goal 使用 #288 精确文本规则。业务批次镜像与完整紧凑绑定一致，运行批次描述沿用九键。receipt_ref 按正式引用域在追加前由权威分配，并与其余字段同一条 durable 事件保存。时间、receipt_ref 和事件分配元数据不进入创建请求摘要。
- 对此类型必须在旧批量展开和通用 Mission 归一化之前按原 bytes 验证。严格 JSONL 解码保留行终止符和原行。此类型要求原 LF、精确字段与类型、规范编码、原包和 payload 逐字相符、原 #288 摘要、K 与映射一致。原文本及编码验证均在重建投影前完成。禁止接受 `cases` 等旧容器字段或通过通用 upsert/旧 append 进入正式路径。事件专用 dispatch 仍需写入侧和回放侧两条入口，写入侧另验当前 writer 围栏与权限。
- 回放产生一条兼容的 `rc7_mission` 投影记录，保留内部 Scope 保护所需的紧凑绑定及镜像。只读源索引从同一固定原始账本完整扫描，在原包验证后保存定位信息。其索引和投影可重建，不能替代原字节。旧 Admin/Field/节点入口须保持正式 Scope 保护，面向界面仅通过经授权的新读取投影返回必要字段。紧凑绑定含 actor/K，须防止现有序列化器无差别返回完整内部记录。批次与 N1–N10 初始化仍按后续独立原事件校验。更新正式 Mission 的专用事件和权限继续单独评审，旧 upsert 不得变更该实体。

## 恢复与证明

- 同一受控物理账本绑定单一配置 authority。原始索引要核 K、mission_id、operation、mapping、receipt_ref、event_id 的唯一性并检查既有 Mission 身份冲突。重复原行、复制到不同 seq 或 event_id、相同 K 不同载荷、同 Mission 的旧 v1 或后续未批准事件均 HOLD。首个成功命中不能结束全量验证。对旧事件识别潜在 Mission 冲突时同时对照原文本和旧 validator 归一化身份，避免白空格隐藏交叉记录。只以精确相关 payload 标识关联，不能使用投影 history 的字符串前缀。
- 已完成当前 lookup 授权后，从同一原事件取原 event_id 与持久 receipt_ref，计算移除单个终止 LF 的原行 SHA-256，依 #288 构造规范回执。回执引用和回执字节在任意冷重启后相同。投影丢失或更新不得改写原回执。数据库只对账原引用和哈希。若找到合法创建事件但正式批次尚未建立，原回执查询可按 V3 成功，图和执行保持 INITIALIZATION_HOLD。
- 验收覆盖全部原始重复、元数据差异、旧容器劫持、空白归一化、精确文本与摘要、LF/CRLF、不可用或损坏账本、fsync 后无回包、当前许可撤销、零副作用的旧 reader 拒绝和新 reader 混合账本冷回放。另验实际 Ubuntu/Windows 二进制追加、离线回退拒绝、Host 权限和所有旧写端的部署隔离。受审前仅可构建独立解码与临时 R1 回放探针。
