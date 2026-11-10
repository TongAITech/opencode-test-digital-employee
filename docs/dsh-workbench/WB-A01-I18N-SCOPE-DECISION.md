# WB-A01 双语与主题功能范围的正式设计决定

**设计决定：** `RETAIN_ZH_EN_FULL_PRODUCT_SCOPE`（保留中文/英文，不按“仅中文”裁剪）。  
**阶段：** `W0_DESIGN_CONTRACT_ONLY`，**不是** C01/C02 实施验收或 F 全局 W0 冻结。  
**主设计范围：** P05-03 QA Skill 双语说明、X01-01 整站中文/英文与主题/布局设置。  
**现状：** `P05-03=NOT_RUN / X01-01=NOT_RUN / C01_C02_NOT_IMPLEMENTED`。

## 1. 原始来源与事实证据（只读锚点）

固定来源 [naodeng/dsh-qa@fc5a054](https://github.com/naodeng/dsh-qa/tree/fc5a054a48973d004580a3cc1de60da3f701150b)，PolyForm Noncommercial，**没有复制其 JS、CSS、词典或构建物**。

- [public/i18n.js#L5-L8](https://github.com/naodeng/dsh-qa/blob/fc5a054a48973d004580a3cc1de60da3f701150b/public/i18n.js#L5-L8)：语言设置和中文词典入口；英文词典在同文件。
- [public/i18n.js#L700-L722](https://github.com/naodeng/dsh-qa/blob/fc5a054a48973d004580a3cc1de60da3f701150b/public/i18n.js#L700-L722)：存在当前语言、语言设置、翻译与中文回退机制。
- [public/app.js#L2048-L2094](https://github.com/naodeng/dsh-qa/blob/fc5a054a48973d004580a3cc1de60da3f701150b/public/app.js#L2048-L2094)：设置页中的中文/English 切换，与系统/浅色/深色主题为两个独立控件。
- [public/index.html#L46-L60](https://github.com/naodeng/dsh-qa/blob/fc5a054a48973d004580a3cc1de60da3f701150b/public/index.html#L46-L60)：全局设置入口与导航。
- [public/index.html#L224-L225](https://github.com/naodeng/dsh-qa/blob/fc5a054a48973d004580a3cc1de60da3f701150b/public/index.html#L224-L225)：独立国际化资源和应用入口。

**来源核查修正：** 之前 A01 X01-01 仅指向 `setThemePreference()`，不足以证明语言切换。应同时关联 `i18n.js` 的语言函数和 `openSettings()` 的实际切换入口。P05-03 的 Skill 双语能力来源于全局词典和 Skill 页面，不可把普通主题开关当作语言切换。

## 2. A01 正式保留范围

1. **六页面：** P01 测试首页、P02 DSH 测试对话、P03 项目看板、P04 日历排期、P05 QA Skill 安装、P06 项目详情；语言变化要更新标题、导航、表单、状态、提示、异常文案、可访问性标签。
2. **项目详情十分区：** D01–D10 全部纳入；额外的投产日期—需求—版本—SST 范围、错误以及人工门禁状态必须在中/英文语言模式下可读。
3. **默认中文、可选英文：** 新版 UI 应独立原创实现，不要求复用原版 `i18n.js` 代码或词典原文。英文条目缺失时显示有界的中文回退并登记翻译缺口，不得无感展示裸 key 或凭空给空文案；非法 locale 明确回退并留审计记录。
4. **主题与语言独立：** system/light/dark、侧栏折叠、项目雷达宽度和语言独立保存；切换语言不得重置主题、自动打开 Host 会话或绕过用户操作门禁。
5. **业务状态不变：** locale 改变只影响表示层，不得改写 project_id、batch_id、release_date、需求/版本/SST 选集、Mission、host_session_id、relation/access/truth revisions、NodeGate 或人工审批；不得通过翻译改变错误码、R1 原始事实、SST/业务系统标识。
6. **失败封闭：** 中英切换、未知语言、缺译文、跨页面跳转、刷新与从 DSH Host 恢复后要重新验证上下文。英文显示 `PASS` 不能把原本的 `BLOCKED`、`NEEDS_REVISION` 或 `HUMAN_GATE` 转换为业务通过。

## 3. 可执行设计反例与阶段门禁

机器合同：`docs/dsh-workbench/WB-A01-I18N-DECISION.json`。  
负向 gate：`tools/dsh_workbench/w0_i18n_contract.py` 和 `tests/test_dsh_workbench_a01_i18n_scope.py`。

契约禁止静默删除英文、改为仅中文、从 50 项矩阵移除 P05-03/X01-01、将任一标成 `QA_PASS`、缩减六页面/十区、语言切换丢失业务 Scope 或主题、删除原始来源许可证声明、缺译文悄悄变为原始 key。

### 实施和验收责任

- **A / 当前 W0：** 保留两个 O 类原版候选，完成来源入口设计确认及代码化合同。阶段完成仅为 `A01_I18N_DESIGN_DECISION_SUBMITTED`。
- **C/D / 后续 W1：** 在获 W0 设计冻结准入后，才进行原创双语产品实现，并提供 zh/en 六页十区真实 UI、持久语言偏好、QA Skill 文字、主题隔离与业务 Scope 零副作用证据。
- **F / 后续 F02：** 对两种语言、全部页面与反例独立执行录屏/截图/接口/Scope 对账；不能以 W0 合同或原版源码有语言切换作为我们的功能通过证明。

**本阶段禁止：** 擅自裁剪双语、把 P05-03/X01-01 当已实现、宣布 W0_DESIGN_FROZEN、改变 A02 的 `BLOCKED_LICENSE`、复制 PolyForm Noncommercial 受限源码、发布银行 Windows ZIP。
