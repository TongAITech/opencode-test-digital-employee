# C02 Scope API 客户端组件（未接UI）

基线009c4d38；B06未ready，C02仍BLOCKED_DEPENDENCY_B06，不宣称实现完成。正式/workbench骨架继续明确业务未就绪，此模块没有导入UI，不发实际B06请求。无样例业务成功展示。

B已在本轮确认06未来路由：GET /api/workbench/v1/projects/{project}/release-dates/{date}/scope，重复query参数requirement_ids/system_version_ids/sst_ids，batch_id/page_size/page_cursor；不传principal，宿主身份服务端绑定。响应source_refs、relation_revision、access_scope_revision及顶层next_page_cursor维持06。本组件不验证游标签名/不替代服务端ACL，真实HTTP仍待B06。

新增scope-client.mjs提供注入fetch的GET端口和状态机：消费所有页直到显式null，校验实际关联/来源/修订/筛选、SPLIT或UNSPLIT、重复和游标环/数量界限；权限/关系失效清空记录；切批次立即清旧Scope数据、abort旧请求并以代次阻断迟到响应；语言状态不修改Scope身份。READY只代表完整合法协议响应，不是业务执行或Gate PASS。

Node 18项Scope正负边界及C01三项共21通过；包含401/403/404/409/422/503、来源漂移、缺分页/空集合、重复、权限修订、非法日期、迟到响应、切批次与语言身份。组件夹具不是真Postgres HTTP/Host授权或产品UI验收。独立C01组件workflow增加本测试，精确源远端结果需另验。未改08/09/10/R1。

## F发现的共享Scope引用P1及修复

F对46006d31独立攻击发现：公开LOADING state.scope与内部校验快照共用引用，外部修改project后可接受与原请求不符的响应。这是客户端协议快照隔离缺陷，不是已证明的服务端ACL绕过。保留旧18+3绿测覆盖遗漏。

修复：内部请求快照深复制/深冻结；port每次收到独立深冻结副本；状态通过私有字段发布深复制/深冻结快照，仅公开getter。原输入、嵌套filter、port请求、LOADING/READY状态及返回行/来源对象互不共享可变引用。新增原输入/公开状态/嵌套数组/端口参数/响应数据篡改反例，foreign响应保持SCOPE_MISMATCH；Node21项Scope+C01三项=24通过。精确新源远端CI与F复验另取，C02仍未接真实B06。
