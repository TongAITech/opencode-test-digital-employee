# F 独立验收 Mission Scope 第一阶段 3514f749

F 拒绝 [PR259](https://github.com/TongAITech/opencode-test-digital-employee/pull/259) 精确源 `3514f7493b54d541a071ab411a6a2703a1858c81`。**P1，显式保真复制执行输入控制的 Python copy hook，可返回无 Scope 或身份冲突的对象。** 审查依据是 E245 精确 `5be49d089cdf8e320c29276418e3069fe9c0e796`、D247/D248、F249、B251 和 E 本次实现证据。只在独立工作区和临时本机 R1 运行。

## 实际通过的范围

- 对基线 `2de01bc49ae229e1dda9f04107d0680a92d50bff` 重现两条历史路径。动态附加的 `scope_binding=None` 被通用序列化丢弃，直接 append 改变账本。对同一 canonical M1 的 v2 原行注入 `batch_id:null`，以可变 ID `' M1 '` 和另一 release append v3，冷投影的唯一目标被覆盖且 Scope 丢失。
- 在精确 3514 上用相同 R1 场景，两个入口先返回 HOLD。asdict、durable acceptance、append 的 tripwire 未触发，拒绝前后文件字节和投影保持。冷回放保留旧 `batch_id:null`。清洁派生 dataclass 仍序列化额外字段，异常 Scope descriptor 被拒绝且无 getter 调用。普通 clone 和 deepcopy 保留 709 字节紧凑绑定，SHA256 为 `204e86f036cc5c8ba3e67e5c45799a6fcf77d04625c5dbd00491618fc2f18c90`。默认 replace 仍重置 init=False 状态，属于合同已限定的入口。带空格的绑定 Mission 或 release ID 均拒绝。
- 本地按工作流分母运行 **223/223，9.36 秒，零跳过**。包含新增 29、紧凑 codec 9、受影响旧用例 185。[CI 42973653072](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42973653072) 核对实际 checkout 和 Verify source 均为精确 3514。Python 3.8.18 实际 223/223（5.01 秒），Python 3.11.18 实际 223/223（6.65 秒）。
- 新共享叶源与基线 codec 文件逐字节一致。独立 `-I -S` 进程验证旧入口重新导出的函数与共享叶是同一对象，未加载 RC6/RC7 runtime。用实际 `SOURCE_DIRS` 和 `_copy_tree` 复制源码后，独立进程能导入保真 helper、复制旧 Mission 并序列化，未加载 Workbench 工具。此测试针对新叶包与运行域导入，管理服务器的归档启动修复由 PR257 另审。

## 独立新增失败

`clone_mission` 先校验原对象，再直接调用 `deepcopy(mission)`。其返回值在 clone 出口未经复验。隔离解码同样调用 clone，随后把原输入校验过的绑定写到 copy 返回对象上。实测以下三种路径都执行了输入控制的回调。

| 输入 | 实际结果 |
|---|---|
| 给已隔离绑定的精确 Mission 加实例 `__deepcopy__`，回调返回普通无绑定 Mission | 回调执行一次。原对象仍有 Scope，返回对象无 Scope。 |
| 给隔离解码的无绑定精确 Mission 加实例 `__deepcopy__`，回调返回 `Mission('OTHER','OTHER-RT',...)` | 回调执行一次。隔离解码返回的对象为 OTHER，绑定仍写入 M1。稍后调用隔离 serializer 才因身份冲突拒绝。 |
| 在隔离解码的 `artifact_refs` 中放入具有 `__deepcopy__` 的 str 子类 | 回调执行一次，原引用仍为 reference，返回对象的引用被改成 changed。 |

下面的片段可在候选根目录运行。Python 先把 tests 加入搜索路径以复用紧凑 fixture。输出与独立脚本实测一致。

```python
import sys
sys.path.insert(0, 'tests')
from rc7_runtime.models import Mission
from rc7_runtime.mission_scope_preservation import (
    clone_mission, isolate_mission_scope, serialize_mission_scope,
)
from test_dsh_workbench_mission_scope_binding_codec import bound

def legacy():
    return Mission('M1', 'RT1', 'goal')

calls = []
def lose_scope(memo):
    calls.append('clone')
    return legacy()

m = isolate_mission_scope(legacy(), bound())
m.__deepcopy__ = lose_scope
c = clone_mission(m)
assert calls == ['clone']
assert serialize_mission_scope(m) and serialize_mission_scope(c) == {}

m = legacy()
def replace_identity(memo):
    calls.append('isolate')
    return Mission('OTHER', 'OTHER-RT', 'substitute')
m.__deepcopy__ = replace_identity
c = isolate_mission_scope(m, bound())
assert calls[-1] == 'isolate'
assert c.mission_id == 'OTHER' and c._scope_state.mission_id == 'M1'

class Ref(str):
    def __deepcopy__(self, memo):
        calls.append('nested')
        return 'changed'

m = legacy()
m.artifact_refs = [Ref('reference')]
c = isolate_mission_scope(m, bound())
assert calls[-1] == 'nested'
assert m.artifact_refs == ['reference'] and c.artifact_refs == ['changed']
```

修订验收须在调用任何输入可控的 copy/reduction hook 前完成拒绝或受控复制，核原对象及返回对象类型、身份、Scope 和普通字段。三个新增负例未调用生产 writer，未观测到本次真实 R1 写入。当前生产绑定继续 HOLD，正式 writer 闭包、admission、PG 008 和行内 Host 仍各自等待验收。此提交只保留独立报告。
