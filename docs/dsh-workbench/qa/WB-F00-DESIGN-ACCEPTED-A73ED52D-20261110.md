# WB-F00 当前设计独立接受

状态：**WB-F00_DESIGN_ACCEPTED**。
精确被审源：`a73ed52d88425d5e60cbe07467a0ab5cbed5f708`。
日期：2026-11-10。签署角色：本轮独立 F Agent；未参与被测合同、D01实现或B/D/E签署编写。本签署是新的独立设计裁决，不搬运旧F接受结论。

## 签署与合同完整性

已核验B正式签署371f43f0、D正式签署9e4f6c98、E正式签署278a5a58均在被审HEAD祖先中，且各文件分别明确接受14534d611966b1692b682011d636bef3aed3f747的PostgreSQL增量职责范围；不再使用单一Agent的BDE综合视角替代三个责任方签署。D实现a1ed947b亦在当前祖先中。

对14534d61与当前HEAD运行git diff --exit-code，00–07、A03、locale机器范围与门禁DAG完全无差异。三个职责签署所覆盖的合同字节未改变；自上轮完整技术设计审查以来仅新增四份签署/证据文件及D01小范围实现、测试。因此上轮WB-F-SIGNOFF-01签署证据P1关闭，当前未发现剩余W0设计P0/P1。

确认六页十区、50项业务目标、zh-CN默认/en-US正式范围、12个语言负例不被裁剪；需求/版本/SST来源及复合关联正确；PostgreSQL业务权威与R1正式运行事实边界、事务/权限/审计/迁移/回滚、外置证据哈希、跨存储幂等恢复、SSE水位及发布依赖闭包均接受为可实施设计。BUSINESS_TZ/来源缺失保持MIGRATION_HOLD；真实数据库和Host验收归W1+，不反向阻断W0。

## 本轮独立执行证据

执行环境：Python3.9.6、Node25.2.1，本地隔离worktree固定被审HEAD。

- `python3 -m unittest discover -s tests -p 'test_dsh_workbench*.py'`：263/263 PASS。
- 三套Node W0 Scope/source-fence/feature-reconciliation测试：30/30 PASS。
- a01_locale_scope.py：PASS；ci_admission.py：PASS（13 workflows）。
- F #112精确e9982c620e6d56b674425d5dc2aeb7c7cd9eb71c的scope-first测试在/tmp隔离加载：9/9 PASS；该overlay不是原A提交自带测试。
- `python3 -m unittest discover -s tests -p 'test_dsh_workbench_host*_d.py' -v`：33/33 PASS，包含真实临时loopback transport测试。
- GitHub当前精确a73ed52d check-runs读取：w0-contracts SUCCESS，14 SKIPPED；跳过项没有计入PASS。

D01独立源码审查：新逻辑只比较规范包身份与声明版本，不从manifest推断面板运行兼容性；版本匹配仍RUNTIME_UNVERIFIED，field_verified/bank_final始终false。401/403/404明确分类，失败即停不继续session明细；新恢复测试覆盖缺失/损坏/修复与版本冲突。接受此增量为COMPONENT_TESTED；并未接受D01 IMPLEMENTATION_QA_PASS或银行DSH现场兼容性。

## 准入与限制

F正式接受本精确HEAD的W0设计，允许A依照A01/A03签署及同源CI记录W0_DESIGN_FROZEN并按DAG调度W1 ready工单。F不直接修改08/09/10，不替A执行冻结记账。后续仅追加签署/账本可由A核验合同字节一致；任何合同或实现变化都需新的精确源测试/对应独立验收，不可搬运本源测试数字。

本结论不是产品QA_PASS：50项产品、真正PostgreSQL/API/DSH1.18.26/Windows/离线安装/资源租约/实际并发/现场恢复、F01–F04均未由本轮验收。A02_BLOCKED_LICENSE、NO_RC72_MAINLINE_MERGE、NO_BANK_ZIP保持；最终发布需完整实现、独立QA及许可证和现场门禁。
