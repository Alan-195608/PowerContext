# PowerContext 比赛实现与验证

平台已确认成绩为 220/240：除第十题“按查询和预算选择原文证据”0/20 外，其余十题满分。本次证据选择修复已完成本地与 Linux 固定环境验证，正式成绩等待用户提测确认。

## 证据选择

默认关闭的 `PrepareContextRequest.evidence_selection` 开启后，由 `PreparedContextBuilder.build_scopes_result` 在传入 Memory 候选中选择原文。实现位于 `src/powercontext/builtin/runtime/evidence_selection.py`。

- 科学符号、复合词与词形归一化只用于匹配，交付的文本始终是原文半开 Python 字符区间。
- 超预算长句先定位查询概念密集的窗口，避免早期通用词或较短干扰句挤掉后部证据。
- 连续窗口排序统一承担长度成本，避免完整结果句在句子层与窗口层被重复扣分。
- 扩展片段时避免跨过其他已选区间，输出前合并同一 entry 相邻或相交区间，避免重复支付引用和正文字节。
- 完整 UTF-8 预算包含 trust policy、envelope、JSON、引用与正文。`origins`、JSON items 与 fragments 逐项对应精确 scope、revision、entry 和版本。

算法离线执行，不读取标注或题目 ID，不调用模型或在线服务。关闭开关时保留普通 prepare 行为。

## 可复验检查

按 `competition/README.md` 准备 Python 3.12 固定依赖，执行：

```bash
make -C competition test-evidence
PYTHONPATH=src:competition PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 competition/.venv/bin/python -m pytest -q \
  -c competition/pytest.ini --confcutdir=competition \
  tests/builtin/runtime/test_prepared_context.py \
  tests/e2e/competition/test_evidence_quality_regressions.py \
  tests/e2e/competition/test_evidence_selection_quality.py
```

Linux 固定环境实际结果为官方公开 3 项、仓内兼容与回归 79 项通过。本机合并运行同样为 82 项通过。新增两项原文质量回归在修复前版本上均失败，修复后通过；长句尾部和科学符号回归亦验证过已发布旧版本的失败行为。修改文件的 Ruff 与类型检查通过。全仓库 pre-commit 已执行；全仓类型检查仍报告 189 条诊断，未声称全仓检查通过。其自动格式化产生的官方测试和无关源码改动已还原。

SciFact 小型回归夹具仅用于仓内测试，保留来源、文档 ID 和 CC BY 4.0 / ODC-By 1.0 许可说明。它不进入产品源码，也不替换官方评测输入。

## 扩展质量验证及范围

本地另用公开 SciFact 训练/开发数据构造原始 claim 与三篇原始摘要的请求，通过真实 Memory 获取候选，再在 1,400 和 1,800 bytes 两档预算评分。按官方口径合并区间，计算词频多重集合召回和全部标注字符完整覆盖。

| 集合 | 文档案例数 | 可评分请求数 | 词项召回 | 完整覆盖 |
| --- | ---: | ---: | ---: | ---: |
| 开发集 | 209 | 347 | 0.71953 | 0.56484 |
| 训练集 | 564 | 962 | 0.70283 | 0.55405 |

这些数字首先排除了目标证据未被 Memory 召回的 13/21 个案例，以及证据加完整引用无法放入预算的 45/124 次请求。案例不是独立 claim 数。

进一步将未召回的每个案例都按两档请求零召回、零完整覆盖计入，得到保守估计：

| 集合 | 保守计入请求数 | 词项召回 | 完整覆盖 |
| --- | ---: | ---: | ---: |
| 开发集 | 373 | 0.66938 | 0.52547 |
| 训练集 | 1004 | 0.67343 | 0.53088 |

上述扩展数据、候选构造及规模均不同于平台正式 24 claim / 48 请求，结果不能换算为正式分数或保证隐藏数据通过。完整语义改写仍是离线词面排序的局限。平台没有提供上次失败断言，因此无法确认唯一失败根因。

## 协作与提交边界

MiniMax 负责提案实现、实验、测试和分析；Codex 负责调度、独立复核、集成和 GitHub 更新；用户负责最终平台提测。工作分支为 `codex/competition-solutions`，仓库为 `Alan-195608/PowerContext`。

产品代码放在 `src/`，回归放在 `tests/`；官方测试和评分文件保持原样。完整语料、标注、日志、缓存和模型提案保存在本地忽略目录 `.artifacts/`，不进入 Git。提交时使用该仓库及可获取的完整 40 位 commit SHA。
