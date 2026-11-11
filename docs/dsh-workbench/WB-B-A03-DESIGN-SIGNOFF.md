# WB-B / WB-A03 领域关系与数据库设计签署记录

**状态：B_DESIGN_SIGNOFF（设计可实现性；以本 PR 的修订合同为准）/ W1_IMPLEMENTATION_NOT_STARTED / F_QA_NOT_RUN。**
- 审查时 W0 源 SHA：80efa1bfa585fe29a5939c889d5b5a08e4f742ed（PR #84；W0 更新后需要重新做 delta review）。
- RC7.2 冻结运行基线：work/rc7.2@58e5b25ac75a8f6dc71e46fc6bdd0d71aa690d0d；参照 docs/rc7.2/00–05。
- F 独立证据：PR #85 / docs/dsh-workbench/qa/WB-F00-HEAD-DELTA-4349EE6.md，FG02/03/04/13/16。F 的结论不能由 B 代签。
- 测试证据：tests/test_dsh_workbench_b_a03_design.py 是一次性 SQLite SQL 约束设计可行性见证；不证明 PostgreSQL、正式 API、R1/SSE、数据库迁移或行内环境已经实现。
- 不复制 naodeng/dsh-qa PolyForm Noncommercial 受限源码；业务行为设计与独立原创实现分离。

## 1. 冻结边界与冲突消解

投产批次的**唯一用户可见身份**是 YYYY-MM-DD 的投产日期（例：2026-11-12）；不使用 BATCH-001 或版本号作为面向用户的批次名称。稳定 batch_id 是隐藏技术主键，改期时不变。业务日期是 DATE，**不是 UTC 时间戳的 date() 截断**。新建批次输入 ISO 日期直接存 DATE；从 RC7.2 planned_release_time 迁移时，必须有经银行业务责任人批准的 BUSINESS_TZ 与 DST/非整点规则，否则 MIGRATION_HOLD，不默认 Asia/Shanghai。

RC7.2 docs/rc7.2/00、02 的运行资产最低要求 ReleaseBatch/Requirement/SST，01 的 ReleaseBatch 有 planned_release_time、version_ids、requirement_ids，但没有 project/release_date/系统版本复合关联。**工作台是独立关联/查询投影，不更改原始 R1 ReleaseBatch/Attempt/Evidence 和 N1–N10 领域真相**。映射通过稳定 source_id + source_ref + mapping_revision，保持历史 R1 hash/事件/分母。

一个项目同一有效投产日期至多一个批次，跨项目允许同一天。同批次内：Requirement ↔ SystemVersion 为多对多，且双方均必须在该 batch；**BR 与 BV 的复合 FK 不能代替需求—版本真实来源连边，BRV 还必须 FK 到 source_verified_requirement_version。** SST 只能挂在经过来源校验的 (project,batch,requirement,system_version) 连边上。同版本可被多个需求共享，不能因此自动把 SST 从一个需求复制到另一个需求。未拆分时保留合法 BRV 和 split_state=UNSPLIT，不造假 SST 行。

## 2. PostgreSQL 规范化关系（B01–B05 的实施目标，当前无迁移代码）

下表为工程设计契约；W1 按它实现 SQL migration、约束、repository 和真实事务测试。所有关联必须包含 project_id，项目/批次关系不能仅靠前端授权。

