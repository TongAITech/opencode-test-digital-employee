# B 组 A03 集成源差量复核与复签

状态：**B_DESIGN_SIGNOFF_RECONFIRMED=ACCEPTED（仅 W0 设计）；W0_NOT_FROZEN；B01/B02 BLOCKED_W0_DESIGN_FROZEN。**

## 1. 审查基线与证据来源

- A 最新 W0 源：7067d19742c1954bc5b940f11fe00aa6db24065a（work/dsh-wb-w0）。
- B 原设计/FG18 修订源：98bac426a35063a306f4eaa4b43c80cf0a0a1745（PR #89 已合入 A W0）。
- B 本轮差量 PR：#95；当前施工源见 PR HEAD。
- F 独立审查：PR #94 固定审查 A 75fd2c64159db863cfd1319d41a887785b556d40；F 报告 blob 3d5e2d7d43d630d45e18cc016e57b97c981849e7。
- 原始 B 领域设计详见 WB-B-A03-DESIGN-SIGNOFF.md；本文件只记录集成差量，不重复原签署正文。

## 2. A 集成差量逐 blob 核对

| 资产 | B 源 blob | A@75fd/7067d19 blob | 结论 |
|---|---|---|---|
| tests/test_dsh_workbench_b_a03_design.py | bfb7ba93d4a85b5101a4557ea72f1559a0221e57 | bfb7ba93d4a85b5101a4557ea72f1559a0221e57 | 原 SQL witness 字节一致，FG18 未回退 |
| WB-B-A03-DESIGN-SIGNOFF.md | 49c42c22c79d0a5beb6b9a2253353198023eaa26 | 49c42c22c79d0a5beb6b9a2253353198023eaa26 | 原 B 设计签署未丢失 |
| 02-BUSINESS-DOMAIN-CONTRACT.md | 145d04bf417e88e295bcb48f6b1858f773adffae | 7e10899a874749ed04b39122647f1871cfb2cc5a | B 规范性内容保留；A 仅加集成注释 |
| 06-API-AND-EVENT-CONTRACT.md | 985e9491f05aa7b81697ea926fce4814b59705d7 | f4b0f0c521da406530b8380b913d4ce63c5cc7f4 | B Scope/ACL/错误语义保留；本 PR 再补 B06 专属分页 shape |

A 从 75fd2c6 前进到 7067d19 的唯一提交改动 RC7.2 Journey Playwright adapter、C09 smoke test 与 FG17 专项 workflow；上述 B 领域文件在两个 A SHA 上 blob 不变。因此 B 的领域差量复签适用于 A@7067d19。

## 3. B 组语义差量复核

B 已核对 A 集成树保留以下关系和反例：
- authoritative_req_version（需求—版本权威来源连边）作为 BRV 复合 FK 前置；
- authoritative_link（需求/版本/SST 来源连边）作为 BRVS 复合 FK 前置；
- 合法 BRV 以 UNSPLIT LEFT JOIN 返回，不伪造 SST；
- 同批次多需求、多系统版本、多 SST；同版本可被多个需求共享，但 SST 不自动共享；
- SST 原始 source ID 版本限定唯一，内部 sst_id 项目内稳定唯一，sst_source_trace 保留 namespace/revision/ref；
- 403 授权先行、404 授权后不存在、409 修订冲突、422 错误/跨批次关联拒绝；
- 非法批量关联或日期审计写入失败时事务无部分副作用。

## 4. B01/B02 W0 设计见证补强

原 B W0 witness 已验证日期唯一、改期回滚、复合关联和 FG18；但轻量 system_version fixture 没有真正声明所属 system 的复合 FK，batch_date_history 也未完整见证 actor/changed_at/approved_change_ref 和不可改写属性。本轮新增独立 B01_B02_IDENTITY_DDL 与 TestB01B02IdentityAndDateDesignWitness，原 DDL 保持不变，以兼容 F 原始 FG18 测试。

新增设计反例：
- B01：同项目日期唯一、跨项目同日合法；改期保持 batch_id；date_revision/relation_revision CAS；审批人、原因、审批引用、带时区 changed_at 同事务留痕；日期冲突与旧 revision 均 409 且零副作用；审计写失败回滚；历史只追加；403 优先于资源存在性。
- B02：system_identity 复合主键与来源唯一身份；system_version_identity 必须复合 FK 到所属 system；相同 version_label 在不同 system 合法；同 raw ID 不同 namespace 可区分；相同 namespace 重复来源及跨项目错误归属拒绝。

这些仍是 SQLite 设计见证，不是 W1 PostgreSQL schema、repository/service、HTTP、真实并发锁、迁移或冷重启验收。

## 5. B06 Scope API 精确契约（答复 E PR #96）

**请求：** DSH Host middleware 从已认证宿主会话派生 principal 并绑定到服务端 request context；principal 不是 query/body 字段，也不是 E adapter 可自报/传入的参数。业务查询参数为 project_id + batch_id，或 project_id + release_date；可选 requirement_ids[]、system_version_ids[]、sst_ids[]、page_size、page_cursor。B06 不接收 mission_id，不维护 authorized_mission_ids。

