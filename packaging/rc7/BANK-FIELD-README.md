# RC7 行内开箱验证入口

本包状态固定为 `ENGINEERING_CANDIDATE_NOT_BANK_FINAL`。只有真实行内 DSH + 4A + PFC + DB/CAT + Real Mission 端到端通过后，才允许讨论 Bank Final。

## 1. 解压后先做离线自检

在包根目录运行：

```bat
workspace-template\runtime\python\python.exe -m rc7_release.runtime_turnkey_certificate verify --package-root . --rerun-smoke
```

必须看到 `status=PASS` 且 `smoke_count=16`。失败时不要继续业务验证。

## 2. 探测增强能力

```bat
packaging\rc7\PROBE-RC7-ENHANCEMENTS.cmd
```

输出会明确区分：
- 既有 P0 Mission DSH 插件：仍由原交付门禁保证；
- 可选插件：默认关闭，只允许包内本地目录或显式批准的行内 npm 镜像；
- 本地 OCR/CV：交付必需；
- DSH Vision Router：可选，只有本地物化且实际启用后才算 ACTIVE；
- 行内 VLM：必须配置 `PFC_BANK_VLM_ENDPOINT` 且显式设置 `PFC_BANK_VLM_APPROVED=1`；
- 公网图片上传始终禁止。

可选增强插件包括：`@perrylink/dsh-plugin-doctor`、`dsh-vision-router`、`dsh-plugin-anydoc`、`dsh-memento`、`dsh-error-handling`。

如果包内没有某个可选插件，而行内 npm 镜像已批准，可设置：

```bat
set PFC_NPM_REGISTRY_URL=<行内npm镜像>
set PFC_NPM_REGISTRY_APPROVED=1
workspace-template\runtime\python\python.exe -m rc7_release.optional_enhancements --home . acquire
```

该命令不会访问公网 registry；未批准镜像时会 HOLD。

## 3. 行内绑定

至少配置并探测：
- `DSH_HOME` / 实际 DSH launcher；
- `PFC_4A_SCRIPT`：指向行内 `foura_auth.py`，每次重新登录获取新态；
- `PFC_CAT_CONFIG`；
- `PFC_MAVEN_MIRROR_URL`；
- `PFC_PIP_INDEX_URL`；
- 需要数据库时配置 TDSQL / OceanBase / TiDB DSN，写操作仍必须 Human Gate。

执行：

```bat
workspace-template\runtime\python\python.exe -m rc7_release.bank_binding probe
```

## 4. 产品化后管

启动新增产品化页面：

```bat
packaging\rc7\START-RC7-ADMIN-PRODUCT.cmd
```

默认使用 canonical R1：`runtime-state/r1/event-stream.jsonl`。

产品化页面新增 `BR/SR/TR` 视图，支持版本、需求、BR/SR/TR 层级、状态和全文查询；数据从 `requirement_analysis` 的 R1 产物实时派生，不建立第二套业务真相库。页面仍可跳转原有完整用例维护页。

## 5. 真实业务验证

优先挑 1 个真实 SST，走完整链路：

需求分析 → BR/SR/TR → CodeGraph → Test Design → Accepted Cases → Script Readiness → Runtime Preparation/Test Data → L1-L7 → Actual/Oracle/Evidence → Failure Diagnosis/Recovery → Product Defect → Convergence → Final Report。

```bat
packaging\rc7\FIELD-QUALIFY-ONE-SST.cmd
```

任何真实依赖缺失应进入 HOLD/BLOCKED 并留下 R1 证据，禁止转成假 PASS。
