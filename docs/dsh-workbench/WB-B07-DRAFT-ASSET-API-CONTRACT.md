# B07 业务草稿资产与追踪增量合同

状态：DESIGN_REVIEW_PENDING / B_E_D_REVIEW_REQUIRED / IMPLEMENTATION_NOT_STARTED。基线62bddde58da3d5a6e70d0d62f6772e9e22279f67；仅定义新增业务草稿接口，不修改RC7.2正式事实所有权。B07依赖已独立接受的B05；新增HTTP写入须本增量经B/E/D职责审查后实现。本文件不代签旧团队，也不宣告新实现验收。

## 1. 正式事实边界

已核对rc7_runtime/rc72_domain.py::TestObligation、case_runtime.py、defect_qualification_control.py、final_report.py及reporting.py。正式TestObligation/Case准备与执行、Defect资格/关闭、正式报告都受R1与控制面约束。工作台只拥有业务草稿与人工资料，不能把保存草稿变成正式Case、注册Obligation、已确认Defect、正式Report或NodeGate结果。

asset_kind限定为case_draft、obligation_draft、defect_note、report_draft、knowledge、meeting_minutes、milestone；asset_state仅ACTIVE/RETIRED。ACTIVE只是业务记录可见状态，不表示QA PASS或发布。任何结构化test_result、assertion_result、nodegate、mission_state、attempt、evidence_verified、formal_report、r1_payload及类似正式事实写字段拒绝400。自由正文可记录人工说明，但不能被解析为正式结果Oracle；界面始终标明草稿/资料。

正式R1映射另存asset_r1_reference，关联到具体asset_revision，包含canonical_type、canonical_id、mission_id、R1 truth_revision、source_ref、受控内容hash及验证时间。浏览器不能提交“verified=true”或直接写已验证映射；只由E拥有的只读验证接缝在最小Mission身份project+batch校验后读取指定正式对象并验证谱系，交可信服务端映射写入。此写入只记录引用，不调用R1 append/dispatch/update。接缝缺失或R1不可用时引用保持UNRESOLVED/STALE，不能提升草稿状态。普通草稿读取可独立于R1，但已存引用必须标为历史引用元数据，不返回凭空生成的正式结果；当前事实查询仍由E的正式只读接口负责。

缺少合法R1对象或引用谱系不清时，不创建已验证映射。退役/恢复业务草稿不关闭Defect、不删除Evidence、不改变原Case/Obligation/Report，旧asset_revision与引用永久可追溯。不能按名称、版本label、raw SST ID或正文字符串推断R1关系。

## 2. Scope与关系结构

首批表：asset_root PK(project_id,batch_id,asset_id)、asset_revision PK(project_id,batch_id,asset_id,revision)、asset_brv_link与asset_brvs_link（均包含asset_revision）。root以复合FK指向稳定ReleaseBatch；revision记录kind专属payload、title、ACTIVE/RETIRED、创建时业务日期快照、actor、reason与来源引用。root.current_revision只能CAS推进，版本行不可UPDATE/DELETE。

资产可明确选择BATCH_WIDE或EXACT_RELATIONS。BATCH_WIDE不伪造需求/版本/SST；只有未提供关系筛选时进入结果。EXACT_RELATIONS至少有一条合法BRV或BRVS；BRV link复合FK到已验证batch_requirement_version，BRVS link复合FK到batch_requirement_version_sst，均与同一project+batch+asset_revision绑定。UNSPLIT允许合法BRV链接，不能插入假SST。选定SST时必须使用完整BRVS身份；多选只返回真实边，不生成笛卡尔积。

批次改期保持batch_id及资产身份；响应中的release_date来自当前ReleaseBatch，revision保留当时业务日期快照与审计。Scope链接变更生成新asset_revision，历史版本不移动或覆盖。跨project/batch/不合法BRV/BRVS一律422且整事务无副作用。

所有kind共享相同Scope与授权。里程碑due_date是DATE，独立于投产日期；日历due范围过滤不改变当前批次或Scope。日历和项目详情里程碑读取同一asset_id/revision/表，禁止另建复制日历事实。

## 3. 新HTTP接口（待实现）

稳定路径：`/api/workbench/v1/projects/{project_id}/batches/{batch_id}/assets`。path身份不可由body覆盖。所有请求复用B06可信Host provider与project ACL，缺provider503；未认证/越权先403，不泄露资源存在性。以下kind为query/body枚举，URL不按名称联想资产。

| 方法/路径 | 输入与结果 |
|---|---|
| GET collection | kind可选；重复requirement_ids/system_version_ids/sst_ids；due_from/due_to仅milestone使用；include_retired默认false；page_size 1–100/page_cursor；返回当前合法Scope内记录及顶层next_page_cursor |
| GET collection/{asset_id} | 返回指定资产当前版本；include_retired=true才读退役当前版本；历史版本通过revision参数显式读取并保留原Scope/引用；仍先鉴权 |
| POST collection | request_id、expected_relation_revision、kind、title、payload、scope_level与BRV/BRVS链接；服务器分配稳定asset_id，返回201及revision1 |
| PATCH collection/{asset_id} | request_id、expected_asset_revision、expected_relation_revision、reason；allowlist更新title/payload/Scope，生成revision+1；kind、project、batch、asset_id不可变 |
| DELETE collection/{asset_id} | JSON含request_id、expected_asset_revision、expected_relation_revision、reason；创建RETIRED新版本，返回200；无物理删除 |
| POST collection/{asset_id}/restore | 同样CAS/审计字段，重新校验当前合法Scope后创建ACTIVE新版本；不恢复或修改任何R1正式状态 |

