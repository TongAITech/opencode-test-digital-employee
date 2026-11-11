# E：紧凑Mission绑定纯模块证据

基线W0 199a316334abb41c77890ed5608b989e2a7e6126；设计精确源3266cb2d814c8f2233733ba4b53642940a7892a0。B206/612116f1、D207/e48f5800及F208/67c358f84ee036b79738f1c64dd48aed69d43b67对该新源的纯模块范围已准入；旧b61审阅不抵消B205兼容缺陷，全部历史保留。首次按错误文件名读取F报告失败，随后通过PR files定位正确qa路径并完整读取，确认报告已发布才建独立worktree e-mission-binding-codec施工。

新增stdlib独立mission_scope_binding_codec：parse_scope只检查DTO受管scope域；parse_mission_json全局拒重复键/非finite（含指数溢出）/非法UTF8，保留未知outer有限0.5/1e3，输出深不可变detached envelope与scope；serialize_scope只产新作用域片段，legacy严格{}；require_unchanged比较外层mission/release与全部不可变binding，不是CAS或授权。严格15/4/7、date/三revision/digest与K/mapping/镜像一致；null/partial/flat-only/冲突稳定拒绝，不补镜像、不降legacy。永久op仅结构标识，不证明事件发生。

实际本地运行：新模块9/9（0.157s）、已有Scope codec11/11（0.157s），覆盖每字段缺省/未知/错型/nonhashable、raw每对象重复键、float/exponent/bool/64位/date/digest/Unicode、嵌套unknown outer兼容、序列化脱离输入/深不可变、每个binding叶子改变拒绝、legacy身份改变拒绝、公开tuple伪造仍重校验、成功/失败输入不变、禁open/socket调用和两个新进程稳定性。git diff --check通过。新模块没有接入models/overlay/control/reader/writer/PG/Host，没有正式事实操作。

新增定向Python3.8/3.11 CI，checkout显式ref=${{ github.event.pull_request.head.sha || github.sha }}；无DB、业务网络或离线包。一次代码+测试+证据提交后冻结完整SHA，远端实际CI结果交A记PR body/主台账，不追加证据HEAD。纯组件测试不是来源verified、正式绑定完成或现场通过；正式model/factory/writer/008仍须独立门禁，真实Host/Windows仍FIELD_NEEDS_BANK_TRANSFER。请求F对完整实现SHA独立验收。
