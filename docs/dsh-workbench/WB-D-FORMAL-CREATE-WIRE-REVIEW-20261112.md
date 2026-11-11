# D 审查正式 Mission 创建请求与恢复回执

审查 A #288 精确提交 `0d01905b3c38eae3e7360949da9f73ab7129380f`。接受首版业务命令仅含 goal、保留紧凑绑定形状、将独立九字段映射纳入摘要的方向。以下补充应在纯编码冻结前明确。正式 Host、事件写入和 008 准入继续 HOLD。

## Host 输入和主体

- DSH 原生对话和 HTTP 提交使用同一受控命令服务。模型提出的 goal 是业务内容。K 中的 authority、actor 及原 context 由服务器从可信当前 Host 及受审映射取得。浏览器或模型只提供用户选择的项目、批次、合法筛选、重试用 creation_key 和 goal。项目、批次、日期及三类筛选须按当前权限和真实 Scope 重读。排除正文提供的主体、许可、内部快照、摘要、状态、时间和预留身份。由原 K 复用已持久预留，终端或模型切换不得改变原 K。
- `business_http.py` 现有 HostIdentity 只有 principal/mutation_authorized，`write_context.py` 的 HMAC 只对当前 principal 和密钥计算，`business_store.py` 原样传入 PostgreSQL 的 `wb.principal`。它们适合现有工作台能力。正式路径还需真实 Host 的动作授权、native proof 或 CSRF 证明、authority 映射及可恢复原 context。subject 不 trim、normalize 或用会话显示名替换；原 context 在允许恢复的会话切换中如何核验，需要真实 Host 合同和验收。
- 按 V3 分离 create 与 lookup。lookup 使用原 authority、原主体及原 context，校验当前 lookup 和 can_write，允许 create 已撤权但 lookup 仍受权的原回执查询。撤去 lookup 或 can_write 后不返回摘要、目标、原回执或存在性。UNKNOWN 保留 intent 供原 authority 核对。显式重提仍需重新获得 create 和 HostFence，查询永不自动提交。摘要和回执哈希是完整性字段，当前动作权限独立验证。

## 摘要字节和初始 Mission

- `models.py` 的 Mission 构造器实际调用 Python `.strip()`。冻结首尾拒绝集合以保留输入字节：U+0009–000D、U+001C–0020、U+0085、U+00A0、U+1680、U+2000–200A、U+2028、U+2029、U+202F、U+205F、U+3000。另拒 NUL 和孤立代理码位。Python 3.9.6 和 Node 的实测显示 U+001C 与 U+0085 仅被 Python trim，U+FEFF 仅被 Node trim。U+2028 两者都 trim。跨语言实现不可调用平台默认 trim。用起始和末尾分别构造拒绝向量，另测含内部换行、内部控制字符、NFC/NFD、非 BMP 和 4096 字节边界。
- 规范 JSON 的控制字符转义须唯一。建议与现有 Python 规范编码一致，固定双引号、反斜杠和五种短转义（退格、制表、换行、换页、回车），其余 U+0000–001F 用小写十六进制 `\\u00xx`，斜杠和非 ASCII 直接编码。黄金向量需覆盖 U+2028/U+2029 的内部原 UTF-8、任意已允许控制字符和无 BOM。接收网络 JSON 时禁止重复键及非整数数值形态。由 schema 校验版本和各整数上下界。
- 紧凑 Scope 接受至 BIGINT 最大值 `9223372036854775807`，真实 Node JSON.parse/JSON.stringify 实测变为 `9223372036854776000`。保留既有 wire 数字形状和范围。Host 浏览器只传业务命令，最终摘要在服务端生成。需要跨语言校验时使用可保留整数十进制的解码路径，用 2^53 前后和 BIGINT 最大值做向量。普通 JavaScript Number 不得成为摘要或回执重建数据源。
- 所有进入 008 text 列的身份和引用仍须通过对应 PG 域约束（含 UTF-8 字节长度及拒 NUL）。结构 codec 对某值的接受范围可能较大，正式命令装配必须再次核对。首次登记明确从一个采样产生 created_at/updated_at，确定整数时间单位并持久保存。源事件须校验原 goal 和初始状态；不得用当前已更新的 Mission goal 或时间重建原摘要。

## R1 原始回执和恢复

- `rc6_runtime/truth.py` 的 JSONL 以默认文本模式写入，平台可能转写换行。当前 `iter_raw` 走文本通用换行并返回解码对象。用相同 UTF-8 JSON 的 LF 与 CRLF 模拟写入，文本读取结果完全一致，二进制去末尾单 LF 得不同 SHA-256，分别为 `56b9c089bd586f15209ff3900968eb9a21ad88f7bec3d8763c8da6d40993c7b7` 与 `3ed4109ebf66ee7e621aca0d188e803dd8852714c0a1b9c2db00c33c2df739c2`。因此正式新事件应固定 LF 二进制边界，在验证后的同一固定字节快照逐行核原 event_ref；若后续允许 CRLF 源，必须明确保留 CR 或拒绝的约定。不要用文本迭代器、重序列化或 splitlines 的多种分隔语义替代原字节。
- 缺终止符、重复源事件、重复原始 JSON 键、坏行、同 K 不同内容或无法建立物理账本来源均进入 HOLD。原权威要在同一事件定位中核 K、operation、request_digest、完整映射、event_ref、binding_ref 和事件原字节哈希。receipt_ref 必须有唯一且可恢复的持久来源或已审确定性规则。PG 对账只登记原引用和回执哈希；同内容冷恢复应生成完全相同的回执字节。
- 分别验证失联发生在 durable append 前、append 后回执发出前、PG 回执登记中。创建成功仅证明原事件存在。INITIALIZATION_HOLD 和后续可读性需要各自真实来源。绝不能用 receipt 推断节点初始化或执行门禁通过。

建议先冻结上述纯格式、整数范围及向量。之后可独立实现脱离 Host/008/R1 写入的编码和二进制事件字节核验。真实 Host 的动作证明、固定物理账本、原始事件格式及身份恢复仍各自验收。
