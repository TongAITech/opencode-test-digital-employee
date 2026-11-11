# A 本轮精确集成回归

测试源：d31d8ef70229942215060bd58ef3b593b1b95be1；角色A（不是独立F）。工作区测试前干净。RC7.2远端edaf9290594ecaf66c482470da64ae706ff8c7aa；PR84保持Draft。

| 验证 | 实际结果 |
|---|---|
| Psycopg3.2.13 / PostgreSQL17.6隔离Unix socket，test_dsh_workbench_b*postgres.py | 222/222，74.790秒 |
| Playwright真实浏览器tests/browser/test*.py，真实PG | 6/6，25.091秒 |
| 原F目录反例tests/browser/f_directory*.py由A复跑 | 3/3，12.694秒；不新增F批准 |
| Node c01、c02_scope、draft_forms、directory_client | 43/43 |
| Python test_dsh_workbench*.py 无PG测试环境 | 561发现，269执行通过，292明确跳过；不能称561实际通过 |
| 远端W0同源 | [42859333314](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42859333314) SUCCESS |
| 远端真实浏览器同源 | [42859326708](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42859326708) SUCCESS |

已集成独立F777b8bd7接受目录修复的源为16fe658d。A本轮不把这份F签署移到新的联合HEAD；组件签署来源保留。

历史完整R4联合源7586a80c的ABCD-v4 [42847197247](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42847197247)五job全成功；F8afcdba9独立联合报告已集成。它不证明当前新增界面、行内Windows离线或真实Host通过。

独立候选：PR180源47950777，A真实socket4/4及真实PG提交后断连恢复1/1；F尚不可用，不合入。PR181源957874d6为正式Mission绑定协议V2，B/D/E/F复签未完成，无R1实现改动。

未实现队列：c-calendar在16fe658d干净、没有年月日视图代码，原子任务额度中断不记完成；正式绑定V2由A补齐候选而非E签署。E03正式控制API、生产Scope绑定、正式R1资产映射及完整业务页面仍阻断产品全验。真实Host/Windows按用户说明FIELD_NEEDS_BANK_TRANSFER。RELEASE_NOT_APPROVED，没有生成最终ZIP。
