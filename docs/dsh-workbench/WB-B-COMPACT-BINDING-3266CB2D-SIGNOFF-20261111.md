# B：紧凑 binding 数字域兼容修订窄复签

被审PR #198，完整 `3266cb2d814c8f2233733ba4b53642940a7892a0`。前次b61cda8e审查报告提交`e0a851bd9cc8493a47f96f5033346f4850fa24aa`（PR #205）保留历史结论，不转签旧源。

结论：**B_COMPACT_BINDING_PURE_MODULE_DESIGN_ACCEPTED_AT_3266CB2D**。前次唯一完整envelope有限浮点兼容P1已消除；当前无剩余B设计P1。准入仅独立纯parser/serializer/不可变比较模块及相应测试，不授权改正式models、reader/replay、writer、008或冻结合同，不表示来源、PREPARE、正式创建事件、Host/F/现场资格通过。

## 窄复核依据

- strict数字规则明确只作用于scope_binding及K/mapping、受管镜像/身份字段；作用域integer拒绝bool/float/指数值，不以1.0/1e0数值等于1通过。
- unknown outer的合法有限0.5/1e3归原模型，plain DTO不参与scope分类/比较，不重编码、不修改；raw入口禁止全局parse_float=reject。LEGACY_UNBOUND及其空作用域serializer不会因未知outer有限数值而改变。
- 完整bound增加未知outer有限数值仍仅BOUND_STRUCTURAL_ONLY，作用域serializer与原值相同，不吞未知字段去“修复”完整Mission。
- raw全局重复key/NaN/Infinity规则被明确限制为新raw入口的严格策略；plain DTO的未知outer语义仍归原模型，旧正式reader/replay无任何变化。它不把此新入口策略伪装成既有legacy模型策略。
- 紧凑15键/K4键/mapping7键、完整PG快照引用/历史三revision、namespace/outer一致、永久creation_operation_ref与缺来源HOLD边界未变。前次对此分段接受在本新SHA重新确认有效；DTO仍只表示结构，不能授verified/create许可。

## 实际核查与准入边界

比较b61cda8e→3266cb2d，变化仅数字域/新raw策略、兼容向量/比较边界文字及调查证据。逐字比较字段表至§4.2之前的映射/示例段完全相同，SHA256 `c17d1734cfe8bd858d2b3691d168fdf9971e77d3ed26123b5757b2bab3507f37`。用stdlib解析0.5/1e3 legacy例及bound额外字段例，确认作用域不存在/作用域片段不变；1e0被解析为float、true为bool，具备严格scope type拒绝所需区分。这是文档向量/标准解析行为自洽审计，**不是新纯模块实现测试通过**。

后续精确实现必须覆盖raw/DTO、legacy缺省、显式null/partial/flat-only、镜像/内部身份冲突、schema/type/digest/date、任一不可变字段修改、未知outer有限数值与输入不变/零外部副作用等正反边界。完整PG snapshot/intent、永久操作分配及正式查询接口仍未因本签署变成已存在；接入正式模型/读取/写入必须另审完整增量。

只新增本独立报告，未改候选、08/09/10、数据库、R1或任何正式运行路径。真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER；独立实现QA与D/E/F所需签署仍须精确源证据。
