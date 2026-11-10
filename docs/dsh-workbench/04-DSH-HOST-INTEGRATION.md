# DSH 宿主与插件契约
状态：W0_DESIGN_IN_PROGRESS / W0_NOT_FROZEN；W0 候选合同待 A01/A03/F00 正式签署；W1–W4 实现与现场 QA 未运行；A02 BLOCKED_LICENSE

## 原生能力优先
插件使用 DSH 宿主已有的面板注册、会话、模型目录、技能、命令、附件、取消、历史等能力。不得自建第二套 API Key、模型配置、对话历史。行内 DSH 1.18.26 兼容性需要现场 Qualification，不能以开源 Harness 版本通过替代。
项目通用会话、投产日期指挥会话、短生命周期 Worker 会话严格区分；任务事实存入正式 R1，不能依赖找回历史对话才能续跑 Mission。

## 会话绑定
(project_id, batch_id?, mission_id?, host_session_id, context_version) 为持久化绑定；登录态/Agent session 与 SUT 4A 认证状态独立。SUT 自动登录依照已有 4A skill 与现场权限设置，不从旧会话伪造登录成功。
原生消息携带经过校验的 ContextEnvelope（项目、日期、需求/版本/SST 合法集合与 Mission ID）；动态切换筛选不会篡改已发生 Attempt 的 provenance。

## Agent Teams
队员配置目标可扩展至 32；必须分别展示“可配置队员数”“宿主可实际同时运行数”“资源/模型并发数”。当前 8 上限和 32 扩容均以实际 host qualification 为准，禁止宣称已验证。
Captain 仅负责控制、授权、规划与派工；业务 Worker 使用独立会话、签名租约、真实工具与受控资源；独立 Reviewer 检查证据及充分度。断线/崩溃重启按 Mission/R1 恢复，不重复执行成功 Attempt。

## 环境
Windows 免安装 Git Bash、离线 Node/Python/浏览器工具包；每项依赖包含版本、文件哈希、License、能力探测和可重复启动/卸载验证。Linux 兼容性为后续 RC8 契约，不得把未验的目标标记已通过。
