# 验证样例：订单 status 筛选

任务：修改 `orders.py::list_orders`，新增 `pending`、`paid`、`cancelled` 状态筛选；非法 status（含空字符串、非字符串及空列表输入下的非法参数）抛出含 status 的 ValueError。保持 None 返回全部、输入顺序、独立列表及浅拷贝字典，不修改调用方数据；无 status 的订单在不筛选时保留，在筛选时排除。

有效规格与必需来源：

| 来源 | 必须包含的内容 |
| --- | --- |
| `sample/specs/orders.md` | ORD-001 筛选和校验、ORD-002 全部兼容约束 |
| `sample/orders.py` | `list_orders` 函数及真实源码 |
| `sample/tests/test_orders.py` | TargetTests 4 个目标测试、RegressionTests 3 个回归测试 |

输出路径相对于工程根目录（如 `specs/orders.md`）。`sample/specs/unrelated.md` 是库存资料，不应进入本任务的上下文。所有来源包含当前内容哈希和行区间。

初始数据：测试里构造 id 1/pending、2/paid、3/cancelled、4/paid、5/无 status 的五个订单。paid 的结果必须为 `[2, 4]`；pending 为 `[1]`；cancelled 为 `[3]`；不传 status 返回全部五条。修改前快照仅返回所有订单，目标功能失败而旧行为可用。

步骤：在 `minimax/` 执行 README 中的安装、集成测试和 `verify.py` 命令。脚本在新的运行目录中复制业务工程并恢复 `snapshots/orders.before.py`，不会改动提交的最终源码。

1. 运行目标测试，要求因断言不满足退出 1；运行回归测试要求退出 0。
2. 导入真实文件到 seekdb，查询并核对必要来源。先读取空任务状态，再将进展写入 PowerContext。
3. 新进程构造上下文，包含任务、规格、源代码、测试和已保存进展。真实模式发送给 MiniMax 并应用其返回代码；历史证据模式核对提交的请求与代码哈希后重用已生成代码。
4. 用原封不动的同一测试文件运行目标与回归测试，均退出 0。验证测试文件 SHA-256 前后一致。
5. 保存完成事项、待办及验证结果，关闭进程。在不同 PID 中重新启动并从精确 Memory 引用读取，核对内容一致。后续上下文的 `next_action` 必须来自已保存待办。
6. 将规格改成 v2，加入 ORD-003 新规格标记并重新导入；上下文必须返回新的规格全文与新 SHA-256，不得包含被替换的 v1 标题。

预期：输出 `passed: true`；六项 `checks` 为 true；修改前后代码哈希不同，测试哈希相同，保存与恢复 PID 不同。真实模式另外保留模型调用记录及补丁。一次验收以本次生成的 `acceptance.json` 和 `evidence/` 为准。

集成测试还验证：重导入删除文档后不会返回已删除来源；SQL 输入不能注入；必要规格缺失时明确失败；PowerContext 各任务隔离、重复保存和恢复；鉴权信息不会发往非官方 MiniMax 域名。

重置：换一个全新的 `--run-dir` 重新运行。每个运行目录自带完整初始工程、数据库、原始日志和最终结果，不需要任何未提交的本机文件。历史证据模式只需要仓库与公开依赖；重新真实生成另需自己的 MiniMax 配置或环境变量。
