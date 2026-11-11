# E Mission Scope 第一阶段实现证据

实现基线 `2de01bc49ae229e1dda9f04107d0680a92d50bff`。设计 PR245 `5be49d089cdf8e320c29276418e3069fe9c0e796` 经 D248、F249、B251 限定接受。历史 D247 的直接序列化/写入失败保留。

基线临时 R1 重现动态 `scope_binding=None` 经 `to_payload` 和 `append_entity` 丢失。随后以带空白的 Mission ID 和另一个 release 调用直接 append，原带 null 的 canonical 目标行被无 Scope 的新行覆盖，R1 bytes 改变。实现现在以实际类型、静态声明和内部 ABSENT 单例判断旧 Mission，先拒绝异常对象，随后按全局 canonical mission_id 查实际目标行，再进入 durable acceptance 和既有写入。原 release 参数覆盖行为在完全旧目标仍通过。现有 raw replay 保留历史行和 bytes。

内部 `init=False` 状态持有已核结构的不可变紧凑值。隔离入口从现有 Mission 和 Scope DTO 生成独立对象，独立 serializer 只返回 Scope 片段。`clone_mission` 和 `deepcopy` 保留绑定，默认 `dataclasses.replace` 对 bound 仍不受支持，测试记录其 init=False 缺省行为。普通旧构造与 clean 派生序列化保持，两个正式 append 的类型和 HOLD 规则以临时日志验证。

共享 `dsh_scope_codec` 是 stdlib 叶包，WorkBench 旧入口显式重导出原 API。实际 `cmp` 与基线 codec 源逐字节相同，F249 所依赖的既有 F 紧凑审计脚本重跑成功，完整黄金向量 709 bytes，SHA256 `204e86f036cc5c8ba3e67e5c45799a6fcf77d04625c5dbd00491618fc2f18c90`。三个 hash-seed 独立进程字节一致。新 `-I` 子进程证明旧纯入口未加载 RC6/RC7 runtime。按 `SOURCE_DIRS` 用实际 `_copy_tree` 复制源码并从隔离目录导入，叶包与保真模块均存在，运行导入未加载 Workbench。最终 Windows ZIP 留待发布门禁。

开发中的后置 mixin tripwire 先实际失败，旧检查只看 Mission 之前的继承顺序，`asdict` 仍能调用后置 mixin 的 getter。改为静态核实际生效的属性访问方法，回归通过。其他异常 Scope descriptor、伪造 ABSENT、显式 null、完整 compact 冷回放、跨 release 的 canonical 旧行、非规范 bytes、trim/覆盖身份、clone/replace、acceptance/append 零调用均有测试。

最终本地 pytest **415/415，9.98s**。仓内 223 项包含新增 29 项、紧凑 codec 9 项、受影响旧 185 项，另重跑未修改的 F224/F227/F229 独立脚本共 192 项。另执行 F 紧凑字节审计与 `git diff --check`。真实 3.8/3.11 工作流显式检出 PR 精确 HEAD，仓内 223 项与本地 415 项分别记录。后续 CI 实际结果由 A 写入工程台账，候选冻结交 F 独立验收。

实现范围为第一阶段结构保真与局部写保护。正式 reader、admission、writer、批次权威映射、PG 008/009、Host 和现场资格仍由后续增量审查。底层 raw 端口及陈旧跨进程投影保持既有边界。
