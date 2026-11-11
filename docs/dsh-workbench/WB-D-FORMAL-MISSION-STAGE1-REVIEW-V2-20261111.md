# D 对 Mission 第一阶段合同的复审

D 接受 [E PR245](https://github.com/TongAITech/opencode-test-digital-employee/pull/245) 精确提交 `5be49d089cdf8e320c29276418e3069fe9c0e796` 的第一阶段合同。旧 [D PR247](https://github.com/TongAITech/opencode-test-digital-employee/pull/247) 对 `ff98337d` 的 P1 保留。准入范围为 typed 结构保真、旧构造和 wire 兼容、隔离 DTO、局部负向 HOLD。

- 通用 `to_payload` 在 `asdict`、深拷贝和字段丢弃前拒绝保留键及非 ABSENT。直接 `append_entity` 先拒绝同样输入，对合法旧输入再查实际 canonical 写入目标，两项都先于 durable acceptance、payload 转换与 append。RC72 通用 append 保留 exact type 拒绝。
- 使用真实临时 R1 独立复现旧路径。先写 `mission_id=M`、`release_id=R-old`、`batch_id=null` 的 v2，再用普通 Mission 将可变 `mission_id` 设为 `' M '`，以 `R-new` 调直接 append v3。旧源码改变账本字节，覆盖了同一 M 并丢失 Scope。现有 overlay 会 strip，TruthRuntime 按 artifact type 与 canonical entity ID 存投影，release 参数只影响内容和写后查询。新实现验收须包含此用例，按 canonical mission_id 查当前可见目标，禁止附加新 release 过滤导致查不到旧行。重复目标或任意保留键均拒绝，原行与账本字节须保持。
- 临时 legacy dataclass 子类的额外字段由旧 `to_payload` 保留，直接 append 返回 `UNSUPPORTED_RC7_ENTITY`。新合同保留两项行为，并要求识别真实继承、动态与声明保留键及遮蔽的内部状态。实现测试须放置 getter tripwire，确保拒绝先于属性执行。缺省枚举可来自可信基类声明，旧 D 探针已确认 `init=False` 标量在 vars 缺席而在 asdict 出现。
- 隔离 serializer 只输出独立 DTO，不进入现有写端或 Control 重建。旧 D 探针已确认默认 replace 重置绑定，deepcopy 保留值。新实现须以显式 clone 保留规范绑定及身份，旧缺省复制和 raw 历史回放沿旧行为。

以上为设计准入及旧源码复现。跨进程陈旧投影、原始 append、正式批次映射、008、HostFence 和官方首副作用闭包各有独立审查边界，生产 bound 路由继续 HOLD。
