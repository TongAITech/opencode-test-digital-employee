# WB-D01 — 公开 DSH 宿主与 RC7.2 现有接口差异审计（只读来源）

状态：**SOURCE_AUDIT_COMPLETE / BANK_1_18_26_UNKNOWN / FIELD_QA_NOT_RUN / NO_HOST_WRITE**
日期：2026-11-09。D 组独立审计；不对应任何行内实际版本兼容结论。

## 固定来源和版本轴

1. 本仓库 `work/rc7.2@58e5b25ac75a8f6dc71e46fc6bdd0d71aa690d0d`：
   - `rc7_release/rc72_dsh_agentteams_host.py`：已编码的 loopback `GET /session/status`、`GET /session/{id}` 与签名 Host Membership/Observation。
   - `rc7_release/rc72_captain_host_reentry.py`：R1 的签名 Captain 重进与代次租约校验；会话 ID 自报不能获得控制权。
   - `rc7_runtime/rc72_agentteams_capacity.py`：本仓库策略 roster 32、默认 max_active_workers 4；不等于实际可并发 32。
   - `workspace-template/.opencode/{skills,commands,agents}`：存在工作空间资产目录，但不是 DSH 原生安装能力/宿主插件生命周期的有效证据。
2. 公开 AgentTeams `NanmiCoder/dsh-agent-teams@369c2785c473e546124ab1709664058e6ea93948`：
   - `compatibility.json`（blob `c08f0e6b227bf70ab5603e4dc10aff870d82180a`），固定链接：https://github.com/NanmiCoder/dsh-agent-teams/blob/369c2785c473e546124ab1709664058e6ea93948/compatibility.json
   - `README.md`（blob `3fe23a0763d115d026c96aba33bb087b77b77936`），固定链接：https://github.com/NanmiCoder/dsh-agent-teams/blob/369c2785c473e546124ab1709664058e6ea93948/README.md
   - `skills/dsh-plugin-development/SKILL.md`（blob `6c12357b3651a8f8ec05a0ba7fcf64ccfcb98b82`），固定链接：https://github.com/NanmiCoder/dsh-agent-teams/blob/369c2785c473e546124ab1709664058e6ea93948/skills/dsh-plugin-development/SKILL.md

这只是公开源码读权限下的快照；与银行 DSH 1.18.26 的安装来源、构建 SHA、内嵌 Harness 核心、Profile、Agent Teams 插件版本**没有匹配证明**。不得把独立版本号、软件“最新版”或 npm channel 当作兼容声明。

## 已核对的接口与产品边界差异

| 维度 | 本仓库 RC7.2 现有证据 | 上述开源 DSH 插件宿主约束 | 行内 1.18.26 |
| --- | --- | --- | --- |
| Session | 显式 OpenCode 风格 GET /session/status 和 /session/{id} | Harness 会话/子智能体及 client Chat 会话语义须按目标 exports/types 取证；不推定同一路由 | UNKNOWN |
| 面板入口 | 04 只规定原生入口，新工作台尚未实现 | Host/service/HTTP 与 Client slot、Conversation Node 的生命周期分离；Web UI 需双端适配 | UNKNOWN |
| 宿主插件注册 | 当前工作台无正式 DSH 注册、停用/卸载生命周期 | 插件 bundle、profile、server/client exports 与 loader 需基于实际安装包，不能手写宿主 profile 冒充安装 | UNKNOWN |
| 模型 | 工作台无可用原生模型目录适配 | 官方建议沿宿主 provider/model 管线，插件/宿主独立发布，不能复制 API Key；模型路由 fallback 与恢复需独立校验 | UNKNOWN |
| Skills/Commands | 工作空间 .opencode 文件存在 | 不等于 DSH 运行时注册成功，须逐能力读取 Host 原生接口/权限/出错代码 | UNKNOWN |
| 附件/取消/历史 | 04 设计目标；现无工作台真实回归 | 区分聊天生成取消、子 Agent 退休和正式 Mission 取消；不能混淆历史前缀/成员自身持久消息 | UNKNOWN |
| 权限与身份 | Source 以签名观测与 R1 租约门禁控制 Captain | UI 不可自报 authenticated principal；Host 能力缺失要拒绝敏感操作，按当前版本 exports/types 确认认证服务 | UNKNOWN |
| Agent Teams | roster 32；active 4 为源配置策略 | 开源 AgentTeams 最新取证快照 README 为 plugin 0.1.29、recommended Harness 0.2.1-rc.2；不同于本仓库的安装已验证版本，且不证明 1.18.26 可用 | UNKNOWN |
| Windows | 本仓库已有 RC7.2 Git Bash 启动脚本但未含新工作台 | 开源兼容测试与打包路径是独立证据；不能代替银行非管理员离线冷启、Desktop 实际验证 | UNKNOWN |

