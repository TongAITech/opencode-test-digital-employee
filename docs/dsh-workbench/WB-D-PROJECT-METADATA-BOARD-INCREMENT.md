# D：项目元数据、项目／迭代与六阶段看板最小增量候选

状态：**A_B_E_F_DESIGN_REVIEW_REQUIRED / NOT_IMPLEMENTED**。调查基线 W0 `199a316334abb41c77890ed5608b989e2a7e6126`、RC7.2 `edaf9290`。只新增本候选与调查证据，不修改01/02/06、A01、业务SQL、模型、R1或08/09/10。本候选的字段、角色、端口均须精确评审，不能当作已存在API。它是分阶段建设建议，不冒充D/B/E/F联合签署。

## 1. 已冻结目标与真实能力差异

01/A01要求P03-01项目/迭代新增编辑，P03-02六阶段与筛选，P03-03拖拽/跨窗一致，P03-04真实门禁才发布；P06-02基本资料/成员/目录，P06-03时间线。02要求project稳定身份、project+batch+DATE及合法BRV/BRVS穿透，06禁止客户端自报主体和拖卡片伪造N10。

真实PG17.6隔离fixture catalog见[调查证据](evidence/WB-D-PROJECT-BOARD-INVENTORY-20261111.md)：project只有project_id/name/access_scope_revision；主键只有project_id，name仅非空检查、没有UNIQUE；没有type/parent/metadata revision/成员/阶段。runtime只有project SELECT，无INSERT/UPDATE/DELETE或name列UPDATE；project RLS enabled=true、FORCE=false，只有SELECT policy。project_acl是权限映射，不是可直接展示的人员目录，runtime无SELECT权限。`provision_project`仅owner行政bootstrap，不能暴露成HTTP创建端点。

现有HostIdentity只有principal/mutation_authorized；主体由服务器provider给出，write-context只约束原主体恢复域，不授创建或成员管理权。现有目录只读name/稳定project_id和批次DATE，没有看板phase或质量统计。已有资产CRUD的项目can_write/mutation/CSRF/原主体回执机制可作为**已有项目元数据**的授权/恢复模式参考，不能直接挪用asset表装项目或假批次。

## 2. 分阶段开工边界

| 阶段 | 真实前置与可推进内容 | 不得核销的后续能力 |
|---|---|---|
| M0 已有项目读取 | 现在可复用已验目录，按project_id读已授权name；未知type/parent/member/phase显示未接入而非默认值/空统计。新metadata读投影可在B/C精确评审后单独实现。 | 不代表项目创建、编辑、成员或看板完整。 |
| M1 已有项目metadata编辑 | **READY_FOR_B_E_DESIGN_REVIEW**：仅既有project_id的name字段；当前可信Host mutation证明+当前项目can_write；新增metadata CAS/历史/幂等回执/审计事务，先迁移评审再实现。无需新的全局Host create能力或行内运行才能做该组件。 | 不改project_id、type/parent/成员/ACL/目录、batch或R1；不核销完整P03-01/P06-02。名称策略见第3节，不能跳过冻结后直接上线写名。 |
| M2 新项目/新迭代与成员 | 先冻结服务端命名空间/类型/父子/成员来源及动作矩阵，建立经审核的创建/成员能力端口与原子首次ACL。可在行外做协议/缺能力拒绝/实库原子性测试；真实Host认证资格另验。 | 当前mutation boolean、客户端role、父项目can_write都不能授首次create或成员变更。 |
| M3 六阶段业务计划 | 按第6节的**project+batch**卡片；前五阶段为业务计划，PG CAS/审计。可先实现查询和非发布流转候选，不依赖正式执行网关。 | 手拖“执行中/缺陷回归”不是R1任务运行，不能给Attempt/NodeGate写事实。 |
| M4 正式发布投影与跨窗同步 | 由E给出完整正式发布资格查询和新鲜度/范围协议；B/E给出项目/批次事件快照水位。 | 当前E02恒HOLD且人审UNKNOWN，发布必须拒绝；outbox/手刷不冒充SSE或发布。 |

## 3. 字段及命名策略必须显式冻结

