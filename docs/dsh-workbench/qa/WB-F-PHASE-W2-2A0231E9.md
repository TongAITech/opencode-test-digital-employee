# F 六种草稿分区本轮独立复验

精确被审源：`2a0231e9811e364f07bea771fc2a7ca7f57ec6cb`，PR #169。独立新 worktree `f-phase-w2`，未参与产品实现，未修改08/09/10。仅本地隔离PostgreSQL、nonowner运行角色、loopback HTTP和Chromium；没有真实Host、银行网络或生产R1。

## 复验结果

- `python3 -m unittest discover -s tests/browser -p 'test*.py'`：5/5 PASS，使用真实PG连接与本机Playwright。
- C01、C02及draft_forms三套Node：33/33 PASS。
- 从此前独立F提交 `12baa6a0806cdef0d08de74d78547049e3a6160b` 原样保留并重跑嵌套正式状态负例：1/1 PASS；case.steps嵌套nodegate对象被真实HTTP400拒绝，asset_root仍0，恢复合法输入后完整六kind生命周期通过。这是复跑旧F反例，不冒称新发现的攻击。

数据库Oracle核对6个root/24个不可变revision，各类型create/edit/retire/restore保持同asset_id且均UNRESOLVED。空步骤拒绝零写；两语切换不改变身份。case提交实际成功后丢响应，切报告清空旧私密表单及列表，原pending禁止新写；Bob携带Alice旧context被409拒绝且root仍7，Alice同key核对后仍7，无重复。R1字节不变，正文不产生正式Case/Obligation/Defect/Report结果。

## 既有独立报告核对

- 目录报告 `83f103663822fbf0fa3032b433106feedafa75f1` 明确绑定源 `03779776aba95a720380c10310a3a6a32700b713`，本地16+2例，未将A提供CI冒充F远端核验。
- 遗留隔离报告 `d7a8beb453f598e02768e5dfbde59bc736decfdd` 明确绑定源 `ee33d642fc30b7b7925fbf87d971670abf2e5f78`，本地5+1例；工作台模式默认拒绝旧私有API、独立legacy兼容与安全CLI不建R1的边界明确。
- 原六kind报告 `12baa6a0` 绑定相同最新2a0231e9，本轮重新执行其核心证据，不依赖旧执行数字直接签署。

## 裁决与限制

`SIX_DRAFT_FORMS_COMPONENT_RECHECK_ACCEPTED`。本组件范围内未发现剩余P0/P1。旧目录及遗留隔离报告可由A按各自完整源继续集成；它们的测试数字不转移成本轮联合HEAD结果。

RC7.2新上游 `edaf9290594ecaf66c482470da64ae706ff8c7aa` 尚不在本次精确源内。A前向集成后必须提供新联合HEAD，另做兼容回归；本报告不预签其结果。真实Host/SSO、同principal会话epoch、完整C04/F01/F02与现场资格未通过，FIELD_NEEDS_BANK_TRANSFER。未调用正式执行器、未写正式R1，不授予发布或最终包资格。
