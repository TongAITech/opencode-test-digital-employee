# WB-A02 非商业授权边界、原创实现与 SBOM 审查
**BLOCKED_LICENSE / ORIGINAL_IMPLEMENTATION_PATH_ONLY / F_AND_LEGAL_REVIEW_PENDING**
naodeng/dsh-qa@fc5a054a48973d004580a3cc1de60da3f701150b 标识 PolyForm-Noncommercial-1.0.0；目前未确认银行商业适用授权。不得把原作者受限 JS/CSS/模板、素材或去标识派生代码复制至银行交付，也不能通过去掉声明规避限制。

1. A 的交付限于行为抽象、领域/接口/测试合同；C/D/E 的正式源码必须独立创作并可经 PR/文件来源审核，不能直接照搬原始实现。
2. 第三方（含 MIT 的 ZSeven-W/dsh-qa）要逐文件核对实际权属和传递依赖许可证、驱动及运行环境。根目录 MIT 不能自动批准全部依赖。
3. 打包前对真实 staging 目录执行 files manifest/SHA256/provenance/notices/安全路径扫描并经独立审核；当前 w0_contract_gate.py 只有设计期门禁，还**没有**接入正式 Windows ZIP 流水线。
4. 清单字段 source_repository、provenance_review_ref 均为自报，不能独立证明原创；必须由 F 和有权限的许可证审核人员复查 Git 历史、相似代码、真实 SBOM/NOTICE 和分发权。
5. 无适用许可时，关闭门槛是原版受限源码零打包、原创可审计、第三方许可齐备、F/法务放行。未放行保持 BLOCKED_LICENSE，不得根据 W0 单测成功改变状态。
6. 获得授权后才依据书面 grant_ref、用途、版本、主体、期限、分发范围进行单独合法性确认。
