# D 对正式 Mission 绑定第一阶段的审查

审查对象为 [E PR245](https://github.com/TongAITech/opencode-test-digital-employee/pull/245) 的 `ff98337d1b97da68082dbb96e262057a817aa0b5`，源码基线 `27fb6cc70a60a024d885dd6952ca44f70204a738`。按 [D PR242](https://github.com/TongAITech/opencode-test-digital-employee/pull/242) 的构造、冷回放和写端清单核对。第一阶段结论为 **P1 HOLD**，修订后可独立复审结构保真和旧 Mission 兼容。

## D-FMB-01 · 通用序列化及 Mission 写端须拒绝非缺省状态

E 合同第 1 节规定对象 guard 检查内部状态，也要求在旧 payload 中移除内部字段，但缺少对通用 `to_payload` 和直接 `append_entity` 的明确拒绝规则。现有 `append_entity` 并不调用 `reject_reserved`。它在 `rc7_runtime/truth_overlay.py:373–384` 先做 durable acceptance，再经 `:243–260` 调用 `to_payload` 并覆盖 release ID。通用 `to_payload` 在 `rc7_runtime/models.py:288–294` 用 `asdict`，动态字段不会进入 payload。保护 Control 的检查并不保护直接入口。

在临时目录使用实际 `TruthRuntime`，给精确类型 `Mission` 附加 `scope_binding={'synthetic': True}` 和 `_scope_state=b'fixture'`。直接 `reject_reserved` 返回 `MISSION_SCOPE_NOT_ADMITTED`，随后直接调用 `append_entity` 成功持久化一个无任何 Scope 键的 Mission。该探针用动态值模拟候选状态，候选 HEAD 本身没有类型实现。它证明已有绕开 Control 的调用路径和丢字段机制。若实现只移除新增 dataclass 字段，带绑定对象同样会成为无 Scope payload。

冻结规则须规定精确 Mission 在两处拒绝。通用 `to_payload` 在调用 `asdict` 前判定，直接 `append_entity` 在 durable acceptance 和 `append_atomic` 前判定。三保留动态键任意出现，以及内部状态为完整绑定、null 或未知值，均稳定返回 `MISSION_SCOPE_NOT_ADMITTED`。先检查动态字段，随后仅允许可信内部枚举单例 `ABSENT`。通用序列化仅对合法旧缺省态移除内部字段，旧 ID 处理和旧 payload 保持原语义。应保留 `append_rc72_entity` 对 Mission 的精确类型拒绝。测试直接调用两处，验证 HOLD 和 R1 字节、投影不变，另以未绑定对象证明旧持久化仍可执行。

只有独立纯 serializer 输出紧凑 DTO。第一阶段须证明它未接入任何现有写端、Control 重建及生产入口，且无从该 DTO 到既有 append 的新增转换调用。实测现有 `TruthRuntime.append_atomic` 接受显式 scope 字典并保留其内容。它和 `JsonlEventStore.append` 仍是原始端口，因此阶段一的隔离不能作为底层写端闭合的证据。旧日志回放继续保留历史字段。

## 缺省态和复制的源码核对

- 用当前 Mission 的临时 dataclass 子类声明 `_scope_state = field(init=False, default=ABSENT)`。新建对象的 `vars` 中没有该键，`asdict` 却包含枚举单例。默认实例通过类字段取值。实现须对可信 Mission 的缺省读取保留这一行为，不能只把 `vars(...).get(...)` 当成完整状态判定，也不能对任意对象信任伪造属性。
- 给该探针设置绑定字节后，`deepcopy` 保留字节，默认 `dataclasses.replace` 返回 `ABSENT`。对缺省探针深拷贝后枚举身份不变。候选已要求显式保真复制路径。实现验收须覆盖绑定身份不得被 clone 重置或改写，以及旧无绑定的复制行为。
- 定向搜索运行、交付、管理和工作台目录未发现现有正式 Mission 的直接 `asdict(mission)`、`replace(mission,...)` 或 `Mission(**...)`。直接通用入口为 `models.to_payload`。另有 `rc72_truth._json_payload` 使用 `asdict`，但 `rc7_runtime/rc72_truth.py:54` 的精确类型映射不含 Mission，`:332–350` 在序列化前拒绝它，临时账本探针实际收到 `UNSUPPORTED_RC72_ENTITY`。
- D242 的八个构造或重建点仍可定位。旧直接创建在 bank `rc7_runtime/bank_mission.py:149`、N1 `rc7_runtime/rc72_mission_node_dispatch.py:369` 和五处 qualification，Control 在 `rc7_runtime/closed_loop_control.py:580–599` 从受检原始行重建。正式旧构造签名及输出需逐项保留，已带保留键的原始行继续由原保护边界 HOLD。

批次单事件三身份、受控来源校验、先副作用闭合、008、HostFence 和真实 Host 验收仍按各阶段另行审查。当前可用的结构设计包括旧 wire 键缺省、15/4/7 隔离往返和只读诊断。所有探针仅用内存和临时目录，无真实 Host、PG 或完整集成回归证据。
