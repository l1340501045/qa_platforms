# 生成侧收敛 — 覆盖保持 cap 执行清单

## 执行原则

- 先改测试，再改实现。
- 只触碰本任务列出的文件；禁止 `git add -A` / `git add .`。
- 4.1 的核心目标是覆盖保持，不是边界值垄断。
- 4.2、4.3 已有能力保持不退化；本轮重点修 4.1 并补离线 debt 报告。

## 文件范围

- 修改：`src/testcase_generator/stages/write_cases/convergence.py`
- 修改：`tests/testcase_generator/test_generation_convergence.py`
- 修改：`scripts/convergence_offline_eval.py`
- 可选同步：`docs/spec/2026-06-30-generation-convergence-design.md`
- 不改：`src/testcase_generator/schemas/test_case.py`
- 不改：DB model / alembic / callbacks

## Step 1：补失败测试，复现 boundary 垄断缺陷

- [ ] 在 `tests/testcase_generator/test_generation_convergence.py` 新增测试：
  - 同一 TP 34 条，20 条 `boundary_value`、7 条 `functional_correctness`、7 条 `invalid_input`。
  - `cap_cases_per_testpoint(cases, n=3)` 后，保留维度必须是三类各至少一条。
  - 旧实现会失败，因为 `(is_bdy, dim_novel, step_count)` 会先拿 boundary。

建议测试骨架：

```python
def test_cap_prefers_dimension_coverage_over_boundary_monopoly():
    from src.testcase_generator.stages.write_cases.convergence import cap_cases_per_testpoint

    cases = []
    for i in range(20):
        cases.append(_case(f"TC-B{i}", test_point_id="TP-fat", title=f"字数恰好等于{i}的边界校验", dimensions=["boundary_value"]))
    for i in range(7):
        cases.append(_case(f"TC-F{i}", test_point_id="TP-fat", title=f"主流程功能正确性校验{i}", dimensions=["functional_correctness"]))
    for i in range(7):
        cases.append(_case(f"TC-I{i}", test_point_id="TP-fat", title=f"非法输入拦截校验{i}", dimensions=["invalid_input"]))

    kept = cap_cases_per_testpoint(cases, n=3)

    kept_dims = {dim for case in kept for dim in case.dimensions}
    assert kept_dims >= {"boundary_value", "functional_correctness", "invalid_input"}
```

- [ ] 运行：`uv run pytest tests/testcase_generator/test_generation_convergence.py -k boundary_monopoly -q`
- [ ] 预期：失败，证明当前策略缺陷存在。

## Step 2：补多维度与边界形态测试

- [ ] 新增测试：case 的 `dimensions=["boundary_value", "invalid_input"]` 时，`invalid_input` 也能作为覆盖新增参与选择，不只看首维度。
- [ ] 新增测试：当同 TP 全部为 `boundary_value` 时，`n=3` 优先保留不同数字集合的边界 case。
- [ ] 新增测试：低于 cap 的 TP 原样返回，不写 `duplicate_of`。
- [ ] 运行：`uv run pytest tests/testcase_generator/test_generation_convergence.py -k cap -q`
- [ ] 预期：新增测试中至少前两个失败。

## Step 3：实现 coverage atom helper

- [ ] 在 `src/testcase_generator/stages/write_cases/convergence.py` 中新增：
  - `_NUM = re.compile(r"\d+(?:\.\d+)?")`，或从 dedup 安全复用等价逻辑。
  - `_case_text(case)`：拼接 title、expected_results、steps.expected_result。
  - `_case_coverage_atoms(case)`：返回 `dim:*`、`boundary`、`boundary_num:*`、`source:*`。

实现约束：

- 遍历全部 `case.dimensions`，去空字符串。
- boundary 检测应覆盖 title、expected_results、steps expected_result，不只看 title。
- 不把完整 title 当高权重 atom。

- [ ] 运行：`uv run pytest tests/testcase_generator/test_generation_convergence.py -k cap -q`

## Step 4：替换 cap 排序为贪心最大新增覆盖

