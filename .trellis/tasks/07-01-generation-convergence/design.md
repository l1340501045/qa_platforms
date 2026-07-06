# 生成侧收敛 — 覆盖保持 cap 技术设计

## Problem Statement

`cases_per_tp_cap=3` 是预算约束，不是覆盖保证。当前实现把边界值作为第一排序键，导致某些虚胖 TP 被收敛后只剩 boundary 代表，丢掉其他维度的独立断言。修正目标是把 4.1 从“固定排序取前 N”改成“覆盖保持的代表选择”，并在 cap 不足时报告 coverage debt。

## Architecture

4.1 仍在 `src/testcase_generator/stages/write_cases/convergence.py` 内完成，保持纯函数、确定性、无 LLM 成本。对每个 `test_point_id` 分组后，超 cap 的组通过贪心最大新增覆盖选择代表；4.2 存在性合并仍先执行，4.1 cap 后执行；4.3 P0 配额不改变。

## Data Flow

1. `write_cases/node.py` 生成并汇总 `all_test_cases`。
2. `apply_convergence` 在 `existence_merge_enabled=True` 时先调用 `merge_existence_cases`。
3. `apply_convergence` 在 `split_cap_enabled=True` 时调用修订后的 `cap_cases_per_testpoint`。
4. `cap_cases_per_testpoint` 对每个 TP：
   - 未超 cap：原样返回。
   - 超 cap：计算每条 case 的 coverage atoms 和 quality score，贪心选择 `n` 条代表。
   - 被裁对象继续按现有兼容行为写 `duplicate_of` 指向代表，但离线评估必须额外判断 dropped coverage，不能把所有裁剪解释为真重复。
5. `scripts/convergence_offline_eval.py` 使用同一选择逻辑统计 coverage debt。

## Coverage Atoms

新增内部 helper，建议放在 `write_cases/convergence.py`：

```python
def _case_coverage_atoms(case: GeneratedTestCase) -> set[str]:
    ...
```

至少生成以下 atom：

- `dim:<dimension>`：遍历 `case.dimensions` 全量字段，去空值、保序去重。
- `boundary`：标题或 expected_results 命中 `_BOUNDARY_KW`。
- `boundary_num:<numbers>`：边界 case 中出现的数字集合；可复用 dedup 中 `_NUM` 的等价逻辑，避免“1000 行”和“999 行”完全等价。
- `source:<case.provenance.source_section>`：同 TP 跨章节时保留来源多样性。

不要把完整 title 直接作为高权重 atom。多数 case title 天然不同，直接高权重化会让选择退化为原始顺序；title/expected_results 可用于质量 tie-break 或离线报告样例。

## Selection Algorithm

贪心最大新增覆盖，稳定、可复现：

```python
selected: list[GeneratedTestCase] = []
covered_atoms: set[str] = set()

while len(selected) < n:
    choose remaining case with max score:
        new_dim_atoms_count * 1000
        + new_non_dim_atoms_count * 100
        + boundary_bonus * 20
        + priority_score * 10
        + step_count
        + expected_result_count
        - original_index_epsilon
    add chosen atoms to covered_atoms
```

约束：

- 维度新增覆盖必须压过 boundary bonus。这样 `functional_correctness`/`invalid_input` 不会被大量 boundary 挤掉。
- boundary bonus 只在维度覆盖相同或无新增维度时发挥作用。
- `priority_score` 建议使用 `P0=4, P1=3, P2=2, P3=1`。
- 同分时保持输入稳定序，避免非确定性。
- `n < 1` 继续抛 `ValueError`。

## Coverage Debt Reporting

新增内部分析 helper，供离线脚本使用：

```python
@dataclass(frozen=True)
class CapCoverageDebt:
    test_point_id: str
    total: int
    kept_ids: list[str]
    dropped_ids: list[str]
    dropped_dimensions: list[str]
    dropped_boundary_atoms: list[str]
    dropped_source_sections: list[str]

    @property
    def has_debt(self) -> bool:
        return bool(self.dropped_dimensions or self.dropped_boundary_atoms or self.dropped_source_sections)
```

`cap_cases_per_testpoint` 不需要改变公开返回类型；离线脚本可以调用 helper 对 kept/dropped 计算 debt。若实现者更希望把 `audit: list[CapCoverageDebt] | None = None` 作为可选参数传入，也可以，但默认行为不能变。

## Case-Level Priority Calibration

2026-07-03 增补：P0 配额在 test point 层只能约束“测试点为什么重要”，不能保证每条展开 case 都值得 P0。`write_cases` 之前统一用 `tp.priority` 覆盖 LLM case priority，导致同一个 P0 测试点拆出的纯页面元素核对也继承 P0。