**响应固定字段：**
- project_id、batch_id、release_date、relation_revision、access_scope_revision；
- source_refs：去重后的非空字符串数组，覆盖本页每条 BRV 的 source_verified_requirement_version.source_link_ref，以及每条 SPLIT SST 的 source_verified_link.source_link_ref；UNSPLIT 只含 BRV 来源；
- records：真实 BRV LEFT JOIN BRVS；每行含 requirement_id、system_version_id、split_state、sst_id、source_verified_requirement_version；SPLIT 行另含 source_verified_link；UNSPLIT 行 sst_id=null、source_verified_link=null；
- warnings、gap_indicators：固定数组，无内容时为空数组；
- next_page_cursor：固定顶层字段且必须存在；null 表示最后一页，非 null 表示后续页。

**分页：** 请求游标为 page_cursor，响应游标为 next_page_cursor；B06 不使用外层 pagination envelope，也不并列输出另一套响应游标。cursor 绑定 principal/project/batch/filter/relation_revision/access_scope_revision/稳定排序位置；若查询依赖 R1，再绑定 truth_revision。修订变化返回 409 STALE_CURSOR。消费所有页直至 next_page_cursor=null 才可标记 Scope 完整。

**职责边界：** B06 只授权 project+batch+relation query，不处理 Mission allow-list。E 在 B06 成功后读取 R1，验证 Mission 显式 project_id、batch_id 与 Scope 一致；缺失/不匹配必须 HOLD，不能从 release_id/name/version_label 猜 batch_id。B06 不产生 R1 truth_revision/as_of；E 负责补充 R1 truth 与 R1 source ref。B06 的 source_refs 只代表 B 领域来源。

06-API-AND-EVENT-CONTRACT.md 已追加 B06 专属字段说明，明确覆盖泛化 pagination 描述；A 仍需在共享账本中保持单一规范。

## 6. 同 HEAD CI 证据

B PR #95 最新 HEAD 50765bb3b458d63391dc2909349ad800cf0be65f：
- B SQL witness：23/23 PASS；
- F 原始 FG18 跨版本 SST 反例：1/1 PASS；
- W0+B/C/D/E shared contracts：165/165 PASS；
- E W0 contract：40/40 PASS。

原始日志：
- B job 129319358547 / run 42663054969
- E job 129319458904 / run 42663082990

F PR #94 对 75fd2c6 的 FG18 设计复验通过；A 7067d19 的 FG17 专项 CI 另有 Py3.11 C09 3/3、Q1 Py3.8 C09 3/3 及五次独立 1/1。F 尚未独立复核 7067d19，因此 B 不替 F 更新 FG17 裁决。

## 7. B 组正式差量复签与门禁

**B_DESIGN_SIGNOFF_RECONFIRMED = ACCEPTED**，范围仅限 B 负责的领域关系、来源身份、日期/系统版本设计、B06 Scope payload 与负向验收标准。B 不代签 A01、D、E、F，不宣布 W0 冻结。

- B01/B02：BLOCKED_W0_DESIGN_FROZEN；真实 W1 实现未启动。
- B03→B04→B05→B06：等待 B01/B02 和相应前置 QA；B06 稳定 Scope API 未实现。
- B07/B08：继续受 B05/B07 和 W2 依赖约束。
- BUSINESS_TZ_APPROVAL、可信 source mapping、真实 PostgreSQL/迁移/回滚仍 HOLD。
- F 对 75fd2c6 的总裁决为 REVIEWED_WITH_BLOCKERS；A 7067d19 仍待 F 差量复核；FG21 PR #84→work/rc7.2 mergeable=false/dirty，A02 BLOCKED_LICENSE。W0 继续 NOT_FROZEN。

**下一 ready 工单：** 等待 A/F 正式解除 WB-W0_DESIGN_FROZEN；届时 B01 与 B02 才可并行转 READY。随后按 B03→B04→B05→B06 顺序施工。本轮不创建 PostgreSQL migration、不标 IMPLEMENTATION_QA_PASS、不构建 Windows ZIP、不改 RC7.2 主线。

## 8. R4 最新联合集成差量复核（A@b385e042c4543f5d918d61bff5e01be1d88afba7；F PR #101）

B 自 PR #95 前次签署所依赖的 A@7067d19 重新核对当前 A W0 源 `b385e042c4543f5d918d61bff5e01be1d88afba7`。B 原 `WB-B-A03-DESIGN-SIGNOFF.md`、02 业务领域合同和 06 通用 API 合同在新 A HEAD 的 blob 未发生变化；A 新增 RC7.2 R4 逻辑 Agent Teams 名册32/默认活跃4 与 FG17 targeted 收敛不改变 B 领域来源 ID、复合 FK、投产批次或 B06 的 ownership 边界。

