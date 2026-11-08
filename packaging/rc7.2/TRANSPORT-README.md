# RC7.2 Windows 搬运包

解压到本地目录后，双击根目录 `start-rc7.2.cmd`。

包内包含 Python、Node、浏览器/BrowserSkill、CodeGraph、Java/Maven、
基础 Maven 缓存、L6/L7 工具、离线插件和经过独立 SHA-256 校验的
Windows x64 DSH 主程序。正式包必须包含
`workspace-template/runtime/dsh/dsh.exe`，不得使用系统 PATH 的 DSH
或仅以插件目录冒充主程序。Git Bash、模型账号、4A、业务路由、CAT、
数据库和内部项目依赖镜像仍属于现场绑定，请沿用银行批准的配置。

构建时必须通过受控 GitHub Actions 参数提供获准分发的主程序下载地址
`RC72_DSH_MAIN_URL`（Secret）及经独立渠道核定的
`RC72_DSH_MAIN_SHA256`（Variable）；可选鉴权头
`RC72_DSH_MAIN_AUTHORIZATION`（Secret）。若无合法来源、SHA 错误、
非 Windows x64 原生程序，构建直接失败，不会生成新的“合格包”。
这些配置不得提交到仓库，亦不得使用虚构二进制代替。

完整性校验：在包根目录使用包内 Python 运行：

```
workspace-template\runtime\python\python.exe -m rc7_release.rc72_package verify --package-root .
workspace-template\runtime\python\python.exe -m rc7_release.runtime_delivery_contract --package-root .
```

业务状态以 `runtime-state/r1/event-stream.jsonl` 为准。请保存整个
`runtime-state` 目录；更换工作会话不代表新建任务或重做已完成工作。

包内 `SOURCE_COMMIT`、`PACKAGE_MANIFEST.json`、`CHECKSUMS.sha256` 分别记录
源码版本、文件清单和文件校验值。传输 ZIP 另有 SHA-256 文件。

本包是现场验收前搬运候选。Windows 工程验证、载荷存在性检查和干净解压
不等于真实银行任务通过。Q3 信创 Linux、Q4 正式离线验收、Q5 Browser/BSK、
Q6 可信人工审批、Q7 真实 ReleaseBatch、Q8 恢复演练及最终验收由现场证据决定。
`field_verified=false`，`bank_final=false`。


### 第三轮 P2 离线主程序来源安全要求

离线构建从经批准的 **HTTPS 直接下载地址** 获取 DSH 主程序，禁止重定向（即使跳向另一个 HTTPS 域名），避免携带批准的 Authorization 密钥跨主机转发。来源不可提供不可控的 HTTP 302/307 跳转下载链接，应提供最终直连、具有再分发授权且 SHA-256 独立固定的源。网络错误不会回显批准 URL/凭证。包内 `workspace-template/runtime/dsh` 各级目录不得为符号链接/重解析逃逸；本地源必须先满足物理大小范围再复制。这些只是工程候选安全控制，不替代 Authenticode/厂商身份证明及真实 DSH 启动、Q3–Q9。