| 字段/语义 | 现有依据 | 本候选边界/待冻结决定 |
|---|---|---|
| project_id | PG text PK | 不可变身份，不按name/父项/日期重新生成；客户端不能以编辑操作替换。 |
| name | 已有text、btrim非空，当前非唯一 | M1可只围绕此真实字段设计。A/B须先明确它是可重名显示名还是命名空间内唯一业务名，以及长度、空白/Unicode/大小写比较、历史重名处理。不能擅加全库UNIQUE，也不能只在当前可见项目列表判重。 |
| metadata_revision | 当前没有 | 建议独立正revision，从1初始化，和access_scope_revision分开；名字/其他metadata修改才递增。wire整数范围/客户端精确编码由B/C在该增量固定，不把ACL epoch当metadata CAS。 |
| project_kind | 当前没有 | 候选PROJECT/ITERATION仅是待签enum，不把所有legacy行静默当PROJECT；旧kind未知应可见。新增/转换、是否允许转换、历史分母待A/B定。 |
| parent_project_id | 当前没有 | 迭代父项须稳定project_id、显式FK/类型/namespace/无环校验；深度、重挂、跨namespace规则待签。不能按name猜父项或自动迁移。 |
| 成员/角色 | 只有技术ACL表 | 人员显示来源、成员和ACL是否/如何映射、角色动作均待D/B/A冻结；不把can_write当“成员管理员”，不直接回传全部principal或接受客户端role。 |
| 本地目录/Host会话 | 当前project表没有 | 属D原生能力和路径许可单，不因保存name顺便创建目录/会话；接口未知时单独不可用，不阻断M1。 |

A01“重复名称拒绝”仍为目标，**本文件不把它删除或假装已满足**。M1真正提交name写之前，必须由A/B固定上述名称域与冲突策略；这是可在行外完成的设计决定，不是“等待行内DSH”。若选择唯一业务名，需服务器掌握的namespace_ref及相应唯一约束/并发冲突/旧重名隔离；若明确name仅显示名，须A显式说明如何保留A01所要求的业务命名去重能力，不能由实现自行弱化。无权重名只返回通用NAME_UNAVAILABLE，不泄漏另一个项目ID/成员。

## 4. M1 已有项目metadata的精确拟议协议

以下路径是新增候选，当前没有：GET/PATCH `/api/workbench/v1/projects/{project_id}/metadata`。现有GET项目目录不是此写入口；当前非资产PATCH只返回405。

读返回至少project_id/name/metadata_revision/access_scope_revision；只从授权PG行投影，不默认type/parent/member。写body仅允许request_id、expected_metadata_revision、expected_access_scope_revision、changes（M1仅name）、reason；禁止principal/actor/authorization/role/owner/type/parent/members/batch/phase及任何R1字段。具体字符串上限/名称比较按第3节精确冻结，JSON重复键、非法UTF8、body超限、错误类型拒绝。客户端不能提交或覆盖metadata_revision新值。

授权顺序：server Host主体→可信mutation/CSRF+Origin或受审原生证明→原`X-DSH-Write-Context`→当前项目can_write→解析/核受控字段→PG事务中再次核权限并处理幂等/CAS。项目不存在/不可读不泄漏存在性；不能用查询body principal，读会话不自动有写权。metadata成功不证明Host资格已在行内验收，但可用真实PG+显式fixture Host做组件验证。

幂等域沿现有业务域K=(project_id,server principal,request_id)，与既有request_log共享时必须含`project.metadata.update/v1`动作及完整受控负载摘要，跨动作/异payload同key为409。摘要包含原expected revisions、changes及reason，不纳入可变Cookie/CSRF/token。必须持久化原完整结果；不能只像旧BusinessStore某些方法返回None/推算revision，不能借用绑定batch/asset的asset_request_result结构。

一个PG事务完成：SET LOCAL可信主体与scope→当前write授权→幂等声明/原结果→锁project行→核metadata/access revisions→受限metadata更新及metadata_revision+1→不可变前后值历史/audit→原结果/事务outbox→commit。需要新迁移和列级UPDATE权限/UPDATE RLS策略；当前runtime没有，不能靠owner连接完成HTTP。project_id/ACL epoch由runtime写入禁止；metadata审计约束不得误拦现有ACL触发器只更新access_scope_revision。迁移编号由A/B排程，不占用已规划的008。

