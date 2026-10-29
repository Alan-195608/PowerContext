# 规有所依：SDD 上下文管理系统

本作品位于官方 `2026-competition-ecosystem` 分支派生的 `minimax/` 目录。选择有独立功能测试和回归测试的订单列表工程，完成 status 筛选开发任务：seekdb 存储并检索规格、源码及测试，MiniMax 实际生成代码，PowerContext 保存任务状态并在新进程中恢复和使用。

## 快速复现

环境：Linux x86_64 或 macOS arm64，Python 3.12，`uv`，Git。首次安装需要联网访问 GitHub 和 Python 包仓库。实测 macOS arm64 / CPython 3.12.13，seekdb 1.4.0（`pylibseekdb==1.4.0.post1`），PowerContext 固定提交 `dab240063bfcfa7917898dc44da4baadb3747bd0`；完整依赖版本在 `uv.lock`。

```bash
cd minimax
uv sync --frozen
uv run --frozen python -m pytest -q
uv run --frozen python verify.py --recorded --run-dir .runs/review-001
```

最后一条命令从全新目录开始，启动真实 seekdb、真实 PowerContext，执行修改前后的同一组测试，检查来源、规格更新、进程重启和任务状态复用。`--recorded` 使用提交中保存的真实 MiniMax 开发结果，核对请求上下文、响应代码和前后快照哈希；不调用模型，不声称又发生一次模型调用。成功输出 `passed: true` 和六项检查，详细结果在指定运行目录的 `acceptance.json`。

每次使用新的 `--run-dir`。脚本不覆盖已有目录，不依赖交付之外的本地数据。重置方法是选择另一空目录；无需删除任何历史结果。

## 再次执行真实 MiniMax 开发

本次真实调用已记录在 `evidence/minimax-development.json`，返回模型 `MiniMax-M3.1-Flash`，请求 id `0732aa1bee32833fa3cefb67c407383c`。修改前后快照和 `evidence/change.patch` 与该响应严格对应。

可复用个人 Claude 设置，配置文件仅读取，不修改：

```bash
uv run --frozen python verify.py --run-dir .runs/live-001 --claude-config "$HOME/.claude/settings.json"
```

或在本机环境中配置（真实凭据不写进仓库）：

```bash
export MINIMAX_API_KEY='你的密钥'
export MINIMAX_BASE_URL='https://api.minimax.cn/anthropic'
export MINIMAX_MODEL='MiniMax-M3.1-Flash'
uv run --frozen python verify.py --run-dir .runs/live-002
```