**特别发现 D-G05 / P0：接口家族错认风险。** 不能用开源 OpenCode 会话 GET 两个端点可达来宣布 DSH 宿主的 Panel/Client/Skills/Commands/模型/附件兼容。DSH 原生 UI 可能要求 host+client 双面 bundle、版本特定 slot/projection、Profile 服务与卸载 disposer，且插件与宿主版本不一一相等；按精确安装来源和 exports/types 验证。

## 只读 Qualification 的安全顺序和停机条件

1. 取得银行**获授权的脱敏版本信息**：DSH 启动程序版本/构建标识、内嵌 Harness/CLI 包版本、插件规范名/精确版本、实际 profile 身份、Windows/Git Bash/Node 版本。敏感路径与账户不入报告。
2. 只读 inventory 精确安装版本的 package.json、exports/types、已获许可的插件接口声明、Profile 服务注册接口。Host/Client 分开确认，不能把上述开源文档模板当作 1.18.26 的实际 API。
3. `wb_d_host_probe.py` 对已获授权的 loopback 端点最多两次 GET，记录 schema/能力被观察与错误；仅证明旧 RC7.2 所需 HTTP 形状，不访问 tokens/模型密钥、不创建会话、不改变插件配置。
4. 额外按真实宿主 API 且**仅在授权环境**核验原生插件入口、session 创建/切换/读取、model catalog、Skills/Commands、附件、取消、历史、权限变化及断线恢复。要发 POST/造成执行副作用须另签现场计划与权限，不属于本 D01 只读阶段。
5. 与 E/F 分开量测 roster_count、peak_active_worker_count、leased_resource_peak、model_quota_window（附观测周期与 trace），任何缺失均 HOLD，不填 PASS。
6. 遇到认证或路由未知、版本差异、敏感数据、超时、重定向或插件不能查证：停止非只读探测，标 `CAPABILITY_UNKNOWN` 或 `FIELD_QA_BLOCKED`；**不可自动安装、降级安全门禁或回退到第二套密钥存储**。

## 真实状态与移交

- SOURCE_AUDIT_COMPLETE：仅已阅读本仓库与公开固定提交/文件，并提交对账表。
- WB-D01 implementation/field：**FIELD_QA_NOT_RUN**；缺银行当前 DSH 1.18.26 的 source SHA、API schema、实际注册/会话日志。
- D02/D03/D04：工单依赖不满足，NOT_STARTED；Mission 恢复真相始终是 R1，非聊天历史。
- 上游许可证：未复制任何 naodeng PolyForm Noncommercial 代码；A02 继续 BLOCKED_LICENSE。
- 本文不修改 A 的 08/09/10。随独立 PR 向 A 请求复核并保持 D-G01..05 未闭环；F 审查最新 W0 HEAD 后才能决定设计冻结。

审计字段：task_id=WB-D01；source_sha=上述两个锁定 commit；test_command=GitHub read-only fetch_file / compare、`python -m unittest discover -s tests -p 'test_dsh_workbench_host_d.py' -v`；result=SOURCE_AUDIT_COMPLETE（不是 FIELD_QA_PASS）；date=2026-11-09；known_limitations=未访问银行 1.18.26、无真实 DSH Host / model / provider / Windows 日志。

OSS_HOST_CLIENT_SEPARATION：只读来源审计，不代表宿主原生 UI 验收。NO_DUPLICATE_MODEL_KEYS 是 D 组保留的密钥 single-owner 契约。


## D01 增量施工：离线只读版本元数据核验（F 审后）

