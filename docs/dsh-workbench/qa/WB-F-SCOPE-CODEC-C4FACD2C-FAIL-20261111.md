# F：纯Scope codec旧源结构错误边界失败

PR：[195](https://github.com/TongAITech/opencode-test-digital-employee/pull/195)。被测完整源：`c4facd2cc754bfef42a414dac56b2d1390c50914`。独立worktree`f-scope-codec-exact`固定该源，没有修改被测实现/测试、08/09/10或正式事实。本提交仅保留F失败报告。

结论：**COMPONENT_NOT_ACCEPTED_AT_C4FACD2C / P1_CODEC_ERROR_BOUNDARY**。该PR后续若修订必须对新完整SHA另验；不能把本轮既有9项通过转签为修复通过。

## 已独立复现的P1

`canonical_scope_bytes`在校验非null `sst_id`的文本类型之前，先将其放入 `(requirement_id,system_id,version_id,sst_id)`并执行`key in seen`/`seen.add(key)`。JSON中合法但schema错误的`sst_id:[]`或`sst_id:{}`触发Python原生`TypeError: unhashable type: 'list'/'dict'`，不是约定`ScopeStructureError('INVALID_SCOPE_STRUCTURE')`。`parse_snapshot_json`同样将此TypeError原样抛出。

这是纯组件错误类型/稳定拒绝合同的实际缺口，不是已验证的权限绕过或生产R1数据损坏：没有无效输入被接受，没有数据库、Host或R1写副作用。修复应先完成类型验证再使用哈希集合，保留严格schema与稳定错误边界；F不修被测功能。

最小复现（仓库根目录）：

```sh
PYTHONPATH=tests python3 - <<'PY'
import json
from test_dsh_workbench_scope_snapshot_codec import snapshot
from tools.dsh_workbench.scope_snapshot_codec import canonical_scope_bytes,parse_snapshot_json
for bad in ([],{}):
    value=snapshot();value['edges'][0]['sst_id']=bad
    for name,call in [('DTO',lambda:canonical_scope_bytes(value)),('JSON',lambda:parse_snapshot_json(json.dumps(value)))]:
        try:call();print('UNEXPECTED_ACCEPT')
        except Exception as error:print(type(bad).__name__,name,type(error).__name__,str(error))
PY
```

实际输出：list DTO/JSON均TypeError；dict DTO/JSON均TypeError。

## 本轮覆盖分母

- `python3 -m unittest discover -s tests -p test_dsh_workbench_scope_snapshot_codec.py -v`：既有9/9，0.157秒；没有覆盖上述非hashable字段路径，因此不能以此声称全面通过。
- F另将UNSPLIT与SPLIT有效fixture的每个可遍历字段替换为不同类型的[]/{}，分别经DTO与JSON入口：**288次实际尝试，280次约定结构错误，8次原生TypeError**。8次均位于sst_id（两种fixture×两种坏类型×两个入口）；0次无效接受。每次前后输入深度比较相同，未被修改。
- 本次没有执行/声称真实Python3.8、PG、生产绑定、Host或现场通过。此源码只做纯结构处理；后续新源应真实验证支持的Python版本并另出精确结论。

后续新SHA修复不能覆盖本报告的旧失败。正式008、Host fence、writer及typed Mission模型仍不在纯组件验收范围；发布状态NOT_APPROVED。
