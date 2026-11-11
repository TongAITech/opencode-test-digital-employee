# Runtime ReleaseBatch 的来源与正式 reader 候选

源码基线 `800dfa3742f6f093989c140b178c79d92d43c18f`。承接 D242 和 E245 第 2–4 节。候选供 A/B/E/F 对 reader 边界审查。所有事件形状和状态属于拟议合同。

## 真实来源和已复现行为

| 路径 | 作用 |
|---|---|
| `rc7_runtime/rc72_domain.py:122–145`、`rc72_repository.py:41–56` | ReleaseBatch 对象有 release_batch_id 与 mission_id，持久化时由 repository 的 release_id 补足第三个字段。 |
| `rc7_runtime/rc72_truth.py:31,87–96,133–142,332–350` | RC72_RELEASE_BATCH_UPSERTED 按 release_batch_id 标识实体，overlay 校验并规范化三元组。 |
| `rc7_runtime/rc72_state_machine.py:199–223` | 缺行时实际持久化 Batch，再逐个建 N1–N10。已有行检查 batch/mission，同函数没有为 Workbench 分配身份或验证 PG 绑定。 |
| `rc6_runtime/truth.py:88,194–227,326–349` | 投影按类型及实体 ID 保留最高版本，另有版本历史。同一版本同 payload 可折叠。当前一行不能证明只有一个原始创建事件，也不能证明历史三元组不变。 |
| `rc7_runtime/rc72_field_mission_start.py:134–175,208–250` | launcher 要求唯一既存批次，读取三元组，并匹配同批次、同 Mission、同 release 和精确 source commit 的 Q7 及原生镜像证据。随后初始化节点及 Field-start receipt。 |
| `rc7_release/rc72_mission_bindings.py:16–60`、`rc72_configured_mission.py:95–136`、`rc7_runtime/rc72_mission_factory.py:117` | 加载与组合运行能力。给定批次时先查 canonical row 和 release；Captain 路线要求可信 Host 注入和精确批次。配置、CLI 参数和 loader 不提供业务批次映射。 |
| `tools/dsh_workbench/e01_service.py:38`、`e02_service.py:16–39`、`e02_lineage.py:35–37` | E02 当前先调用 E01 quality，再做冷回放及平面身份检查，把 PG batch 直接传给 ETU/Obligation lineage。新正式路径必须拆出前置身份检查，不能先走会取详情的 quality。 |

临时目录调用真实 state machine，以 `runtime-release`、`runtime-batch`、`mission` 创建正式批次与十节点。随后调用现有 `CanonicalRC72Repository.persist`，以同批次键写 v2，但改用另一 release 和 Mission。冷回放按批次键只返回一条当前行，三元组已改变。此探针展示旧写端与投影语义，不能用作绑定授权。reader 必须核原始 creation 事件唯一性，以及 canonical Batch 的全部相关版本三元组。正常状态版本演进可保留，身份漂移即使改回也须 HOLD。去重后的投影和内容哈希不能替代源事件检查。

## 最小 reader 合同

- PG batch_id 属于业务项目，runtime release_id 对应 Mission.release_id，runtime release_batch_id 对应 canonical ReleaseBatch 主身份。三者独立。生产首版按 durable PREPARE 预留，原 K 重试复用同一份身份及永久 creation_operation_ref。不同 Mission 可共享 PG 批次，各自仍保留独立正式运行身份。
- 依 E245，在同一条受控正式 Mission creation 事件内保存紧凑绑定和独立版本化描述。V1 精确字段为 schema_version、formal_authority_ref、mapping_ref、project_id、batch_id、runtime_release_id、runtime_release_batch_id、mission_id、creation_operation_ref。相同字段与绑定逐字核对。完整版本化 request digest 纳入描述及永久操作引用，008 复用同一 operation ref 保存意图和回执引用。mapping_ref、runtime release batch ID 在 authority 内唯一。首版正式分配独立 runtime release。紧凑 15/4/7 维持原形，映射权威来自正式 creation 事件及已审来源，PG journal 与投影均为辅助查验。
- 先验证当前可信 Host 读取主体和当前项目/PG Scope 授权。随后固定同一 R1 读取修订，只查 Mission 身份、绑定、正式 creation 来源和历史 PG 快照。验证同一 authority/K/digest/operation 唯一原始事件、版本及映射，验证 PG 历史 snapshot 与 scope digest。按 runtime release batch 键查询 canonical row，核 batch/release/mission 三元组及历史版本；同时检查同 Mission 的相斥 Batch 或同 authority 的相斥映射。只有通过后才查询任务、图、运行与 Evidence，lineage 接受 runtime release batch，业务响应仍保留 PG batch。返回前重查当前授权与相关修订，变化须重读或失败关闭。冷回放内部可能加载整个日志，Oracle 测的是明细查询与返回顺序。
- 正式 creation 成立但 canonical Batch 尚未登记时，原主体 lookup 可按 V3 返回可查原回执，图与执行进入 INITIALIZATION_HOLD。旧缺映射、平面兼容行、未知版本、重复源事件、映射冲突、损坏或撤权均关闭正式 graph，无字符串猜测及 unscoped fallback。受控初始化恢复使用原 operation 和预留 ID，按确定性身份补齐，冲突停止。只读 replay 和 lookup 不创建事实。UNKNOWN 或 PG 回执写失败先 lookup，只有显式 submit 且重新通过当前创建动作、mutation、can_write 和 HostFence 才可能进入正式提交。
- 读取授权、原主体 lookup、正式创建、初始化、执行及 N10 各用自身权限。真实 Host 创建动作和撤权围栏能力仍待行内资格。已有 Q7、source/mirror、Captain 与 worker 资源租约、Human Gate、NodeGate 都是后续动作的前置。reader 成功仅证明该次受权读取的来源和关联。当前 E02 的发布 HOLD 保留。

## 可执行验收

先用真实临时 R1 重跑上述批次创建及 v2 身份漂移探针，检查字节、投影、历史和三元组。reader 实现后可用隔离来源 fixture 测身份不等、无映射、缺 canonical row、重复原始创建、映射及 digest 篡改、跨 authority、同 Mission 多批次、v2 漂移再改回、撤权和快照变化。每个拒绝用调用计数验证零任务、图、执行、Evidence 明细查询，原始账本与数据库无写入。允许同三元组正常状态演进。成功用三个不同 ID 与真实 ETU/Obligation lineage，验证内部使用正式运行批次而响应保留 PG 身份。

正式验收依赖受控 creator、真实 PG 快照与 008、来源核验、实际 Host/lease 能力，并覆盖独立 PREPARE 后崩溃、append 后断线、回执失败、双进程争用、初始化中断与冷恢复。真实链路可由原 K 查到同一 creation 回执且只出现一条受控源事件。fixture 结果仅说明 reader 或协议行为。受控事件 schema、索引、权限和 writer 闭包分别签审。
