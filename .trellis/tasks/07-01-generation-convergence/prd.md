# 生成侧收敛（覆盖保持修订）

## Goal

收敛生成侧虚胖，同时把每测试点 cap 从“边界值优先排序”修正为“覆盖保持优先选择”：在有限名额下最大化维度/断言覆盖多样性，边界值作为高价值代表参与加权但不能垄断全部名额。

## Background

当前 4.1 拆条上限已能把虚胖测试点压到 `cases_per_tp_cap=3`，但线上审查发现 `0c54ebc5` 某 test point 生成 34 条后被 cap 到 3 条，保留的 3 条全是 `boundary_value`。这说明“边界优先”生效了，但维度多样性没有生效：`functional_correctness`、`invalid_input` 等可能承载独立断言的维度被裁掉。

行业最佳实践不把 boundary value 作为压倒性一级排序，而是先定义覆盖目标，再在预算内做覆盖保持/最大新增覆盖选择。等价类、边界值、组合覆盖、风险优先都应转成可比较的 coverage atoms 或权重；当独立覆盖数超过 cap 时，系统必须报告 coverage debt，而不是声称“不丢覆盖”。

## Confirmed Evidence

- 当前实现的排序键是 `(is_bdy, dim_novel, step_count)`，即边界优先于维度新颖性：`src/testcase_generator/stages/write_cases/convergence.py:55-66`。
- 当前实现只看 `dimensions[0]`，多维度 case 的后续维度不会贡献新颖性：`src/testcase_generator/stages/write_cases/convergence.py:60-63`。
- 现有设计文档的原始目标是“保留多样性代表”，并把“不同 dimension 各一”放在边界/异常语义之前：`docs/spec/2026-06-30-generation-convergence-design.md:26-27`。
- `GeneratedTestCase` 当前没有 `rule_codes` 字段；write_cases 阶段不能可靠按规则锚定保留，不能继续在 4.1 中要求 rule_codes 护栏。规则级覆盖仍由 test_points 层的 rule_id/structural_type 和 4.3 配额豁免承担。

## Requirements

- R1 关时零回归：`split_cap_enabled=False`、`existence_merge_enabled=False`、`p0_quota_enabled=False` 时，现有生成结果逐字节不变。
- R2 拆条上限必须改为覆盖保持选择：同一 `test_point_id` 超过 `cases_per_tp_cap` 时，优先最大化新增覆盖，而不是先按边界值排序。
- R3 coverage atoms 至少包含：
  - 所有 `dimensions` 中的维度，而不是只看首个维度。
  - 边界/异常语义：复用 `_BOUNDARY_KW`，并把边界命中作为加权覆盖特征。
  - 边界数字集合：复用或等价实现 dedup 中的数字提取，避免把不同边界值全当同一种边界。
  - `provenance.source_section`，用于避免同 TP 跨章节代表被单一章节垄断。
- R4 维度新增覆盖的权重必须高于边界加权。示例：同一 TP 中存在大量 `boundary_value` 和少量 `functional_correctness`、`invalid_input` 时，`n=3` 应优先保留三个不同维度代表，而不是三条 boundary。
- R5 边界值仍需保护：如果一个 TP 只有 boundary 维度，或维度已覆盖完且还有剩余名额，应该优先保留不同边界形态/数字集合，而不是任意保留步数最长者。
- R6 当独立覆盖数超过 cap，必须在离线评估中显式报告 coverage debt，包括被裁掉的维度、边界形态、source section 和样例 case id。不能把这种情况描述为“未丢覆盖”。
- R7 `duplicate_of` 只能继续作为兼容现有软标记使用；实现和报告不得把所有 cap 裁剪都语义化为真重复。离线报告中要区分“疑似重复裁剪”和“coverage overflow 裁剪”。
- R8 存在性合并保持现有要求：只合并纯展示/存在性用例，合并后保留全部检查点，判定型用例不参与合并。
- R9 P0 配额保持现有要求：只裁 risk 派生的边际 P0，结构化覆盖点和规则锚点不被误降。
- R10 本轮不做 DB schema 变更、不新增 LLM 调用、不引入 embedding；策略必须是确定性、纯函数、可单测、可离线评估。

## Acceptance Criteria

- [ ] 4.1 cap 单测：构造 20 条 `boundary_value`、7 条 `functional_correctness`、7 条 `invalid_input` 的同 TP，`n=3` 后必须保留三个维度各一条。
- [ ] 4.1 cap 单测：同一 case 有多个 dimensions 时，后续维度也能贡献覆盖新颖性。
- [ ] 4.1 cap 单测：只有 boundary 维度时，优先保留不同边界数字/形态代表。
- [ ] 4.1 cap 单测：`n=1` 时仍至少留 1 条，且选择最高覆盖/质量代表。
- [ ] 4.1 cap 单测：低于 cap 的 TP 原样返回，不写 `duplicate_of`。
- [ ] 4.2 存在性合并单测：合并保留全部检查点，判定型不被误并。
- [ ] 4.3 P0 配额单测：配额后 P0 不超过阈值，risk 高者保留，结构化覆盖点不被误降。
- [ ] 接入测试：开关关时结果原样；开关开时先存在性合并、再覆盖保持 cap。
- [ ] 离线评估：对目标 batch 输出总量前后、每 TP 条数分布、cap debt TP 列表、每个 debt TP 的 dropped dimensions/boundary/source_section 样例。
- [ ] 对 `0c54ebc5` 这类 34 条 TP，离线报告不能只显示“裁到 3 条成功”，必须显示是否存在 coverage debt；若保留 3 条，维度应尽量多样。
- [ ] `uv run pytest tests/testcase_generator/test_generation_convergence.py` 通过。
- [ ] `uv run pytest tests/testcase_generator --ignore=tests/testcase_generator/integration` 通过。
- [ ] `uv run ruff check` 涉及文件干净。

## Out of Scope

- 不把 `cases_per_tp_cap` 从 3 改成全局默认更大值；若评估证明天然多断言 TP 普遍有 coverage debt，再另开任务讨论动态 cap。
- 不新增 `GeneratedTestCase` 持久化字段；coverage debt 先通过离线评估报告暴露。
- 不做 TestPoint likelihood/impact 落库和 alembic 迁移。
- 不重跑 PRD 生成，不引入 LLM 二次裁剪。

## Notes

- 行业调研记录：`.trellis/tasks/07-01-generation-convergence/research/coverage-preserving-cap.md`。
- 来源 spec：`docs/spec/2026-06-30-generation-convergence-design.md`。
- 关联 roadmap ⑥。
