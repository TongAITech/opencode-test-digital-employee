# B M1纯协议codec实现与证据

状态：CODE_COMPLETE / LOCAL_PURE_TEST_PASS / EXACT_HEAD_CI_AND_F_REQUIRED。实现基线`428de3d0`；组件路径`tools/dsh_workbench/project_metadata_codec.py`。本提交未接HTTP、SQL、权限/profile、R1、模型或08/09/10；不代表M1产品完成或生产metadata可写。

## 冻结协议与实际边界

遵循B a21b82fe命名候选、A9a41b145决定及D/E/F限定设计签署。接口`parse_rename_request(raw_bytes, project_id)`输出仅含不可变str字段的frozen/slotted DTO，派生name_key/canonical_bytes均为不可变bytes。route target不是principal/namespace授权；公共构造也验证规范语法，任何DTO均不是admission许可证。

名称策略project-name/utf8-exact-v1：拒所有C0和DEL；只trim两端ASCII U+0020；1–128 Unicode标量、≤512 UTF8字节；不casefold或Unicode归一化。其他Unicode空白精确保留。128标量最多512字节，因此合法UTF8下name字节上限是明确防御性冗余，不能伪造一个“128标量但513字节”的正负向量。reason保持原样（允许空串、空白和JSON合法控制字符），UTF8≤2048字节，不套用name规则。

body仅bytes、≤16384原始字节，包括JSON空白和转义开销。JSON严格UTF8，拒BOM、重复键（含转义等价键、未知子树重复）、所有JSON数值/NaN/Infinity，因为本请求没有数值字段；revision必须规范正十进制字符串且≤9223372036854775807。未知字段、未知changes、错类型、深度解码失败稳定拒绝。JSON转义单独代理在整个树拒绝，合法配对代理解码成一个补充平面标量可接受；普通字符串name不等于JSON原始字节。错误只返回固定code，不反射请求内容。

request_id限定ASCII `[A-Za-z0-9._:-]` 1–128。canonical UTF8 JSON排序键、紧凑分隔、不ASCII转义，含schema/action/name_policy/route project/request_id/两个原expected revisions/规范name/原reason。ACTION固定`project.metadata.update/v1`，不能由body指定。JSON排列/转义/边缘ASCII名称空格不同但规范payload相同则摘要一致；项目/action/revision/reason/request_id变化分域。请求id仍参与原K，主体由未来受信端口提供而非codec生成。没有当前DB值，因此绝不判断NO_CHANGE、是否重复名称、是否已提交或授权。

## 实际验证

本地Python **3.9.6**：`python3 -m unittest discover -s tests -p test_dsh_workbench_project_metadata_codec.py -v`，最终28 tests / 0.012s / OK。包含固定canonical字符串+SHA256 golden vector；128标量512字节、reason2048字节、body16384字节边界；C0全32个码点及DEL、raw/escaped代理、deep JSON、两个revision、不可变/构造拒绝、跨action/主体无权威字段、重复失败后原重放数据不变。初次测试有两个fixture错误（None被helper默认值替换、20KiB深树先命中body上限），已修为直接调用入口及8KiB深树；不隐藏该测试修正，也不把它说成产品bug。

`git diff --check`通过。专门CI `.github/workflows/dsh-wb-project-metadata-codec.yml`真实运行Python3.8/3.11，并打印精确源码HEAD与runtime；提交时结果未产生，只能在PR body登记后续真实结果，不预写PASS、不因CI改源HEAD。纯stdlib无需PG依赖；本次未运行PG或Windows包，不以纯向量替代数据库Oracle。

## 后续PG/store真实实施前置（本提交没有完成）

1. 009显式依赖001–007且独立于预留008的runner/manifest：当前runner仅连续target1–7。需受审分支执行、checksum/依赖缺失拒绝、up/down/up、非空历史拒绝破坏性down；禁止空008占位。
2. 行政完整namespace成员/排除依据、旧冲突治理、NAMING_ACTIVE与binding key/唯一性约束；未知legacy不自动分域。metadata name、name_key、独立metadata_revision原子维护；原ACL/关系/date不挪用。Scope固定profile因schema/权限变化须另评审，不能放宽现有profile。
3. **A尚未实证锁序**：B候选namespace→project→binding→claim只是待证明建议，不是锁正确性证据。既有request_log等表FK/project行KEY SHARE与rename的FOR UPDATE可能发生反向等待；首个store设计必须选并证明FOR NO KEY UPDATE兼容性（其前提是rename不改被引用唯一身份），或统一跨动作claim/项目锁顺序，不能只给metadata私有锁序忽略原资产/批次请求。
4. 同K跨动作PG两个连接：旧asset/batch动作与rename同时争用同(project,principal,request_id)，至少测双方提交顺序、胜者commit/rollback/timeout、恢复查询；只允许一个action+digest原回执，另一冲突且无业务/history/outbox残留；有界等待/死锁错误全rollback、连接可复用，不许无限挂起或双accepted。另测ACL撤销/域停用与锁交错，原receipt replay优先于新CAS但仍重授权。
5. 实际DML最小权限、RLS、维护约束/append-only历史、授权原主体、NO_CHANGE业务结果持久化、目录digest含metaRev防A→B→A cursor复活、原批次/BRV/R1零影响；JSON解析DTO不能代替这些Oracle。NO_CHANGE必须由DB事务核实际值，本codec无此属性或结论。

下一步是独立精确PG迁移/store候选审查，SQL/Host生产资格与F实现验收未授权转签。此小组件不构建Windows离线包。
