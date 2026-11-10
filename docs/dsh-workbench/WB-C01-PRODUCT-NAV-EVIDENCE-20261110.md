# C01 正式导航首个实现增量

基线 b6a61e4c；独立原创实现，不引用受限源码。正式入口为现有 product_server 的 /workbench/，与 tools/dsh_workbench/ui_w0_prototype 独立。五个主导航加项目详情入口，详情保留十区；默认中文，完整英文导航、设置、错误/未就绪文案。支持light/dark/system，原生button/select键盘可达。

本增量只建立导航骨架。统一Scope位置保留投产日期→需求→系统版本→SST；B06及Host未接入，明确未就绪且不显示虚构记录。重新检查保留未就绪，未发业务写入/未计算Gate。没有完成C02或50项产品功能。

测试：node --test tests/test_dsh_workbench_c01.mjs，3/3通过；python3 -m unittest discover -s tests -p test_dsh_workbench_c01_browser.py -v，真实Chromium+真实product_server socket 1/1通过，遍历五导航/项目入口/十区、中英文切换、Gate分区保留、主题重载恢复、坏JSON设置冷恢复、未就绪重查及浏览器无错误。无截图替代业务Oracle，真实B06/DSH/Windows/F02均NOT_RUN。

未改08/09/10或R1。独立F须对新提交验收；C01此增量COMPONENT_TESTED，完整实现门禁仍待实际原生宿主和集成验证。

## F独立红灯后的真实整改

F在98292caf真Chromium复现P1：/workbench无尾斜杠时相对模块路径错而导航空白；P2：Enter导航重绘后焦点丢到BODY。保留这两个历史缺陷，不把原先浏览器测试通过当作完整覆盖。

修复为正式HTML明确/workbench/资源base，两个入口解析相同模块/CSS；设置更新前捕获当前控件或导航身份，重绘后恢复同一控件焦点。补真浏览器双路径加载、标题非空/5导航，以及Enter→保持chat焦点→Tab到board→Enter保持board和详情gates焦点断言，未删除旧负向与恢复断言。重新执行Node3/3及真实Chromium1/1通过；F须在修复后精确源独立复验。

## 远端W0 CI真实红灯整改

c699965f 的 run42781123558/job129711159296 为264项/1 ERROR：新增浏览器测试被W0无浏览器依赖通配发现，缺playwright导致导入失败。保留历史FAIL。浏览器全部原断言及F反例原样迁至tests/browser/test_c01_product_browser.py，不跳过、不删除；新增独立dsh-wb-c01-product.yml安装固定Playwright1.56.0与Chromium，对PR精确head执行（含Draft）。W0保持纯合同依赖。

本地实际W0 263/263、独立真浏览器1/1与CI admission13项通过；此前263+浏览器=264，同一分母分层运行。新远端SHA仍需查询，不以本地成功替代远端红灯。更新的浏览器命令：python3 -m unittest discover -s tests/browser -p test_c01_product_browser.py -v。
