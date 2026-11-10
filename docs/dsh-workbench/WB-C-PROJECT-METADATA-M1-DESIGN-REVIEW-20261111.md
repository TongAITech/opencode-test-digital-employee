# C：M1既有治理根项目改名——revision、目录与界面恢复审查

独立worktree `c-project-metadata-design`，base `1410f5f023cdb50419263083ff4f70dac1796b71`。本报告只审设计，不改实现、合同原文或08/09/10。

精确输入：D211 `1e1a75ff6c49cfaf36a6f36f3bdde1e047cf77d2`；B230 `a21b82fe805926a22b5d90babec5670dd912c6aa`；A-M1决定 `9a41b1456ceed0a0efb66ab662e1d3e3dff136aa`。另完整读取E233 `bfd96c0b`、F234含跨动作锁补充 `a776640e`、D后续动作/恢复签署 `96600655`。这些报告未被移写为C的功能测试。

结论：**C_M1_GOVERNED_ROOT_RENAME_DESIGN_ACCEPTED_FOR_ISOLATED_IMPLEMENTATION / NO_NEW_C_P0_P1 / SQL_API_UI_NOT_IMPLEMENTED_OR_ACCEPTED**。接受A限定的NAMING_ACTIVE完整治理域内已有根PROJECT改名；允许开展同源双语组件实现，但具体metadata新wire、目录内部摘要兼容、SQL/profile和实现SHA仍须各组精确审查，不给未实现候选产品PASS。M2创建/迭代/成员、M3计划卡及M4发布/SSE不包含在本签署。

## 1. 单一名称事实、稳定身份及只读legacy

唯一当前文本仍为project.name；name_key只为受约束规范字节，不可作为第二个可编辑名称。project_id是目录、详情与现有批次关联的稳定身份，绝不按name join或在rename后重新分配。只开放服务器批准的完整治理NAMING_ACTIVE根PROJECT；未治理/类型未知legacy仍按原ACL展示原name，不因metadata_revision机械初值1变成可改名PROJECT，不在前端自动归域/规范化旧名/解决重名。

GET可读不是write授权；当前Host mutation、CSRF/Origin、原主体write-context、当前can_write和治理政策仍分别核验。缺可信Host写条件时明确未就绪；reader/未治理项目只读，不把普通表单、当前Scope已READY或可见目录成员当管理资格。namespace/type/parent/owner/role字段均不可让用户自填以激活改名。NAME_UNAVAILABLE只显示“名称不可用 / Name unavailable”，不猜或回传不可见项目身份、成员或父项，不从可见项目列表判重，不提供任意namespace探测。

## 2. 名称输入保真及两语提示

接受固定`project-name/utf8-exact-v1`：拒非法UTF8/孤立代理、U+0000–001F和U+007F，仅去两端U+0020；规范后1–128 Unicode标量且UTF8≤512字节，其他Unicode空白、大小写、组合序列精确保留。服务端和DB为Oracle，客户端校验仅提示。禁止`.trim()`、NFC/NFKC、casefold、locale排序/大小写或把不可见空白静默换成普通空格。控制字符不能因浏览器编辑器自动清理就称已拒绝，HTTP/codec层另测。

拟用界面提示必须两语可见：

- 中文：“名称最多128个Unicode标量、512个UTF-8字节；只去除首尾普通空格（U+0020）。大小写、组合字符及其他Unicode空白会原样保留，并按精确字节区分。”
- English: “Up to 128 Unicode scalar values and 512 UTF-8 bytes. Only leading and trailing ordinary spaces (U+0020) are removed. Case, combining characters and other Unicode whitespace are preserved and compared exactly.”

浏览器`maxlength=128`按UTF16单元计数，会错误拒绝合法128个非BMP字符；不得把它当该政策实现。计数要先拒孤立代理，再按标量和TextEncoder UTF8字节计数，不能让TextEncoder以替换字符掩盖代理错误。表单预览/服务端规范后显示都保留完整文本，可额外显示字符/字节数或明确空白诊断，但不改存储值。128个4字节标量正好512字节为有效上界；129个不能因字节或字符规则被误接受。普通ASCII首尾空格规范导致NO_CHANGE时应明确告知，不造改名历史。长名仍要375px内换行、完整可访问名称与键盘焦点，不用裁业务值/ellipsis或全页overflow隐藏伪造移动通过。