环境变量优先于指定的 Claude 配置。适配器读取 `env.ANTHROPIC_AUTH_TOKEN`（或 `ANTHROPIC_API_KEY`）、`ANTHROPIC_BASE_URL` 和 `ANTHROPIC_MODEL`，去除 Claude 的 `[1m]` 后缀。仅接受官方 MiniMax HTTPS 域名。通过 [MiniMax Anthropic 兼容接口](https://platform.minimax.io/docs/api-reference/text-anthropic-api)发送一次开发请求。日志只保留请求正文、最终文本、请求 id、模型、用量和代码哈希，不保存鉴权头或模型私有思维链。模型输出只允许替换指定 Python 源文件，测试不交给模型修改。

## 模块入口和输入输出

以下命令均在 `minimax/` 下执行；`--run-dir` 是本项目专用的数据库及状态目录。

```bash
# 导入实际文件（sample/orders.py 是最终代码；verify.py 会单独重建修改前工程）
uv run --frozen python -m sdd --run-dir .runs/manual import --project sample
# 查询规格、代码、测试、已完成事项、待办及验证结果
uv run --frozen python -m sdd --run-dir .runs/manual context --task sample/task.json --out .runs/manual/context.json
# 写入任务进展；sample/state.json 仅是输入示例，业务状态持久化在 PowerContext
uv run --frozen python -m sdd --run-dir .runs/manual save --task-id orders-status-filter --state sample/state.json
# 另一个新进程读取实际 Memory 的精确引用
uv run --frozen python -m sdd --run-dir .runs/manual resume --task-id orders-status-filter
# 恢复状态进入后续上下文，第一项待办决定 next_action
uv run --frozen python -m sdd --run-dir .runs/manual context --task sample/task.json
```

`import` 输入工程目录，输出文档数量和来源；`context` 输入任务 JSON，输出三类来源的路径、行区间、SHA-256 和完整内容，以及任务进度、验证结果、下一步动作和 PowerContext 引用。`save` 输入含 `completed`、`todo` 数组的 JSON；`resume` 输出从 PowerContext 读取的内容和精确地址。`generate` 输入项目目录和 `--context` 文件，调用 MiniMax 后输出模型及前后代码哈希，具体参数见 `python -m sdd --help`。

完整验证样例、预期输出和验收对应关系见 [SCENARIO.md](SCENARIO.md)。架构与技术分工见 [TECHNICAL.md](TECHNICAL.md)。

## 已交付证据

| 证据 | 作用 |
| --- | --- |
| `evidence/minimax-development.json` | 本次真实 MiniMax 的任务、完整输入上下文、最终代码响应、用量及哈希 |
| `evidence/01-target-before.json` / `08-target-after.json` | 同一组目标测试：修改前 4 个测试、12 个功能失败；修改后 4 个全部通过 |
| `evidence/02-regression-before.json` / `09-regression-after.json` | 修改前后各 3 个回归测试全部通过 |
| `evidence/10-all-after.json` | 最终 7 个业务测试全部通过，记录命令、退出码和源代码版本 |
| `evidence/events.jsonl` | seekdb 版本、实际 SQL、绑定参数及返回路径；PowerContext 状态写入、读取和上下文使用 |
| `evidence/11-save-outcome.json` / `12-restart-resume.json` | 不同 PID 的状态保存与恢复，包含相同精确 Memory 地址和验证结果 |
| `evidence/14-context-after-restart.json` / `16-context-updated-spec.json` | 已有状态进入后续上下文，规格 v2 导入后被实际返回 |
| `snapshots/orders.before.py` / `orders.after.py` / `evidence/change.patch` | 初始、最终代码和差异 |
| `evidence/acceptance-live.json` | 真实模型端到端验证结果；属于本地验收，不代替平台成绩 |

证据中的绝对路径和进程号记录原始实测环境，仅用于审计。复现命令会在新目录中重新生成全部服务和日志，不读取原机器的路径。

## 范围与限制

这是面向小型单工程的 CLI 模块。每个 `--run-dir` 管理一个工程快照，任务状态按 task id 隔离。请勿多个写进程并发使用同一目录；导入会替换该工程已有文档（包括移除已删除文件）。

资料选择采用 SQL 字面子串匹配，按规格、代码、测试各返回最多 4 条，路径排序；适合本题明确来源的小样例，不宣称语义召回或大型仓库排名能力。必要来源没有检索到时明确报错，不补造来源。规格重新导入后使用新内容，生成前检查目标源码与上下文哈希一致。目录导入仅接受 `.md`、`.py` 普通文件，跳过隐藏文件和符号链接。

PowerContext 使用自身 SQLite 持久化后端保存 Memory；seekdb 独立承担工程资料的存储和检索，符合题面分工。未配置额外 embedding 或生成服务，状态操作不需要额外模型费用。真实 MiniMax 调用需要可用额度；历史证据复现不需要 API key。

`sample/`、`sdd/` 和验证程序均为本作品原创。PowerContext 复用 OceanBase 官方开源项目（Apache-2.0），通过固定 Git 提交安装，未复制或修改其运行时。`pylibseekdb` 通过正式 Python 包仓库安装。使用 Codex 实现上下文模块与验证框架；最终订单业务修改由上述 MiniMax 调用生成。
