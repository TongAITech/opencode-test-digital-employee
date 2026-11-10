# RC7.2 R4-06 C12 — 本地已批准 DSH 主程序的一次性 Windows 搬运包

## 目的与边界

`work/rc7.2` 既有 GitHub-hosted portable-transport workflow 只识别 `RC72_DSH_MAIN_URL` (Secret) + `RC72_DSH_MAIN_SHA256` (Variable)；银行实际交付的 `dsh.exe` 如只存放于受控文件服务器或合规 Windows 构建机，**不能直接将银行二进制传到不受控公共 runner**。本入口复用正式 `rc72_package`、`rc72_dsh_main_payload`、`runtime_payload_materializer` 和独立 `rc72_qa_offline_audit.py`，不构建假 DSH。

**不在行内无外网 PC 上安装**：本脚本只能在银行批准的 Windows x64 构建主机运行，构建时需要既有 RC7.2 离线工具链下载源/内部合规镜像、Python 环境、Node/npm、Java/Maven、Chrome、ripgrep、对应真实签名来源；最终成品才是供银行电脑离线搬运的文件。构建宿主无网络或依赖缓存缺失时，必须明确失败，不得删减离线依赖换 PASS。

## 输入物（全部为真实、受控来源）

1. 当前拟交付的 Git 40 位 `SOURCE_COMMIT` 和没有已修改 tracked 文件的工作树。
2. 获准离线分发的 **真实 Windows x64 PE32+ CLI `dsh.exe`**，不得使用 Desktop installer、伪造 PE 测试夹具或其他机器的未批准旧程序。
3. 由独立渠道确认的 `dsh.exe` 64 位 SHA256，与上述真实文件逐字节匹配。
4. 独立批准留痕文件路径（如已签字的批准单）。构建器保存该文件 SHA256，**仅能保证留痕文件存在且构建时没有变化，不能代替组织确认签字有效性**。
5. 在获准构建机上配置经过批准的全部既有 RC7.2 构建前置依赖，包括 `rg.exe` 可在 PATH 查到、node/npm、Python 依赖、BrowserSkill/Chromium/CodeGraph/Java/Maven 源和 GitHub API 或镜像。不得将银行密钥提交到 Git 或 CI 日志。

## 操作（受控 Windows PowerShell，不上传银行 EXE）

```powershell
# 从正式拟交付源码检出；E 组尚未验收时不得称主线已发布
git checkout <已完成独立验收并合入的源提交>
$sourceCommit = (git rev-parse HEAD).Trim()

# 以下路径指向受控构建机磁盘，仅作为操作示例，不应复制到仓库
$dshFile = "D:\approved-payload\dsh.exe"
$approval = "D:\approved-payload\authorization-record.pdf"
$dshSha256 = "<从独立核对渠道获取的64位SHA256>"

# 只读取文件，零下载、零构建
python -m rc7_release.rc72_c12_local_portable preflight `
  --source-commit $sourceCommit --dsh-file $dshFile `
  --dsh-sha256 $dshSha256 --approval-record $approval

# 仅在真实批准来源核验后，执行完整依赖物料、封包、全新解压和独立 Q2 核验
python -m rc7_release.rc72_c12_local_portable build `
  --repo-root . --output dist --source-commit $sourceCommit `
  --dsh-file $dshFile --dsh-sha256 $dshSha256 --approval-record $approval
```

**重要：** 仅在**银行批准的 Windows 管理员权限、专用临时构建 VM**上运行完整构建。完成全新解压后，脚本对新包内 Node 的准确 exe 路径自动添加单程序 Windows Defender 出站阻断规则，必须保证主机防火墙各 Profile 已启用，并在执行 Q2 后无论成功或失败都清理该规则；若缺少权限、无法添加/清理、Q2 仍可出站，构建失败并拒绝留下最终合格 ZIP。**不要在共享生产 PC 上运行此构建。** Windows pip-mirror 验证仍需要受控 Python/pytest 与真实离线物料。

## 工程执行顺序

- **真正无副作用的 preflight 在最前**：精确 SHA 格式、真实文件大小及 PE32+/AMD64、独立 SHA256、批准文件哈希；失败不下载、不建 ZIP。
- 真实 Windows 构建机绑定 `git HEAD` 与 `SOURCE_COMMIT` 且拒绝 tracked worktree 改动；禁止覆盖已有同 SHA ZIP、收据或构建目录。
- 调用已冻结的 `plugin_payload.acquire` 与 `rc72_package.build_package(make_zip=False)`；必须先由正式 `rc72_dsh_main_payload.materialize(source_file=...)` 复制并重验真实 exe，再获取所有 offline payload，封存 `PACKAGE_MANIFEST`、`CHECKSUMS` 和全能力清单。
- 使用原生 `_repack` 一次成包并生成 ZIP SHA256；独立临时空目录重新解压，验证路径无法逃逸、没有 ZIP symlink。
- **从新解压的包内 Python 执行** package identity、runtime delivery、full capability inventory、Windows clean R1 qualification、隔离环境下的完整 Python/document/OCR probe、禁止网络外连的 Node execution-node 验证、严格全文检索验证；再由源码外的独立 QA audit 校验同一 source commit 和物理 DSH，并运行 Windows pip-mirror 实证测试。与 GitHub 既有 Q2 流程对齐，全部失败即拒绝出 ZIP。
- 上述任何步骤失败，不保留貌似可交付的最终 ZIP；全部成功才写出 `PHYSICAL_Q2_CANDIDATE_ONLY` 收据（主程序 SHA、批准文件 SHA、ZIP SHA，均非银行最终 PASS）。

## 核销、真实输入与限制

仓库源测试使用的是**结构化假 PE 负例夹具**，只验拒绝机制。它不能证明真实 EXE 已获得授权，也不能证明实际 1.5GB 包已运行。必须由银行批准的构建主机运行一次真实构建，第三方 E/银行现场在新机器上核对 ZIP 文件 SHA、无 PATH 劫持、正式 DSH 可启动、AgentTeams 32 逻辑成员与第 33 位拒绝、Q3–Q9/4A/BSK/Libra/N8→N9→N10 Evidence。缺任一项保持 `C12_PHYSICAL_HOLD / FIELD_VERIFIED=false / BANK_FINAL=NO`。

此脚本**不与旧 GitHub 纯 HTTPS 路径混为一谈**；选择本地 DSH 模式不意味着可自动用于 GitHub-hosted runner。
