# D：M1既有根项目改名与命名域精确审查

被审：[PR #230](https://github.com/TongAITech/opencode-test-digital-employee/pull/230)，完整源 **`a21b82fe805926a22b5d90babec5670dd912c6aa`**，base为D211 `1e1a75ff`。已完整读取B命名域候选、D原最小分阶段候选及其catalog/调查证据；另完整核对A产品决策 `9a41b145` 中 `WB-A-PROJECT-METADATA-M1-DECISION-20261111.md`，不改原B HEAD。独立worktree `d-project-metadata-m1-review` 从被审源建立。

结论：**D_M1_RENAME_AUTH_RECOVERY_DESIGN_ACCEPTED_AT_A21B82FE_WITH_A_9A41B145 / NO_NEW_D_P0_P1 / IMPLEMENTATION_AND_FIELD_NOT_QUALIFIED**。

D接受在A已选定的root-first/名称字节/完整域/009分阶段范围内继续独立实现候选；本报告不是现有metadata API、SQL迁移、production治理来源或真实Host已经可用的证据，不代签B/E/F及新profile。

## 1. 当前权限足够支持的范围，不扩大成新全局能力

M1只对**已存在、行政完整治理绑定、NAMING_ACTIVE且政策允许rename的根PROJECT**修改唯一当前project.name。当前可信server principal+项目can_write、Host mutation/CSRF+Origin证明、原主体write-context可以作为这项既有项目业务修改的授权条件；无需为此等待新的global project.create动作或真实Mission HostAdmissionFence。若用既有受审原生调用证明替代浏览器CSRF，应仍沿D211的独立可信路径，不能把任意字段当证明。

这些条件必须共同校验：mutation_authorized=true不是项目ACL、命名域管理权或首次创建权；拥有任一项目can_write、甚至拥有同域某项目写权，均不能自行创建project/iteration、改kind/parent/namespace、管理成员、创建目录/Host会话或临时授自己ACL。PATCH白名单只含原request/revisions/changes{name}/reason，客户端principal/role/namespace/type/parent/owner均不可提交。namespace政策由服务器受控绑定决定，普通writer不能切域或激活域；行政治理不是新的公开超级用户端点。

原项目仅name/ID/ACL epoch、runtime项目只读、owner provision仅行政bootstrap等事实与源码相符；新受控rename的列权限/函数/RLS/前置授权仍须B/E/F审真实SQL。不能用migration owner HTTP连接实现“当前主体可写”。父子ACL独立，M1不提供iteration写入口，即使命名域先定义了iteration规则，也不授迭代创建/重挂/成员能力。

## 2. A已冻结的名称选择与完整治理分母

A9a41b145明确选择B的`project-name/utf8-exact-v1`、128标量/512字节、只trim首尾U+0020、其余大小写/组合字符/Unicode空白精确保留；D不再把该选择当待现场确认。服务端及DB必须核规范文本/key一致，名称只用于显示与域内唯一性，不能用于join或替换project_id。它不代表现有数据库已经有name UNIQUE。

根域(namespace,ROOT)、iteration域(namespace,parent root)及bytea比较有明确边界；不是visible-list、用户私有域或按项目各建一个namespace规避A01去重。行政来源的ref/revision/hash、完整成员及其余legacy排除依据是启用域条件；未知潜在成员、旧同域冲突、非法旧名保持GOVERNANCE_HOLD。治理必须有独立行政审计，不按最小ID/当前用户自动选保留者，不改ID、不把重复行偷移到别域。

未知legacy仍按原ACL读取原name，不强制规范化、不默认为PROJECT、不因其metadata_revision机械初值1就有rename资格；写返回METADATA_NOT_GOVERNED。这不会阻断已有完整合格域的编码/隔离实库测试；行政fixture只证明该组件路径，不证明生产治理权威。

A接受有限的一位NAME_UNAVAILABLE信息是交互唯一命名的显式产品决定；不能再声称严格零存在性泄漏。禁止返回不可见项目ID/成员/owner/父项，不设任意namespace名称探测端点。该有限信息不授跨项目或namespace读取详情。

## 3. 原主体恢复、CAS与目录ABA

原K=(project,server principal,request_id)和动作/受控负载摘要、完整原回执、事务CAS/history/audit/result/outbox共同构成单PG事务证明。context不纳入可变Cookie/CSRF，不是授权token；重试仍核当前Host/项目权限和原主体域。Alice未知请求不能被Bob换context重包；撤权/不可读/原context不可验证时不泄漏原结果，不换key/主体绕开，不以缓存判无提交。

同K同digest的已提交结果是**历史回执**，应在当前授权后取回，不受后来metadata或ACL CAS值覆盖；未提交的新操作才比较expected revisions。恢复不重新写name/key或重复history/outbox。UI收到旧applied_metadata_revision后重读当前值，不能用原receipt回滚新值；NO_CHANGE也须有可重放的原回执，但不伪造metadata变化版本/历史/changed事件。域被停用时不能产生新rename；若返回原已提交历史回执，也不能把它当重新授权或继续写入许可。

仅name不变的digest不能拒绝A→B→A旧cursor。B新增metadata_revision与投影schema版本的Directory策略合理；ACL epoch、metadata CAS、date/relation revision仍相互独立。必须以单调metaRev及稳定身份编码，而非name哈希/当前名称来冒充变化代次。rename不应伪改batch/date/BRV或使十区合法Scope无故失效。旧cursor/schema兼容须C/D在具体wire实现复核；不能在旧v1静默接受不匹配水位。

## 4. 已知实现阻断必须保留，不等于设计拒绝

- 当前business_migrations.migrate只接受1–7并按range(1,target+1)连续扫描。009不能直接套旧runner，也不能造空008或跳过checksum。A已选择009显式依赖001–007、008仍留E；先有受审依赖manifest/runner实施单，验证旧prefix兼容、未知依赖/重复/缺文件/checksum/回滚行为，才能实际安装009。该项是行外可解决的代码依赖，不是新Host现场阻断。
- 在A9a41b145源码核对现有profile ID `dsh.scope-source.project-only.pg17.001-007.v2` 及固定内容hash校验。009增项目列/权限/约束/函数/触发器后不能让旧profile自学习、过滤掉差异或跳资格。未批准新模板时明确UNQUALIFIED；新的SQL/角色/触发器和profile另交B/E/F精确审阅。B候选老base尚未包含这份后续资格实现，不把它谎称为B HEAD本身已有能力。
- 锁顺序/namespace共享锁、project更新锁、绑定/幂等域及行政迁域的顺序在设计上提出，但尚无SQL。真实两连接撤权/域停用/迁域/唯一冲突/死锁/事务终止必须实测，不能以本D审查代替证明。受控rename的history/key/CAS不能被直接DML绕开；已发生历史不可破坏性down。

## 5. 实际核查与证据边界

已读实际HostIdentity、asset_request mutation/context前置、write_context、BusinessStore、DirectoryStore及migration runner；PR230 HEAD核对为a21b82fe，RC7.2远端edaf9290。没有新metadata实现，因此没有运行/宣称新rename/namespace权限产品测试通过。

本次另在PG17.6的既有Directory/PostgresIdentity可丢弃fixture实际运行**当前源码特征观察**：给Alice第二个项目的fixture ACL以形成cursor，owner仅在隔离fixture将P1的name作A→临时B→A，随后旧cursor仍被当前DirectoryStore接受，完整digest等于原值。结果：`cursor_exists=true, digest_after_A_B_A_equals_original=true, old_cursor_still_accepted=true`。这确认新metaRev要求有实际依据；不是新M1失败/通过，也未通过运行角色绕过现有权限或修改生产数据。

同轮调用现runner `migrate(None,target=9)` 在任何连接操作前抛 `UNKNOWN_MIGRATION_TARGET`。它确认现有runner阻断，**不是009迁移测试**。fixture finally清理；没有新SQL文件、Host适配、R1或原始Evidence改动，没有把已有目录测试PASS转签本候选。

最低实现验收保留：同域不可互见重名拒绝且无详情泄漏、未知legacy阻止域启用、旧冲突治理、current write/mutation/context各自失败、Bob重包拒绝、原回执/NO_CHANGE/后来改名、ABA、namespace停用与ACL撤权竞态、key/name原子约束及history/outbox故障全回滚、009依赖/新profile失配fail-closed。M1不提供项目创建、成员/父子/目录、R1阶段或RELEASED，当前E02 HOLD/Human UNKNOWN仍拒绝发布。

只新增本独立报告，不改候选/实现、08–10或冻结原文。D精确接受这项有界M1设计继续推进；SQL/namespace生产治理来源、真实Host/Windows及B/E/F各自证据仍独立，不核销完整项目管理或最终交付。
