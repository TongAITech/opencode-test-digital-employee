# F：紧凑binding外层数值兼容精确窄复核

被审PR：[198](https://github.com/TongAITech/opencode-test-digital-employee/pull/198)。新完整合同源：`3266cb2d814c8f2233733ba4b53642940a7892a0`；父源`b61cda8e1b57d89331062abfd8ed9c196a5d8d15`。独立worktree`f-typed-numeric-exact`固定新SHA；只追加F报告，未修改候选/实现、08/09/10、正式model/reader或R1。

结论：**COMPACT_BINDING_PURE_MODULE_NUMERIC_DESIGN_ACCEPTED_EXACT_3266CB2D**。B [#205](https://github.com/TongAITech/opencode-test-digital-employee/pull/205)指出的“全局浮点/指数拒绝会误伤未知outer”设计P1在新文本中已消除；未发现阻断独立纯parser/serializer/不可变比较阶段的新P0/P1。仍须B/D/E同一新SHA职责签署和A记录，不开放正式model/overlay/control/reader/writer接入。

## 历史结论不转签

F [#204](https://github.com/TongAITech/opencode-test-digital-employee/pull/204)保留其对b61字段DTO/serializer/不可变域的结构判断；但该报告没有充分区分raw JSON与未知outer数值域，**不能用旧报告授予旧b61完整raw入口准入或抵消B #205的真实兼容P1**。本次以B反例和3266cb2d实际修订重新核查，不修改或隐去旧结论。新raw设计的接受只指向3266cb2d；还没有新parser实现PASS。

## 差异核对

§4.1将严格数字规则限定于scope_binding/K/mapping及定义的scope镜像/身份；未知outer有限float/exponent留给原模型。§4.3禁止全局parse_float=reject，plain DTO不校验/重编码未知outer，raw解析后遵守相同域边界；给出无绑定0.5/1e3、bound外层0.5/1e3不影响Scope、Scope date_revision/mapping schema的1e0/true拒绝向量。§4.4比较只作用于受管scope域，不把未知outer数字纳入scope摘要/比较。

新raw helper在所有层拒绝重复键/NaN/Infinity只是它的新严格JSON策略，不改现有正式reader/replay；plain DTO未知outer语义仍归原模型。未知outer指数的原始词法是否保留不是scope模块承诺：它不能重写整个Mission，也不能通过全局canonical重编码或serializer丢掉该字段。受管schema/revision仍需严格type=int且非bool；不能因1.0==1或True==1而放行。

15键binding、K4/mapping7、镜像冲突拒绝、legacy wire省略、operation_ref非事件证明、PG完整快照/正式creation/Host权限分别核验及无I/O纯范围未被此次修订改变。

## F独立实证（不是新实现测试）

调用当前正式`truth_overlay.validate_rc7_mission`，以`to_payload(Mission(...))`建立原本合法的运行字段，再从实际JSON分别解出diagnostic_score的`0.5`/`1e3`。unbound及增加文档完整bound-extra四个组合均被当前validator保留为有限float（0.5/1000.0），原传入DTO深度相等；bound-extra的受管binding和镜像没有变化，unbound没有被添加任何binding/flat字段。此实验确认旧行为与B反例，不证明旧validator验证了新typed来源。

F另独立解析新稿JSON示例，核15/4/7键数、原完整身份/Scope片段保持；JSON的1e0解为float、true解为bool，均不是严格integer。这些是设计向量和Python类型事实，**未执行尚不存在的新parse/serialize函数**，不计产品功能PASS。相对父源仅两份文档变动，未运行或声称正式生产PG→factory→R1链/Host/Windows通过。

可重复现有行为的内存探针：

```python
import copy,json,math,pathlib,re
from rc7_runtime.models import Mission,to_payload
from rc7_runtime.truth_overlay import validate_rc7_mission
text=pathlib.Path('docs/dsh-workbench/WB-E-TYPED-MISSION-PRESERVATION-CANDIDATE.md').read_text()
example=json.loads(re.search(r'```json\n(.*?)\n```',text,re.S).group(1))
assert len(example['scope_binding'])==15
assert len(example['scope_binding']['creation_key_scope'])==4
assert len(example['scope_binding']['mapping'])==7
for token,expected in [('0.5',0.5),('1e3',1000.0)]:
    for bound in [False,True]:
        value=to_payload(Mission(mission_id='M1',release_id='R1',goal='F legacy compatibility probe'))
        if bound:value.update(copy.deepcopy(example))
        raw=json.dumps(value,separators=(',',':'))[:-1]+',"diagnostic_score":'+token+'}'
        dto=json.loads(raw);original=copy.deepcopy(dto);out=validate_rc7_mission(dto)
        assert out['diagnostic_score']==expected and math.isfinite(out['diagnostic_score'])
        assert dto==original
        if bound:
            assert out['scope_binding']==example['scope_binding']
            assert {k:out[k] for k in ['scope_binding','project_id','batch_id']}=={k:example[k] for k in ['scope_binding','project_id','batch_id']}
        else:assert not {'scope_binding','project_id','batch_id'}&set(out)
for token in ['1e0','true']:
    assert type(json.loads('{"date_revision":'+token+'}')['date_revision']) is not int
```

## 新实现仍必须独立验收

raw/DTO分别覆盖unknown outer有限数值（包括嵌套未知运行字段）、绑定域数字/bool/非hashable错误分类、原输入不变、raw返回未知outer数值仍存在、legacy serializer严格{}、bound serializer不包含diagnostic_score且结果与未添加该字段相同。raw非有限数值策略还应覆盖指数溢出形成非finite；它不授权plain DTO或旧reader政策改变。

原#204的其他实施门禁继续：所有受管不可变字段和legacy外层mission/release不能变；缺镜像/flat-only/null不被修补；DTO结构不替代PG来源/正式creation/Host证明。新模块不接正式model/overlay/control/reader，不读文件/DB/网络；实际受支持Python和最新完整实现SHA另验。真实DSH/Windows仍FIELD_NEEDS_BANK_TRANSFER，最终发布NOT_APPROVED。
