# B：Mission Scope V3 精确复审与分段准入

被审：PR #188，完整 `32fffb2115251f2860954fe0772ec45ef433b3b7`。对照B的V2报告 `2f6313316237240ac41290bdc4a0b4b00284ae67` 与当前真实001–005表/BusinessStore/ScopeStore。只审这一SHA，不把后续修订自动签入。

结论：**B_PURE_COMPONENT_DESIGN_ACCEPTED / B_FORMAL_CREATION_SIGNOFF_PENDING_ONE_P1**。V2三处问题均获得实质修订，不再用它们阻断无副作用纯组件；正式创建仍有一处持久化顺序P1须明确。008 SQL、锁原语与正式运行实现尚未存在或验收，本报告不是其实施QA，也不代签D/E/F或现场。

## 原问题核销范围

| 原审查项 | V3结果 | B结论 |
|---|---|---|
| B-MS-01：来源tag与字节 | 五种source按真实列分型，version无source_ref；业务复合键定位身份。version_ids显式映射system_version_ids，分页字段改为next_page_cursor；完整来源由新端口查询，不再伪称B06含date_revision/identity sources。控制字符、surrogate、整数域、UTF-8与排序已精确定义 | **文档规范已核销**；可准入codec/DTO实现。实际最终SQL连结和黄金向量实现测试后验 |
| B-MS-02：PG域键/回执复合约束 | K完整含authority/actor/project/key，batch作为不可变payload；snapshot完整FK含digest；receipt只存引用/hash而不重复正式身份，避免错配冗余列；权威内唯一性与分权/append-only/回滚HOLD明确 | **键与约束设计已核销**；008实际DDL/角色/FORCE RLS/拒绝测试仍须新PR签署 |
| B-MS-03：原主体幂等/未知恢复 | 同K改batch或其他payload409、原authority/context不自动切换、lookup不隐式submit、不得重分配、UNKNOWN不当NOT_FOUND已明确 | **K与恢复规则可签**；首次intent的独立durable顺序尚有下述P1，正式创建整体暂不签 |
| B-MS-04：锁端口/权限/事务 | 新IDLE-owned READ COMMITTED端口明确不嵌套/放松B06；受限锁函数、project→batch锁序、取锁后复验、SQLSTATE及硬预算与触发器提交顺序均给出；不将现有runtime权限当新权限 | **抽象协议方向已核销**；不能声称现有端口已可调用。SQL/两连接及崩溃实现验收后才能开放此能力；Host/writer语义由D/E另审 |

V3准确保留现有ScopeStore的IDLE与READ ONLY保护，未要求移除已修复的身份隔离检查。B接受上述抽象协议审查不依赖行内现场：行内证据只影响真实Host资格，不影响可测试的纯规范与PG组件施工。也不能因为抽象协议可签而把不存在的端口写成已实现。

## 正式创建剩余P1：PREPARE意图必须先独立durable

V3第2节说正式authority预留身份、PG保存意图；第3节第48行的最终PG事务一直到R1 durable append之后才提交回执引用，却未明确首次intent必须早于该事务另行提交。若实现者在这个最终事务中首次INSERT intent，会出现：

1. 首次K分配了runtime_release_id/mission_id/binding_ref/mapping_ref并计算request_digest，intent尚未提交。
2. 原子创建事件已durable进入R1。
3. PG连接失败/进程崩溃，最终事务连同首次intent全部回滚；调用者未收到正式身份或完整digest。
4. 新进程只知原K，而正式端口当前定义为lookup(K,digest)；若再次分配身份，digest改变并违反同K恢复规则；不再次分配则无法据已丢失的intent恢复。这可能安全HOLD，但不是合同承诺的可确定原身份/原回执恢复。

这是契约允许的一条未定顺序，不是对尚未实现端口宣称已复现漏洞。V2曾要求“任何正式副作用前持久化intent”，V3是单独新增合同，须把这个关键约束明确写入，不能让实现从历史草稿自行推定。

**最小必需修订：** 定义独立PREPARE事务，按K确定并持久提交不可变snapshot/intent、原authority/context、预留正式身份及完整request_digest；只有确认该事务durable之后才可进入正式提交围栏。PREPARE同K同payload读取原intent，同K异payload（包括batch变化）409；PG提交未知时先读取原K确认，未确认不重分配。最终锁定快照事务只重读/核验已存在的immutable intent并比较当前Scope/授权，不可把首次intent创建与R1 append后PG回执提交混为一次可回滚事务。PREPARE自身不产生正式创建事件、执行、accepted或PASS；过时意图保持审计/HOLD，不自动换键或改绑。

R1已durable而PG回执插入/提交失败时，持久intent足以按原K/digest向原权威lookup，核完整身份/回执hash后再补PG引用；绝不因PG rollback宣称R1未发生。若PG存储、原权威或原intent无法确认，保持HOLD，不重分配/重建。正式预留器若有独立副作用，也必须按K幂等恢复预留，不能让PREPARE失败分配另一个身份；具体预留/事件语义仍由E签署。

此P1修订不改变B已接受的纯编码/DTO/K规则；作者给新精确SHA后，B可仅针对PREPARE顺序窄复核。

## B允许立即施工的具体边界

- 纯Scope DTO/tag校验、排序、canonical bytes及scope_digest；拒绝重复/错tag/错复合身份/非法日期/无效Unicode/不合整数域，固定完整快照黄金向量及跨进程测试。
- K的纯结构/规范字节校验、creation payload规范化与独立域摘要纯函数。输入身份仅作为数据校验，不能由纯函数“预留”身份、授verified权限、访问Host或判定真实可创建。实现PR须固定完整request schema、独立域及黄金向量，K与mapping的authority/project/batch一致性须测试。
- 缺能力时只返回明确HOLD/CAPABILITY_UNAVAILABLE的适配边界；不得挂正式submit入口，不自动分配ID、写PG/R1、运行任务或生成accepted。纯组件的输入是DTO，不是可信verifier的授权证书。

以上是**B职责内的设计准入**，不是全组签署或测试通过；还须满足V3第7节要求的D等精确审查与独立实现验收。锁定快照原语、008、正式typed模型/factory/writer或运行能力不在这次准入内。

## 实际核查证据与限制

1. 真实本地PG17.6/Psycopg3.2.13、隔离fixture Scope（setUp→scope_seed→information_schema→doCleanups）：requirement、system_version、verified_requirement_version、sst_identity、verified_sst_link五类映射全部与真实列匹配；再次确认system_version无source_ref，V3未再伪造该键。只检查现有schema，不是008实施验收。
2. 用Python标准JSON编码逐字验证V3两个hex向量：`7b2261223a22e4b8ade69687222c227a223a225c6e227d`、`225c5c5c225c753030303122`，2/2文档向量自洽。这里未实现生产codec，不计为产品功能测试通过。
3. 只新增本报告；未改被审文本、008/实现、正式模型、R1、08/09/10。未调用真实DSH、生产PG或行内Windows；未把旧F或V2意见转签。现场仍FIELD_NEEDS_BANK_TRANSFER，正式发布未批准。
