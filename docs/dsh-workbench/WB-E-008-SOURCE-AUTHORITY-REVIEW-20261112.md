# E 审查 008 物理合同及正式来源边界

审查 [B PR265](https://github.com/TongAITech/opencode-test-digital-employee/pull/265) 精确 `4d058cf3363e129a45846fafd1f583850c07626a`、[D PR267](https://github.com/TongAITech/opencode-test-digital-employee/pull/267) 精确 `8875872091bbf50cfe93ed31d9aeff3818ed2bb2`，并核 [E PR245](https://github.com/TongAITech/opencode-test-digital-employee/pull/245) 与 [D PR263](https://github.com/TongAITech/opencode-test-digital-employee/pull/263) 的正式批次来源约束。E 接受隔离 PostgreSQL 结构及 PREPARE 事务候选施工。生产 PREPARE 分配与最终 R1 append 保持 HOLD。

## 可独立施工的 PostgreSQL 范围

- 可用隔离显式 008 节点验证固定字段的 snapshot、intent、receipt 引用和 journal，覆盖复合 FK、摘要、append-only/FORCE RLS、角色授权、叶子回退、目录 profile 和与 009 的两种安装顺序。PREPARE 事务可用隔离测试端口提供预留输入，验证完整 K 判等、同 K 并发只持久一次、换业务批次或选择冲突、失败原子回滚及未知提交后按原 K 恢复。测试输入不进入原 authority。
- 接入真实 allocator 前必须签原 K、原 Host 主体/context、当前 mutation/create 权限、服务边界及未知分配查询。若角色能直接 INSERT intent/receipt/journal，需证明连接仅供受控入口使用，生产入口将 PREPARE 和 PERSISTED、receipt 和 RECEIPT_LINKED 分别写于同一事务。测试须覆盖缺诊断、错 K/actor、伪造回执发行者和撤权后的历史保留。
- `FOR NO KEY UPDATE` 可作为实库候选。005 的 ACL 触发器推进 project 版本，关系触发器推进 release_batch 版本。002 的日期更新推进关系版本。候选应用临界区需要覆盖真实写路径、反序死锁、锁后重读和旧 FK KEY SHARE 兼容性，覆盖结果供 V3 锁模式改动签署。专用锁 owner 须显式获得 `EXECUTE wb.allowed(text,boolean)`。角色及函数授权一并进入固定目录模板。

## 正式运行批次及请求摘要

- `CanonicalRC72Repository.persist` 用 repository 的 release_id 补足运行批次行。`bootstrap_release_batch` 用 ReleaseBatch 的 release_batch_id 查正式行和创建节点。PG `batch_id`、Mission `runtime_release_id`、canonical `runtime_release_batch_id` 在职责和写入路径上分别独立。首版正式 PREPARE 必须固定第三个 ID 和永久 operation ref，authority 内唯一。E 建议新 008 同一 intent 内声明非空第三 ID 及唯一域，便于同一事务和原 K 查询一次读全。若采用独立表，须以完整 K 一对一约束，并证明 PREPARE 成功必有配套 reservation，避免允许只写 parent 的半条意图。
- 正式 request digest 需覆盖独立九字段描述、K、紧凑绑定必需身份及 Scope 摘要。摘要置于同一创建事件的外部协议字段或既有紧凑绑定相应位置，避免描述自引用，保持 15/4/7 与九字段各自精确。正式摘要 wire、event schema、可验证 receipt 字节和物理唯一域须在生产创建可用前精确冻结。旧键缺描述时保持未解析，不借当前投影或 PG 预留补写 R1 来源。
- canonical ReleaseBatch 当前投影不能证明原 creation 唯一或历史三元组稳定。正式 reader 在固定受管 ledger 中核原始事件与精确 batch ID 全历史，之后以 runtime release batch 查 ETU/Obligation，响应保留 PG 业务批次。原回执可查而 canonical Batch 尚缺时，图与执行为 INITIALIZATION_HOLD。纯描述 codec 或无副作用读取可以独立验证。

## 实库探针与最终提交阻断

在可丢弃 `MetadataPG` fixture 上使用 PostgreSQL 17.6、UTF8、8192 字节块，加载真实 001–007+009。临时 NOLOGIN/NOINHERIT 角色使用 schema USAGE、两个源表 SELECT、`wb.allowed` EXECUTE、候选列 UPDATE 及候选 permissive/restrictive UPDATE 策略。先漏授 `wb.allowed` EXECUTE 时，锁查询报权限不足。补齐后，以事务内原主体 alice 执行两个 `FOR NO KEY UPDATE` 均取到行，两个实际列 UPDATE 均报 `42501`。这是角色和策略探针，未安装 008 或运行生产 SECURITY DEFINER 端口。

保持两行锁时，最后一次 `SELECT 1` 成功。第二连接删除 alice 的真实 ACL，`pg_blocking_pids` 观测到等待。第三连接 `pg_terminate_backend` 成功后，ACL 删除提交，旧连接下一查询报 `57P01`。探针执行退出码 0，未调用 R1。该顺序使一项已发出的外部调用可在当前授权失效后到达 writer。重 ping、超时和事后 lookup 都不能把这项调用与撤权排序。原 PG intent 的持久性也不保护实时权限。

E 保持最终 append HOLD，直至共同 authority 排序或耐连接故障的 reservation 经过实际证明。若选 reservation，须明确撤权、日期/关系变更、Host/角色/DDL 谁参与排序，谁可关闭预留，以及失联或期限过后如何禁止旧 writer 提交。回收需从同一 authority 证明结果并阻断过期持有者，单靠墙钟到期释放会留下旧调用。生产验收需两个受控 writer 和真实 PG，用同步点在外部 append 前后杀 backend、提交权限或 Scope 变动，并分别断言拒绝路径 R1 原字节零变动、未知路径唯一原回执可查且不重放。Host fixture 的通过属于协议验证，实际 Host 撤权与执行资源仍需行内验收。