F 最新独立审核 PR #101：FG17 targeted real browser PASS；FG21 Git merge conflict resolved；新 FG22 为 CI 入场负向错误码不一致（W0 159 cases / 1 FAIL，F 164 / 1 FAIL）；A02 商业授权仍阻断。**F=REVIEWED_WITH_BLOCKERS、W0_NOT_FROZEN**，B 不代替 A 修复其 CI validator，也不以 B 测试绿灯覆盖 FG22。当前 B01/B02 的 W1 PostgreSQL 施工门禁仍未解除。

### 8.1 B 组补强：来源 SST 身份 ≠ 已核验来源链

B 的早期 FG18 W0 SQL witness 虽记录了 `sst_source_trace`，但 `authoritative_link` 只 FK→`sst`，允许一个有内部 SST 身份、却没有 source_trace 的对象伪造为已验证关系。这是新的 W0 设计负向覆盖缺口；本次改为 `authoritative_link(project_id,version_id,sst_id)` 必须复合 FK→`sst_source_trace`，trace 本身再 FK→`sst`。source_ref / source_revision / source_namespace 和两个 source_link_ref 均增加非空白检查。

新增三项 W0 负向测试：未留痕 SST 不得变成 authoritative link；同 raw ID 不同系统版本的 source trace 不可互认；空白来源 namespace/revision/ref/requirement-version-link/SST-link 一律拒绝。原 F 独立跨版本 raw SST ID 测试保持原始 source key 语义与输入，不修改 F 代码。关联仍需要完整 BRV + 权威 requirement-version edge + authoritative SST edge；本轮只是 SQLite 设计契约，不是 PostgreSQL migration 或外部真来源导入。

### 8.2 新 HEAD 验证边界

本轮 B PR #95 最新 HEAD 与 run/job 必须按 GitHub 同 SHA 原始 CI 更新；A@b385e042c4543f5d918d61bff5e01be1d88afba7 的全局 W0 contract 仍因 FG22 RED，允许 B 原型独立设计子集 PASS，但不得显示全局 W0 绿灯、F ACCEPTED 或 WB-B01/B02 IMPLEMENTATION_QA_PASS。

## 9. FG22 A 组修复差量（A@5bba94c213e2d54a83f8aa360b0f3d71ea8d26a1）

A 自 R4 `b385e042c4543f5d918d61bff5e01be1d88afba7` 之后仅修改 `tests/test_dsh_workbench_ci_admission.py` 修复 F 提出的 FG22 Q1 Admission reject-code 测试不一致，并补充真实 CDP test 被删与 Draft 不应入场两类独立反例；B 领域 02/06、原始设计签署以及 B 原型保持各自源语义不变。

A 同 SHA W0 合同工作流 job 129538382920 实际 `Ran 161 tests ... OK` 和 `CI_ADMISSION_POLICY_PASS workflow_count=12`。这只是 A FG22 合同整改的正向证据，不意味着 F 已审核新 SHA、W0_DESIGN_FROZEN、PostgreSQL 实库或银行现场验收。B 在 A 新源之上重新合成独立 PR，重新跑 B 专项与联合合同并保留历史红灯。

## 10. A 组 W0 集成并账增量复核（A@3f96e032e7e33491ab1330bff73aa8a4acf1b8c7）

A 最新 W0 集成提交 `3f96e032e7e33491ab1330bff73aa8a4acf1b8c7` 已包含 B PR #95 早期 `67c4fc5` 的日期/系统版本设计 witness、B06 API payload/来源主体约束，及 C #97、E #96 原创合同。A 的 06 合同 blob 与 B 原签署版本一致；新 B PR 差量只修改 B 自有 SQL witness 和本复签补充，不倒退 A 的 08/09/10/A03 集成账本或 C/E 文件。B 新增的三项 source trace 负向约束与旧 F FG18 原始反例相互独立；需要 F 在最新源独立审查。

A 已修复 FG22 旧错误码单测，W0 合同绿灯；但最后 W0_DESIGN_FROZEN 仍须 F 独立签署，不能因 CI 绿灯单方放行 B01/B02 正式 PostgreSQL 实施。B 本轮只提交 W0 SQL 设计见证，不声称 W1 SQL migration/API 可用。

## 11. A 更新集成合同核验（200a96ac2ce3b69f2bd76a98517444699c8fbe92）

A 对前一集成源 `3f96e03` 新增 A-owned 修复：`tests/test_dsh_workbench_w0.py` 将已过时的 B_FG18_CORRECTION_SUBMITTED 期待更新为 B_DESIGN_SIGNOFF_RECONFIRMED/FG18_DESIGN_RECHECK_PASS 且保留 W0_NOT_FROZEN、真实实现 QA 未执行的负向门禁；CI admission 加入 C Node scope 负向准入。A 当前同 HEAD W0 job 129542422674 SUCCESS。B 使用这一 A 源复验自身不可篡改来源边界，本条不冒充 F 已接受或 W1 正式 DB 实现。