| 对象 | 必需列/键 | 来源与规则 |
|---|---|---|
| project | PK project_id | 主体权限由 DSH 宿主提供，DB 不信任客户端自报 |
| release_batch | PK (project_id,batch_id), UNIQUE(project_id,release_date), release_date DATE NOT NULL, relation_revision BIGINT, status | batch_id 永不因改期变化；同项目日期冲突 409 |
| batch_date_history | PK (project_id,batch_id,date_revision), old/new DATE, changed_at, actor, reason, approved_change_ref | 与 batch 日期更新同事务追加、不可物理覆盖历史 |
| requirement_identity | PK(project_id,requirement_id), UNIQUE(project_id,source_system,source_namespace,source_object_id), source_revision | 跨环境/源租户同 external ID 不可互认 |
| system_identity | PK(project_id,system_id), source_system/namespace/id | 系统稳定身份 |
| system_version_identity | PK(project_id,system_version_id), FK(project_id,system_id), UNIQUE(project_id,source_system,source_namespace,source_object_id), version_label | 相同 version_label 在不同系统是不同对象 |
| sst_identity | PK(project_id,system_version_id,sst_id), FK(project_id,system_version_id), UNIQUE(project_id,system_version_id,source_system,source_namespace,source_object_id), UNIQUE(project_id,sst_id), source_revision | 来源唯一性限定在系统版本内，内部 sst_id 项目内稳定唯一；同一上游 raw ID 跨版本复用要分配独立内部 ID，保留 raw source_ref/source_revision |
| batch_requirement BR | PK(project_id,batch_id,requirement_id)；FK batch、requirement_identity | 不允许跨 project |
| batch_version BV | PK(project_id,batch_id,system_version_id)；FK batch、system_version_identity | 不允许未参与批次的版本 |
| source_verified_requirement_version | PK(project_id,batch_id,requirement_id,system_version_id), source_link_ref、source_revision；FK→BR/BV | **必须有源系统已确认的需求—版本关系**；仅 BR+BV 均存在不授权组合；未获源证明不可创建 BRV |
| batch_req_version BRV | PK(project_id,batch_id,requirement_id,system_version_id)，复合 FK→BR/BV/**source_verified_requirement_version**，split_state UNSPLIT/SPLIT，relation_revision | 合法空 SST 显示待拆分，不能丢失这条关系 |
| source_verified_link | PK(project_id,batch_id,requirement_id,system_version_id,sst_id), source_link_ref, verified_source_revision, verified_at；复合 FK→BRV 和 SST | 仅持有来源明确的需求/版本/SST 合法连边，禁止猜测或多对多自然乘积 |
| batch_req_version_sst BRVS | PK(project_id,batch_id,requirement_id,system_version_id,sst_id)，复合 FK→BRV + source_verified_link | 有来源证明才可写；同 SST 复用多个需求仅当来源分别明确授权，否则 422 |

PostgreSQL 的所有复合被引用键必须以 PK/UNIQUE 形成真实数据库约束；迁移应使用命名 FK、适当索引、NOT NULL 和有效的身份域。外键禁止 ON DELETE CASCADE 删历史，运行关联采用 RESTRICT/软停用 + audit。应用还需验证客户端请求中关联来源的当前有效性及状态，不仅依赖 FK 防止业务越权。

系统版本不能用 version_label 拼接、SST 不能只凭 sst_id 或 requirement_id 关联。RC7.2 老字段中的 string ID 数组是迁移输入，不是新四元组真相。来源系统身份字段属于数据合同的一部分：source_system、source_namespace（租户/环境）、source_object_id、source_revision、observed_at、source_ref。

## 3. 写入事务、并发与 403/409/422 顺序

- 所有批次写入在 PostgreSQL 单事务执行，至少包含 principal/project ACL、已稳定解析 batch、项目关系、source_verified_link 校验、expected_relation_revision CAS、BR/ BV/ BRV/BRVS、审计与事件 outbox。持久事件只在提交后可见；失败不能留下关联或 outbox 半写入。
- 拒绝顺序：**403** 主体未登录/未获项目权限（不泄露对象是否存在）；已授权且不存在的批次/资源 **404**；乐观锁/重复冲突/改期日期冲突/来源修订已变 **409**；已授权对象存在但复合连边不合法、SST 不属于此版本、越批次复用、来源验证不足 **422**。入参结构错误 **400**。数据库/R1 失联 **503**（不可假空成功）。
- expected_relation_revision 是每批次关联投影版本；CAS UPDATE ... WHERE relation_revision=:expected 必须检查 exactly-one；冲突重试要重新加载 Scope 与来源快照，不可静默覆盖。批次日期更改也需 expected revision，遇 UNIQUE 日期冲突转 409。
- 删除/撤销关联：有关联用例、Obligation、Attempt、Evidence 或 R1 链接时必须标记 retired_at、superseded_by、审计原因，不物理删除。既有 Attempt 的原始 release_date/source_ref 记录保留发生时值，最新 Scope 使用当前日期。
- 来源系统重新同步先进行来源 revision 对账；未知/冲突的 SST links 不写入成功集，登记 SOURCE_LINK_HOLD/422；禁止“先写一部分再恢复”的 silent partial success。
- 可重放命令必须有 service-side principal 和稳定 request_id/idempotency_key、payload hash；同时命中幂等键不同 payload 为 409，不能靠客户端自己写 principal。此处命令控制权归 E，B 只对领域关联变更的原子性负责。

## 4. B06 Scope 合法查询合同（交给 C/E）

入参：principal(服务端认证)、project_id、batch_id 或 project_id+release_date、requirement_ids[]、system_version_ids[]、sst_ids[]、page_size、page_cursor。batch/date 同时出现必须一致，不一致 400 INVALID_SCOPE。原始 ID/label 不作模糊字符串匹配。

**先授权，再解析项目批次，再验证被请求 ID 的批次成员资格，最后做 join。** 无被选关系时显式 422 ILLEGAL_ASSOCIATION；存在合法 BRV 但无 SST 时保留 UNSPLIT 行。查询逻辑为：

~~~sql
FROM batch_req_version brv
LEFT JOIN batch_req_version_sst brvs
  ON brvs.project_id=brv.project_id
 AND brvs.batch_id=brv.batch_id
 AND brvs.requirement_id=brv.requirement_id
 AND brvs.system_version_id=brv.system_version_id
WHERE brv.project_id=:authorized_project_id
  AND brv.batch_id=:resolved_batch_id
  AND (:req_ids_empty OR brv.requirement_id = ANY(:req_ids))
  AND (:version_ids_empty OR brv.system_version_id = ANY(:version_ids))
  AND (:sst_ids_empty OR brvs.sst_id = ANY(:sst_ids))
ORDER BY brv.requirement_id,brv.system_version_id,brvs.sst_id NULLS FIRST
~~~

SQL 在真实实现时必须绑定参数、检查 Array/NULL 语义和固定排序。多选数组只过滤**实际连边**，不对所有合法 requirement 与 version 做 CROSS JOIN；有合法输入 ID 但某两个多选组合没有连边，仍返回其他真实连边；显式要求不存在的单条组合则 422。

返回包含 project_id、batch_id、release_date、relation_revision、access_scope_revision、truth_revision(若引用 R1)、as_of、source_refs、records、warnings、gap_indicators、next_page_cursor。游标签名绑定 principal_id、project_id、batch_id、过滤 ID 集合、relation_revision、access_scope_revision、truth_revision、稳定排序位置；任一权限/关系版本变化 => 409 STALE_CURSOR 并要求重新拉快照，不能跨项目/日期重用。快照/游标创建的数据库事务隔离至少保证当前页一致性；跨页关系变更必须提示重新查询。

**C/E 消费边界：** B06 输出合法 Scope 和来源证明，不产出 NodeGate PASS、Attempt/Evidence 或业务质量分数。E 负责 R1 truth_revision 和 503 降级，D 提供宿主可信 principal，C 只显示状态/筛选；四者不能从前端筛选直接授权或修改 R1。

## 5. 兼容迁移与回滚门禁（B08 真正实施，W0 设计签署）

1. dry-run 检查 RC7.2 ReleaseBatch 原始 ID、mission_id、planned_release_time、name、version_ids、requirement_ids；生成 legacy_id → stable batch_id、project_id、release_date 影子映射。无可靠 project 或时区、同项目同日多批次、相同源 ID 身份冲突、R1 未对账者 **MIGRATION_HOLD**，停止导入该域并列出有来源的冲突报告。
2. 沿原始 Mission/Attempt/Evidence hash 与 release_batch_id 比较迁移前后资产分母；校验两个方向的映射完整性、需求/版本/SST 关联没有虚构边。旧模型缺系统版本到 SST 关系时，标 SOURCE_LINK_HOLD/UNSPLIT，不凭需求字符串推测。
3. 展开/回填：新增带 FK 的影子关系，事务化小批导入（每批 checkpoint/restart），完整审计及等量校验；双读对账，不立即改写旧 R1。切读前保存版本化快照、部署 manifest、schema_migration_id 与回退点；切读必须由 A/E/F 审查。
4. 回退：切回旧读取路径/影子映射，不能抹去已经发生的新审计/Attempt；如迁移已承接新写入，**不应直接 DROP 新表**，必须先证明无新增有效关系或有对应反向兼容写入。重复执行同一 migration_id 幂等，冲突不静默合并，原始 Mission/Attempt/Evidence 字节和 hash 不变。
5. 正向/回滚/停机冷启动都在 W1+/W2 的 PostgreSQL 与 R1 真数据另验。这里不声称已完成。

## 6. 设计级反例核对

| 反例 | 必须的判定 | B 合同见证范围 |
|---|---|---|
| T1 同需求 R1 跨三系统版本多个 SST | 返回真实多关联，非平铺后任意配对 | SQL join 契约；三版本全面场景留 W1 |
| T2 共享版本 R1/R2 不共享 SST | R2 只读 R2 的 source_verified_link | SQLite FK + join 正向 |
| T3 两系统同 version_label | 以 system_version_id + source identity 分离 | SQLite 唯一/显示标签 |
| T4 跨项目同日/跨日期重名 ID | 只有授权项目+batch 的连边 | SQLite 正反例 |
| T5 没有 SST 的 BRV | 明确 UNSPLIT，不能虚构记录 | SQLite LEFT JOIN |
| T6 跨批次冒用 SST/错误来源关系 | 已授权 422，数据库无副作用 | SQLite 拒绝/事务模拟；真实 HTTP 待 W1 |
| T7 一 Case 覆盖多个 SST | Case/Attempt 不重复计数，R1 保留原始事实 | 与 E 的 R1 trace 验收在 W2 |
| T8 改期冲突与历史 | UNIQUE + 审计同事务，稳定 batch_id | SQLite 设计见证；真实迁移待 B08 |
| T9 恢复失效 Scope | 版本/权限变化重读并提示 | C/D/E 联验 |
| T10 越权访问 | 授权前置 403 不泄露对象 | SQLite 鉴权顺序见证；宿主身份待 D/E |
| 409 版本/游标冲突 | 不覆写、关联/事件零副作用 | SQLite CAS 见证，游标待 B06 |
| 503 失联 | UNKNOWN，不显示空成功/PASS | B/E 真源联验 |

## 7. 设计签署声明与保留项

**B 组正式签署：WB-A03 B_DESIGN_SIGNOFF**，签署的是以上字段与复合 FK 设计、真实连边查询规则、授权优先级、事务/并发/改期/迁移/回滚的**实现方案与负向验收标准**。只对 B 的领域边界负责，不代 D/E/F 签署。需要 A 将本文规范性增量合并入 W0 候选，并请 F 复查其差异；在此之前 W0 仍 NOT_FROZEN。

**非放行保留项：** BUSINESS_TZ 的银行业务批准及实际 source mapping 未拿到；PostgreSQL DDL/数据源连通/迁移 dry-run/真实 rollback/HTTP/Scope 分页/冷重启均 NOT_RUN；未获商业授权 BLOCKED_LICENSE；PR #85 FG16 的独立核销由 A/F 负责。无需先完成 W1 实库来获得 W0 设计签署，但 W1/W2 的 IMPLEMENTATION_QA 绝不可借本签署提前晋级。

**后续 ready 规则：** A + F 明确 W0_DESIGN_FROZEN 后 WB-B01 与 WB-B02 可并行启动真实 schema/唯一性/日期历史/系统版本身份；B03 依赖 B01+B02；B04 依赖 B03；B05 依赖 B04；B06 依赖 B05，交付 C/E 合法 Scope API；B07、B08 在 W2 分别依赖 B05、B07。未经前置 Gate 满足只开展设计准备，不登记 IMPLEMENTATION_QA_PASS。

## 8. W0 反向测试发现的设计纠错
首个 B 设计 CI（8 个 SQLite 测试，7 PASS / 1 FAIL）证实只让 BRV FK 到 BR/BV 仍允许 R2 与已参与 B1 的 VB 组成未经授权的关系。修正为先登记 source_verified_requirement_version（含来源 link_ref），BRV 加强制复合外键；再由 source_verified_link 授权 BRVS。三版本五 SST 的 R1 正向 fixture 与不存在的 R2/VB 反例一起验证。**这是真正的设计缺陷纠正，不得把旧红 CI 改写为 PASS；新的同 HEAD CI 以独立结果为准。**

## WB-FG18 / 独立验收红测后的 B 组领域纠偏（2026-11-09）

- F 原始失败来源：https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42634316547/job/129218336677。F 在原始 B DDL 实测同一 Starlink SST-100 来源 ID 在两个系统版本独立出现，第二行被错误项目级唯一约束拒绝。这是确实存在的设计缺陷，历史 FAIL 保留。
- **修复：**项目内内部 SST ID 必须稳定唯一；来源唯一键修改为 (project_id,system_version_id,source_system,source_namespace,source_object_id)，跨版本相同 raw 来源 ID 允许对应两个独立内部 ID。**关联键始终包含 version_id**，不能只看 raw ID 或 version_label。
- SQLite 五列设计见证对应 UNIQUE(project_id,sst_id) + UNIQUE(project_id,version_id,source_system,source_key)。新增 sst_source_trace 以三元复合 FK 记录 source_namespace、source_revision、source_ref，并添加跨版本同 raw ID、正确 JOIN、跨批次/错需求/错版本拒绝、同版本重复拒绝、跨项目正常隔离共四组测试。
- **实施边界：**简化 witness 中 trace 表可单独加载，正式 PostgreSQL 迁移必须在 SST 实例创建事务中强制存储完整原始来源身份与 revision/ref，验证可信源而不是相信 UI 入参；B01–B05 真库测试待 W0 正式冻结后执行。
- 此轮 B 修订和 CI 不代表 F 接受 FG18，需 F 从新 B HEAD 独立重跑其 test_dsh_workbench_b_sst_identity_f.py。A 仍需解决 FG17/FG19，C 需解决 FG20；W0 NOT_FROZEN，A02 BLOCKED_LICENSE，未开始 W1、无银行包。

## WB-FG18 本轮 CI 红绿原始证据（2026-11-09）
- 历史红：F 原始 B HEAD 704c86a 下，F 独立案例 test_same_raw_sst_id_different_system_versions_are_distinct 在 job 129218336677 因旧 UNIQUE(project_id,source_system,source_key) 抛错。红灯不删除。
- 绿色修订来源：B HEAD eb48d161bd5c7caa29733fccfabc44654a376dd6；同 SHA run 42637588144 / job 129229772001，14/14 B SQL 正反例通过、72/72 W0+B 合同通过。
- 更关键的是：此 CI 以固定 F 独立 HEAD 5111044d87a97120d57cddc1b6d3c8e177502c2f checkout 原始 tests/test_dsh_workbench_b_sst_identity_f.py，并设置 WB_B_CHECKOUT=. 指向 B 当次源码；F 旧红反例在修订 DDL 上真实执行 1/1 OK，非改写 F 测试。
- 源日志 https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42637588144/job/129229772001 。此结果证明 W0 SQLite 约束设计纠偏，不替代 F 再审签署、PostgreSQL/HTTP/R1/现场 QA。F 的 FG18 独立关闭结论仍 PENDING，W0 NOT_FROZEN、FG17/FG19/FG20 OPEN、A02 BLOCKED_LICENSE。