首纵向切片kind=milestone：payload只允许due_date、description、owner_display；title非空。日历用GET collection?kind=milestone&due_from=YYYY-MM-DD&due_to=YYYY-MM-DD及同一Scope筛选；详情用同一collection或asset_id，不另建calendar表。首批其余payload：case_draft=preconditions/steps/expected_results/oracle_notes（都是人工草稿文本/数组）；obligation_draft=business_rule/scenario/oracle_notes；defect_note=reproduction_notes/expected_notes/actual_notes（不含正式severity/state结论）；report_draft/knowledge/meeting_minutes=body文本与可选非执行类标签。每kind严格allowlist，未知字段400，不让嵌套JSON绕过正式事实边界。

HostIdentity新增服务端mutation_authorized默认false，仅D的可信provider在校验宿主写权限、CSRF/Origin或相应可信非浏览器调用证明后置true。客户端body/query/header自报mutation_authorized、principal或authorization均拒绝；不能因拥有只读会话自动准许写入。读仍沿用已有HostIdentity(principal)兼容；写还必须project.can_write。body上限64KiB，严格Content-Length/UTF-8 JSON/枚举/日期/数组数量校验；不执行正文HTML、脚本、命令或附件路径。

## 4. 响应、事务与游标

响应含project_id、batch_id、当前release_date、relation_revision、access_scope_revision、assets_revision、records或record、warnings、gap_indicators；collection始终含next_page_cursor，最后为null。合法Scope下没有业务资产可返回records=[]，明确为业务集合为空，不等同B06 Scope无合法连边或质量PASS。单对象无资源404；合法Scope关联非法422；CAS/幂等异负载/过期cursor409；数据库或所需可信身份服务不可用503。

列表页REPEATABLE READ快照；游标签名绑定principal、project、batch、合法Scope过滤、kind/due范围/include_retired、relation_revision、access_scope_revision、assets_revision、page_size和稳定排序位置。资产增修退役/恢复推进assets_revision，关系或权限变化同样使旧cursor409；不得把旧批次/旧权限资产累积进新Scope。排序按asset_id固定，日历可以在客户端按due_date展示同批记录；不能仅按非唯一title/date分页。首次列表验证真实Scope，后续每页重授权。

写入单PG事务包括可信ACL、当前relation_revision校验、root CAS、不可变revision及关联、幂等payload hash/原响应快照、审计和事务outbox。幂等键(project,principal,request_id)，先重新鉴权再查原结果；相同payload返回原提交响应，不用当前新版本冒充原响应；异payload409。验证失败/审计或outbox失败/连接中断均零部分写，无法确认提交时通过同键重放核对，不能凭模型叙述假成功。

outbox事件仅为workbench.asset.created/updated/retired/restored，带project、batch、asset_id、asset_revision与request_ref；不创建Mission/Attempt/Evidence/NodeGate事件。业务提交与outbox同事务，事件消费者幂等键event_id；投递状态由受控服务处理，投递或UI200不等于正式执行成功。

## 5. 权限、历史与迁移

运行角色无schema/迁移/ACL/正式来源或已验证R1映射写权；项目RLS与API授权共同隔离。revision、Scope链接、审计、引用与outbox业务payload不可物理改写；root当前指针更新受CAS与历史/审计/outbox完整性约束。读取退役/历史对象仍检查当前访问权限，旧cursor和历史revision不绕过撤权。关联合法性在恢复时再次核对。

有序带checksum迁移，专用owner、备份/dry-run；空新表可回退并验证既有B01–B06仍工作。非空资产/引用/审计历史须先导出与对账恢复，禁止DROP丢已接受写入；升级/失败中断/重启/重复迁移测试必须在真实PG完成。B08旧业务/R1数据迁移依赖B07另单，B07不猜测旧正式对象映射。

## 6. 验收与评审责任

B：复合FK/Scope/版本CAS/幂等/退役历史/审计outbox/真实PG迁移恢复；E：草稿与正式Case/Obligation/Defect/Report隔离、只读验证后的R1引用映射、无伪状态/越域读取；D：Host写授权/CSRF、连接身份隔离、宿主缺失fail closed。三方须审查精确提交SHA给接受或异议，不能继承旧A03签字。

F独立验证正向/非法关联/跨项目批次/共享版本多SST/UNSPLIT/权限撤销/写入CSRF/幂等与CAS并发/软删除恢复/历史不可改/审计outbox故障/断连后重放/迁移回退；正文写“PASS”不能产生任何R1事实。C03/C04用真实HTTP+PG完成一次“详情建milestone→日历见同ID→详情改期→日历同步→退役/恢复”的业务Oracle，截图只辅助证明界面；两语标签不改身份/Scope。无真实Host时明确fixture组件验收，不授予现场资格。

本合同PR仅设计增量；B/E/D审查、实际实现、同源真实PG/HTTP和F独立验收尚未完成。优先实现milestone纵向切片后，再逐kind扩展；不以首个kind通过冒充整个B07完成。
