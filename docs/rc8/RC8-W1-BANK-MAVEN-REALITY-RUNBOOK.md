# RC8 W1 银行环境 Maven/JUnit 真实链路验证手册

## 目标

本手册只用于 W1 第一条真实执行链验收：

`RC8 Center -> Node -> Maven/JUnit -> JUnit XML Actual -> Artifact -> R1 -> WorkItem Complete`

成功执行本手册之前，不得把 Maven/JUnit 标记为 `REALITY_VERIFIED` 或 `BANK_ENV_VERIFIED`。

CI 中的 synthetic Maven/JUnit fixture 只能证明合同与实现逻辑，不是银行环境真实验证。

## 前置条件

中央端：
- RC8 Center 已启动；
- `/health` 返回 `READY`；
- Center 状态目录和 Artifact 目录可写；
- 不允许 Node 直接连接 Center 数据库。

节点端：
- Windows：Git Bash；
- 信创 Linux：系统 bash；
- Python >= 3.8；
- 实际 Maven 可执行文件；
- 实际 Maven 项目目录，根目录存在 `pom.xml`；
- 显式可用的离线 Maven 仓库；
- 节点能访问 RC8 Center。

## 1. 启动 Center

在 Center 包根目录：

```bash
bash packaging/rc8/rc8-center.sh \
  --host 0.0.0.0 \
  --port 4098 \
  --state-dir runtime/rc8-center
```

检查：

```bash
curl http://<CENTER_IP>:4098/health
```

必须得到 `READY`。仅端口监听不算通过。

## 2. 配置节点环境

Windows Git Bash 示例：

```bash
export RC8_CENTER_URL="http://<CENTER_IP>:4098"
export RC8_NODE_ID="PFC-WIN-NODE-01"
export RC8_NODE_OPERATOR="<测试人员标识>"
export RC8_NODE_STATE_DIR="D:/PFC/RC8/runtime/rc8-node"
export RC8_MVN="D:/tools/apache-maven/bin/mvn.cmd"
export RC8_MAVEN_REPO="D:/PFC/RC8/tools/maven-repository"
```

信创 Linux 示例：

```bash
export RC8_CENTER_URL="http://<CENTER_IP>:4098"
export RC8_NODE_ID="PFC-LINUX-NODE-01"
export RC8_NODE_OPERATOR="<测试人员标识>"
export RC8_NODE_STATE_DIR="/opt/pfc/rc8/runtime/rc8-node"
export RC8_MVN="/opt/tools/apache-maven/bin/mvn"
export RC8_MAVEN_REPO="/opt/pfc/rc8/tools/maven-repository"
```

正式可搬运验收必须显式设置 `RC8_MAVEN_REPO`。不要用开发机默认 `~/.m2` 作为离线可搬运证明。

## 3. 执行严格可搬运 Reality 验证

```bash
bash packaging/rc8/rc8-maven-reality.sh \
  --center "$RC8_CENTER_URL" \
  --node-id "$RC8_NODE_ID" \
  --operator "$RC8_NODE_OPERATOR" \
  --state-dir "$RC8_NODE_STATE_DIR" \
  --maven "$RC8_MVN" \
  --maven-repo "$RC8_MAVEN_REPO" \
  --project-dir "<真实 Maven 项目目录>" \
  --strict-portability \
  --require-pass
```

默认会添加 Maven `-o`，禁止依赖公网临时下载。

如需要指定 Maven goal，可重复传入：

```bash
--goal clean --goal test
```

## 4. 必须检查的本地结果

运行目录：

```text
<RC8_NODE_STATE_DIR>/reality/<RUN_ID>/
```

必须至少出现：

```text
preflight.json
reality-result.json
capability/maven-junit-probe.json
execution/maven-junit-actual.json
execution/maven-stdout.log
execution/maven-stderr.log
```

其中 `maven-stderr.log` 可以是 0 字节；0 字节文件仍必须经过 SHA-256 验证并在 Center 变为 `AVAILABLE`。

`preflight.json` 必须满足：
- `status = PREFLIGHT_PASS`
- Center health = READY
- `pom_exists = true`
- `maven_command_resolved = true`
- `offline = true`
- `strict_portability = true`
- `explicit_maven_repository = true`

注意：`PREFLIGHT_PASS` 只表示执行前条件成立，不表示测试通过。

## 5. Reality 结果判断

### 通过链路

`reality-result.json`：

```text
reality_status = EXECUTION_CHAIN_VERIFIED
work_item_state = COMPLETED
r1_receipt.status = PERSISTENCE_VERIFIED 或 IDEMPOTENT_REPLAY
```

并且在使用 `--require-pass` 时：

```text
actual.tests > 0
actual.failures = 0
actual.errors = 0
actual.passed = true
```

### 链路已验证但测试失败

如果真实 JUnit 有失败，链路本身仍可能正确：

```text
reality_status = EXECUTION_CHAIN_VERIFIED_TEST_FAILED
actual.passed = false
```

这必须被报告成测试失败，禁止把“链路成功”转换成业务测试 PASS。

### 能力未验证

```text
reality_status = CAPABILITY_NOT_VERIFIED
```

此时禁止执行依赖 `maven-junit` 的正式 WorkItem。

## 6. Center 侧必须核对

不能只看节点本地结果。必须同时核对中央事实：

1. 节点已经注册并可见；
2. `maven-junit` capability 的状态为 VERIFIED；
3. VERIFIED 记录含 probe evidence reference；
4. 执行 WorkItem 的 owner 为当前 Node；
5. Actual JSON、stdout、stderr、JUnit XML 全部在 Artifact Store 为 AVAILABLE；
6. R1 中存在 `MAVEN_JUNIT_ACTUAL_RECORDED`；
7. R1 event references 与 Artifact IDs 一致；
8. WorkItem 在 R1/Artifact 成功后才 COMPLETED；
9. JUnit XML 的失败值不能被 Maven exit code 0 覆盖。

## 7. 银行环境 Reality Verification 判定

只有同时满足以下条件，才允许记录：

```text
MAVEN_JUNIT_BANK_ENV_REALITY_VERIFIED = YES
```

条件：
- 在目标银行办公 PC / 信创 Linux 节点执行；
- 使用真实 RC8 Center；
- 使用真实 Maven；
- 使用真实测试项目；
- 使用显式离线 Maven 仓库；
- 使用真实 Surefire/Failsafe XML；
- Artifact 真正上传中央并校验；
- R1 真正中央持久化；
- WorkItem 生命周期真实完成；
- `preflight.json` 和 `reality-result.json` 保留；
- Center 侧事实与节点本地事实一致。

不能用以下任一项代替 Reality Verification：
- GitHub CI 绿；
- Maven 已安装；
- `mvn -version` 成功；
- Maven exit code 0；
- synthetic/fake Maven；
- synthetic JUnit XML；
- 模型/Agent 声称执行完成；
- Node 本地有日志但 Center 无 Artifact/R1。

## 8. 验证通过后的下一步

完成银行环境单节点 Reality Gate 后，先建设两个产品样板面：
1. 测试任务；
2. 执行节点。

页面必须能从中央事实解释：
- 测了什么；
- 哪个节点执行；
- 使用什么能力；
- Actual 是什么；
- Assertion 为什么成立/失败；
- Evidence 在哪里；
- R1 当前状态；
- 为什么 BLOCKED/FAIL；
- WorkItem 是否完成。

在这两个样板面通过可用性验收前，不扩全量 13 页。
