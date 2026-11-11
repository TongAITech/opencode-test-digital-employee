# WB-A01 中英文与主题范围正式决定（W0 设计，W1 实现）

**A01 范围决定：`KEEP_ZH_EN_W1_REQUIRED`，2026-11-10。** 中文 `zh-CN` 是默认及当前 W0 原型的唯一已呈现语言；**英文 `en-US` 不裁剪**，原版目标 `P05-03` 和 `X01-01` 必须保留至 C01/C02 与 D 的 W1 真正实现及 F02 逐项功能验收。此处只是 A01 产品范围责任人明确设计，不是 B/D/E/F 代签、W0 正式冻结或任何英文功能已运行。

## 来源与落实范围

- 保留 50 项原版目标，其中 35 项 O/A 和 15 项 N；对应 A01 原子登记和 C 的 50 项差异矩阵。**50/50 正式产品均 NOT_RUN**；C W0 原型 `THEME_COLLAPSE_ONLY` 无英文完整切换，Skill P05-03 是 `NO_INTERACTION`，不能算完成。
- `P05-03` 由 D（真实 Skill Catalog/DSH Host）和 C（UI）协同，技能名称、说明、安装条件在两语下保持同一 catalog_id/version/source_ref；英文不存在时显示原来源文本并明确标注回退，不可编造翻译或伪造成功安装。
- `X01-01` 由 C/D 协同，实现完整六页（5 导航 + 从项目进入的第六页）和项目详情十个分区的中文/英文文案、按钮、表单、错误/审批状态；主题的浅色、深色、跟随系统、导航/项目雷达折叠及有界调整独立保留。
- 语言是 **presentation preference**，不得改变 `project_id,batch_id,release_date,requirement_id,system_version_id,sst_id` 业务关系、权限、真 R1 Evidence、NodeGate 或 Human Gate。错误状态仍按机器码 403/404/409/422/503 和 UNKNOWN/STALE/BLOCKED/HUMAN_GATE 判断，不用文案作为事实 Oracle。
- 业务日期是 `YYYY-MM-DD` 的投产日期，不能因语言或格式化时区偏移一天；`BUSINESS_TZ` 未获业务授权时仍在 MIGRATION_HOLD。UI 语言和主题偏好限定用户范围，切用户、切项目、断线、权限撤销不能继承错误 Scope。
- 所有翻译文字、图标、QA Skill 说明等资源需原创/权属可追溯。不得复制 `naodeng/dsh-qa` 的 PolyForm Noncommercial JS/CSS/模板到银行商业交付；A02 许可依然独立 BLOCKED_LICENSE。

## W1 12 个必须实测的正反例

机器追溯：[`WB-A01-LOCALE-SCOPE.json`](WB-A01-LOCALE-SCOPE.json)，用例 A01-L01..L12 分别覆盖：完整六页十区、Skill 双语来源、缺译回退、业务身份稳定、权限/错误状态不变、投产日期不变、用户偏好隔离、主题/侧栏恢复、非法语言与缺 key、审批/证据不伪 PASS、键盘/屏读焦点、第三方资源来源许可。

**验收门槛：** W0 可确认要求完整、拒绝静默裁剪；W1 必须实际运行 zh-CN/en-US 两套交互及负例，F02 逐操作提供同 SHA 截图/操作、真正 Host/API/权限/状态证据。没有这些时 `A01_SCOPE_RECORDED_F_DESIGN_REVIEW_PENDING`、`W0_NOT_FROZEN`、`C01_C02_IMPLEMENTATION_QA_NOT_RUN`、`BLOCKED_LICENSE` 不变。

负向契约：`tests/test_dsh_workbench_a01_locale.py` 拒绝删英文、删 P05-03/X01-01、假 QA_PASS、伪 F 签署、法务越权、缺验收负例、原子源条目缺失。脚本 `tools/dsh_workbench/a01_locale_scope.py` 只做 **设计范围静态检查**，不能算 UI 的 W1 验收。

## 2026-11-10 语言原版入口的固定 SHA 证据补强

只读核对上游 `naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b`：
- [public/i18n.js#L700-L722](https://github.com/naodeng/dsh-qa/blob/fc5a054a48973d004580a3cc1de60da3f701150b/public/i18n.js#L700-L722) 存在当前语言、切换、翻译与中文缺译文回退；[public/i18n.js#L5-L8](https://github.com/naodeng/dsh-qa/blob/fc5a054a48973d004580a3cc1de60da3f701150b/public/i18n.js#L5-L8) 为语言词典入口。
- [public/app.js#L2085-L2091](https://github.com/naodeng/dsh-qa/blob/fc5a054a48973d004580a3cc1de60da3f701150b/public/app.js#L2085-L2091) 为实际设置页语言选择处理；[L2048-L2094](https://github.com/naodeng/dsh-qa/blob/fc5a054a48973d004580a3cc1de60da3f701150b/public/app.js#L2048-L2094) 将语言与 system/light/dark 主题作为独立控件。原先 A01 X01-01 只引用 `setThemePreference()`，不能单独证明 i18n 功能。
- 已将 P05-03/X01-01 的真实语言函数与入口位置回填 A01 原子登记，在唯一正式 `WB-A01-LOCALE-SCOPE.json` 增加只读来源、license 和零源码复制标志。A01 机器验证要求来源锚点不能退化为单一主题函数。
- **边界：** 索引事实不等于我方复制源码的权利；原版 PolyForm Noncommercial 许可保持独立 `BLOCKED_LICENSE`。仍按原 W1 12 条正反例做未来真实 UI/Host 验收；目前中英文 W1 NOT_RUN、F 全局 W0_NOT_FROZEN，不扩展 F #106 结论。
