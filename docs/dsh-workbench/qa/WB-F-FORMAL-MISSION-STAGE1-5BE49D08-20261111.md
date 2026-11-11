# F 独立复审 Mission 第一阶段设计

F 接受 E245 精确 `5be49d089cdf8e320c29276418e3069fe9c0e796` 的第一阶段设计进入隔离实现。准入范围是 typed 表示保真、旧 Mission 兼容、独立 DTO 和局部拒绝。D247 对旧 `ff98337d` 的 P1 保留。已逐项复核 D248 精确 `d3b7e2c4e5fd8888cf94777a5f52ac945a3dd2bb`。

F 在候选现有源码用临时 R1 独立复现两个旧反例。动态附加 `scope_binding` 的普通 Mission 经通用 serializer 丢键并可直接 append。随后向同一 canonical M 注入 `R-old`、v2 和 `batch_id:null`，冷回放确认保留 null。用普通 Mission 的可变 ID `' M '` 和新 release 直接 append v3，R1 bytes 改变，投影只剩唯一 M，Scope 键消失。当前实现按 canonical artifact identity 存投影，因此新 release 过滤会漏掉真实覆盖目标。此处记录的是旧行为复现。

新稿要求 `to_payload` 在 asdict、深拷贝或字段移除前拒绝动态及声明的保留键和非 ABSENT 状态。直接 `append_entity` 在 durable acceptance、payload 构造和 append 前执行同等检查，然后按全局 canonical mission_id 检查唯一当前目标，旧 Scope 键存在即拒绝，null 同样计入。实现验收需保留跨 release 和 ID trim 反例，并核拒绝前后字节、投影、旧行和输入不变。合法旧新建和更新需通过原入口并对比原 wire。

F 还复核了真实派生 dataclass 的旧额外字段输出、RC7 直接 append 精确类型拒绝，以及 RC72 对 Mission 的精确类型拒绝，两次拒绝均未改变临时 R1。模拟 `init=False` 内部字段时，缺省枚举存在于可信声明而实例 vars 中缺键，asdict 仍包含该字段。绑定模拟值经 deepcopy 保留，默认 replace 回到 ABSENT。实现须区分真实继承、声明或动态保留字段、内部缺省及被遮蔽状态，用异常 descriptor tripwire 确认无 getter、深拷贝或序列化先行。对带绑定对象的 clone 要验证规范字节及原身份不丢失。

隔离 serializer 的输出限独立 DTO。实现验收要检查与 Control 重建和通用写端的调用关系，生产 bound 路由持续 HOLD，历史 raw 回放保留原语义。正式批次三身份、reader/writer、008、HostFence 与跨进程陈旧投影各自保留后续准入。该报告只给设计准入和旧源码复现，新 typed 行为等待精确实现验证。
