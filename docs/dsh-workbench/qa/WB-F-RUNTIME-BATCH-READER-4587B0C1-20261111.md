# F 独立审查正式运行批次 reader 设计

F 接受 [D PR263](https://github.com/TongAITech/opencode-test-digital-employee/pull/263) 精确 `4587b0c1050714553cc6a44fd0c58b919c17d5ac` 的有界 reader 设计。实现需满足下列可执行验收条件。被审提交只有设计文档，当前仍无正式创建事件、对应 reader 或正向准入行为。

## 源码与临时 R1 观察

- 实际 `RC72StateMachine.bootstrap_release_batch` 为一个运行批次建立 canonical Batch 与十个节点。`ReleaseBatch` 模型持有 batch 和 Mission，`CanonicalRC72Repository` 在写入时提供 release。loader 与 factory 的 Host/source/release 检查确认其消费给定运行域，未提供 PG 批次映射。
- 同一批次键经真实 repository 写四个版本。v1/v2 同三元组，v2 更新状态。v3 换到另一 Mission 和 release，冷投影仍只有一行。v4 改回原三元组，冷投影一行与原身份相符，完整历史仍显示 v3 漂移。冷回放前后 R1 字节不变。
- 用本机临时 store 追加相同 v1 内容后，实测原始流有两条 v1 记录及不同 event_id，投影历史只保留一个 v1。该观察验证源记录去重风险，拟议的正式 creation 事件目前尚未实现。候选 reader 应按可信同一 ledger 快照的原始事件计数，不能按 payload、摘要、event_id 去重后声称唯一。
- 同一临时流再写合法独立批次 `RUN-BATCH@ALT`。旧 `Projection.history('rc72_release_batch', 'RUN-BATCH')` 实际混入该键，因为内部用 `startswith(id+'@')` 查版本。实现必须按精确 canonical 批次 ID 及原事件来源过滤，验收加入前缀相似键，并要求完整历史身份漂移仍拒绝。
- 另建临时账本。repository 拒绝不存在父批次的义务。现有低层 `append_rc72_entity` 可保存形状合法、`release_batch_id=WRONG` 的义务。冷回放后把真实义务行交给当前 `validate_lineage`，无 ETU 引用时旧校验实际通过，因为义务批次比对位于 ETU 循环内。正式增量必须单独校验每条义务和每条 ETU 的运行批次，包含无 ETU 引用负例。这是旧行为实测，拟议 reader 尚未运行。
- 本地现有 factory、phase2 state machine、E02 lineage 套件共 **65/65**，8.27 秒，零跳过。一个 `TestObligation` dataclass 收集警告。此分母只核当前源码行为。

核心漂移和前缀用例可在候选根目录运行：

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_domain import ReleaseBatch
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_state_machine import RC72StateMachine

with TemporaryDirectory() as directory:
    path = Path(directory) / 'r1.jsonl'
    truth = TruthRuntime(path)
    kind, batch = 'rc72_release_batch', 'RUN-BATCH'
    original = ReleaseBatch(batch, 'M', 'batch', created_at=1, updated_at=1)
    RC72StateMachine(truth, release_id='RUN-RELEASE').bootstrap_release_batch(original)
    assert len(truth.query('rc72_mission_node', mission_id='M')) == 10
    v1 = truth.query(kind, release_batch_id=batch)[0]
    CanonicalRC72Repository(truth, release_id='OTHER').persist(
        ReleaseBatch(batch, 'OTHER-M', 'drift'), artifact_version=2)
    assert TruthRuntime(path).query(kind, release_batch_id=batch)[0]['release_id'] == 'OTHER'
    owner = CanonicalRC72Repository(truth, release_id='RUN-RELEASE')
    owner.persist(original, artifact_version=3)
    truth.store.append('RC72_RELEASE_BATCH_UPSERTED', v1)
    owner.persist(ReleaseBatch(batch + '@ALT', 'ALT-M', 'independent'))
    original_bytes = path.read_bytes()
    cold = TruthRuntime(path)
    current = cold.query(kind, release_batch_id=batch)
    assert len(current) == 1 and current[0]['mission_id'] == 'M'
    history = cold.projection.history(kind, batch)
    assert any(row['release_batch_id'] == batch and row['release_id'] == 'OTHER'
               for row in history)
    assert any(row['release_batch_id'] == batch + '@ALT' for row in history)
    copies = [row for row in cold.store.iter_raw()
              if row['event_type'] == 'RC72_RELEASE_BATCH_UPSERTED'
              and row['payload']['release_batch_id'] == batch
              and row['entity_version'] == 1]
    assert len(copies) == 2 and copies[0]['event_id'] != copies[1]['event_id']
    assert path.read_bytes() == original_bytes
```

## 接受的合同与实现验收边界

- 三个 ID 分属业务批次、运行 release 和运行 ReleaseBatch。独立九字段 V1 描述与紧凑 15/4/7 绑定放在同一唯一正式 creation 事件中，逐字段核公共身份并纳入完整请求摘要。旧 15/4/7 保持原形。无映射、旧平面、未知版本及重复或冲突源均 HOLD。原 K 恢复复用预留身份和永久 operation，lookup 不产生事实。
- authority 内唯一性依赖 V3 第六节每个 ledger 的可信固定 authority。现有 canonical Batch 行及全局投影键未编码 authority。reader 须从可信配置或正式策略核 ledger 与请求、creation、mapping 的 authority 相等，然后检查完整历史及冲突。验收应试同一物理 ledger 上不同 authority 自报同一三元组，来源不明时 HOLD。若后续选择同一 ledger 存多个 authority，需另审命名空间、索引和旧回放合同。
- 当前 E02 先调 E01 quality，后者会读详情与 Evidence 文件。正式 reader 需在同一固定 R1 字节快照完成当前授权、唯一原始 creation、历史 PG snapshot、映射与 canonical Batch 历史预检后，才能调用详情。拒绝 Oracle 分层：授权、来源、三元组等预检失败须零详情及零证据文件访问。详情内的谱系矛盾只能在读到必要记录后发现，须阻断进一步证据访问与响应，不返回部分图。验收须直接监视旧 quality 入口以及其底层明细查询，防止只挪动外层函数名。
- 正式创建已确认而 canonical Batch 尚未初始化时，只有经原主体权限核验的原回执 lookup 仍可成功，图与执行为 `INITIALIZATION_HOLD`。不能把冲突、损坏、过期授权或其他 authority 的事件当作单纯缺行。重授权读取和原操作恢复各验其门禁，禁止把 lookup 升格为 submit。当前发布仍 HOLD。

本次仅审设计和现有行为。正式创建来源、事件与索引实现、008、单 writer、HostFence 及银行现场分别验收。旧 PR259 精确 3514 的复制失败与拒绝报告保持。
