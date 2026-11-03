# RC7.2 完整搬运包对照基线

用户要求：与 RC7.1 同等级的完整搬运包，搬入行内验收。本文记录最终 C12
必须核对的实际继承载荷，不代表已有最终包。施工与同源验证仍须先完成。

仅运行 `rc7_release.rc72_package` 的工程构建/校验不足以证明完整载荷。
继承完整链还包括 `rc7_release.final_unified_overlay`、
`runtime_payload_materializer`、`runtime_turnkey_certificate`、
`final_unified_qualification`、`final_manifest_refresh` 和 `final_archive`。
需将这些真实载荷、入口和验证要求适配到 RC7.2，不能只改包名/版本。

## 已读取的 RC7.1 实际完整制品

原始基线为提交 `366e196826afb3be17d2811044699891bdd28ea5` 的
[成功完整构建](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/40544859972)，
制品 ID `12754241427`，其中交付 ZIP 名为
`PFC-AITest-RC7.1-FIELD-TURNKEY-BANK-WIN10-366e196826af.zip`。
原始元数据报告该交付 ZIP 的 SHA256 为
`31c80458faf1cc7daf15cc5b640ded67f0a07c32f474cbcc21e6dac5e559a7eb`。
已通过 HTTP 范围读取实际 ZIP 中央目录：共 **35,468 个文件，解压后
3,420,334,320 字节**。这次核对没有下载并重算整包摘要，不能声称已在本机
完成历史整包完整性验证。新 RC7.2 交付仍须独立生成、全文件校验和干净解包验证。

实际运行时载荷如下（来自制品目录，数量不作为新版本逐文件相等的门槛；
RC7.2 必须保留对应功能、记录真实解析版本并完成实际能力验证）：

| 包内载荷组 | 基线文件数 | 基线未压缩字节数 |
|---|---:|---:|
| `runtime/allure` | 127 | 33,385,188 |
| `runtime/browser` | 339 | 482,768,902 |
| `runtime/code-intelligence` | 1 | 105,873,408 |
| `runtime/dsh-plugins` | 4,868 | 72,251,760 |
| `runtime/java` | 492 | 317,546,460 |
| `runtime/k6` | 1 | 67,116,752 |
| `runtime/maven` | 96 | 10,869,833 |
| `runtime/maven-repository` | 1,824 | 56,529,233 |
| `runtime/node` | 2,032 | 99,119,403 |
| `runtime/node-execution` | 15,372 | 1,385,392,564 |
| `runtime/python` | 9,747 | 445,089,472 |
| `runtime/ripgrep` | 13 | 4,601,750 |
| `runtime/zap` | 150 | 322,841,446 |

实际归档内的 `PACKAGE_MANIFEST.json` 记录 34,411 个文件，中央目录中没有
缺失这些条目。归档另有 1,057 个未列入该清单的条目：1,047 个编译缓存，
两个清单自身，以及八个构建资格检查生成的 `state/` 启动/插件/DSH 状态文件。
RC7.2 封包前应清理构建产生的临时启动状态和非必需缓存，再重建完整清单与
校验和；不能把 CI 的启动记录或路径作为用户新安装环境的有效运行状态。
这项发现不撤销 RC7.1 的历史构建结果，也不能用其历史 PASS 代替新包验证。

基线的干净解包记录实际验证了包内 Python、CodeGraph、Browser、产品入口和
管理界面健康；统一资格记录还覆盖文档工具、专业工具链和离线载荷。
现场银行绑定仍明确保留待配置状态，完整工程交付不等于 BANK_FINAL。
DSH 核心继续属于银行宿主能力；随包插件、技能、引导和诊断工具应按真实清单
分别核对。不得把这份 RC7.1 参考记录当成 RC7.2 的验证结果。

| 载荷组 | 继承真实来源 | 最终验证要求 |
|---|---|---|
| 产品运行与管理界面 | package.py 的 SOURCE_DIRS、REQUIRED_PRODUCT_FILES；RC7.2 原生服务/统一入口 | 包内版本一致，真实 ReleaseBatch 入口使用同一 R1，管理界面能查询当前状态 |
| Python 与离线库 | package.py 的 Python 复制、build-final-payloads.ps1 的文档/表格/PDF/OCR/CV 依赖 | 在干净目录使用包内解释器验证所需能力，不能借宿主机库通过 |
| Node / 执行库 | final_unified_overlay.PAYLOAD_DIRS、node-execution | 包内 Node、Playwright 等真实可用；平台原生模块与目标匹配 |
| DSH / 插件 / 技能 | .dsh/skills、REQUIRED_DSH_PACKAGES、OPTIONAL_DSH_PACKAGES | 实际启动器可调用；逐项区分随包、可选与银行宿主能力；配置不含凭证 |
| Browser / BSK | package.py 浏览器、Browserskill CLI 与扩展载荷 | 浏览器、CLI、扩展文件齐全且可运行；真实银行连接/批准由现场验收记录 |
| CodeGraph / 搜索 | package.py CodeGraph、ripgrep | 独立二进制、能力探测、来源与校验和；不能以路径占位代替载荷 |
| Java / Maven / 离线仓库 | final_unified_overlay 的 java、maven、maven-repository | 包内 JDK/Maven 可编译执行；断网依赖解析及 JUnit/覆盖率链可用 |
| 报告 / 性能 / 安全工具 | allure、k6、zap | 实际二进制/依赖及能力探测；失败应明确阻断对应能力 |
| 配置 / 工作区 / 双平台入口 | workspace-template、packaging/rc7、packaging/rc7.2 | 完整模板和引导，Windows/Linux 各自匹配的运行时，恢复与诊断入口 |
| 现场验收与证据 | Q3..Q9 工具、handoff、目标 Linux probe、资格/故障演练 | 可以从包内执行、导出完整证据；待现场项保留 PENDING/HOLD |
| 封装与完整性 | final_manifest_refresh、final_archive、CHECKSUMS | 最终源提交/Build ID/载荷清单一致；全文件校验；无缓存/运行状态/密钥；干净解压启动 |

冻结版本不等于固定上游 latest：构建时必须记录实际解析版本、平台、来源、
摘要和能力测试结果，审查原生依赖。已有继承构建器以 Windows 为主，不能把
Windows 可执行文件复制到 Linux 后声称支持双平台。银行宿主能力必须明确
配置与现场核验方式，不能伪造为已随包交付。

最终交付目录：`/Users/tatu/Documents/Codex/2026-11-02/ji-x/outputs/`。
交付件包括完整压缩包、外部校验和、开箱操作说明、工程验证记录和行内验收清单。
现场 BANK_FINAL 不因工程打包成功而自动获得。
