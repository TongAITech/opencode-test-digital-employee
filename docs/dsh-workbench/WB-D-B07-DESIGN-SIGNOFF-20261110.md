# D B07草稿资产HTTP设计签署

D_DESIGN_SIGNOFF_ACCEPTED_FOR_DESIGN_ONLY；精确被审源22fc88ff2884dea92ff6139bf9a56aa1474331e6，范围WB-B07-DRAFT-ASSET-API-CONTRACT.md第3/5/6节宿主/主体/写授权/CSRF与恢复边界。

D接受：HostIdentity仅由可信服务端provider产生；mutation_authorized默认false，读会话不能自动写；provider须验证宿主写权限与CSRF/Origin或可信非浏览器证明，随后还需project.can_write；客户端principal/authorization/mutation_authorized不作信任源；缺provider503。历史/退役读取仍遵从当前权限，撤权失效旧cursor，连接事务清理及RLS继续适用。

实施时浏览器Origin存在性不单独构成认证/CSRF证明，必须使用目标Host实际会话绑定的防护；非浏览器证明也须可验证的发行者/有效期/重放与授权Scope，不能以“无Origin”自动放行。具体DSH1.18.26接口尚未观察，缺真实provider时保持拒绝，不猜测SDK。测试provider只能作为fixture组件证据，不是FIELD。

此签署只属本轮D职责，不代B/E/F，不表示B07实现或现场完成。主体/连接池/CSRF/撤权恢复必须有真实HTTP+PG正负边界测试。没有修改08/09/10/R1。
