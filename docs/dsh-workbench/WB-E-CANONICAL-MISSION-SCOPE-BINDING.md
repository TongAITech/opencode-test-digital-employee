# RC7.2 正式 Mission — 工作台 Scope 绑定增量候选

状态：**DESIGN_REVIEW_PENDING_B_D_F / IMPLEMENTATION_NOT_STARTED / PRODUCTION_BINDING_NOT_IMPLEMENTED**。
精确调查源：`7586a80c0d8f5cd5205a78ca735b1ca15e12a4b2`（含 RC7.2 `edaf9290`）。本提案不改变 R1 事实所有权，不修改冻结合同或运行实现，也不代签 W1/F01/现场资格。

## 1. 已复现事实及证据范围

| 实际入口 | 本地隔离 R1 结果 |
|---|---|
| `models.Mission`（models.py:100） | `project_id`/`batch_id` 不是 typed 字段，传入构造器得到 TypeError |
| `bank_mission.start_or_resume`（bank_mission.py:132、146） | 正式 STARTED 与 RESUMED 均没有这两个字段；不能从公开参数提供绑定 |
| `ClosedLoopControlPlane.bootstrap`（closed_loop_control.py:114） | 只持久化现有 typed Mission，不创建业务 Scope 绑定 |
| 临时 R1 手工添加 extra 字段后，调用正式 `refresh_ready()` | `_mission()`（:564）按现有 typed 字段重建，`_sync_mission()` / `_persist_mission()` 正规更新会丢弃 extra；随后 `mission_overview_scoped` 拒绝 |

显式复现命令：

```bash
python3 -m unittest discover -s tests -p audit_scope_binding_characterization.py -v
```

结果：3/3 **缺口复现**，不是3项产品通过；每例只使用 TemporaryDirectory R1，没有真实 Host、数据库、业务执行或生产 R1。脚本刻意不匹配常规 `test_dsh_workbench*.py` 门禁，不能把“断言当前缺口存在”作为未来实现验收。

E01 的 synthetic fixture 在 `asdict(Mission(...))` 后加入 project/batch，证明了读取拒绝边界，但不能证明正式创建/运行接续已实现。现有组件验收数字不被改写；生产纵向能力仍需补齐此缺口。缺绑定时的403是正确的失败关闭，不能改成从 release_id、名称、日期或版本标签猜归属。

## 2. 唯一正式所有者与最小模型范围

建议由 **RC7.2 正式 Mission 创建/恢复控制面**拥有 typed `MissionScopeBinding` 与写入规则；工作台不得直接 append Mission、修补已有 R1 payload 或另建一套 Mission 状态。B PostgreSQL 仍拥有业务对象与 verified BRV/BRVS，R1 只保存正式运行的不可变身份、来源引用/修订和摘要。

候选 typed 绑定字段：`project_id`、稳定业务 `batch_id`、`mission_id`、正式运行 `release_id`、`binding_ref`、`binding_version`、`relation_revision`、`source_refs`、`scope_digest`、创建时 `release_date` 快照与验证时间。`project_id` / `batch_id` 可在 canonical Mission 上保持现有读取契约所需的扁平身份字段，其余来源随 typed binding 持久化；所有重建/序列化/更新路径必须完整保留。规范化摘要必须覆盖完整身份与经验证的关联集合，而非仅名称或两个合法ID集合。

模型兼容要求：旧 Mission 允许“整个绑定缺失”；已绑定 Mission 不允许半个绑定、空ID、无来源或摘要不匹配。新工作台正式创建必须携带完整已验证绑定；旧独立 legacy 创建不自动获得工作台权限。绑定本身不授 Captain、Worker、执行或人工审批权限。

## 3. 可信验证端口与正式创建

正式工厂接受服务端构造的 Scope 候选和 **受控只读 Scope verifier**。verifier 必须从当前真实 B06/PG verified 关系读取并核验可信 Host 主体、project/batch、修订、来源连边及合法筛选；浏览器字段、`verified=true`、单独的 dataclass 实例或模型文本均不是验证权威。该端口不能从 CLI 任意 import 路径或浏览器参数指定。真实 Host 未接入时保持未就绪，fixture 只作组件测试。

验证必须发生在首个正式 Mission/R1 创建事件之前：主体/项目范围不合法拒绝，来源或关联不合法拒绝，无法读当前修订返回未就绪；不得先创建无绑定 Mission 再由工作台补字段。PG 与 R1 不假定分布式原子事务；验证失败/超时不得签 accepted。跨存储提交不确定时依正式创建回执与稳定创建幂等键查询原结果，无法确认保持 HOLD，不盲目再创建另一 Mission。

