# F 独立验收｜Mission Scope 保真阶段一 4075e25c

- 被测候选为 PR #259 的 `4075e25c88451a8278ec55e42cfe97c7f888224f`，在独立工作树复验。
- 结论为 **REJECT，P1**。本报告只适用于该候选。
- 工作流原测试命令本地 237 passed（8.69s）。[CI 42977611357](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42977611357) 的 checkout ref 和运行时 Git HEAD 均为上述 SHA，Python 3.8.18 为 237 passed（7.31s），Python 3.11.18 为 237 passed（7.02s）。下列反例使用工作流测试之外的独立探针。
- F 独立重跑 #262 在 3514f749 记录的三个 hook 变体。4075e25c 对三个旧变体均提前 HOLD，回调计数为零。

## P1｜实例字典能隐藏已绑定的 Scope

`mission_scope_preservation.py` 的 `_copy_declared_fields` 调用实例字典的 `copy()`。确切 Mission 类型的实例仍可带字典子类。该子类的回调执行一次，返回移除 `_scope_state` 的普通字典，克隆成功返回无绑定 Mission。原 Mission 的 Scope 仍可序列化。

`models.py` 的 `_mission_scope_state` 调用实例字典的 `get()`。合法绑定 Mission 保留原始 Scope 状态时，字典子类仍可向序列化和写入路径报告该字段缺失。独立临时 R1 探针中，`to_payload` 与 `append_entity` 完成，共触发三次回调，写前和写后字节不同。用新的 TruthRuntime 冷读，正式 Mission 行缺少 `scope_binding` 和 `_scope_state`，而原 Mission 的实例字典仍含 `_scope_state`。预期是提前 HOLD、零回调、R1 字节不变。

普通内建字典也需要检查键。独立探针放入一个与 `_scope_state` 哈希相同的非字符串键，序列化返回 `MISSION_SCOPE_NOT_ADMITTED`，但在 HOLD 前执行了一次该键的 `__eq__`。复验要求包括在任何实例字典查询、复制和实例级静态属性查找前，安全校验字典类型与键类型。

从上述 SHA 的仓库根目录运行以下独立探针。R1 只在探针私有的临时目录中写入。

```python
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
sys.path[:0] = ['.', 'tests']
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Mission, to_payload
from rc7_runtime.mission_scope_preservation import clone_mission, isolate_mission_scope, serialize_mission_scope
from rc7_runtime.truth_overlay import append_entity
from test_dsh_workbench_mission_scope_binding_codec import bound

def m():
    return Mission('M1','RT1','goal')
calls = []
class CopyTrap(dict):
    def copy(self):
        calls.append('copy')
        return {k:v for k,v in dict.items(self) if k != '_scope_state'}
class GetTrap(dict):
    def get(self, name, default=None):
        if name == '_scope_state':
            calls.append('get')
            return default
        return dict.get(self, name, default)
value = isolate_mission_scope(m(), bound())
value.__dict__ = CopyTrap(value.__dict__)
out = clone_mission(value)
assert calls == ['copy']
assert serialize_mission_scope(value) and serialize_mission_scope(out) == {}
print('copy subclass hook=1; original_scope=true clone_scope=false')
value = isolate_mission_scope(m(), bound())
value.__dict__ = GetTrap(value.__dict__)
with TemporaryDirectory() as d:
    t = TruthRuntime(Path(d) / 'r1')
    before = t.store.path.read_bytes()
    payload = to_payload(value)
    assert 'scope_binding' not in payload and '_scope_state' not in payload
    append_entity(t, value, release_id='RT1')
    row = TruthRuntime(t.store.path).query('rc7_mission', mission_id='M1')[0]
    assert '_scope_state' in value.__dict__
    assert 'scope_binding' not in row and '_scope_state' not in row
    assert t.store.path.read_bytes() != before
    assert calls.count('get') >= 1
    print('get subclass hooks=',calls.count('get'),'original_scope=true persisted_scope=false raw_changed=true')

calls.clear()
class AliasKey:
    def __hash__(self):
        return hash('_scope_state')
    def __eq__(self, other):
        calls.append(('equal', other))
        return other == '_scope_state'
value = m()
value.__dict__[AliasKey()] = None
try:
    to_payload(value)
except ValueError as exc:
    print('exact dict alien key result:',str(exc), 'calls=',calls)
else:
    print('exact dict alien key result: PASS', 'calls=',calls)
assert calls
```

本报告只给出阶段一候选拒绝。正式 Mission writer 与 admission、PG008、DSH 原生宿主及发布门禁均无本轮验收结论。
