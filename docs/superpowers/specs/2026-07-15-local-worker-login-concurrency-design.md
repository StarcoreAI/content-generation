# 本地 Worker 同平台 2 并发修复与测试方案

更新时间：2026-07-15

状态：待评审，尚未开始实施

## 1. 核心要求

本轮目标不是把同平台并发降为 1，而是让同一平台默认使用 2 个浏览器窗口稳定爬取，以缩短单个平台的处理时间。

必须满足：

- 一个任务展开后有 2 个及以上问题时，同一平台默认启动 2 个窗口，并把问题分给两个 worker。
- 普通 `need_login` 完成人工登录后，原任务仍按配置使用 2 个窗口重试。
- 只有出现 `verification_required`、验证码、账号异常或风险验证时，才允许本次恢复重试临时降为 1 个窗口。
- 只有 1 个问题时只启动 1 个窗口，因为第二个窗口没有任务；这不算把默认并发改为 1。
- DeepSeek、元宝、千问、Kimi、豆包共用同一套并发和登录态规则。

一句话验收标准：豆包修复登录态后，2 问题和 10 问题任务都能实际开启两个同平台窗口并完整返回结果；其他四个平台完成双窗口烟测。

## 2. 已确认的问题

### 2.1 核心问题是登录态路径不一致

当前同时存在两类 state 路径：

```text
共享路径：ai-search-crawler/storage/state.json
平台路径：geo_v2-pro/data/<platform>_state.json
```

启动脚本会设置共享 `STORAGE_STATE_PATH`，而登录恢复应把新状态保存到平台路径。bridge 当前又可能因为父进程已经设置了 `STORAGE_STATE_PATH`，不再用平台路径覆盖子进程环境。

结果是：人工登录可能更新了一个文件，随后单窗口或双窗口爬取却读取另一个旧文件。2026-07-15 的豆包日志正好符合这一现象：登录恢复后仍出现 `saved state is missing or no longer valid`，并且两个 worker 对同一轮登录状态判断不一致。

这个路径问题位于所有平台共用的 worker/bridge 层，所以不能只按豆包特例修复。

### 2.2 `Total Queries: 0` 是启动失败的结果

双窗口由外部 Node 爬虫并行启动。当前任一 worker 在启动阶段抛出 `need_login`，整个 Node 任务会失败，因此还没进入稳定提问阶段就可能看到 `Total Queries: 0`。

现有证据首先指向旧登录态，而不是豆包回答抓取、页面选择器或平台明确禁止双窗口。应先统一 state 路径并重新验证，不能据此取消双窗口目标。

### 2.3 手工登录未自动继续仍需复验

14:26 的日志停留在等待登录，没有出现 `login ready`。当时窗口后来被人工关闭，现有日志不足以确认是页面尚未完全就绪、登录检测未识别，还是选择器失效。

因此本轮先用正确的平台 state 做一次独立 login-only 复验。只有在页面已明确登录且输入框可用、工具仍不能判定 ready 时，才针对对应平台补最小的登录就绪判断；不预先重写所有平台适配器。

## 3. 最小改动方案

### 3.1 每个平台只认自己的 state

每个平台的运行时权威路径固定为：

```text
data/deepseek_state.json
data/yuanbao_state.json
data/qwen_state.json
data/kimi_state.json
data/doubao_state.json
```

规则如下：

1. `run_login_job()` 把人工登录结果写入当前平台的 state 文件。
2. `run_node_crawler()` 为当前平台解析一次 state 路径，并无条件写入本次 Node 子进程的 `STORAGE_STATE_PATH`；父进程遗留的共享路径不能覆盖它。
3. 并发为 2 时，现有 `accounts.txt` 机制继续保留：worker-1 使用当前平台 state，worker-2 使用它在本次临时目录中的副本。
4. `accounts.txt` 在每次 Node 调用前重新生成，两个入口都必须来自本次最新的平台 state，不能复用上一次任务的副本。
5. 共享 `storage/state.json` 可暂时留给旧入口兼容，但不再参与新 worker 的平台爬取状态选择。

