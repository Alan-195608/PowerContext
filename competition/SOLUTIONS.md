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

Linux Python 3.12 固定依赖环境合并运行官方公开验收、prepared-context 兼容测试和仓内回归：93 项通过。API 与 JS 操作契约另有 49 项通过，生成文件检查通过。新增特殊换行字符测试在旧版本上可复现 JSON 解析失败；修复后，正文及原文字符位置保持一致，完整输出仍按实际 UTF-8 字节计费。

修改文件的 Ruff 与类型检查通过。已运行全仓 `uv run prek run -a`；原有 SQL 字符串规则和全仓类型诊断仍未通过，不声称全仓检查通过。自动格式化造成的官方测试及无关源码改动已还原。

## 本次修复与扩展质量验证

- OpenAPI 明确声明默认关闭的 `evidence_selection`，并重新生成 HTTP 模型与 schema，使开关能够通过正式 HTTP 请求传入。
- 两条 prepare 路径使用共同的 JSON 编码器，将 U+0085、U+2028、U+2029 转义为 JSON Unicode 表示。这样按行读取 envelope 不再分裂 JSON，解码后原文不变，字节预算包含转义开销。
- 查询中的连字符复合词会生成额外匹配别名；降低该合成别名的权重，避免同一概念被重复加权。片段排序适度提高文档后部结果段的得分。产品不读取 gold 标注、数据集编号或题目编号。

公开 SciFact 训练集和开发集分别构造词面、随机、检索干扰候选，通过真实 Memory 获取候选，再在 1,400 / 1,800 bytes 预算下比较已失败提交与本次代码。缺失召回及无法完整放入预算的请求也计入，不排除难例。

| 候选构造 | 旧词项召回 | 新词项召回 | 旧完整覆盖 | 新完整覆盖 |
| --- | ---: | ---: | ---: | ---: |
| 开发集：词面干扰、标题加摘要 | 0.7031 | 0.7291 | 0.4919 | 0.5462 |
| 开发集：随机干扰、标题加摘要 | 0.8127 | 0.8374 | 0.5571 | 0.6169 |
| 开发集：检索干扰、标题加摘要 | 0.6761 | 0.7090 | 0.4674 | 0.5245 |
| 开发集：仅摘要压力检查 | 0.6841 | 0.6817 | 0.4864 | 0.5163 |
| 训练集：词面干扰、标题加摘要 | 0.6833 | 0.7197 | 0.4840 | 0.5250 |
| 训练集：随机干扰、标题加摘要 | 0.8007 | 0.8296 | 0.5690 | 0.6100 |

总计八份候选缓存中七份词项召回提升；另两份是不同种子及候选保留方式，完整结果保存在本地审计日志。上述数据不同于平台正式 24 claim / 48 请求，不能换算为正式分数。仅摘要压力检查存在小幅词项召回下降，离线词面排序仍有语义改写局限。平台未提供失败断言，特殊字符错误虽已复现，仍无法认定它是上次零分的唯一根因。

SciFact 小型回归夹具仅用于仓内测试，保留来源、文档 ID 和 CC BY 4.0 / ODC-By 1.0 许可说明。完整语料和标注不进入产品源码。

## 协作与提交边界

Qoder、MiniMax 参与提案与实验；额度耗尽后 Codex 接手修复、独立复核、集成和 GitHub 更新；用户负责最终平台提测。工作分支为 `codex/competition-solutions`，仓库为 `Alan-195608/PowerContext`。

产品代码放在 `src/`，回归放在 `tests/`；官方测试和评分文件保持原样。完整语料、标注、日志、缓存和模型提案保存在本地忽略目录 `.artifacts/`，不进入 Git。提交时使用该仓库及可获取的完整 40 位 commit SHA。