## 3. metadata GET/PATCH与精确revision

接受拟议GET/PATCH `/api/workbench/v1/projects/{project_id}/metadata`，目前未实现。GET只按当前授权项目返回其单一name、稳定project_id、metadata/access revisions与治理只读状态；不返回全namespace成员或把未知type/parent默认补值。PATCH只接受request_id、expected_metadata_revision、expected_access_scope_revision、changes{name}、reason；重复/未知JSON键、错误类型/非法UTF8、16KiB body、request_id ASCII1–128及reason2048 UTF8字节边界由服务端按B230拒绝，客户端不得夹带principal/namespace/batch/phase/新revision。

M1新增metadata wire的两个revision必须是规范正bigint十进制字符串：`[1-9][0-9]*`且≤`9223372036854775807`；拒`0`、前导零、符号、空白、小数、指数、JSON number及溢出。前端保留字符串，必要比较用经边界检查的BigInt/精确十进制比较，禁止Number/parseInt/浮点排序或从当前Scope数字epoch反推PATCH CAS。metadata_revision、access_scope_revision、Directory digest及batch DATE/relation revision不是可互换水位。

GET响应、原始PATCH负载和历史receipt必须身份及schema核验；metadata请求的迟到结果不得覆盖另一项目或另一主体的展示。未知字段/状态/schema不默认为编辑成功。现有ScopeClient仍由既有协议验证，不能为了新metadata wire放宽它的来源/安全整数检查或把metadata revision塞进Scope摘要。

## 4. Directory防ABA与rename专用刷新

实际源码：DirectoryStore现在对project_id/name/数字access_scope_revision做digest，DirectoryClient只接受`business-directory/v1`且验证数字access epoch；当前并无metadata_revision。B/A要求内部快照投影版本和metaRev参与全部当前授权项目的稳定排序编码，A→B→A后旧cursor也必须409；不能只hash可见单页name或以当前name相同恢复旧token。内部摘要投影版本不等于HTTP records/schema必须升版。

按A补充采用最小兼容审点：**server内部digest快照加入metadata_revision与明确snapshot投影版本，cursor绑定该内部版本/新digest，旧cursor拒绝；现有目录响应records及`business-directory/v1`可以保持不变。** 不要求给records增加metadata_revision，也不要求把旧目录access_scope_revision数字改字符串；现有DirectoryClient仍验证其原wire，批次目录/Scope协议不被改写。metadata新GET/PATCH的两revision独立严格用规范bigint字符串，并从该端点读取当前CAS，不从旧目录数字epoch反推。C审的是旧cursor失效和旧client可消费的精确退出，不指定未经实现评审的最终SQL/序列化常量。若B后续确需新目录wire/字段，则必须另交project-only route/schema兼容矩阵（包括旧client、批次v1与未知schema失败关闭）并重新审核，不能把“新增字段”或“内部版本”当自动兼容证明；本次没有这项扩展需求或实现。

C核对到当前DirectoryPanel.load会清project/batch、调用scopePanel.setContext({})；chooseProject同样清batch/Scope。这是普通目录导航现有行为，**不得直接拿来作为rename后刷新**。新M1需专用元数据/项目目录重读路径：保持原project_id、batch_id、DATE和合法Scope/relation/access revisions；只用当前授权新快照更新名称与metadata水位。更新完整分页目录时先不呈现部分新旧名称，409旧cursor从头重新读，代次拒绝迟到响应。纯rename不得伪造Scope修订、清空十区数据或触发执行。若重读证明项目已不可读/ACL变化、batch/date真变更，则按对应现有授权/Scope失效规则清旧；不能用“rename不清Scope”保留撤权后的私密数据。

