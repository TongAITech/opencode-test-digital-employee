# D 正式 Mission Scope 协议 V2 独立复审

被审：[PR #181](https://github.com/TongAITech/opencode-test-digital-employee/pull/181)，精确源 `957874d6d24b78b6c61b243f3c952d57bc33a0b2`。独立 worktree `d-binding-v2-review`，从被审源建立；对照 A 集成源 `aa533c21`、RC7.2 远端 `edaf9290` 与前次 D 报告 `b6d42a77`。本次任务及工具正常执行，没有收到额度错误。

结论：**D_V2_CORE_RULES_ACCEPTED / D_V2_REVIEWED_WITH_REQUIRED_DETAILS / FORMAL_CREATE_ADMISSION_NOT_ACCEPTED**。V2 已明确补齐原主体恢复规则和创建前权限原则；仍有两项 P1 需要规范化后才能准入会写正式 R1 的创建/恢复实现。它们是未实现合同的规范缺口，不是已复现的新实现越权漏洞。本文不代签 B/E/F，不代表产品或现场通过。

## 审查范围与旧项核销

已完整读取 V2、原绑定提案、04 宿主合同、前次 D 审查、HostIdentity/业务 HTTP/资产 mutation、write-context、D01 探测、正式 Mission 创建/恢复与 HostBindings/Captain fencer。PR 相对初稿只变更两份文档，没有运行符号变化；GitNexus 工具未在本次会话暴露，未声称运行调用图分析，按真实 diff 和调用点手工核查。

| 旧项 | 本次精确结论 |
|---|---|
| D-MSB-01 创建权限不可从 Scope 读权推出 | V2 第41行明确 server-derived `mission.create`、可信 mutation/CSRF/Origin 或原生证明、B `can_write`，缺真实能力失败关闭；**创建入口原则已补齐**。恢复的动作矩阵及提交围栏仍见下列 P1，不能合并为无保留准入。 |
| D-MSB-02 原主体幂等与未知结果 | V2 第33–37行明确 formal_authority/actor/project/batch/key 域、完整 digest、预定身份、原权威查询、异负载冲突、Alice/Bob 隔离、撤权拒绝、V1 不开放跨主体委派、write-context 不是创建许可；**设计规则已消除原歧义**。实际新创建/恢复实现尚未存在，未记实现 QA_PASS。 |

## 仍需修订的 P1

### D-V2-01：把 lookup、重新 submit 与当前 Host 动作明确分开

V2 第33–37行定义 submit/lookup 与“恢复重新核当前 Host 及项目授权”，第41行只明确新创建的 `mission.create`。第35行允许权威 NOT_FOUND 后安全重交原 intent，但没有写明这次会产生正式副作用的重新 submit 必须重新通过创建动作与 mutation 证明；也没有指定 lookup 的动作许可和是否可以隐式转 submit。当前 `HostIdentity` 只有 `principal` 与 `mutation_authorized` 两个字段（business_http.py:15–18），不承载正式动作矩阵或会话代次。`write_context.py:10–15` 只按服务器 key 和 principal 生成主体域 HMAC，不能补出这些许可。

最小修订：列出三个操作的规范矩阵——首次 submit、同 intent 的再次 submit、只读 lookup。任何可能 append R1 的路径（包括 NOT_FOUND 后重交）必须重新核同一可信主体的 `mission.create`、当前 `can_write` 和可信 mutation/原生证明；lookup 不可暗转 submit，返回 NOT_FOUND/UNKNOWN 本身不授创建许可。lookup 的独立动作名或与既有动作的明确等价关系由 D/E 固定，当前文字不能让各实现自行猜。只读读取既有 Mission 的权限也不能升级成恢复提交权。

退出反例：Alice 创建已发生但丢回执后仅撤销创建动作、仍保留项目读/写权；lookup 可以按正式矩阵返回/拒绝，但从 lookup 转重交不得产生新创建；原 key、actor 或 digest 改变保持拒绝/HOLD。该测试应走正式端口，不能只复用资产请求的 mutation boolean 测试。

### D-V2-02：Host 撤权/提交围栏既有现场未知，也有尚未写定的接口合同

V2 第43–45行正确承认“刚验证过”不足，并规定缺能力 HOLD；但“Host 权威最终动作/会话代次围栏”仍无输入/输出、持有范围、释放/超时、撤权线性化点和重启后代次拒绝协议，第45行明确仍需确定超时及持久 fence 代次。这不是取得一个真实 Host 地址后就自然解决的资格问题，而是正式创建调用方与 Host 适配方之间尚未固定的可测试端口。

最小修订：在不宣称现有 DSH 已提供能力的前提下，定义一个**所需抽象能力合同**：服务端 authority/principal/action/project/batch/intent-digest 绑定；围栏获取、最终提交许可、释放的规范结果；撤权先于/后于正式提交线性化时各自产生什么结果；超时、失效、崩溃和未知 append 的恢复规则。结果至少能区分拒绝、缺能力、过期/失效、未知与已批准的正式提交许可；无法证明范围、代次或顺序时 HOLD。时间戳、调用方 dataclass、自签 flag 不能自动成为许可。实现可先有缺能力拒绝适配器；fixture 只能验证此抽象合同，真实 DSH 是否满足它仍须行内 qualification。

仓库确有 `CaptainDispatchFencer`、OS ledger lock、原生工具/审批 verifier 与签名权威，不应报告为“没有围栏”。但这些现有路径保护的是已经登记 Mission 的 Captain/执行/人审等特定动作，不能因同名 fence 就当成新工作台业务绑定创建和会话撤权的完整实现；需 E 逐一说明正式创建如何接入并避免重复授权系统。新围栏也不能绕过既有资源租约、Captain/Worker、Human Gate 或 NodeGate。

## 可以并行准备的隔离范围

无需等待真实现场即可继续准备纯 Scope canonical 编码/黄金向量、纯 DTO 完整性校验、不可变输入/原主体幂等域的纯函数，以及“缺 Host 正式能力返回 HOLD、零 R1 副作用”的适配器候选。不能据此开放真实创建、绑定已有 legacy Mission、更新冻结正式模型或覆盖旧事实。正式 typed 模型/工厂/重建路径仍须 E/B/F 对精确增量审查；本报告不是替它们批准实现。

真实 DSH/SSO 的角色、动作、会话代次、撤权时效及所需抽象能力是否受支持，继续 **FIELD_NEEDS_BANK_TRANSFER**。不在行外尝试访问行内环境，不编造 JWT claim、Cookie、签名或宿主认证接口。项目草稿 asset 的已验主体恢复不是 Mission 创建通过的替代物。

## 本次实际验证与边界

| 命令/检查 | 实际结果 |
|---|---|
| `python3 -m unittest discover -s tests -p audit_scope_binding_characterization.py -v` | 3/3 **缺口复现**，TemporaryDirectory R1；不是修复通过 |
| `WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p test_dsh_workbench_b_write_context_postgres.py -v` | 16/16，8.101秒；真实隔离PG17.6及HTTP，含继承基础用例。原主体资产恢复/CSRF/只读/换key拒绝仍成立；不是正式 Mission 恢复验证 |
| `python3 -m unittest discover -s tests -p 'test_dsh_workbench_host*d.py' -v` | 33/33，2.572秒；包含本地可丢弃loopback fixture，非真实DSH 1.18.26 |
| PR源/远端核对 | PR181完整HEAD仍957874d6；RC7.2远端edaf9290；只变文档，无运行实现准入或现场证据 |

审查未修改被审实现、08/09/10、正式模型、原始 R1、许可证或主线；未授 F01/最终发布资格。最初 `gh pr diff --stat` 因当前 gh 不支持该参数失败，随后用 `gh pr diff --name-only`、完整 diff 与本地 git diff 完成范围核查，未计该失败为测试通过。
