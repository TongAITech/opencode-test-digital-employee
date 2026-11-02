# RC7.2 Windows 搬运包

解压到本地目录后，双击根目录 `start-rc7.2.cmd`。

包内包含 Python、Node、浏览器/BrowserSkill、CodeGraph、Java/Maven、
基础 Maven 缓存、L6/L7 工具和离线插件。启动不需要下载这些核心载荷。
银行 DSH 主程序、Git Bash、模型账号、4A、业务路由、CAT、数据库和内部
项目依赖镜像属于现场绑定，请沿用银行已批准的安装与配置。

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