现有 `data/<platform>_cookies.json` 转临时 state 的兼容逻辑保留，因为它也是平台专用输入。平台 state 和平台 cookies 都不存在时应进入 `need_login`，不能拿共享 state 顶替。

这里的 `accounts.txt` 只是外部 Node 爬虫启动两个上下文所需的现有接口，不把同一个账号描述成两个独立账号，也不在本轮建设账号池。

### 3.2 保持 2 并发，只对风控临时降级

| 场景 | 本次有效并发 |
|---|---:|
| 正常任务，问题数不少于 2 | 2 |
| 正常任务，只有 1 个问题 | 1 |
| 普通 `need_login`，登录成功后重试 | 2 |
| 验证码、风险验证、账号异常，处理后重试 | 1 |
| 第二次仍失败 | 停止并回传失败 |

登录恢复最多一次，不增加循环重试、账号轮换或复杂状态机。

### 3.3 暂不改 Node 调度器

第一轮不改外部 Node 爬虫的任务分配和 `Promise.all` 行为。原因是当前已确认的根因在 state 选择，而现有调度器本来就能启动两个 worker；同时修改调度器会扩大范围并掩盖 state 修复是否有效。

统一路径后，如果仍能稳定复现“一个 worker ready、另一个 worker 使用同一份最新 state 却 `need_login`”，则本轮验收失败，保留两份 worker 日志，再单独处理 Node 的 worker 隔离或失败续跑。不能用永久降为 1 来宣告完成。

### 3.4 保留现有日志，不新增日志系统

继续使用现有的不覆盖日志：

```text
node-stdout.log / node-stderr.log
node-stdout-2.log / node-stderr-2.log
```

只需保证日志能看出平台、实际并发数、使用的 state 路径和 worker 编号。不得记录 Cookie、state 内容、账号或密码。

## 4. 实施范围

必改范围只包括：

- `scripts/local_crawl_worker.py`：保持默认并发 2，普通登录恢复重试 2，风控恢复重试 1，登录写入平台 state。
- `services/node_crawler_bridge.py`：平台 state 覆盖父进程共享 state，并用同一路径生成本次双窗口 `accounts.txt`。
- `tests/test_local_crawl_worker.py`：覆盖默认双窗口和两类登录恢复。
- `tests/test_node_crawler_bridge.py`：覆盖 state 优先级、双窗口参数和临时 state 副本。

只有 login-only 复验确认“页面已就绪但检测不到”时，才修改 `scripts/node_auth_preflight.mjs` 或对应平台的现有适配器，并只补该失败条件的测试。

本轮不做：

- 不把默认并发改为 1。
- 不删除 `accounts.txt` 双窗口入口。
- 不建设多账号池、账号管理、轮换或健康检查。
- 不修改云端任务模型、running job 心跳或租约。
- 不重构 Node 调度器。
- 不根据猜测修改五个平台的选择器。
- 不修改或上传真实 state 内容。

## 5. 自动化测试方案

### 5.1 Worker 测试

- 默认 `crawler_concurrency` 为 2。
- 2 个问题首次爬取传入 `concurrency=2`。
- 普通 `need_login` 完成人工登录后，第二次仍传入 `concurrency=2`。
- `verification_required`、验证码、账号异常或风险验证恢复后，第二次传入 `concurrency=1`。
- 第二次失败后直接返回 failed，不进入第三次爬取或第二次登录。
- `run_login_job()` 明确把当前平台 state 路径传给登录工具。

### 5.2 Bridge 测试

- 父进程设置了错误的共享 `STORAGE_STATE_PATH` 时，Node 子进程仍收到当前平台 state 路径。
- 并发 2 且有 2 个问题时，命令包含 `--accounts-file` 和 `--concurrency 2`。
- `accounts.txt` 第一行是当前平台 state，第二行是本次临时目录中的副本，内容来自同一份最新 state。
- 只有 1 个问题时有效并发为 1，不额外启动空 worker。
- 第一次和登录恢复后的第二次 Node 日志不会互相覆盖。