CAS失败409且全回滚；两人同revision只能一人成交。name编辑不改batch_id/date/history/relations/Mission，metadata和权限代次独立；directory项目快照已含name，变更后旧项目cursor应409。批次目录与关系没变时不必伪造relation_revision增长或清空十区Scope。审计至少保存可信actor、project/action/request、前后metadata revision/name、原因、时间；业务角色不可篡改。建议新增project metadata history/result/outbox逻辑载体，由B签复合PK/FK/append-only/RLS及迁移/回滚，不假造asset_id或batch。

未知提交恢复规则：

| 事件 | 规定 |
|---|---|
| commit后响应丢失 | 捕获原path/body/request/context，只重试同一请求；服务器重新授权后返回原receipt，name/history/audit/outbox仅一次。不能生成新request或更新expected revision后盲重放。 |
| 同key同payload但别人已改到更新revision | 返回原历史回执，不覆盖更新值；UI再读当前metadata，不能把旧receipt当最新状态回滚界面。 |
| Alice未知→Bob同项目也有can_write | Bob不能用新context替换原context重发Alice的待恢复请求；旧主体context不符先409，零新业务写；原Alice重新授权才按原域对账。 |
| 撤权/重新授予 | 每次恢复先核当前权限，撤权不泄漏原receipt；恢复权限后可核原结果。原请求没有commit且epoch已变，不能用旧许可新写，返回冲突并要求明确新意图。 |
| server key轮换、原context无法验证、DB不可读 | HOLD/未知；不改当前用户token伪装恢复、不凭缓存判无写入。跨代次受审恢复另案。 |
| DB证明无原事务结果 | 只有当前权威PG在正常可读/无未决事务条件下确认原K未提交，才可结束未知状态；UI必须明确重新提交意图，不静默换body/key绕开。 |

M1为单PG事务业务修改，不涉及R1跨库PREPARE，也不需要复刻正式Mission HostAdmissionFence。未来若metadata写操作新增外部目录/会话/R1副作用，应另升合同，不能沿用此单事务恢复证明。

## 5. M2 首次create、父子及成员的额外权威

首次create之前不存在project ACL，不能调用wb.allowed(new_id,true)当创建授权，也不能把mutation_authorized=True、某个client role或“可写任一项目”升级成全局创建。新服务端动作名候选`project.create`、`iteration.create`、`project.members.manage`、`project.parent.manage`，是**待签所需能力**，不宣称现有DSH已提供。需受控Host/服务端授权端口派生当前主体、动作、namespace_ref、允许父项/角色模板及可审计grant引用；请求中的namespace/parent只是目标，不能作为授权证明。缺动作/namespace权威时拒绝/未就绪，不能fallback owner连接或临时给自己ACL。

namespace身份和授权来源尚未定义；必须由A/D/B决定受管服务器安装域、组织/租户或其他真实来源，不从工作目录、父项目名、当前可见项目集合或登录名猜。稳定project_id由受控分配器给出；create单PG事务内检查原主体namespace幂等、名称唯一域、插project/类型父项、首次ACL、history/audit/原结果，失败全部回滚。首次owner/member模板由服务端已批准政策决定，不能接受任意principal/role/can_write；原行政provision函数不是新HTTP实现。未来若同时创建原生会话/目录需另有外部副作用恢复单。

父子结构不自动继承ACL：能看父项不等于能看子项；有child读权但无parent读权时父项身份/名称按协议隐藏，不泄漏；重挂父项须独立管理动作与目标父/子权限/namespace/无环校验，不通过编辑name夹带。成员显示资料与ACL授予分开，add/remove/role变更均需members.manage和修订CAS，撤权推进已有access_scope_revision使旧cursor失效。不能用成员表“显示我为owner”给自己创建或管理能力。

## 6. 六阶段看板卡片与正式发布边界

**本候选选择看板业务卡片为(project_id,batch_id)，不是一个项目永远只有一个阶段。** 原project入口/详情卡仍为project；项目多个投产日期产生多个显式批次卡，card携稳定batch_id和当前DATE/date_revision。项目未建batch留在“未分配投产批次”的非阶段区域，不塞入“需求分析”冒充已开始，也不新增第七个业务阶段。卡片label可name+DATE，身份绝不按label join；改期保持同card和历史/正式引用。