在 F \`WB-F00-ABCDE-INDEPENDENT-REVIEW-20261109.md\` 认可本组 13/13 设计测试、但拒绝现场资格之后，D 组增加 **独立原创的 allowlisted manifest inspector**，不用 DSH 模型额度，不调用任何插件安装器。

源码：\`tools/dsh_workbench/wb_d_manifest_inspector.py\`。输入为用户已合法取得的 DSH 本地解压根目录，而不是配置档案。**仅读取**以下相对 \`package.json\`（可单选）：

- \`package.json\`（根 package 身份）。
- \`node_modules/@deepseek-ai/dsh/package.json\`（仅当确实存在）。
- \`node_modules/@nanmicoder/dsh-agent-teams/package.json\`（仅当确实存在）。
- \`node_modules/@deepseek-ai/deepseek-harness/package.json\`（仅当确实存在）。

非白名单路径、符号链接、非常规 JSON、同名重复字段、超过 64KiB 的 manifest 默认拒绝；无法用相对路径读 \`profiles/\`、\`opencode.json\`、密钥、Credential/Cookie。JSON **只输出**受校验的 name/version/node engine、exports 声明与 client export 是否声明、dsh bundle 元数据声明布尔值、原始 manifest SHA256，不输出路径、API Key、exports 配置内容或 manifest 其他 JSON。仅看 exports 是否“声明”不意味着 client plugin 可加载。

可重复命令（必须在有权执行的现场、目录不含生产秘密且通过本地安全审查之后）：

\`\`\`bash
python tools/dsh_workbench/wb_d_manifest_inspector.py --root /path/to/authorized/read-only/dsh
python tools/dsh_workbench/wb_d_manifest_inspector.py --root /path/to/authorized/read-only/dsh --manifest package.json
python -m unittest discover -s tests -p 'test_dsh_workbench_host_inventory_d.py' -v
\`\`\`

**不要复制此示例路径作为银行实际根目录**。返回 \`METADATA_OBSERVED\` 仅证明已读取允许的 metadata，并始终携带 \`field_verified=false\`、\`dsh_1_18_26_compatible=false\`、\`bank_final=false\`、\`models/skills/commands/attachments/history/cancel=NOT_PROBED\`。此处兼容字段 false 代表**未获兼容认证**，不是断言不兼容；后续现场必须结合实际 DSH version/exports/运行时 Host+Client 证据进行真实验收。任何非白名单/读错/缺全部 manifest 退出非零，不能借“不存在”宣布版本一致。

新负向测试覆盖泄露秘钥、未知路径、符号链接、root 伪装、重复键、过长数据、无包、错误 JSON、非本地实现依赖与 CLI 返回码。**该 CI 不在银行设备运行，不读取实际 1.18.26 安装包**；故 D01 仍 \`FIELD_QA_NOT_RUN\`、D02/03/04 仍因 W0 门禁 \`NOT_STARTED\`。模型密钥仍只由 DSH Host 拥有（NO_DUPLICATE_MODEL_KEYS）。F 的 FG17–19 及 LICENSE/HOLD 不可因本工具通过而关闭。


## D01 真实 loopback HTTP 传输边界测试（非真实 DSH）

测试文件 \`tests/test_dsh_workbench_host_live_loopback_d.py\` 使用 Python \`ThreadingHTTPServer\` 动态绑定 \`127.0.0.1:0\` 后开启真正的本机 socket/GET，调用同一 \`wb_d_host_probe.probe\` 客户端而非注入 FakeOpener。五个可重复用例：正常双 GET 且脱敏、服务端返回不同 Session 身份、302 重定向拒绝、超长状态响应拒绝、异常状态 Schema 拒绝；每例检查实际请求路径和无 POST，不能发送外网或模型密钥。

**这是 GitHub CI 的临时 fixture HTTP 服务，而不是银行 DSH 1.18.26。** 它能核验只读请求代码的网络行为，却不能证明实际 1.18.26 存在这些接口或 Host/Client/模型/插件兼容；不升级 \`D01_FIELD_QA_NOT_RUN\`。任意真实 Profile 访问、POST/插件安装、模型调用或 Windows offline 资格均不属于该测试，仍受 W0/F 依赖阻断。
