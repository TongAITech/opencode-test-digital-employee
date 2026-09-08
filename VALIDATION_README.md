# AITest V1.12.0 Recovery · Windows 验证

将 ZIP 完整解压到可写的搬运目录。Windows x64 Git Bash 中第一次执行：

```bash
./INSTALL.sh
```

默认正式安装目录是 `/d/PFC/AITest`。安装会校验全部 SHA256 和离线依赖、复制 Runtime、初始化 R1 数据目录、运行包内 Python self-check 并生成安装身份；不会启动 OpenCode，也不要求模型、Starlink、4A、CAT 或 DB 认证，不执行在线依赖安装。

目标目录已存在时安装会停止，保留现有 Runtime/Data。需要其他目录时可执行 `./INSTALL.sh --target /d/PFC/AITest-new`。不要覆盖已有安装，也不要把搬运目录作为正式运行位置。

安装后长期使用：

```bash
cd /d/PFC/AITest
./AITEST.sh
```

选择“开始/继续测试对话”时，即使 Model 为 `AUTH_REQUIRED`，OpenCode process 和 Control Loop 也会启动。模型就绪与进程就绪分别显示；模型认证或绑定未完成时，Mission 等待对应引导，不把未执行标记成通过。

宿主 OpenCode 配置先只发现路径，不自动读取内容。选择复用已批准宿主 provider 时明确授权读取，只接纳 provider/model 与已安装本地插件或 SDK 引用；不复制 API key/password/token，不修改宿主文件。内联 secret、远程插件安装或无法确认的银行插件保持 `BANK_PROVIDER_BINDING_REQUIRED`。支持保留 `wizard-local/aicoder-plus` 一类自定义 provider 标识，不强制转换为 `/v1` 服务。配置变动后需要重新确认绑定。包内模型服务绑定也可独立配置。

进入 OpenCode 后只需输入：

```text
测试 BLOAN1.9.4
```

唯一主要入口 `aitest-director` 通过真实用户消息调用 `aitest_director(action=start_test)`；Planner 与 Worker 由 Session Router 建立独立 Session。无需手工创建 Session、切换 Agent 或执行规划／调度命令。模型服务不可用时保留明确 setup gate。

需要需求或 SST 附件时，返回菜单选择“导入需求/SST 附件”，选择刚才的 Mission 和文件。DOCX、可提取文字的 PDF、TXT、MD、JSON 均可导入。返回对话输入“继续测试”。

4A 登录、验证码等只在人工操作的浏览器里完成，不要发进对话。选择“浏览器人工教学 / 4A”可开启观察；按提示完成人工操作后，在对话输入“完成”。Runtime 重新验证当前页面后恢复原步骤；文字本身不代表授权成功。

Starlink 先用行内批准的 Current Release 导出文件：选择“导入 Current Release / Starlink 批准导出”，填写项目、版本、批准记录和有效期。导出需包含项目、发布版本、需求列表、仓库列表、修订号和采集时间；如导出格式不同，请由行内负责人按包内绑定合同转换。文件导入成功不代表实时 Starlink 连接成功。

CAT、DB 的登录和适配器由行内负责人绑定；缺少授权或接口时会显示 `BANK_BINDING_REQUIRED`，不要将其当成测试通过。凭据只交给行内凭据管理或登录窗口，不放进对话、需求文件或证据。

验证完成后选择“导出证据”。ZIP 位于 `data/exports`，包含 Runtime 快照与测试证据。关闭后重新运行同一入口、输入“继续测试”，恢复同一安装目录中的持久状态。


本次 `10.REC.3` 的机器验证结果位于 `MACHINE_VALIDATION_RESULT.json`。`windows-install-manifest.json` 是 CI 安装身份的验证证据；交付根目录 `INSTALL_MANIFEST.json` 是待安装模板，实际安装时会生成该主机自己的身份。

Context stress 使用至少 10MB 合成证据来源，在真实 OpenCode 和后台 Control Loop 中通过有界读取、checkpoint、两次自动 rotation、successor 完成、重启及证据导出重放验证上下文保护。脚本化模型协议验证只证明工具调用与调度链路，不能证明真实 AI 的语义规划质量；`AUTONOMOUS_PLAN` 未获真实模型证据前保持未证明，WorkItem 不 Closure。BLOAN、Starlink、4A、CAT、DB、增量覆盖平台始终需要真实行内验证。