新增确定性 case 级校准层：

- 只处理 `parent_priority == "P0"`。
- 若单条 case 命中页面/按钮/Tab/文案/展示等存在性信号，且没有提交、权限、状态、数据完整性、接口、worker、恢复、限流等业务风险信号，也没有结构化维度，则降为 `P2`。
- 业务风险、结构化覆盖、规则锚点派生的高价值 P0 不降级。
- 该判断放在 `src/testcase_generator/stages/write_cases/priority_calibration.py`，生成路径和审查导出复用同一规则。
- 该层受 `p0_quota_enabled` 控制；关闭 P0 配额时保持旧行为，case 继续继承父测试点优先级。

这对齐风险测试实践：优先级应由具体失败后果驱动；边界值、页面存在性、字段展示是测试设计技术或覆盖信号，不应天然占用最高执行优先级。

## Critical Flow Anchors

2026-07-03 增补：审计报告中的 `critical_flow_coverage` 不能只作为事后诊断，否则下一批仍可能靠 LLM 偶然覆盖主链路。关键业务流应成为 test-points 阶段的确定性结构化覆盖输入。

新增共享目录：

- `src/testcase_generator/services/critical_flows.py`
- `CRITICAL_FLOW_SPECS` 维护关键流 key、source tokens、中文标题、覆盖说明。
- `CRITICAL_FLOW_PATTERNS` 由同一目录派生，供 `scripts/audit_export.py` 复用，避免生成和审计各有一套关键流定义。
- source_ref 匹配使用章节边界判断，避免 `§5.8.13` 误命中 `§5.8.13.1` 导致覆盖虚增。

生成侧接入：

- `src/testcase_generator/stages/test_points/critical_flow.py` 根据 `FeatureItem.source_refs` 命中关键章节。
- 每条关键流最多生成 1 个 `TestPointSchema`。
- 锚点字段：
  - `dimension="functional_correctness"`
  - `priority="P0"`
  - `likelihood=3`
  - `impact=3`
  - `structural_type="critical_flow"`
  - `structural_key=<flow_key>`
  - `derived_from` 保留所有命中的 source_ref
- 接入点放在 `runtime.structural_coverage_enabled` 分支内，保持关时零回归；开启最佳实践配置时，关键流锚点与权限/状态机结构化点一起豁免 P0 配额。

设计边界：

- 不新增 LLM 调用。
- 不新增 DB 字段。
- 不根据全文关键词凭空创建锚点，只基于 `feature.source_refs` 的 PRD 坐标命中。
- 旧批次审计结果不回写；下一批通过 `critical_flow_coverage` 和 `structural_key=critical_flow` 复验。

## Compatibility

- 关时零回归：覆盖保持 cap 新逻辑只在 `split_cap_enabled=True` 时触发。
- 用例级 P0 校准随 `p0_quota_enabled=True` 启用；关闭 P0 配额时零回归。
- 关键流锚点随 `structural_coverage_enabled=True` 启用；关闭结构化覆盖时不改变历史 test-points 输出。
- 不新增 schema 字段，不做 DB 迁移。
- 保留现有 `duplicate_of` 兼容行为，但文档和离线报告必须承认 cap overflow 不是语义重复。
- 不再在 4.1 要求 `rule_codes`。`GeneratedTestCase` 没有该字段，规则级护栏由 test_points 层完成。

## Tests

重点测试不再是“边界必留多条”，而是“有限预算内覆盖多样性优先”：

- boundary 多数 + functional/invalid 少数，`n=3` 保留三个维度。
- 多 dimensions case 的第二维度能参与新增覆盖。
- 全部都是 boundary 时，保留不同数字/边界形态。
- `n=1` 留最高质量代表。
- 低于 cap 原样。
- 离线 debt helper 能报告 dropped dimensions/source/boundary。
- 关键流锚点：source_refs 命中关键章节时生成 `structural_type=critical_flow` 的 P0 锚点；同一 flow 多章节命中时只保留一个锚点并合并 `derived_from`。
- 章节前缀碰撞：`§5.8.13.1` 只命中 `submit_result_state`，不额外生成 `batch_submit`。

## Rollback

发现误裁后，可关闭 `split_cap_enabled` 立刻回退 4.1；4.2 和 4.3 独立灰度，不受影响。若离线报告显示大量 coverage debt，下一步不是调排序，而是讨论动态 cap 或上游拆分天然多断言 TP。