### 5.3 进程级测试

用假 Node 进程串起一次完整恢复：

```text
首次双窗口返回 need_login
-> login job 保存 data/<platform>_state.json
-> 原任务再次以 concurrency=2 启动
-> 两个 worker 都读取该平台最新 state
-> 返回完整结果
```

该测试必须在父进程预先设置错误共享 state 的情况下运行，防止路径问题再次出现。

实现后的基础验证命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_local_crawl_worker tests.test_node_crawler_bridge -v
.\run_tests.bat
```

外部 Node 项目保持运行现有测试；只有实际修改外部 Node 代码时才增加对应测试。

## 6. 真实浏览器测试方案

### 6.1 先验证豆包

1. 在云端取消上次遗留的 running 测试任务，保留现有日志。
2. 单独执行豆包 login-only；完成人工登录后，确认出现 `login ready`，并且只有 `data/doubao_state.json` 的修改时间更新。
3. 创建 2 问题、重复 1 次的豆包测试任务；确认同一平台实际出现 2 个窗口，`worker-1` 和 `worker-2` 都进入提问，最终为 2/2。
4. 创建现有 10 问题测试；确认仍为 2 个窗口、两个 worker 都至少处理一个问题，最终为 10/10。
5. 若自然出现普通 `need_login`，确认人工登录后重试仍开 2 个窗口；不通过故意破坏真实 state 来制造过期。
6. 若出现验证码或风险验证，确认本次恢复只开 1 个窗口；不主动反复触发风控。

### 6.2 再验证其他平台

DeepSeek、元宝、千问、Kimi 各执行一个 2 问题任务：

- 缺少或已失效 state 时先完成该平台 login-only；Kimi 当前应先登录。
- 每个平台都必须实际出现两个窗口。
- 两个 worker 都必须进入提问，最终结果为 2/2。
- 一个平台的登录不能修改另一个平台的 state 文件。

### 6.3 失败停止条件

出现以下任一情况时停止扩大测试批量，不把并发改为 1 后继续验收：

- 最新平台 state 下仍持续出现一个 worker ready、另一个 `need_login`。
- 页面已经登录且输入框可用，login-only 等待 60 秒仍没有 `login ready`。
- 两个窗口都打开，但始终只有一个 worker 获得问题。
- 结果数量少于输入问题数量，或任务再次出现 `Total Queries: 0`。

此时保留该次 `node-stdout*`、`node-stderr*` 和 operator log，再针对已复现的下一层问题做最小修复。

## 7. 验收标准

全部满足才算修复完成：

- 正常的同平台多问题任务默认有效并发为 2，没有任何代码把它收敛为 1。
- 登录、单窗口调用和双窗口调用都使用当前平台的同一个权威 state 来源。
- 普通登录恢复后仍以 2 并发完成原任务；风控类错误才临时单窗口重试一次。
- 豆包 2 问题为 2/2，10 问题为 10/10，且日志证明两个 worker 都实际提问。
- 其他四个平台各完成一次双窗口 2/2 烟测。
- 共享 `storage/state.json` 不能覆盖平台 state。
- 自动化测试全部通过，日志不覆盖，真实登录态没有进入日志、云端或 Git。

## 8. 回退方式

如果双窗口修复造成新的阻塞，运营可以临时用 `--crawler-concurrency 1` 完成紧急任务。它只是运行时回退手段，不改变默认值、设计目标或最终验收标准。

回退时不删除、不覆盖任何 `data/*_state.json`；取消云端仍为 running 的测试任务，并保留失败日志用于继续定位。

## 9. 后续实施顺序

用户确认本方案后再开始写代码，顺序固定为：

1. 先补 state 优先级和登录恢复并发测试。
2. 用最小改动统一 bridge 的 state 选择。
3. 保持默认 2 并发并跑自动化测试。
4. 完成豆包 login-only、2 问题和 10 问题验证。
5. 完成其他四个平台的双窗口烟测。
6. 只有真实日志证明还有下一层问题时，再扩大修改范围。
