# B07 milestone首纵向切片实现

基线0b22bb804086d50d27bee9afcbc1446d52e720c2，独立worktree wb-b07-milestone / 分支work/dsh-wb-b07-milestone。合同源22fc88ff2884dea92ff6139bf9a56aa1474331e6，D39e7bccd/E44828bf0已分别设计签署。**B作者明确B_AUTHOR_DESIGN_SIGNOFF_ACCEPTED**，仅签本人的领域/Scope/版本/CAS/幂等/审计outbox/迁移设计责任，不冒充独立B评审或E/D/F。

状态CODE_COMPLETE / F_INDEPENDENT_QA_PENDING。本次只实现milestone业务草稿；case/obligation/defect/report/knowledge/minutes与E正式引用映射尚未实现，不能声称整个B07完成。现场统一FIELD_NEEDS_BANK_TRANSFER，行外fixture不替代真实DSH、CSRF宿主或Windows验收。

## 实现与入口

business_assets.AssetStore提供create/update/retire/restore/get/list；真实HTTP由business_asset_http挂到既有business_http.scope_handler，仍可与Scope/quality统一宿主入口共存。

`/api/workbench/v1/projects/{p}/batches/{b}/assets`：POST创建，GET列表；`/{asset_id}`：GET详情/指定revision、PATCH修改、DELETE软退役；`/{asset_id}/restore`：POST恢复。详情与日历都查询同一asset_id/current_revision，日历只加kind=milestone和due_from/due_to，不创建影子日历表。

create输入：request_id、expected_relation_revision、kind='milestone'、title、payload={due_date,description?,owner_display?}、scope_level、brv_links/brvs_links。修改/退役/恢复带expected_asset_revision与reason；PATCH payload按字段合并。scope_level=BATCH_WIDE时无伪造关系，EXACT_RELATIONS复合FK至真实BRV/BRVS；UNSPLIT允许BRV，不能虚构SST。其他kind/未知或嵌套正式结果字段400；正文PASS只是草稿文字，不写R1、NodeGate或执行结论。

响应metadata含当前投产日期、relation/access/assets revision，record含asset_id/revision/kind/title/payload/state/scope_level/links/创建时投产日期快照，r1_reference_state固定NOT_LINKED。列表records及顶层next_page_cursor；同一合法Scope空资产集合可正常为空，不是质量PASS。

HostIdentity.mutation_authorized默认false，只由可信provider在宿主session+Origin+CSRF或可信非浏览器证明验证后置true；写还需当前project.can_write。provider缺失503，读身份不能写403，body/query mutation_authorized或principal拒绝。API自身不假设Origin存在即合法，不以缺Origin绕过。测试provider明确验证fixture Cookie/Origin/X-CSRF-Token组合，真实DSH provider仍需搬运行内配置验证。

body最多64KiB，严格JSON/Content-Length/UTF-8/重复key拒绝、读取超时；SQL参数化，正文不执行。provider及当前项目权限先于对象body读取，连接保持IDLE事务身份门禁；GET snapshot用REPEATABLE READ。

## 数据与恢复

migration006：asset_root+不可变asset_revision、版本化BRV/BRVS链接、asset_outbox与asset_request_result。root当前指针CAS推进，日期/状态/Scope/原因/actor每版保留；DB延迟约束要求每个新版本都具备合法Scope、对应当前指针、审计和outbox，初版必须1且后续连续。asset_revision/links/outbox/原响应不可UPDATE/DELETE；运行角色仅更新root.current_revision，无物理删除/迁移权。

原请求按当前主体重新授权后幂等：同键同payload返回原提交响应，即使资产后来已更新也不伪装成当前记录；异payload409。事务包括修订锁/合法关系/不可变新版本/root CAS/audit/outbox/原响应。audit/outbox故障、非法日期/关系或断连在提交前均回滚，重连同键可安全对账恢复；业务outbox只有workbench.asset.*，不等于R1正式事件或执行PASS。

资产写推进assets_revision，签名列表cursor同时绑定主体/Scope/kind/due范围/include_retired/关系/权限/资产revision/page_size。资产、权限或关系变化使旧cursor409。退役历史按当前权限读取，恢复重新验证当前合法关联，不改变任何正式Case/Defect/Evidence。

迁移owner显式migrate(connection,target=6)，运行角色执行006_milestone.runtime.sql；downgrade(target=5)仅新资产表全空可回退，非空拒绝并要求备份/对账恢复。降级不触既有B01–B06或R1。依赖许可证沿用Psycopg/PostgreSQL，无新增受限源码。

## 真实验证

```sh
WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_b*postgres.py' -v
```

milestone测试独立真实PG数据库/nonowner角色与loopback HTTP，覆盖详情创建→日历同ID→改due范围→退役/历史/恢复；CAS并发、幂等原响应、错误日期/嵌套正式字段、非法共享版本SST/UNSPLIT、撤权读历史/重放拒绝、CSRF/Origin/伪字段、audit和outbox分别故障回滚、backend终止提交前回滚并重连同键恢复、分页水位、append-only及空/非空迁移回退。继承B01–B06负向与恢复，不用SQLite或截图代替Oracle。

首轮milestone真实38/38通过，加入audit独立故障/断连后40/40通过；后续DB约束与输入边界加固须最终同SHA再验。专属CI通配已覆盖milestone测试；无PG/driver的轻量检查仅明确SKIP，不当PG验收。最终源必须交F独立验收与C真实UI纵向联调。

首片自查修复：初源1d862a4c虽禁止历史Scope行改删，但仍可向已提交版本INSERT新合法连边，可能静默扩Scope。修复为不可变revision保存scope_link_count，版本及两种link表均有延迟完整性约束，创建必须同事务完整提交，后续补边拒绝。新增真实PG攻击与CRUD/降级定向3例均通过；新源全量CI/F须独立核实，不继承旧140数字。