- [ ] 修改 `cap_cases_per_testpoint` 的超 cap 分支：
  - 删除 `seen_dims` 在遍历阶段提前写入的逻辑。
  - 使用 `covered_atoms` 在每轮选择后更新。
  - 每轮从 remaining 中选择新增覆盖分最高的 case。
  - 维度新增覆盖权重大于 boundary bonus。
  - 同分保持输入稳定序。

建议权重：

```python
DIM_WEIGHT = 1000
OTHER_ATOM_WEIGHT = 100
BOUNDARY_BONUS = 20
PRIORITY_WEIGHT = 10
PRIORITY_SCORE = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}
```

- [ ] 保留现有 `duplicate_of` 兼容行为：被裁 case 指向 candidate 首条代表。
- [ ] 运行：`uv run pytest tests/testcase_generator/test_generation_convergence.py -k cap -q`
- [ ] 预期：cap 相关测试全部通过。

## Step 5：补 coverage debt 分析

- [ ] 在 `convergence.py` 新增 `CapCoverageDebt` dataclass 和 helper：

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

- [ ] 新增 `analyze_cap_coverage_debt(tp_cases, kept_cases) -> CapCoverageDebt`。
- [ ] 补单测：当 cap 小于独立维度数时，helper 报告 dropped_dimensions；当 dropped case 不带新 atoms 时，`has_debt=False`。
- [ ] 运行：`uv run pytest tests/testcase_generator/test_generation_convergence.py -k debt -q`

## Step 6：更新离线评估脚本

- [ ] 修改 `scripts/convergence_offline_eval.py`：
  - 运行合并 + cap 后，按 TP 输出 cap debt。
  - 汇总字段至少包含：`debt_tp_count`、`dropped_dimensions`、`dropped_boundary_atoms`、`dropped_source_sections`、样例 case id。
  - 对 `0c54ebc5` 或指定 batch，报告不能只说“裁剪成功”，必须显示 debt。
- [ ] 运行：`uv run python scripts/convergence_offline_eval.py 278c211f-6f25-4970-a425-9db94cbc8ff7`
- [ ] 若本地没有 `.audit` 数据，脚本命令可以失败，但单测必须覆盖 debt helper；最终审查时明确说明离线数据缺失。

## Step 7：回归 4.2 / 4.3 / 接入路径

- [ ] 运行：`uv run pytest tests/testcase_generator/test_generation_convergence.py`
- [ ] 重点确认：
  - existence merge 仍保留全部检查点。
  - `apply_convergence` 仍是先 merge 再 cap。
  - P0 quota 测试不受 4.1 修改影响。
  - 开关关时仍原样返回。

## Step 8：质量检查

- [ ] 运行：`uv run pytest tests/testcase_generator --ignore=tests/testcase_generator/integration`
- [ ] 运行：`uv run ruff check src/testcase_generator/stages/write_cases/convergence.py tests/testcase_generator/test_generation_convergence.py scripts/convergence_offline_eval.py`
- [ ] 运行：`uv run ruff format --check src/testcase_generator/stages/write_cases/convergence.py tests/testcase_generator/test_generation_convergence.py scripts/convergence_offline_eval.py`
- [ ] 检查：`git diff -- src/testcase_generator/stages/write_cases/convergence.py tests/testcase_generator/test_generation_convergence.py scripts/convergence_offline_eval.py .trellis/tasks/07-01-generation-convergence`

## Review Notes For Claude Code

- 不要用 boundary 作为第一排序键。
- 不要只看 `dimensions[0]`。
- 不要新增 DB 字段。
- 不要把 coverage overflow 伪装成 dedup 成功。
- 若发现 `cases_per_tp_cap=3` 无法覆盖所有独立维度，正确行为是报告 debt，不是继续调排序直到报告“无丢覆盖”。

## 2026-07-03 增补：关键业务流结构化锚点

背景：批次报告显示 `critical_flow_coverage` 只能事后发现主链路偏薄，不能保证下一批生成阶段主动覆盖。为对齐风险测试实践，关键业务流需要变成 test-points 阶段的确定性结构化覆盖输入。

文件范围：

