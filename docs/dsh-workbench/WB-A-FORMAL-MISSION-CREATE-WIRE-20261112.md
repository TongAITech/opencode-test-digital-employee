# 正式 Mission 创建请求与回执编码候选

基线 `37aac78c`。输入 V3、E245、B265/E272、D273/F277。提案限于首次登记 Mission 的不可变输入及恢复回执。Host 权限、资源、执行、人工门禁和 008 最终写入继续单独验收。

## 请求摘要和同键重试

- V1 业务正文只接受 `goal`。采用 UTF-8，有效非空，最多 4096 字节。允许中文、换行和非 BMP 字符，禁止 NUL 和非法代理码位。拒绝首尾空白，避免现有 Mission 构造器修剪后改变摘要语义。待跨组核实各语言的首尾空白判定集合。字段原字节不做 Unicode 归一化。
- 创建命令不允许调用者提供状态、版本、时间、Evidence、评估或任务。首次登记固定为 Mission REGISTERED、sufficiency UNKNOWN、revision 1、空引用、无最近评估。受控写入器生成登记时间，必须在原事件内持久保存并在查询回执时复用。该时间不参与创建请求摘要。
- 摘要预映像对象精确键为 `schema_version`、`command`、`scope_binding`、`runtime_batch_mapping`。版本整数 1。command 精确为 `{"goal": ...}`。scope_binding 使用完整紧凑绑定移除 `request_digest` 后的 14 键，已有 K4、业务批次、快照引用/摘要、修订、Mission/绑定 ID 和永久操作引用。runtime_batch_mapping 为已验收的精确九字段描述。所有共享身份须逐字一致。
- 采用 V3 规范 JSON：键按 Unicode 码位顺序，紧凑分隔符，UTF-8 无 BOM，不转义非 ASCII，标准 JSON 控制字符转义，整数十进制，无浮点和重复键。字节上限 65536。摘要为小写 SHA-256，领域前缀为 UTF-8 `dsh.mission-create.v1` 加单个 LF，再连接规范 JSON。完整紧凑绑定继续保留 15 键，写入上述摘要。
- 008 PREPARE 复用原 K 的比较须包含规范 goal。现有测试选择记录尚无正文键。正式选择 wire 在最终实现前增量评审，将同一 command 纳入 selection；同 K 改 goal 在获取新预留之前返回冲突。原 context 另核，瞬时 Host token 不进预映像。不同 K 的候选创建不受此比较影响。

## 原事件与回执

- 受控创建事件以原 R1 权威记录固定初始 Mission、完整绑定和九字段描述。事件类型、overlay 注册、历史索引和旧读兼容由 E 单独设计审查。正式读取必须核原 K、请求摘要、精确映射、唯一原事件与历史关联。
- 回执 V1 候选精确键为 `schema_version`、`creation_key_scope`、`request_digest`、`creation_operation_ref`、`runtime_batch_mapping`、`binding_ref`、`event_ref`、`event_sha256`、`receipt_ref`。schema_version 整数 1，所有重复身份均逐字核对。event_sha256 核唯一原始 JSONL 事件字节，排除一个尾部 LF，未经规范化。回执本身用上述规范 JSON 编码，008 receipt_hash 为小写 SHA-256，领域前缀为 UTF-8 `dsh.mission-create-receipt.v1` 加 LF。
- receipt_ref 与 event_ref 从原权威返回。receipt_ref 在同一 authority 下唯一，查询原 K 时固定。若需要从原事件推导回执，引用规则与跨进程黄金向量必须先签审。PG 只存原引用与回执哈希，保持原事件的事实地位。未能核验原权威返回 UNKNOWN 并保留原预留。
- 回执证明创建事件已持久化。批次、节点初始化和执行状态由后续正式读取确定，初始化尚缺时返回 INITIALIZATION_HOLD。

## 评审与验收

B 核 selection/prepare 兼容及 008 存储上限。E 核初始状态、回执来源和正式事件边界。D 核实际 Host 请求来源和映射。A/F 核纯组件向量。首批向量须包括中文、组合字符、非 BMP、控制字符、重试改 goal、过长、交叉 authority、错误批次、失联后原字节恢复和双份源事件。先完成独立编码与拒绝测试，再进入正式事件和跨存储验收。

## B、D、E 实证后的编码决定

本段收敛 #289、#292、#293 的评审。优先于上文未确定项，范围限独立纯组件。

- goal 首尾拒绝集合固定为 U+0009–000D、U+001C–0020、U+0085、U+00A0、U+1680、U+2000–200A、U+2028、U+2029、U+202F、U+205F、U+3000。U+FEFF 不属于首尾集合。禁用平台默认 trim，禁止 NUL，内部控制字符按规范 JSON 转义。
- JSON 的引号、反斜杠以及退格、制表、换行、换页、回车使用短转义。其余 U+0000–001F 使用小写四位十六进制。斜杠及所有其余有效 Unicode 直接编码。BIGINT 用无损十进制整数保留至 9223372036854775807，服务端生成摘要，普通 JavaScript Number 不参与权威摘要。请求和选择各自对最终规范字节限 65536。所有用于 PostgreSQL text 的新引用同时校验 UTF-8 上限 384 和 NUL。
- 正式选择使用 schema_version 2，键为 `schema_version,formal_authority_ref,actor_ref,project_id,creation_key,batch_id,filters,mapping_policy,command`，领域前缀 `dsh.mission-prepare-selection.v2` 加 LF。保留三类筛选的 V3 排序语义。测试夹具的旧选择与请求永远不转换成正式 intent。重试比对已核实的原规范字节，独立校验原 context。
- Mission revision 与 R1 artifact_version 分别固定为整数 1，时间使用一个整数 Unix 秒填两个字段。回执引用在正式追加前由原权威生成并保存于同一原事件；原 event_id 是该权威内 event_ref。V1 正式创建行固定 LF，读取原字节时拒 CRLF 的该类事件。旧 R1 其他事件仍可按兼容规则读。事件哈希使用排除终止 LF 的原始行字节。实现回执需待 E 的正式事件 schema 签署，本轮可施工请求和选择的纯编码与黄金向量。