NO_CHANGE无metadata/changed事件增长，必要手刷当前名称即可；不把receipt/outbox当跨窗SSE。其他窗口只有明确刷新后才宣称当前名称；未刷新快照应有其读取状态，不能写实时同步。卡片仍只按稳定身份，rename不新增批次、不伪造看板phase/成员/目录/会话。

## 5. 原主体unknown恢复和当前展示必须分离

待恢复请求捕获并保持原path/method/body/request_id/expected revisions/action digest/主体context；不因切项目、批次、section、语言或后来的GET更改其负载、换key或替换主体。公开展示在身份/权限变化时清旧；旧主体私有待恢复意图保留在受限恢复域，Bob不能见Alice正文或拿Bob context重包提交。原context无法验证、当前权限撤销、服务不可读均HOLD/未知，不凭本地缓存判定未提交。

同K同digest成功的旧receipt先经当前授权取回，作为原操作历史确认，不按现在CAS重算、不再写一次name/history/outbox。UI不得把receipt里的旧name/applied_metadata_revision写成当前值；保留历史操作确认，再GET当前metadata。当前GET失败时展示“操作历史已确认、当前值未取得”，而不是用旧receipt回滚更新name。若后来其他人又改名，GET的较新版本为当前显示；绝不通过比较Number或最后到达顺序让旧response获胜。

未提交原意图才核原expected metadata/access revisions；冲突需当前权威值和用户明确新意图，不能自动刷新CAS后重试同key/换key。NO_CHANGE也持久回执、可恢复，无新metadata历史/版本/changed事件。只有权威PG在正常可读且无未决事务条件下证明原K未提交才能结束unknown；表单取消、页面切换、403、404样式信息或超时都不构成该证明。现有资产恢复测试不移签新metadata。

## 6. 实现退出与实际本轮检查

本轮完整读取精确候选/决策/相关审查，另核当前directory-client/panel、scope-client、milestone-panel原主体pending机制、business_http目录/unsafe dispatch、DirectoryStore digest。metadata API、009 SQL、名称codec和新wire均未实现，故未运行或宣称这些新功能PASS。必要现有回归仅`node --test tests/test_dsh_workbench_directory_client.mjs`：11/11、零跳过；它只保护已有目录协议，绝不证明M1 wire/rename/ABA已通过。没有新DB/权限探针或更改其他组源码。

最低实施矩阵：

| 范围 | 必须真实Oracle/负向/恢复 |
|---|---|
| 名称 | ASCII trim/NO_CHANGE、Unicode其他空白/大小写/组合序列精确保留、1/128/129标量、512/513字节、代理/控制拒绝；两语/键盘/长名375px完整可访问 |
| wire与目录 | metadata字符串revision跨2^53及bigint上界/溢出；拒数字/前导零；内部全授权快照含metaRev及投影版本；旧cursor和ABA拒绝；现有目录v1 records/批次Scope协议保持兼容，只有metadata新wire用字符串revision |
| 当前值与unknown | commit后丢响应、后来别人改名、原receipt重放不回滚新值；NO_CHANGE重放；Alice未知→Bob→Alice恢复；撤权/服务503/context失效HOLD；切页/语言/项目不换原K负载 |
| Scope连续性 | rename成功/NO_CHANGE/冲突/旧cursor重读后，同project/batch/DATE/relation/access及十区合法数据不被清空；真正撤权/改期失效仍清旧；迟到metadata/目录响应拒绝 |
| 权限与DB | 完整治理域/不可见同名Oracle、legacy只读、当前mutation/context/can_write各自拒绝、跨动作同K、直接DML绕过拒绝、history/key/outbox故障原子回滚、无R1副作用 |

009显式依赖runner、真实SQL/最小权限、新固定profile审批及F补充的跨动作claim/FK/锁顺序两连接证明仍为B/E/F实现签署门禁；C不以设计接受代签。没有把候选功能、行政fixture或当前目录PASS写成生产治理、真实DSH/Windows/离线或最终交付PASS。