- 新增：`src/testcase_generator/services/critical_flows.py`
- 新增：`src/testcase_generator/stages/test_points/critical_flow.py`
- 新增：`tests/testcase_generator/test_critical_flow_anchors.py`
- 修改：`src/testcase_generator/stages/test_points/node.py`
- 修改：`src/testcase_generator/schemas/test_point.py`
- 修改：`scripts/audit_export.py`
- 修改：`.audit/6f30e1bd-89ad-4e98-878c-4b48014eb1a4/REPORT.md`
- 修改：`.trellis/tasks/07-01-generation-convergence/design.md`

实现清单：

- [x] 建立 `CRITICAL_FLOW_SPECS` 作为单一来源，覆盖账户授权拉取、批创提交、提交结果状态、任务状态、监测来源/绑定、提交防超限、事件资产。
- [x] `audit_export.py` 删除本地重复 `CRITICAL_FLOW_PATTERNS`，改读共享目录。
- [x] `build_critical_flow_test_points()` 基于 `FeatureItem.source_refs` 生成 `structural_type=critical_flow` 的 P0 锚点。
- [x] 同一关键流多章节命中时只产 1 个锚点，`derived_from` 合并所有命中 source_ref。
- [x] 章节 token 使用边界匹配，避免 `§5.8.13` 误命中 `§5.8.13.1` 造成父链路覆盖虚增。
- [x] `test_points_node()` 在 `structural_coverage_enabled=True` 分支中追加关键流锚点，并与权限/状态机结构化点一起重编号。
- [x] `TestPointSchema.structural_type` 文案补充 `critical_flow`。
- [x] 补 helper 单测、去重单测、章节前缀碰撞单测、未命中单测、节点级接入单测。

验证命令：

- [x] `uv run pytest tests/testcase_generator/test_critical_flow_anchors.py -q`
- [x] `uv run pytest tests/testcase_generator/test_test_points_rule_driven.py -q`
- [x] `uv run pytest tests/testcase_generator/test_test_points_batching.py -q`
- [x] `uv run pytest tests/testcase_generator/test_generation_convergence.py -q`
- [x] `uv run pytest tests/testcase_generator/test_audit_export_module_tree.py -q`

待验证：

- [ ] 下一批真实生成后，检查 `index.json.quality_diagnostics.stable.critical_flow_coverage` 是否改善。
- [ ] 抽样 `structural_key=event_asset/submit_limit/monitoring_binding` 展开的 case，确认 write_cases 没有把关键流锚点降格成页面展示用例。

## 2026-07-03 增补：P0 用例级风险词收窄

背景：批次报告指出 stable P0 仍偏高，且页面/字段展示类用例会因父测试点 P0 继承而占用 P0。此前已新增 `calibrate_case_priority()`，但 `BUSINESS_RISK_RE` 把 `账户`、`数据`、`投放`、`状态`、`授权` 这类领域名词也当作风险信号，导致“账户列表展示账户名称/授权状态”一类纯展示 case 仍保留 P0。

文件范围：

- 修改：`src/testcase_generator/stages/write_cases/priority_calibration.py`
- 修改：`tests/testcase_generator/test_case_priority_calibration.py`
- 修改：`.audit/6f30e1bd-89ad-4e98-878c-4b48014eb1a4/REPORT.md`

实现清单：

- [x] 将 P0 保级依据从领域名词收窄到失败影响、状态变更、权限、数据副作用、接口/worker、恢复、边界、算法分配等可观察风险。
- [x] `账户授权入口列表展示账户名称、账户ID和授权状态` 这类纯展示 case 从 P0 降为 P2。
- [x] `账户授权失败时批创提交被阻止且任务不写入` 仍保持 P0。
- [x] `K>M 循环复用分配算法` 这类核心业务计算即使带提示展示，也不被误判为低价值展示。

离线复算旧批次：

- stable 执行集仍为 1848 条，旧优先级不会回写。
- 按新规则重新识别 stable 低价值展示样本：`stable_low_value_display_like_count=329`，其中 `stable_p0_low_value_display_like_count=137`。
- 旧报告中的 19 条是旧风险词口径下的保守计数；新口径会在下一批生成时实际降噪。

验证命令：

- [x] `uv run pytest tests/testcase_generator/test_case_priority_calibration.py -q`
- [x] `uv run pytest tests/testcase_generator/test_case_priority_calibration.py tests/testcase_generator/test_write_cases_cheat_sheet.py -q`
