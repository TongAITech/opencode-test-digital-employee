# B06 PostgreSQL Scope真实HTTP工单

基线111bc4806bb39f7bb44d857610d3b17878b23eac（F135接受B05后），独立worktree wb-b06 / 分支work/dsh-wb-b06。状态CODE_COMPLETE / F_INDEPENDENT_REVIEW_PENDING / DSH_FIELD_NOT_RUN。无R1写入或旧unscoped fallback，不修改08/09/10。

## 数据Oracle与页一致性

business_scope.ScopeStore.scope使用真实BRV JOIN权威RV证明 LEFT JOIN BRVS及权威SST证明；UNSPLIT保留真实BRV、sst_id与source_verified_link为null，不插入假SST。返回06固定字段，包括顶层next_page_cursor、两种revision、逐行来源ref/revision，source_refs覆盖本页全部证明。重复数组参数归一去重后只过滤真实连边；不存在的选择422，不执行笛卡尔乘积。

每页先可信项目授权，再解析稳定batch_id/DATE；同批次改期保留batch_id。事务采用REPEATABLE READ READ ONLY，计数/来源/分页查询共享同一快照。page_size 1–100，需求/版本/SST各至多100值。HMAC-SHA256游标绑定principal、project、batch、业务日期、规范化filter、relation_revision、access_scope_revision、page_size与位置。跨主体/批次/过滤器/修订、篡改、改期、换key均409；断线重连同key与相同修订可继续。每页重新授权，撤权优先403。

migration005新增project.access_scope_revision，由ACL INSERT/UPDATE/DELETE触发推进，防止撤权后重授使旧cursor复活；关系表INSERT由DB触发推进relation_revision，任何受控writer都不能添加新边却保留旧水位。RelationStore对005自动水位/旧001–004显式水位保持兼容。原日期历史及P1事务IDLE门禁保留。

## HTTP与身份边界

business_http.create_scope_server(address, connection_factory, cursor_key, host_identity_provider=None)返回真实ThreadingHTTPServer。路由：
`GET /api/workbench/v1/projects/{project}/release-dates/{YYYY-MM-DD}/scope`

query为可选batch_id、重复requirement_ids/system_version_ids/sst_ids、page_size、page_cursor。未知字段（包括principal/authorization）拒绝400；无可信认证403。缺资源404，非法连边422，过期游标409，DB或来源服务不可用503；异常不泄露凭据或其他项目对象。POST/PUT/DELETE为405。

HostIdentity只能由服务器配置的provider返回；不存在浏览器body/query/header principal回退。provider缺失503，未认证身份403。connection_factory每请求返回新的非owner runtime autocommit连接，按事务IDLE建立独立身份Scope。真实D身份接口尚未接入时默认fail closed；测试用固定Host token provider是明确的工程fixture，不代表银行宿主已验收。当前不提供自行登录/自建模型钥匙/会话历史。

服务端启动示例（由可信进程配置，不是用户输入）：

```python
from tools.dsh_workbench.business_http import create_scope_server, HostIdentity
server=create_scope_server(('127.0.0.1',port),runtime_connection_factory,
                           stable_secret_cursor_key,verified_host_identity_provider)
server.serve_forever()
```

key必须至少32字节，来自受控配置，重启保持稳定；轮换后旧cursor409。不得使用测试固定key/token部署。迁移owner显式migrate(connection,target=5)，runtime沿用001–004权限；005不授权迁移/ACL写权。

## 迁移回退与恢复

自动downgrade对005一律HOLD，要求先停止Scope流量、退休旧cursor签名key、备份并记录retirement receipt，防止epoch回退使旧cursor复活。005_scope.down.sql供此受控回退流程使用，保留业务表与所有资产；恢复005后使用新key。原B01–B05空表回退与非空HOLD测试在原schema继续执行；005下相应继承用例改验key退休HOLD而不假称自动回退成功。Windows/宿主离线恢复仍属D/F后续现场工单。

## 真实验证入口

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py' -v
```

PostgreSQL17.6、逐测试独立DB/nonowner角色；B06实际loopback HTTP查询真PG。覆盖合法分页到null、共享版本不共享SST、UNSPLIT来源、403/404/409/422/503、缺Host provider、游标篡改/跨身份/权限变化、页内并发提交保持旧快照而下一页拒绝、DB恢复、同key重连与换key拒绝、其他writer推进水位。Node导入现有C ScopeClient消费真实HTTP/PG为READY；C最新PR131应再按自身精确SHA联调，不将本工程fixture称作真实宿主。

首轮真实测试暴露空query严格解析400，已修复；005继承旧schema自动回退测试初次失败，明确改为scope key退休HOLD语义，原schema回退测试仍保留。当前组件全PG99/99通过，新源需同SHA CI和独立F接受后入账；不是现场/产品全局QA_PASS。
