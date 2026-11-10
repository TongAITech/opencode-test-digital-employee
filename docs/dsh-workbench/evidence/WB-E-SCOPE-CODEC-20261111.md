# E：纯 Scope codec 施工证据

基线 W0 abed3b5b；设计源 V3 04ca971676509da9379ed53a29b495d2a32c325c，B 窄复签94ee70bc46c91bcfd753f889113fd5681eac00ef。只新增独立 stdlib 纯组件和测试，不携入候选合同父提交。B/D准入限纯组件，正式模型/工厂/writer/008及真实授权仍未准入。

模块 scope_snapshot_codec 提供严格JSON解析、tag结构验证、规范UTF8字节及Scope SHA256、不可变K元组工厂、无参数/无回调的缺Host能力HOLD结果。结构验证不证明来源是verified、不验证数据库FK或授权，也不定义未冻结的创建请求wire摘要。它没有数据库、文件、网络、运行执行或正式R1入口。

实际运行 `python3 -m unittest discover -s tests -p test_dsh_workbench_scope_snapshot_codec.py -v`：9/9通过，含完整字节黄金向量及固定摘要86048f9023f4d38a02b0a90c748630d78aa3aae33af78895d3e00874ce6e0e99；各对象逐key未知/缺键及重复JSON键、bool/float/指数/64位边界、surrogate/控制字符、SPLIT与UNSPLIT、不同需求共享版本但不同SST、重复边/来源矛盾、过滤完整性、输入不变、禁止open/socket调用下运行和两个新Python进程一致性。`git diff --check`通过；AST按Python3.8语法解析通过，本机未执行Python3.8运行时，不将语法检查冒充该版本运行验收。

请求F对新PR精确HEAD独立验收。pure PASS不等于生产绑定、真实PG、真实Host或Windows通过。真实DSH及Windows继续FIELD_NEEDS_BANK_TRANSFER；默认Host结果HOLD，零正式创建资格。

## 后续实际反例与修复（不覆盖首轮记录）

在首轮源 c4facd2c 上实际执行 `sst_id=[]` 和 `sst_id={}`，两者均抛原始 `TypeError: unhashable type`，不是 ScopeStructureError；首轮9/9未覆盖此反例，不能当它已通过。修复将 nullable SST 的非null text 检查移到任何 tuple/hash/set 使用之前。新增ID、nullable来源、filter元素和K主体的不可哈希/错误类型矩阵及每次失败后的输入不变断言。当前本地10/10通过，diff检查通过。

新增定向workflow dsh-wb-scope-codec：workflow_dispatch及PR paths触发，ubuntu-22.04上的真实Python3.8/3.11，stdlib测试，无DB、业务网络或离线包构建。运行结果待推送后核实；定义工作流不计两版本实际通过。
