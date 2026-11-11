# B：M1 可选009与真实PostgreSQL改名候选

历史记录：仅对应旧冻结源`785790deb6d277f3be0e363f4901835d1fa625be`。该源后来实证治理并发与ICU缺陷，未获准部署；见[修复与红绿证据](WB-B-PROJECT-METADATA-009-GOVERNANCE-FIX-20261111.md)。下文保留旧运行结果，不转签到后续源。

状态：**ISOLATED_PG_CANDIDATE / B_LOCAL_REGRESSION_PASS / D_E_F_EXACT_REVIEW_REQUIRED / NO_HTTP_OR_PRODUCTION_ENABLEMENT**。基线 W0 `c8b779abdea173699a28eeccec1098ed53187a59`，只引用不改变已冻结codec `63ea53b13e931576955670dd96f2d5a334cd0242`。输入B230 a21b82fe、A9a41b145、D235 96600655、E233 bfd96c0b、F234 a776640e、C237 bcf5669d。代码、测试和此证据一起冻结；CI随后只写PR body。

## 1. 实际启用边界

- 009目录为`migrations/optional`，不进入旧001–007文件枚举、默认migrate或旧profile artifact。显式`migrate_project_metadata(admin_connection, executor_role)`先校验固定manifest内容hash、SQL up/down hash、唯一文件、显式图、真实已应用版本和checksum，要求001–007齐全，不补装008，不从max(version)推断连续。沿原迁移advisory lock/单事务；旧downgrade遇可选迁移明确拒绝，不误扫009。
- 执行角色由行政部署创建并提交审核，候选不自动创建/授登录凭据。009需要NOLOGIN/NOINHERIT/无角色成员边、无owner/BYPASS/DDL高权/危险replication GUC权；额外角色仅拥有两只固定路径的入口函数，不拥有业务表。暂时schema CREATE仅同迁移事务内转函数owner后撤销。runtime显式获两只函数EXECUTE，不继承/可SET executor，不直接获得name UPDATE或namespace SELECT。`FOR SHARE`实测需要至少一个UPDATE列权限，executor只获namespace_revision列，不获状态/政策/治理列；入口函数不更新该列。
- 空009 down移除额外函数/表/约束及executor留在旧对象上的grant；已有治理记录或业务历史拒绝down，需保留数据和审计的行政恢复/forward修复。测试的“空”指无009业务/治理历史，原001–007项目仍保留。
- 这是已治理根PROJECT改名；不建项目/迭代、成员、父子、目录或Host会话。完整行政分母为每个现有project的MEMBER/有依据EXCLUDED，激活时核绑定与规范key；未知潜在成员或同域冲突不激活。行政新建项目使既有活动域退回HOLD，避免遗漏新分母。生产行政来源及历史非法/同名的审核纠正流程另交付；本候选不会静默重命名、移动冲突项目或授权普通写者自行治理。已有非法/冲突legacy在治理完成前可读，不获得改名资格。

## 2. 写入、恢复、锁与目录

`ProjectMetadataStore(connection).get_metadata(principal, project_id)`和`.rename(principal, MetadataRenameRequest)`为内部端口，组合原BusinessStore IDLE/SET LOCAL/当前ACL边界。调用方必须独立验证Host mutation、CSRF/Origin、原主体context；DTO/PG GUC都不证明Host授权。GET为`project-metadata/v1`，两revision字符串，治理状态GOVERNED_ROOT_ACTIVE/METADATA_NOT_GOVERNED/GOVERNANCE_HOLD，无namespace成员。receipt为`project-metadata-receipt/v1`，project/request/action/outcome/name/applied_metadata_revision/access_scope_revision/audit_id/history_revision；outcome APPLIED或NO_CHANGE，版本/audit字符串，NO_CHANGE history_revision null。503 `METADATA_DATABASE_UNAVAILABLE`或`METADATA_RETRY_REQUIRED`。403 FORBIDDEN不披露项目；同域唯一冲突只返回NAME_UNAVAILABLE。

DB用相同算法复核canonical原字节与SHA256；action进入digest，共用原request_log K=(project, actor, request_id)。DB以复合FK绑定claim摘要、audit原身份、history/result/outbox；当前name只有wb.project.name，binding仅保存UTF8 key，deferred约束核一致性与变更proof。NO_CHANGE同样有operation audit/原结果，无revision增加、变化历史或changed事件。已提交同K/digest先重核当前ACL再返回完整历史回执，不重新CAS、不写当前name。域停用阻止新写但可恢复已提交原结果；撤权无原结果泄漏、恢复原主体后可读取原回执。`reason`原UTF8 bytea保存，audit hex可逆，包括合法JSON NUL/换行，不交给PG text/jsonb吞掉或替换。

锁序为namespace FOR SHARE→project **FOR NO KEY UPDATE**→binding FOR NO KEY UPDATE→shared claim→当前ACL/治理/CAS→写入；绑定等待后重读域，变域失败重试。旧asset/batch先claim，project外键取KEY SHARE；真实不同K旧批次在新事务尚持父锁时成功，验证所选锁兼容性。连接间测试用pg_blocking_pids观察实际等待，覆盖旧claim commit/rollback、实际AssetStore完成或注入回滚、metadata先持锁后的旧动作冲突/超时/回滚获胜，以及同域隐藏名并发/同revision并发。候选锁等待上限1.5秒、statement 5秒，不放宽外部更严设置，恢复后原连接可用；连接checkout/既有授权读与DDL的整体时限仍属部署配置，不声称拥有DDL/role fence。

`MetadataDirectoryStore`是可选009目录子类，仅全授权项目内部摘要加入metaRev和投影版本；原wire `business-directory/v1`、项目record字段、数字access epoch、batch digest均不改。旧cursor拒绝；A→B→A项目记录虽相同，metaRev使旧cursor仍失效。旧DirectoryStore默认路径保持原输出，没有HTTP选择新子类。无R1端口、文件或执行写入；真实PG测试比对原批次记录，未声称已验行内R1现场。

## 3. 实际验证与尚未准入

本地真实 PostgreSQL **17.6** / psycopg **3.2.13**，每测试独立数据库/runtime role，不用SQLite。全部 B PG suite **296 tests / 111.963s / OK / 0 skipped**，包含27个新增实库测试和2个manifest测试；最后进一步强化audit/history/outbox注入对name/key/audit/claim/result/history/outbox零前缀的Oracle，另重跑新增29项。旧codec28和profile artifact2分别通过。测试通过证明隔离候选，不代F独立测试。模拟响应丢失在真实PG已提交后丢弃调用返回，以新连接原K恢复；不声称执行了真实HTTP断网。

[实际catalog捕获](evidence/WB-B-M1-009-PG17-CATALOG-20261111.json)仅审阅输入：默认profile v2面对已装009真返回UNQUALIFIED（project列/约束和RI执行态漂移）；空009 down后原profile回到MATCHED_AS_OF，两个结果均admission_authorized=false。没有用部署catalog自动学习模板、不修改profile v2、不加入新生产profile。未来009精确SQL/角色/触发器及新固定模板须D/E/F审核，生产治理清单和真实Host身份另证。

首次实库探测发现namespace row-lock实际需UPDATE列权，最小修正后验证；两处测试fixture缺asset cursor key和旧runtime迁移授权，按实际既有合同补齐fixture。一次catalog采集误把SQL LIKE的百分号作为参数占位，纠正采集后才落盘，未把失败记成证据。无008/HTTP/UI/08–10/冻结合同或R1变更，不为本组件生成Windows离线包。M1产品仍待同源端点/界面与新profile、F实证；RELEASED/现场/最终交付均未核销。
