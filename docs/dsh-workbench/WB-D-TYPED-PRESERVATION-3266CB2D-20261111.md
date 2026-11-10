# D typed 纯结构候选 3266cb2d 窄复签

被审：[PR #198](https://github.com/TongAITech/opencode-test-digital-employee/pull/198)，完整新冻结源 **`3266cb2d814c8f2233733ba4b53642940a7892a0`**。对照前审源 `b61cda8e` 和 D 报告 `f2d8a27c`，本报告重新核对本次窄增量，不转签旧实现/测试结果。独立 worktree `d-typed-preservation-recheck` 从新源建立。

结论：**D_COMPACT_PURE_PARSER_DESIGN_ACCEPTED_AT_3266CB2D / NO_D_P0_P1_FOR_ISOLATED_PHASE / FORMAL_MODEL_HOST_008_FACTS_NOT_ADMITTED**。

## 数值兼容增量的范围正确

本次修订将旧“任意层浮点/指数拒绝”限定回受管 scope 域，避免让纯作用域模块变成整个 legacy Mission 的额外 validator：

- scope_binding（含K/mapping）、外层受管身份及flat镜像仍严格校验。整数revision/schema不可接受bool、1.0或raw 1e0；文本身份不可接受数值；镜像错类型/不等仍拒绝，不降legacy或补来源。
- 未知outer `diagnostic_score:0.5` 或有限 `1e3` 不进入scope分类、不可变比较或scope serializer；不修改传入DTO，不重写整个Mission，也不承诺保留未知数值的原词法拼写。旧无绑定可仍为LEGACY_UNBOUND，完整bound仍只为BOUND_STRUCTURAL_ONLY。
- raw入口任意层重复键及NaN/Infinity拒绝明确只是**新纯入口**的策略，不修改当前正式reader/replay；plain DTO未知outer的语义仍留原模型。实现不能用全局parse_float=reject误拒这些兼容输入。

这个放宽不把未知outer字段变成主体、动作、Host证明、正式事实或执行许可；scope serializer仍只产出已核的作用域片段。D未在此窄增量发现新的P0/P1。

## 原权限与身份边界保持

15键binding、K4、mapping7及镜像/authority/project/batch/mission/release相等关系未改变；partial/null/flat-only、冲突及未知schema仍拒绝。永久creation_operation_ref仍由原K的durable PREPARE固定，不与可变Host fence/网络attempt混同，同K不重分配。它及actor/authority/K字符串仅是结构数据，不能充当当前Host许可。

`original_context_ref`仍属于V3的PREPARE/当前授权恢复域，不因紧凑wire未复制它而取消；parser不验证或构造该权威。当前PG授权及受控正式creation身份核验必须先于tasks/executions/evidence，受控查询缺失/UNKNOWN/冲突保持HOLD；没有因未知outer浮点兼容而放宽这一边界。

**D接受本新精确SHA的纯parser/DTO/detached serialize/immutability阶段施工**，条件仍是模块不接models/overlay/control/replay/reader/writer，不做PG/文件/网络/Host操作，不自行校验业务来源/事件或开放创建。现场不可访问不阻断这项纯结构工作。正式模型保存、正式reader升级、008、writer/事件及真实Host的各自增量仍须对应B/E/F审阅与证据；本复签不替它们准入，不授F或现场资格。

## 本次实际核对

- PR198完整HEAD核对为3266cb2d；RC7.2远端edaf9290。已读b61cda8e→3266cb2d完整diff：只改候选和只读审计文档，无运行实现变更。
- 用git show逐字比较第3节（既有reader/身份先于明细）、第4.2节（永久op与正式事实查询）、独立模块范围段，均未改变。§4.2新源段落SHA256=`f9bb47cc0c6f3fcd695fa15fc5db230ad66705c4d237308d8c2eb6b4a0ed699c`。
- stdlib仅解析前后文档JSON示例，键数仍15/4/7。这是文档静态核对，**不是parser实现测试或Host资格通过**。本次没有运行实现改变，未重复旧PG/Host/characterization测试分母或把旧PASS移用新源。
- 实现必须增加raw/DTO无绑定及bound未知outer 0.5/1e3兼容、受管域1e0/float/bool拒绝、未知outer变化不改变scope比较/序列化、原输入不变测试；错误码仍仅内部诊断，不能未经授权暴露身份存在性。

只新增本独立报告，不改候选/实现、08/09/10、冻结合同、原始事实或许可证。真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER；这与纯结构阶段准入是不同门禁。
