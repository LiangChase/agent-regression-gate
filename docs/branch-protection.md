# Main 分支合并阻断

## 它在计划里的位置

按 [开发计划 M6](../agent-regression-gate-development-plan.md) 和 [阶段计划 P7](../agent-regression-gate-phase-plan.md)：

- 被测对象是 SUT 的行为；
- 门禁执行点是 **Gate 仓库的 PR**；
- 普通 PR 使用确定性 ChatKit fixture，不依赖模型密钥；
- 真实 SUT 通过 `config/sut.lock.yaml` 固定 SHA，由手动 live smoke 验证；
- **不在 SUT 仓库里新增 CI workflow**，SUT 是外部被测系统。

“阻断合并”指的是：当 Gate PR 中的 critical 行为断言失败时，GitHub 拒绝这个 PR 合并到 Gate 的 `main`。SUT 的变更通过更新 lock 的 Gate PR 进入验证，而不是直接给 SUT 分支加门禁。

## 当前需要的规则

配置源文件：[`.github/rulesets/main-branch-protection.json`](../.github/rulesets/main-branch-protection.json)

| 规则 | 值 |
|---|---|
| 目标分支 | `refs/heads/main` |
| 要求 Pull Request | 是，批准数 0（允许单人通过 PR 合并） |
| Required status check | `Critical behavior rules (offline fixture)` |
| 分支必须最新 | 是 |
| 禁止删除分支 | 是 |
| 禁止 force push | 是 |
| Bypass actors | 空 |

Required check 名称必须与 [`.github/workflows/regression.yml`](../.github/workflows/regression.yml) 中 `deterministic-gate` job 的 `name` 完全一致。改名 job 时必须同步修改 ruleset 文件。

## 方式一：GitHub UI

1. 打开仓库 **Settings → Rules → Rulesets → New branch ruleset**；
2. Target branches 选择 `main`；
3. Enforcement 选择 **Active**；
4. 勾选 Require a pull request、Require status checks、Block force pushes、Restrict deletions；
5. Required check 选择 `Critical behavior rules (offline fixture)`；
6. Bypass list 保持为空；
7. 保存。

## 方式二：脚本（需要管理员 token）

脚本使用 GitHub REST API，不依赖 `gh`：

- Token 要求：fine-grained PAT，仓库范围包含本仓库，权限 **Administration: Read and write**；
- 不要把 token 写进仓库或提交历史；
- 脚本不会打印 token。

PowerShell：

```powershell
$env:GH_TOKEN = "<fine-grained PAT>"
uv run python scripts/apply_github_ruleset.py dry-run
uv run python scripts/apply_github_ruleset.py check
uv run python scripts/apply_github_ruleset.py apply
uv run python scripts/apply_github_ruleset.py check
Remove-Item Env:GH_TOKEN
```

返回码：

- `0`：成功 / 已符合；
- `1`：本地配置或在线规则不符合；
- `2`：缺少 token、无法读取或无法访问 API；
- `3`：ruleset 尚未生效。

`dry-run` 不需要 token，也不会访问网络，只校验 JSON 和 workflow job 名称是否一致。

## 验证是否真的阻断

启用后：

1. 在 `main` 上直接 push，应被 GitHub 拒绝；
2. 创建一个会失败的 PR，Merge 按钮应被 required check 阻止；
3. 创建一个通过的 PR，应允许合并。

也可以：

```powershell
$env:GH_TOKEN = "<token>"
uv run python scripts/apply_github_ruleset.py check
```

## 注意事项

- 这是仓库设置，需要仓库管理员或所有者执行；代码提交本身不能替仓库改规则。
- Required approvals 为 0 是为了单人开发也能通过 PR 合并；团队需要 review 时改为 1。
- `strict_required_status_checks_policy` 要求 PR 分支先更新到最新 `main`。
- 如果修改 job 名称或新增 required job，必须同步更新 ruleset 文件并重新 apply。
- SUT 分支不在这个 ruleset 的范围内；SUT 只作为锁定的被测 revision。真实模型验证仍是手动 `Live SUT smoke`。
- PR 来自 fork 时，确定性 fixture 不需要模型密钥，仍可完成核心门禁。
