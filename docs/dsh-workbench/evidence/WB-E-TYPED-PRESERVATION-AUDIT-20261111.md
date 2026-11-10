# typed保留只读调查证据

基线W0 b6d93e41，新独立worktree e-typed-preservation；未修改PR195冻结源a9758687。本次仅新增候选与本证据。

实际执行全仓/RC7调用点搜索、读取models/to_payload/truth_overlay/control/bank_mission/dispatch/factory/CLI/reader/session与相关冻结合同条款。另确认真实节点dispatch是第二条bootstrap Mission入口（rc72_mission_node_dispatch.py:362），不能只改bank_mission。native factory compose零R1，不是Mission创建事实；CLI真实run先保留Field/Q7 admission。

显式运行 `python3 -m unittest discover -s tests -p audit_scope_binding_characterization.py -v`：3/3、0.037s **缺口复现**。真实调用正式start_or_resume在TemporaryDirectory日志建立/恢复Mission仍无project/batch；手工flat extra经refresh丢失；constructor不接受这些字段。没有访问/改写任何生产R1；没有把测试fixture当正式来源。此命令不计产品修复PASS。

`git diff --check`实际通过。首次写本证据因新基线尚无evidence目录失败，随后创建独立目录后完成；该写入失败不是检查通过。真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER；typed字段方案、wire与事件自引用、writer边界待精确评审，正式实现没有准入。

## 紧凑wire细化（本轮仍只设计）

按A架构建议将§4替换为15键紧凑绑定合同：完整快照留PG，仅保留不可变引用/摘要/date及三revision、完整K/request_digest、显式mapping、业务/运行身份及预分配creation_operation_ref。给出每字段类型、严格镜像/映射/K相等、legacy缺省省略及null/partial/flat-only/冲突错误矩阵。永久operation_ref与网络尝试/Host fence分离，同K不重分配；PREPARE先查K、并发冲突取原分配；完整request digest具体wire仍待签，必须覆盖永久ref或其经审定确定性关联。正式reader先查受控creation事实再明细，纯parser不查权威。

结构JSON示例已用stdlib解析并核对15/4/7键数与身份相等，diff检查通过。首次示例校验脚本误写16个绑定键导致断言失败；按实际明确列出的15键纠正检查后通过，未将该脚本错误计为产品失败/通过。未运行产品功能测试（只有文档变化）；未实现模型/008/正式读取/写入或更改冻结原文。新完整SHA交B/D/F精确审核后再准入纯parser实现。
