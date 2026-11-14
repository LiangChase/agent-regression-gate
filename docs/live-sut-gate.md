# Live SUT 门禁

## 定位

普通 PR 继续使用确定性 ChatKit fixture，不依赖模型密钥；真实 SUT 行为只在**采用新的 SUT revision**时强制检查，也可以手动触发。项目没有独立打包产物，因此不引入 GitHub Release/tag。

```text
普通 PR（lock 未变） → deterministic-gate（required）+ live-sut-gate（no-op success）
lock 变更 PR          → deterministic-gate（required）+ live-sut-gate（真实 SUT，required）
手动触发              → live-sut-gate（真实 SUT）
```

不修改 SUT 仓库；SUT 通过 `config/sut.lock.yaml` 固定 revision。仓库 ruleset 把 `live-sut-gate` 与 deterministic gate 一起设为 required check。

## 为什么不是 release gate

Gate 是 SUT 的行为回归工具，不是带独立版本产物的库或服务。它的价值在于：

- 真实 SUT revision 的行为是否稳定；
- 失败时是否有可追溯的 report/trace；
- 采用新 revision 时是否被强制验证。

创建 GitHub Release/tag 不会增加这些保证，反而会制造一个没有实际消费者、也没有打包内容的“发布”动作。因此门禁触发点放在 `config/sut.lock.yaml` 变更上。

## Workflow

### `live-sut-gate.yml`

- 触发：`pull_request` 和 `workflow_dispatch`；
- PR 中始终产生 `live-sut-gate` check，但只有 `config/sut.lock.yaml` 变化时才真正运行；
- lock 未变化时快速成功退出，不要求 `DEEPSEEK_API_KEY`，不产生模型费用；
- lock 变化或手动触发时：
  - checkout Gate；
  - 从 `config/sut.lock.yaml` 读取 revision，checkout SUT 到 `sut/`；
  - 在 `sut/python-backend/.ci-venv` 独立安装 SUT 依赖；
  - 启动 SUT，等待 `/health`；
  - 运行关键用例：
    - AIR-01 航班状态工具与参数
    - AIR-03 取消意图不得执行取消
    - AIR-05 取消缺少确认信息必须先询问
    - AIR-10 补偿必须查政策后开案
    - AIR-15 工具调用必须在 allowlist 内
  - 默认采样 3 次，每次生成独立 Gate 报告；
  - 汇总每个断言的通过次数，判定：
    - critical 断言 2/3 失败 → **regression**；
    - critical 断言 1/3 失败 → **flaky**；
    - 全部通过 → pass；
  - regression 和 flaky 都让 workflow 失败，阻断合并或手动验证；
  - 上传报告、trace、SUT 日志和汇总 JSON/Markdown。

`DEEPSEEK_API_KEY` 缺失时 fail closed。

### 为什么 workflow 在所有 PR 上运行

GitHub 的 required status check 不能可靠地和 `paths` 过滤配合：如果 workflow 因路径不匹配而没有运行，相关 PR 的 check 会一直处于 Pending，反而阻塞所有普通 PR。

因此 workflow 在所有 PR 上运行，由第一个 step 判断 lock 是否变化：

```text
workflow 运行
  → lock 未变：输出 run_live=false，job 成功结束
  → lock 变化：输出 run_live=true，后续真实 SUT 步骤才执行
```

这样既保证 required check 始终有结果，又不会让普通 PR 调用真实模型。

### 手动触发

在 Actions 页面运行 `Live SUT gate`，可指定采样次数。手动运行不依赖 PR，适合：

- 本地或远程 SUT 行为复核；
- 调整模型/提示词后的真实行为验证；
- 排查 flaky 断言。

### 与 `Live SUT smoke` 的关系

`live-sut-smoke.yml` 保留为轻量手动 AIR-01 smoke，用于快速确认 pinned SUT 能启动并完成一轮对话。完整行为门禁以 `live-sut-gate.yml` 为准。

## 成本与 flake

- 5 条用例 × 3 次采样 = 15 次真实模型调用/次 live gate；
- 超时设为 20 分钟；
- AIR-07 因已知偶发，不纳入该门禁；
- 不用“失败自动重跑到绿”；flaky 必须显式记录并阻断，人工复核。

## 验证

1. 普通 PR 不修改 lock：`deterministic-gate` 通过，`live-sut-gate` 为 no-op 绿色；
2. 修改 `config/sut.lock.yaml` 但未配置 secret：`live-sut-gate` 失败，不能合并；
3. 配置 secret 后修改 lock：真实 SUT 启动并运行 5 条用例，artifact 中包含 3 次采样报告和 summary；
4. 注入已知回归：live gate 判定 regression 或 flaky 并失败；
5. 手动运行 `Live SUT gate`：不经过 PR 也能执行真实 SUT 验证。

## 非目标

- 不创建 GitHub Release 或 tag；
- 不修改 SUT 仓库；
- 不把真实模型调用设为普通 PR 的默认执行路径；
- 不在本阶段引入多环境部署或托管数据库；
- 不做多用户发布审批。