`release_id`、RC72 ReleaseBatch 与业务 `batch_id` 必须有显式、可审计的正式映射，不假设字符串相等。首版新工作台创建使用正式控制面分配的新运行身份，禁止把已映射到另一个 project/batch 的运行身份复用；业务需求可共享系统版本不等于跨项目共享运行事实。正式 mapping 由创建端口验证并持久化来源引用；不能把业务日期或系统版本号当作 legacy release_id。

Scope 验证不新增执行授权。现有真实 Captain/Host、签名、资源租约、人审、NodeGate 与执行就绪前置继续独立强制校验。创建图/绑定不表示任务已执行或PASS，也不实现 E03 的暂停、恢复、重试网关。

## 4. 不可变性、正规更新与恢复

- 初次绑定在正式创建事件中完整持久化；同Mission的 project/batch/运行身份/binding_ref 不允许在普通更新、refresh、任务登记、状态变更或恢复时重绑定。
- `Mission` typed 构造、`to_payload`、R1 validator、`ClosedLoopControlPlane._mission()` 与所有其他 Mission重建器必须保留并校验绑定。字段遗漏不能静默降为legacy、重写绑定或继续派发。
- 恢复先核对既有正式绑定与请求身份，再读取相关事实/派发；同创建幂等键同完整负载返回原正式回执，异负载或重绑定冲突拒绝且原R1字节不变。现有先查身份再明细的访问顺序保持。
- batch改期保持稳定batch_id，不移动历史Attempt/Evidence。绑定中的创建日期是历史快照，当前业务日期来自B；差异必须可见且有改期审计，不能改旧运行事实。关系修订/来源变化导致原绑定不再满足执行条件时HOLD/STALE，不自动重算为新Scope；正式重基线另案评审。
- 已有无绑定 Mission不自动迁移。只读访问仍拒绝；来源映射、业务时区、旧冲突未取得独立权威证据时 `MIGRATION_HOLD`。未来若提供正式迁移，应独立签署、备份/分母核对/回滚，不由工作台后台修补。
- 冷重放、原始日志恢复、服务重启后身份保持；R1原事实不能被PG缓存、模型回答或浏览器storage替代。

## 5. 冻结合同影响与实现前评审

本候选请求后续专门增量评审，当前不直接改写以下冻结文件：

| 范围 | 待明确增量 |
|---|---|
| 工作台02 | PostgreSQL业务Scope与正式运行身份映射、合法来源/修订、改期/旧数据HOLD |
| 工作台05 | 由RC72正式factory/控制面产生绑定，E01/E02读取不补写事实 |
| 工作台06/A03 | 正式创建/恢复的typed输入、可信verifier、幂等回执、拒绝/未就绪及原始R1不变预期 |
| RC7.2 00–03及正式模型合同 | typed Mission绑定、旧兼容、创建与恢复不变量；不改变N1–N10/NodeGate语义 |
| RC7.2 Worker/租约合同 | Scope绑定不是执行权限；跨代次/资源与签名仍按现有正式路径准入 |

B审查 verified Scope/关联快照/PG-R1映射与改期；D审查真实Host主体、创建权限与恢复身份来源；E负责正式模型/factory/重建路径与只读接续；F独立验证不变量及真实正式创建链。A集成精确源意见后才准实现本增量；不能沿用W0旧签署替代此变化。

## 6. 退出条件（未来，当前均未运行）

1. 真实PostgreSQL verified多需求/多版本/多SST → 受控Scope verifier → **正式RC72创建入口** → 持久R1 → E01/E02真实HTTP成功，不手工给payload塞字段。
2. 正规任务注册/refresh/状态更新/恢复与新进程冷重放后，绑定及来源摘要完全保持；三次以上修订均能同Scope读取。
3. 跨project/batch、非法BRV/BRVS、两需求共享版本但SST不同、伪验证标记、无验证器、来源修订变化、重绑定与幂等异负载拒绝，验证失败前后原R1不变且无关联明细/执行副作用。
4. 真实创建成功但回执丢失，经稳定权威幂等键恢复原Mission/回执，不新建重复运行；PG不可用、R1缺失/截断及中断恢复明确HOLD。
5. 旧无绑定Mission回放不损坏且工作台仍拒绝，不借迁移之名给旧Attempt/Evidence改归属；冻结RC7/RC72受影响回归通过。
6. F绑定实现的最新完整SHA给独立结论；真实DSH/Windows仍须搬运行内验收，不能用本地verifier fixture或本次缺口复现代签现场。