保留六列：需求分析、用例设计、用例评审、执行中、缺陷回归、已发布。前五列存`business_plan_stage`候选枚举，仅是人工业务计划；UI明确“业务计划阶段，不表示正式执行”，同时独立显示可用的R1只读事实/未就绪。拖到执行中或缺陷回归不创建Task/Attempt、不改N1–N10/NodeGate，不推断通过率。是否允许跨级/逆向、未分配初态与历史数据迁移需A/C/B签署；建议前五计划阶段显式选择、理由和时间线，不以默认值伪造发生时间。

计划记录按(project,batch)独立plan_revision，FK到真实release_batch；写需当前项目write+mutation/context，expected_plan_revision及所见date_revision/ACL epoch防止在旧卡片上下文写入。不能把project metadata revision或日期revision当阶段revision。需求/SST筛选若用于找卡片，不会让计划只适用于某条筛选关系；卡片阶段始终批次级，界面须明确，非法/不完整B06 Scope显示缺口而非伪质量指标。

**RELEASED不是客户端可写的第六个计划值**。直接PATCH stage=RELEASED必须拒绝；拖到第六列只能触发E提供的正式资格核验/刷新，不创建publish命令或自己补NodeGate PASS。服务端必须核同project+稳定batch的正式Mission绑定/完整Scope，真实N10收敛与NodeGate、有效Attempt/Oracle/Evidence、所有所需Human批准和当前来源修订/新鲜度；多个Mission不能随便挑一个PASS代表整个批次。具体“完整所需Mission集合、覆盖分母、Gate/Human来源、失效/重基线策略”由E另行冻结，业务卡不自证。

当前E02返回release_decision=HOLD、human_approval=UNKNOWN_NOT_QUERIED，所以**当前候选默认RELEASED一律拒绝/回退**；某行N10 state=PASS、某个Gate PASS或HASH_VERIFIED_ONLY均不能覆盖它。资格不可得、UNKNOWN/过期、HUMAN_GATE/BLOCKED/未完整、无正式证据均不放行。未来已发生的正式发布历史不能因当前失效被删除；显示历史ref与当前待复核分开，不用旧receipt维持“当前已批准”假象。该发布投影不修改正式R1。

## 7. 同步、故障与验证退出

M1/M3先允许明确手动刷新；不把写入outbox或多个窗口本地storage广播冒充可靠SSE。project.metadata.changed是项目级事件，不能塞假batch_id去满足旧通用事件格式；需要B/E单独定义PROJECT与BATCH事件域、ACL epoch、revision/source、快照水位→补放→订阅/断线恢复。阶段事件绑定project+batch，跳revision/主体变化清旧订阅并重查，不能称“实时”却继续显示过期卡片。改期/rename只更新显示，不丢稳定身份。

拟议端点：metadata GET/PATCH；按project/batch读/改business-plan-stage；namespace内project/iteration create；members管理及E正式release-qualification查询。**均非当前已实现端点**，最后名称/状态码/响应由B/E/A03新增量固定。已有read目录继续可用；不能通过旧legacy /api写入口旁路。

首个M1实施单的实库退出：新迁移/空库回滚与有历史安全回退；列权限/RLS拒绝identity/ACL夹带；Alice写、reader只读、伪主体/缺CSRF/context/未知字段拒绝；CAS双并发唯一成交；同key异payload/跨动作冲突；commit后丢响应和主体切换不重复；审计/outbox失败全回滚；旧receipt不覆盖新revision；name域重名并发、历史重名治理及不泄漏；项目rename后目录旧cursor失效、批次/Scope/R1原事实不变；重启和连接池无主体串用。不得用SQLite或截图代业务Oracle。

M2另测无ACL首次创建授权、namespace越权/duplicate竞态、客户端role自授、父子独立ACL、重挂环/跨域、成员撤权与主体幂等；M3测同项目两个批次不同卡片、改期同ID、拖动只影响计划、CAS冲突UI回退；M4用真实N10/Evidence/Human/错误Scope/陈旧来源等拒绝Oracle及无缝SSE补放。当前没有这些功能通过证据。

评审顺序：A确认M1字段/名称策略及批次卡片决定；B签metadata/plan/namespace约束与真实PG实施单；E签发布资格来源/全量范围/非伪执行及事件域；D签当前权限和新动作边界，C签六页面/十分区/双语交互，F对每个精确实现SHA独立验收。先推进M1可独立部分，不把未知create/成员/正式发布或真实Host现场变成停止所有业务开发的理由。
