# 发布前 live SUT gate

## 定位

普通 PR 继续使用确定性 ChatKit fixture，不依赖模型密钥；真实 SUT 行为只在**发布前**强制检查。这与 P7 的边界一致：

```text
普通 PR → deterministic-gate（required，无模型密钥）
发布   → live-sut-gate（真实 SUT，强制）→ 创建 tag / GitHub Release
```

不修改 SUT 仓库；SUT 通过 `config/sut.lock.yaml` 固定 revision。

## Workflow

### `live-sut-gate.yml`

- 触发：`workflow_call`（供 release 调用）和 `workflow_dispatch`（手动）；
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
- regression 和 flaky 都让 workflow 失败，阻断发布；
- 上传报告、trace、SUT 日志和汇总 JSON/Markdown。

### `release.yml`

- 手动触发，输入版本号；
- `live-sut-gate` 作为前置 `needs`；
- 只有 live gate 成功，才创建 `v<version>` tag 和 GitHub Release；
- `DEEPSEEK_API_KEY` 缺失时 fail closed；
- 不使用 Environment 必审，避免单人开发无法发布；tag 的创建应通过该 workflow 进行。

## 为什么不做成普通 PR required check

M6/P7 明确要求：

- 普通 PR 不依赖外部模型 API；
- deterministic fixture 用于稳定 PR 门禁；
- 真实模型 smoke 独立、手动、非普通 PR 必需。

把真实模型设为所有 PR 的 required check 会让 fork PR 无法拿到 secret、PR 变慢变贵，并且引入 flake。发布前强制是低风险且符合文档的折中。

## 成本与 flake

- 5 条用例 × 3 次采样 = 15 次真实模型调用/发布；
- 超时设为 20 分钟；
- AIR-07 因已知偶发，不纳入该门禁；
- 不用“失败自动重跑到绿”；flaky 必须显式记录并阻断发布，人工复核。

## 验证

1. 在 `main` 上推一个正常版本，运行 `Release`，确认 live gate 通过并创建 tag；
2. 用临时回归分支/已知失败用例确认 live gate 失败时 release job 不会创建 tag；
3. 检查 artifact 中包含 3 次采样报告和 summary；
4. 普通 PR 不配置模型密钥仍能通过 deterministic-gate。

## 非目标

- 不修改 SUT 仓库；
- 不把 live gate 设为普通 PR required check；
- 不在本阶段引入多环境部署或托管数据库；
- 不做多用户发布审批。
