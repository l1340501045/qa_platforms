# 覆盖保持 cap 行业实践调研

## 问题

`0c54ebc5` 中某 test point 生成 34 条 case，cap 到 3 条后保留项全为 `boundary_value`。这不是边界值识别失败，而是选择策略把 boundary 作为最高优先级，压过了维度覆盖多样性。

## 调研结论

### 1. 测试集缩减应先保覆盖目标，再做优先级

测试集缩减/优先级排序常见做法是 coverage-based prioritization 或 maximum additional coverage：每次选择能带来最多新增覆盖的测试，再用风险、成本、历史缺陷等作为加权或 tie-break。映射到本仓库，就是先看新增 `dimension`、边界形态、source section，再看 boundary bonus、priority、steps 完整度。

### 2. 边界值是重要覆盖类别，但不是全局压倒性排序键

Boundary Value Analysis 的价值是覆盖等价类边缘和阈值附近的错误高发点。它应作为 coverage atom 或加权项参与选择；如果把 boundary 放成一级排序，会在有限预算下牺牲 functional correctness、invalid input、access control 等同样独立的覆盖面。

### 3. 组合测试的主流思想是覆盖数组，不是单维排序

NIST ACTS / combinatorial testing 的核心是定义参数和交互强度，在较少测试中覆盖尽量多的组合。对当前问题的启发是：把 case 的维度、边界数字、来源章节等建模为 coverage atoms，用预算内最大覆盖代替固定排序。

### 4. cap 小于独立覆盖数时，必须报告 coverage debt

`cases_per_tp_cap=3` 无法保证天然多断言 TP 不丢覆盖。如果一个 TP 有 5 个独立核心维度，压到 3 条必然产生 debt。最佳实践不是隐瞒该事实，而是让离线评估输出 dropped dimensions / boundary atoms / source sections，供后续决定是否动态提高 cap 或上游拆分 TP。

## 本任务设计决策

- `dimension` 新增覆盖权重高于 boundary bonus。
- 遍历全部 `case.dimensions`，不只看首维度。
- boundary 继续保护，但仅在维度覆盖相同或剩余名额存在时优先。
- 离线评估新增 coverage debt 报告。
- 不新增 DB 字段；不引入 LLM 或 embedding；保持确定性纯函数。

## 参考资料

- NIST Automated Combinatorial Testing for Software: https://csrc.nist.gov/projects/automated-combinatorial-testing-for-software
- NIST SP 800-142 Practical Combinatorial Testing: https://csrc.nist.gov/pubs/sp/800/142/final
- Test Case Prioritization Using Test Similarities: https://arxiv.org/abs/1809.00138
- Test case prioritization using diversification and fault-proneness: https://arxiv.org/abs/2106.10524
- SETBVE: Quality-Diversity Driven Exploration of Software Boundary Behaviors: https://arxiv.org/abs/2505.19736
