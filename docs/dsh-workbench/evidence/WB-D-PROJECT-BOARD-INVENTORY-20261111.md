# D 项目／看板已有能力调查证据

调查源 `199a316334abb41c77890ed5608b989e2a7e6126`；RC7.2远端核对 `edaf9290594ecaf66c482470da64ae706ff8c7aa`。新独立worktree `d-project-board-contract`。本次只新增候选与证据，没有实现新API/模型/SQL或修改08/09/10。

## 已读工程合同与源码

- 01六页面/十分区矩阵与P03/P06目标，02完整领域/PG合同，06 API/授权/事件及目录专属增量，A01原子P03-01..04/P06-01..04/X02-01；只根据仓库内冻结目标归纳，未复制受限上游实现。
- migrations001及runtime grants、005 ACL/relation revision触发器、BusinessStore/provision_project、DirectoryStore、business_http HostIdentity与GET/unsafe dispatch、business_asset_http的mutation/context前置、AssetStore的原结果/审计/outbox及write_context。
- 现有directory-panel只显示授权项目卡片和日期选择；无项目CRUD或看板stage。E02 graph投影固定HOLD和UNKNOWN_NOT_QUERIED，不能据其构造发布PASS。

## 真实PG catalog只读检查

实际使用Psycopg3.2.13、PG17.6 Unix socket `host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres`。复用已有 `test_dsh_workbench_b_postgres.PostgresIdentity` 可丢弃fixture和原有migrate(target=7)创建隔离schema/角色；随后仅SELECT information_schema/pg_constraint/pg_policies/pg_class和has_*_privilege读取catalog，finally执行已有fixture清理。没有访问或更改生产R1/银行环境，也没有新增/修改业务SQL文件。

实际JSON见[原始catalog快照](WB-D-PROJECT-BOARD-CATALOG-20261111.json)。关键结果：

| 核对 | 实际结果 |
|---|---|
| project列 | project_id text NOT NULL，name text NOT NULL，access_scope_revision bigint NOT NULL |
| project唯一约束 | 只有PRIMARY KEY(project_id)；name仅btrim非空CHECK，没有name UNIQUE/namespace/type/parent/metadata revision |
| runtime项目权限 | SELECT=true；INSERT/UPDATE/DELETE=false；name列UPDATE=false |
| project RLS | enabled=true，FORCE=false；只有SELECT using wb.allowed(project_id,false) |
| project_acl runtime SELECT | false；不能把该表直接当人员目录暴露 |
| release_batch键 | PRIMARY KEY(project_id,batch_id)，UNIQUE(project_id,release_date) |

上述是**已有数据结构/权限的观察**，不是项目编辑、新建、成员管理或看板产品验收。隔离fixture的迁移建库不代表银行离线数据库迁移验收。没有运行新产品功能测试，也未将历史目录测试PASS移用本候选。

## 实际现有HTTP/恢复边界

business_http当前目录GET只匹配projects及projects/{id}/release-dates；其他metadata/board/new-project路径未实现。unsafe dispatcher仅将含/batches/的路径交asset_request，其他PATCH/POST返回405。provision_project显式注释owner administrative bootstrap且不在HTTP；HostIdentity只有principal/mutation_authorized，无project.create/namespace/members能力。write-context主体HMAC不是动作授权。

现有asset_request在业务解析前核mutation、原主体context和当前项目ACL；AssetStore原结果/事务审计适合借鉴，但资产表/result/outbox带batch/asset域，不能伪造一条batch或asset承载project元数据。DirectoryStore快照包含name和ACL epoch，rename应使旧项目cursor失效；不能把该cursor等同metadata CAS。

调查时最初按猜测文件名读取02/06失败，随后用目录实际路径完整读取；失败不计验证通过。没有因这些失败跳过真实字段/权限核查。真实DSH/Windows仍需行内验收，已有项目metadata设计/实库组件不因现场不可达而全部阻断。
