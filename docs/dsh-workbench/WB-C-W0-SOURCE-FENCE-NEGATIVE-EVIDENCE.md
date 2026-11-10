# C 组 W0 Source Fence 原创负向设计及验收证据

级别：W0 设计验证；不是 W1 正式工作台 API/Host/SSE/R1 集成，不是 F02 产品 QA_PASS。
来源：C PR #97 代码提交 work/dsh-wb-ui-followup，基线 A work/dsh-wb-w0@200a96ac2ce3b69f2bd76a98517444699c8fbe92。
版权：全部原创，不复制 PolyForm Noncommercial 受限 HTML/JS/CSS/素材；A02 BLOCKED_LICENSE 保持。

## 行为与禁错
- ScopeReadFence 以 project_id、stable batch_id、release_date、已选需求/系统版本/SST、relation_revision、access_scope_revision、truth_revision 及 epoch 防止旧响应回写新上下文。
- 响应必须匹配当前项目/批次及对应 revision，否则 SOURCE_SCOPE_MISMATCH；Scope 变更后旧票据为 STALE_RESPONSE；清空 Scope 立即失效。
- 401 AUTH_REQUIRED、403 FORBIDDEN、404 NOT_FOUND、409 REVISION_CONFLICT、422 INVALID_SCOPE、503 SOURCE_UNAVAILABLE 均不可映射为 PASS/零成功。403 文本不显示私有 ID。
- 200 无 R1 来源不算业务成功；NodeGate PASS 缺 Evidence 或人审为 EVIDENCE_OR_REVIEW_MISSING；R1 STALE/UNKNOWN 为 TRUTH_NOT_READY。所有预览状态 verified=false，无任何正式 PASS。
- 详情页模拟错误/迟到按钮只处理内存样本，不发真实请求；原版六页面、十区及独立六阶段业务状态不被替换。

## 测试与历史红线
- 新 tests/test_dsh_workbench_ui_source_fence.mjs 预期 10 项，旧 Scope 14 项及 50 feature reconciliation 6 项，合计应有 30 项。需在两个 W0 CI jobs 中全部执行并保存真实日志。
- 历史代码 SHA 6249f1ad00cfa27d4a3ce63b9a89af8fd5892413 run 42728674597：W0 browser job 只跑旧 20 项 Node，真实 Chromium 新错误场景通过，artifact 13723128464；B→C job 实际只跑旧 15 项。不能报成30/30。
- 此后已修订 workflow 的两个任务命令及合并探针到当前 C follow-up 分支，最新 CI 结果必须同精确 SHA 核验。
- F 最近 #101 在 A b385e04 源的意见 REVIEWED_WITH_BLOCKERS / W0_NOT_FROZEN；新增 C Source Fence 由 F 另行独立审查。

## 正式交付必须等待
- A/F W0_DESIGN_FROZEN：C01 准入；B06 真 PostgreSQL、可信 Host、分页关系、用户授权：C02 准入；正式 F02 真 UI/API/错误、跨分区/SSE 恢复回归：业务 QA 准入。
- A02 商业授权或可审计合法原创来源批准以及 FIELD_QA / Windows 离线才能考虑银行交付。

## 2026-11-10 W0 source-fence 同 SHA 验证通过（仅静态原型）
- 同源实测：C #97 HEAD 15d37ec22e758922cab513a2d403be9211eddaf8；[W0 Chromium job 129545127122](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943652/job/129545127122) 实际 30/30 Node PASS + 真浏览器交互 PASS + 3 PNG；[B→C job 129545127428](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943652/job/129545127428) 30/30 PASS；[E 合同 job 129545126959](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943656/job/129545126959) SUCCESS。只核销 W0 源反例探针，不证明 W1/F02。
- artifact [13723922528](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42729943652/artifacts/13723922528)，scope PNG sha256 6e64316cad45e7d43f1827ce1d45914f0560505539edc39bfaded5232443c8ae；历史 6249f1a 测试漏跑事实保留。
- F 对本 follow-up 最新 UI 和真实截图仍独立审核待办；W0_NOT_FROZEN / A02_BLOCKED_LICENSE / C01_C02_W1_NOT_STARTED / NO_BANK_ZIP。
