# D 正式 Mission Scope 绑定增量独立审查

被审合同：PR #175，精确 `32f3f69484364f42387b24c2fd93bc4c19ab7df4`。
角色：独立 D 设计审查；日期：2026-11-10。
结论：**D_DIRECTION_ACCEPTED / D_REVIEWED_WITH_REQUIRED_DETAILS / D_SIGNOFF_PENDING_CLARIFICATION**。本报告不代签 B/E/F，不是实现或现场验收。

## 已核事实与接受范围

已逐项读取本增量、04 宿主合同、A03 身份/幂等矩阵、已验 write-context 合同与实现、`models.Mission`、`bank_mission.start_or_resume` / 启动 wrapper、`ClosedLoopControlPlane.bootstrap/_mission/_persist_mission`、`rc72_mission_factory` 与原生 Host/Captain 绑定边界。正式新建和 typed 重建当前确实不能保持项目/批次绑定，不能以 synthetic extra payload 冒充正式接续。

在独立 worktree 执行 `python3 -m unittest discover -s tests -p audit_scope_binding_characterization.py -v`：3/3 **缺口复现**。它只操作临时 R1，不是产品修复通过，没有 Host、真实业务执行或生产 R1。

D 接受由 RC72 正式创建/恢复端口持有 typed 不可变绑定，工作台只消费；PG verified 业务 Scope 与运行 release ID 显式来源映射，不能猜同名；普通更新、冷恢复不丢字段、不静默改绑；旧无来源 Mission 保持 HOLD。绑定、Scope digest、dataclass 或 verifier 返回值都不能替代 Captain/Worker/资源租约、人审和 NodeGate 权限。此次不新增模型密钥、会话存储或用户可提交的权威字段。

## 实现前必须消除的 D 设计歧义

以下是设计规范缺口，**不是已复现的新实现越权漏洞**；本增量尚未实现。

| ID | 级别 | 合同需明确的规则及退出证据 |
|---|---|---|
| D-MSB-01 | P1 | 第3节只规定 verifier 核 Host 主体及 B06 Scope；B06 是项目读取能力，不能推导正式 Mission 创建许可。请明确 server-derived Host 创建/恢复动作权限、可信 mutation/CSRF/Origin 或原生非浏览器调用证明，以及 B 项目写权限，在首次正式 R1 创建之前共同校验。读会话、PROJECT 会话、单独 typed 对象或 `verified=true` 不可升级成命令/Captain 身份。缺接口/证明失败关闭。退出测试：有项目读权但无创建权、缺 mutation/CSRF、跨项目/批次、伪 provider/主体均在零 R1 变更前拒绝；合法来源仅创建绑定，不执行或伪 PASS。 |
| D-MSB-02 | P1 | 第3/4节的稳定创建键与丢回执恢复尚未明确原主体域。请将权威创建回执/幂等查询绑定可信原 principal_ref、项目/批次、Mission/运行身份、创建 key 与完整 payload digest。恢复仍重新授权，Bob 即使同项目有写权，也不能把 Alice 未知创建的原 key/context 改成自己后重发并新建 Mission；若允许合法委派恢复，必须作为有独立动作授权的恢复查询，不继承旧身份或盲目重执行。退出测试：Alice 提交已发生但丢回执→Bob 同项目有权时不创建重复→Alice 恢复按原权威 key 得到原 Mission；错主体、异 payload、撤权、缺 verifier、key/权威更换保持 HOLD/拒绝且原 R1 不变。 |

## verifier、恢复与现场约束

- verifier 的安装与可信 Host 适配由服务端受控构造；调用方传入可调用对象、dataclass 或自带密钥后自签，不构成权威。实际接口应保留验证者引用、主体/动作授权与来源修订/摘要的关联；不能允许浏览器或任意 CLI import 选择验证器。正式模型的结构校验仍不等于创建端口的授权验证。
- 已验 `X-DSH-Write-Context` 仅为 opaque 主体恢复域，不是创建权限、真实 SSO、跨 session epoch 证明或 Captain 签名；不能仅因为它匹配就创建 Mission。原 token 缺失、换 key 或无法核实原主体时不填入当前用户 token，未知副作用保持 HOLD。
- 恢复和读取按当前主体重新验证资源范围，最小身份先于明细。原创建者身份归属不排除经明确授权的其他用户读取既有 Mission，但读取权限不能自动变成原创建者的幂等/执行权限。
- 新 binding/R1 只存审计用 opaque 引用与必要来源信息，不存 Host cookie、Authorization、API key、签名私钥或完整认证会话对象。PG 的权限撤销或来源修订失效需被创建/恢复验证器重新检查，不能靠旧验证时间当作当前许可。
- 真实 DSH 1.18.26 的认证、创建角色、会话/撤权代次与签名接口仍需搬运行内验证。当前统一 `FIELD_NEEDS_BANK_TRANSFER`；不编造 JWT claim、SSO 或银行权威。fixture 仅组件测试。

作者将两条规则落实到新的精确合同 SHA 后，D 可对增量文字复签；此前不能把本方向接受记成无保留 `D_DESIGN_SIGNOFF_ACCEPTED`。本次未修改模型、正式工厂、冻结主线、R1 或 08/09/10，也未授予 F01/发布资格。
