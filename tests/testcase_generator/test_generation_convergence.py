"""生成侧收敛测试：拆条上限 + 存在性合并 + P0 配额。"""

from __future__ import annotations

from src.testcase_generator.schemas.test_case import (
    GeneratedTestCase,
    Provenance,
    TestStep,
)
from src.testcase_generator.schemas.test_point import TestPointSchema


def _provenance(*, derived_from: list[str] | None = None, source_section: str = "§5.1") -> Provenance:
    return Provenance(
        derived_from=derived_from or [],
        source_section=source_section,
        verbatim_excerpt="摘录",
        trust_level=3,
    )


def _step(action: str = "执行操作", expected: str = "预期结果") -> TestStep:
    return TestStep(step_number=1, action=action, input_data="", expected_result=expected)


def _case(
    case_id: str,
    *,
    test_point_id: str = "TP-1",
    title: str = "标题包名称字数边界校验",
    dimensions: list[str] | None = None,
    steps: list[TestStep] | None = None,
    expected_results: list[str] | None = None,
    derived_from: list[str] | None = None,
    source_section: str = "§5.1",
    priority: str = "P1",
) -> GeneratedTestCase:
    return GeneratedTestCase(
        id=case_id,
        test_point_id=test_point_id,
        title=title,
        preconditions=[],
        steps=steps if steps is not None else [_step()],
        expected_results=expected_results if expected_results is not None else ["预期正常"],
        priority=priority,
        dimensions=dimensions or ["功能正确性"],
        provenance=_provenance(derived_from=derived_from, source_section=source_section),
        trust_level=3,
    )


# ── 4.1 拆条上限 ──────────────────────────────────────────────────────────


def test_cap_cases_per_testpoint_keeps_representatives_and_respects_cap():
    from src.testcase_generator.stages.write_cases.convergence import cap_cases_per_testpoint

    # TP-1 有 6 条：2 边界、3 不同 dimension、1 普通功能正确性
    cases = [
        _case("TC-1", test_point_id="TP-1", title="字数恰好等于上限的边界校验", dimensions=["边界"]),
        _case("TC-2", test_point_id="TP-1", title="字数超过上限的边界校验", dimensions=["边界"]),
        _case("TC-3", test_point_id="TP-1", title="功能正确性校验", dimensions=["功能正确性"]),
        _case("TC-4", test_point_id="TP-1", title="性能校验", dimensions=["性能"]),
        _case("TC-5", test_point_id="TP-1", title="安全校验", dimensions=["安全"]),
        _case("TC-6", test_point_id="TP-1", title="普通功能校验", dimensions=["功能正确性"]),
        # TP-2 仅 1 条 → 不动
        _case("TC-7", test_point_id="TP-2", title="另一测试点用例"),
    ]

    kept = cap_cases_per_testpoint(cases, n=3)

    by_tp: dict[str, list[GeneratedTestCase]] = {}
    for c in kept:
        by_tp.setdefault(c.test_point_id, []).append(c)

    # 每 tp ≤ n
    assert len(by_tp["TP-1"]) <= 3
    assert len(by_tp["TP-2"]) == 1  # 单条 tp 不动

    kept_ids = {c.id for c in by_tp["TP-1"]}
    # 边界条至少留一条（边界优先保留）
    assert "TC-1" in kept_ids or "TC-2" in kept_ids
    # 不同 dimension 尽量各留代表（边界/性能/安全 至少有一个代表在）
    kept_dims = {c.dimensions[0] for c in by_tp["TP-1"] if c.dimensions}
    assert len(kept_dims) >= 2  # 3 条至少覆盖 2 个不同维度


def test_cap_cases_per_testpoint_marks_culled_as_duplicate_of():
    from src.testcase_generator.stages.write_cases.convergence import cap_cases_per_testpoint

    cases = [
        _case("TC-1", test_point_id="TP-1", title="用例A", dimensions=["功能正确性"]),
        _case("TC-2", test_point_id="TP-1", title="用例B", dimensions=["性能"]),
        _case("TC-3", test_point_id="TP-1", title="用例C", dimensions=["安全"]),
        _case("TC-4", test_point_id="TP-1", title="用例D", dimensions=["兼容"]),
    ]

    kept = cap_cases_per_testpoint(cases, n=2)

    kept_ids = {c.id for c in kept}
    culled = [c for c in cases if c.id not in kept_ids]
    # 被裁用例软标记 duplicate_of 指向保留代表（可恢复，不硬删）
    assert len(culled) == 2
    assert all(c.duplicate_of in kept_ids for c in culled)


def test_cap_cases_per_testpoint_guardrail_keeps_min_one_per_tp():
    from src.testcase_generator.stages.write_cases.convergence import cap_cases_per_testpoint

    # TP-1 有 4 条，n=1 时仍至少留 1 条（边界优先）
    cases = [
        _case("TC-1", test_point_id="TP-1", title="字数恰好等于上限的边界校验"),
        _case("TC-2", test_point_id="TP-1", title="用例B"),
        _case("TC-3", test_point_id="TP-1", title="用例C"),
        _case("TC-4", test_point_id="TP-1", title="用例D"),
    ]

    kept = cap_cases_per_testpoint(cases, n=1)

    # 每 tp 至少 1 条
    assert len(kept) == 1
    # 边界条优先保留
    assert kept[0].id == "TC-1"
    # 被裁的软标记 duplicate_of 指向保留代表
    culled = [c for c in cases if c.id != kept[0].id]
    assert all(c.duplicate_of == "TC-1" for c in culled)


def test_cap_cases_per_testpoint_does_not_cull_when_under_cap():
    from src.testcase_generator.stages.write_cases.convergence import cap_cases_per_testpoint

    cases = [
        _case("TC-1", test_point_id="TP-1", title="用例A"),
        _case("TC-2", test_point_id="TP-1", title="用例B"),
    ]

    kept = cap_cases_per_testpoint(cases, n=3)

    # 未超上限 → 不动，无 duplicate_of 标记
    assert {c.id for c in kept} == {"TC-1", "TC-2"}
    assert all(c.duplicate_of is None for c in kept)


def test_cap_prefers_dimension_coverage_over_boundary_monopoly():
    """Step1：复现 boundary 垄断缺陷。同 TP 20 boundary + 7 functional + 7 invalid，
    n=3 必须保留三类维度各至少一条，而非三条 boundary。"""
    from src.testcase_generator.stages.write_cases.convergence import cap_cases_per_testpoint

    cases = []
    for i in range(20):
        cases.append(
            _case(f"TC-B{i}", test_point_id="TP-fat", title=f"字数恰好等于{i}的边界校验", dimensions=["boundary_value"])
        )
    for i in range(7):
        cases.append(
            _case(
                f"TC-F{i}",
                test_point_id="TP-fat",
                title=f"主流程功能正确性校验{i}",
                dimensions=["functional_correctness"],
            )
        )
    for i in range(7):
        cases.append(
            _case(f"TC-I{i}", test_point_id="TP-fat", title=f"非法输入拦截校验{i}", dimensions=["invalid_input"])
        )

    kept = cap_cases_per_testpoint(cases, n=3)

    kept_dims = {dim for case in kept for dim in case.dimensions}
    assert kept_dims >= {"boundary_value", "functional_correctness", "invalid_input"}
    assert len(kept) <= 3


def test_cap_secondary_dimension_contributes_new_coverage():
    """Step2：case 的 dimensions=["boundary_value","invalid_input"] 时，invalid_input
    也能作为覆盖新增参与选择，不只看首维度。

    TC-2 故意放在第 3 位：旧实现只看 dimensions[0] 时，4 条首维全是 boundary_value，
    排序取前 2 条会选 TC-1/TC-3（纯 boundary），TC-2 不会被保留；新实现因 TC-2 的第二
    维度 invalid_input 带来新增覆盖才选它——这样未来若退回"只看首维"该测试会失败。"""
    from src.testcase_generator.stages.write_cases.convergence import cap_cases_per_testpoint

    cases = [
        # 首维都是 boundary_value，但第三条带 invalid_input 第二维度
        _case("TC-1", test_point_id="TP-1", title="字数恰好等于上限的边界校验", dimensions=["boundary_value"]),
        _case("TC-3", test_point_id="TP-1", title="另一个纯边界校验", dimensions=["boundary_value"]),
        _case(
            "TC-2", test_point_id="TP-1", title="非法输入拦截边界校验", dimensions=["boundary_value", "invalid_input"]
        ),
        _case("TC-4", test_point_id="TP-1", title="再一个纯边界校验", dimensions=["boundary_value"]),
    ]

    kept = cap_cases_per_testpoint(cases, n=2)

    # TC-2 的 invalid_input 第二维度应参与新增覆盖，使 TC-2 被保留（而非前两条纯 boundary）
    assert "TC-2" in {c.id for c in kept}


def test_cap_all_boundary_prefers_distinct_boundary_numbers():
    """Step2：同 TP 全部 boundary_value 时，n=3 优先保留不同数字集合的边界 case，
    而非任意三条。"""
    from src.testcase_generator.stages.write_cases.convergence import cap_cases_per_testpoint

    cases = [
        _case("TC-1", test_point_id="TP-1", title="字数恰好等于20的边界校验", dimensions=["boundary_value"]),
        _case("TC-2", test_point_id="TP-1", title="字数恰好等于20的另一个边界校验", dimensions=["boundary_value"]),
        _case("TC-3", test_point_id="TP-1", title="字数恰好等于100的边界校验", dimensions=["boundary_value"]),
        _case("TC-4", test_point_id="TP-1", title="字数恰好等于1000的边界校验", dimensions=["boundary_value"]),
    ]

    kept = cap_cases_per_testpoint(cases, n=3)

    # 保留的三条应覆盖不同数字集合（20/100/1000），而非 20/20/100
    kept_ids = {c.id for c in kept}
    # TC-3(100) 和 TC-4(1000) 必留（不同数字），TC-1/TC-2 二选一（都是 20）
    assert "TC-3" in kept_ids
    assert "TC-4" in kept_ids
    assert "TC-1" in kept_ids or "TC-2" in kept_ids


def test_cap_boundary_num_uses_set_semantics_not_repeat_counts():
    """同一数字重复出现不应制造假覆盖挤掉真正不同的边界值。复现 review 第三轮 P1：
    旧实现 boundary_num 保留重复次数，'20' 出现三次变 '20,20,20' 与 '20' 被当成不同覆盖，
    导致 cap=2 保两个 20、裁掉真正不同的 100。集合语义下 20 与 20/20/20 等价。"""
    from src.testcase_generator.stages.write_cases.convergence import cap_cases_per_testpoint

    cases = [
        # A: 标题含一个 20 → boundary_num:20
        _case("TC-1", test_point_id="TP-1", title="字数恰好等于20的边界校验", dimensions=["boundary_value"]),
        # B: 标题+预期多次出现 20 → 旧实现 boundary_num:20,20,20，与 A 被当成不同覆盖
        _case(
            "TC-2",
            test_point_id="TP-1",
            title="字数等于20的边界校验",
            dimensions=["boundary_value"],
            expected_results=["预期20字时拦截", "实际20字提示错误"],
        ),
        # C: 真正不同的边界值 100
        _case("TC-3", test_point_id="TP-1", title="字数恰好等于100的边界校验", dimensions=["boundary_value"]),
    ]

    kept = cap_cases_per_testpoint(cases, n=2)

    kept_ids = {c.id for c in kept}
    # 必须保 100（真正不同边界值）+ 一个 20，不能保两个 20 裹掉 100
    assert "TC-3" in kept_ids
    assert ("TC-1" in kept_ids) != ("TC-2" in kept_ids)  # 两个 20 二选一


def test_cap_all_boundary_prefers_distinct_boundary_kinds_without_numbers():
    """无数字的边界形态（为空/超长/最大/最小）不能互相等价被裁：4 条映射到 4 种不同
    boundary_kind，n=2 必须保留两种不同形态代表。复现 review P1：旧实现把它们当成
    同一种 boundary（无 boundary_kind atom），4 条 atoms 全相同，前两条被任意保留。"""
    from src.testcase_generator.stages.write_cases.convergence import (
        _case_coverage_atoms,
        cap_cases_per_testpoint,
    )

    cases = [
        _case("TC-1", test_point_id="TP-1", title="名称为空值的边界校验", dimensions=["boundary_value"]),
        _case("TC-2", test_point_id="TP-1", title="名称超长的边界校验", dimensions=["boundary_value"]),
        _case("TC-3", test_point_id="TP-1", title="名称最大长度的边界校验", dimensions=["boundary_value"]),
        _case("TC-4", test_point_id="TP-1", title="名称最小长度的边界校验", dimensions=["boundary_value"]),
    ]

    kept = cap_cases_per_testpoint(cases, n=2)

    # 保留的两条必须覆盖 ≥2 种不同 boundary_kind（不能两条同形态）
    kept_kinds: set[str] = set()
    for c in kept:
        kept_kinds |= {a for a in _case_coverage_atoms(c) if a.startswith("boundary_kind:")}
    assert len(kept_kinds) >= 2, f"保留集 boundary_kind 过少：{kept_kinds}"


# ── 4.1 cap coverage debt 报告 ──────────────────────────────────────────────


def test_analyze_cap_coverage_debt_reports_dropped_boundary_kinds():
    """被裁的无数字边界形态必须计入 dropped_boundary_atoms，has_debt=True。
    复现 review P1：旧 debt analyzer 只认 boundary_num:*，漏报无数字边界形态。"""
    from src.testcase_generator.stages.write_cases.convergence import (
        analyze_cap_coverage_debt,
        cap_cases_per_testpoint,
    )

    cases = [
        _case("TC-1", test_point_id="TP-1", title="名称为空值的边界校验", dimensions=["boundary_value"]),
        _case("TC-2", test_point_id="TP-1", title="名称超长的边界校验", dimensions=["boundary_value"]),
        _case("TC-3", test_point_id="TP-1", title="名称最大长度的边界校验", dimensions=["boundary_value"]),
        _case("TC-4", test_point_id="TP-1", title="名称最小长度的边界校验", dimensions=["boundary_value"]),
    ]

    kept = cap_cases_per_testpoint(cases, n=2)
    debt = analyze_cap_coverage_debt(cases, kept)

    # 被裁的边界形态（如 min/max/empty/overlong 之类）必须被报告，不能为空
    assert len(debt.dropped_boundary_atoms) >= 1
    assert debt.has_debt is True


def test_boundary_kind_does_not_conflate_buchao_with_chao():
    """「不超过上限」(合法上限内) 与「超过上限」(越界拦截) 是两种不同覆盖，不能都生成 overlong。
    复现 review 第二轮 P1：旧 overlong regex 含「超过」，「不超过」会同时命中 max+overlong，
    与「超过」atom 完全相同，越界覆盖被静默丢失。"""
    from src.testcase_generator.stages.write_cases.convergence import _case_coverage_atoms

    within = _case("TC-1", test_point_id="TP-1", title="金额不超过上限时允许提交", dimensions=["boundary_value"])
    beyond = _case("TC-2", test_point_id="TP-1", title="金额超过上限时拦截提交", dimensions=["boundary_value"])

    within_kinds = {a for a in _case_coverage_atoms(within) if a.startswith("boundary_kind:")}
    beyond_kinds = {a for a in _case_coverage_atoms(beyond) if a.startswith("boundary_kind:")}

    # 「不超过」属上限内合法行为 → max，不应产生 overlong
    assert "boundary_kind:overlong" not in within_kinds
    assert "boundary_kind:max" in within_kinds
    # 「超过」属越界 → overlong
    assert "boundary_kind:overlong" in beyond_kinds


def test_cap_debt_reports_overlong_when_beyond_dropped_but_within_kept():
    """「不超过」(max) 与「超过」(max+overlong) 分类不同：当「超过」被裁而「不超过」被留时，
    debt 必须报告 overlong——被裁的越界形态是独立覆盖，不能漏报。

    直接测 analyze_cap_coverage_debt helper：贪心实际会留覆盖更广的「超过」，故这里手工
    指定 kept=[不超过] 以验证「当超过被裁时 debt 正确报告 overlong」这一契约。"""
    from src.testcase_generator.stages.write_cases.convergence import analyze_cap_coverage_debt

    within = _case("TC-1", test_point_id="TP-1", title="金额不超过上限时允许提交", dimensions=["boundary_value"])
    beyond = _case("TC-2", test_point_id="TP-1", title="金额超过上限时拦截提交", dimensions=["boundary_value"])

    # 手工指定保留「不超过」，裁掉「超过」
    debt = analyze_cap_coverage_debt([within, beyond], [within])

    # 被裁的「超过」越界形态必须被报告
    assert "overlong" in debt.dropped_boundary_atoms
    assert debt.has_debt is True


# ── 4.1 cap coverage debt 报告（既有）──────────────────────────────────────


def test_analyze_cap_coverage_debt_reports_dropped_dimensions():
    """cap 小于独立维度数时，debt helper 必须报告被裁掉的维度，has_debt=True。"""
    from src.testcase_generator.stages.write_cases.convergence import (
        analyze_cap_coverage_debt,
        cap_cases_per_testpoint,
    )

    cases = []
    for i in range(5):
        cases.append(
            _case(f"TC-A{i}", test_point_id="TP-fat", title=f"功能正确性校验{i}", dimensions=["functional_correctness"])
        )
    for i in range(5):
        cases.append(
            _case(f"TC-B{i}", test_point_id="TP-fat", title=f"非法输入拦截校验{i}", dimensions=["invalid_input"])
        )
    for i in range(5):
        cases.append(_case(f"TC-C{i}", test_point_id="TP-fat", title=f"权限控制校验{i}", dimensions=["access_control"]))

    kept = cap_cases_per_testpoint(cases, n=2)
    debt = analyze_cap_coverage_debt(cases, kept)

    assert debt.test_point_id == "TP-fat"
    assert debt.total == 15
    assert len(debt.kept_ids) == 2
    assert len(debt.dropped_ids) == 13
    # n=2 < 3 个独立维度 → 至少一个维度被整体裁掉
    assert len(debt.dropped_dimensions) >= 1
    assert set(debt.dropped_dimensions) <= {"functional_correctness", "invalid_input", "access_control"}
    assert debt.has_debt is True


def test_analyze_cap_coverage_debt_no_debt_when_drops_add_no_new_coverage():
    """被裁 case 不带任何新 atom（同维度同边界同章节重复）时，has_debt=False。"""
    from src.testcase_generator.stages.write_cases.convergence import (
        analyze_cap_coverage_debt,
        cap_cases_per_testpoint,
    )

    cases = [
        _case(
            "TC-1",
            test_point_id="TP-1",
            title="功能正确性校验A",
            dimensions=["functional_correctness"],
            source_section="§5.1",
        ),
        _case(
            "TC-2",
            test_point_id="TP-1",
            title="功能正确性校验B",
            dimensions=["functional_correctness"],
            source_section="§5.1",
        ),
        _case(
            "TC-3",
            test_point_id="TP-1",
            title="功能正确性校验C",
            dimensions=["functional_correctness"],
            source_section="§5.1",
        ),
        _case(
            "TC-4",
            test_point_id="TP-1",
            title="功能正确性校验D",
            dimensions=["functional_correctness"],
            source_section="§5.1",
        ),
    ]

    kept = cap_cases_per_testpoint(cases, n=1)
    debt = analyze_cap_coverage_debt(cases, kept)

    # 全同维度/同章节/无边界数字 → 被裁 case 不贡献新 atom → 无 debt（纯冗余裁剪）
    assert debt.dropped_dimensions == []
    assert debt.dropped_source_sections == []
    assert debt.has_debt is False


# ── 4.2 存在性合并 ──────────────────────────────────────────────────────────


def test_merge_existence_cases_combines_pure_display_checks():
    from src.testcase_generator.stages.write_cases.convergence import merge_existence_cases

    # 同 tp 同 section 下 3 条"仅 1 步存在性"用例
    cases = [
        _case(
            "TC-1",
            test_point_id="TP-1",
            title="页面展示标题字段",
            source_section="§5.6",
            steps=[_step(action="打开页面", expected="页面展示标题字段")],
            expected_results=["页面展示标题字段"],
        ),
        _case(
            "TC-2",
            test_point_id="TP-1",
            title="页面显示描述字段",
            source_section="§5.6",
            steps=[_step(action="打开页面", expected="页面显示描述字段")],
            expected_results=["页面显示描述字段"],
        ),
        _case(
            "TC-3",
            test_point_id="TP-1",
            title="页面包含状态字段",
            source_section="§5.6",
            steps=[_step(action="打开页面", expected="页面包含状态字段")],
            expected_results=["页面包含状态字段"],
        ),
    ]

    merged = merge_existence_cases(cases)

    # 合并为 1 条
    assert len(merged) == 1
    # 全部检查点保留（不丢覆盖）
    combined = " ".join(merged[0].expected_results)
    assert "标题字段" in combined
    assert "描述字段" in combined
    assert "状态字段" in combined


def test_merge_existence_cases_does_not_merge_judgement_cases():
    from src.testcase_generator.stages.write_cases.convergence import merge_existence_cases

    # 含判定步骤的用例（步数≥2 或含输入/校验）不参与合并
    cases = [
        _case(
            "TC-1",
            test_point_id="TP-1",
            title="页面展示标题字段",
            source_section="§5.6",
            steps=[_step(action="打开页面", expected="页面展示标题字段")],
        ),
        _case(
            "TC-2",
            test_point_id="TP-1",
            title="校验标题字数上限",
            source_section="§5.6",
            steps=[
                _step(action="输入超长标题", expected="校验拦截并提示错误"),
                _step(action="提交", expected="保存失败"),
            ],
        ),
    ]

    merged = merge_existence_cases(cases)

    # 判定型用例不并 → 仍 2 条
    assert len(merged) == 2
    assert {c.id for c in merged} == {"TC-1", "TC-2"}


def test_merge_existence_cases_does_not_merge_across_tp_or_section():
    from src.testcase_generator.stages.write_cases.convergence import merge_existence_cases

    cases = [
        _case(
            "TC-1",
            test_point_id="TP-1",
            title="页面展示字段A",
            source_section="§5.6",
            steps=[_step(expected="页面展示字段A")],
        ),
        _case(
            "TC-2",
            test_point_id="TP-1",
            title="页面展示字段B",
            source_section="§5.7",  # 不同 section
            steps=[_step(expected="页面展示字段B")],
        ),
        _case(
            "TC-3",
            test_point_id="TP-2",
            title="页面展示字段C",
            source_section="§5.6",  # 不同 tp
            steps=[_step(expected="页面展示字段C")],
        ),
    ]

    merged = merge_existence_cases(cases)

    # 不同 tp / 不同 section 不并 → 3 条
    assert len(merged) == 3


def test_merge_existence_cases_keeps_non_existence_untouched():
    from src.testcase_generator.stages.write_cases.convergence import merge_existence_cases

    # 单条存在性 + 一条多步判定型，互不干扰
    cases = [
        _case(
            "TC-1",
            test_point_id="TP-1",
            title="页面默认选中第一项",
            source_section="§5.6",
            steps=[_step(expected="页面默认选中第一项")],
        ),
        _case(
            "TC-2",
            test_point_id="TP-1",
            title="切换选项后保存生效",
            source_section="§5.6",
            steps=[_step(action="切换选项", expected="切换成功"), _step(action="点击保存", expected="保存成功")],
        ),
    ]

    merged = merge_existence_cases(cases)

    assert len(merged) == 2
    # 判定型用例 steps 不被改写
    judge = next(c for c in merged if c.id == "TC-2")
    assert len(judge.steps) == 2


def test_cap_marks_merged_representatives_as_duplicate_for_culled_stats():
    """merge 产出的 model_copy 代表被 cap 裁掉时，merged 列表里该代表必须被置 duplicate_of。
    复现 review 第二轮 P2：离线脚本 culled_by_cap 若从原始 cases 推导会漏统计被裁的合并代表；
    本测试锁定 cap 对 merged 代表的原地标记契约，使 culled 可从 merged 正确统计。"""
    from src.testcase_generator.stages.write_cases.convergence import (
        cap_cases_per_testpoint,
        merge_existence_cases,
    )

    # 2 个 section，每 section 2 条存在性 → merge 产出 2 个 model_copy 代表
    cases = [
        _case(
            "TC-1a", test_point_id="TP-1", title="展示字段A1", source_section="§5.6", steps=[_step(expected="展示A1")]
        ),
        _case(
            "TC-1b", test_point_id="TP-1", title="展示字段A2", source_section="§5.6", steps=[_step(expected="展示A2")]
        ),
        _case(
            "TC-2a", test_point_id="TP-1", title="展示字段B1", source_section="§5.7", steps=[_step(expected="展示B1")]
        ),
        _case(
            "TC-2b", test_point_id="TP-1", title="展示字段B2", source_section="§5.7", steps=[_step(expected="展示B2")]
        ),
    ]

    merged = merge_existence_cases(cases)
    assert len(merged) == 2  # 2 个 section → 2 个合并代表

    kept = cap_cases_per_testpoint(merged, n=1)

    # cap 裁掉 1 个合并代表；该代表在 merged 列表里被置 duplicate_of（可被 culled 统计）
    culled_from_merged = [c for c in merged if c.duplicate_of is not None]
    assert len(kept) == 1
    assert len(culled_from_merged) == 1
    # 原始 cases 不被标记（合并代表是 model_copy，非原始对象）
    assert all(c.duplicate_of is None for c in cases)


# ── 接入 apply_convergence（开关因果链）─────────────────────────────────────


def _settings(*, existence_merge=False, split_cap=False, cases_per_tp_cap=3):
    """构造只含 ⑥ 后处理所需字段的假 settings（apply_convergence 仅读这 3 个）。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        existence_merge_enabled=existence_merge,
        split_cap_enabled=split_cap,
        cases_per_tp_cap=cases_per_tp_cap,
    )


def _conv_cases():
    """5 条同 tp 用例：4 条存在性（展示/显示/包含/默认选中）+ 1 条判定型（2 步含校验）。"""
    return [
        _case(
            "TC-1",
            test_point_id="TP-1",
            title="页面展示标题字段",
            source_section="§5.6",
            steps=[_step(action="打开页面", expected="页面展示标题字段")],
            expected_results=["页面展示标题字段"],
        ),
        _case(
            "TC-2",
            test_point_id="TP-1",
            title="页面显示描述字段",
            source_section="§5.6",
            steps=[_step(action="打开页面", expected="页面显示描述字段")],
            expected_results=["页面显示描述字段"],
        ),
        _case(
            "TC-3",
            test_point_id="TP-1",
            title="页面包含状态字段",
            source_section="§5.6",
            steps=[_step(action="打开页面", expected="页面包含状态字段")],
            expected_results=["页面包含状态字段"],
        ),
        _case(
            "TC-4",
            test_point_id="TP-1",
            title="页面默认选中第一项",
            source_section="§5.6",
            steps=[_step(action="打开页面", expected="页面默认选中第一项")],
            expected_results=["页面默认选中第一项"],
        ),
        _case(
            "TC-5",
            test_point_id="TP-1",
            title="校验标题字数上限",
            source_section="§5.6",
            steps=[_step(action="输入超长标题", expected="校验拦截"), _step(action="提交", expected="保存失败")],
            expected_results=["保存失败"],
        ),
    ]


def test_apply_convergence_disabled_keeps_all():
    """两开关关：5 条原样返回，不合并不裁剪（逐字节现状）。"""
    from src.testcase_generator.stages.write_cases.convergence import apply_convergence

    result = apply_convergence(_conv_cases(), _settings())

    assert len(result) == 5
    assert all(c.duplicate_of is None for c in result)


def test_apply_convergence_existence_merge_reduces_count():
    """开 existence_merge：4 存在性合 1 + 1 判定 = 2 条，检查点全保留，判定型不被动。"""
    from src.testcase_generator.stages.write_cases.convergence import apply_convergence

    result = apply_convergence(_conv_cases(), _settings(existence_merge=True))

    assert len(result) == 2
    judge = next(c for c in result if "校验" in c.title)
    assert len(judge.steps) == 2  # 判定型 steps 不被改写
    merged = next(c for c in result if "校验" not in c.title)
    combined = " ".join(merged.expected_results)
    assert "标题字段" in combined and "描述字段" in combined and "状态字段" in combined and "第一项" in combined


def test_apply_convergence_split_cap_culls_to_cap():
    """开 split_cap n=3：5 条裁到 ≤3，被裁不进主集，保留集无 duplicate_of。"""
    from src.testcase_generator.stages.write_cases.convergence import apply_convergence

    result = apply_convergence(_conv_cases(), _settings(split_cap=True, cases_per_tp_cap=3))

    assert len(result) <= 3
    assert all(c.duplicate_of is None for c in result)


def test_apply_convergence_both_enabled_merge_then_cap():
    """双开：先合并（4 存在性→1）得 2 条，再裁剪 n=3 不触发（2<3）→ 2 条。"""
    from src.testcase_generator.stages.write_cases.convergence import apply_convergence

    result = apply_convergence(_conv_cases(), _settings(existence_merge=True, split_cap=True, cases_per_tp_cap=3))

    assert len(result) == 2


# ── 4.3 P0 配额 ─────────────────────────────────────────────────────────────


def _tp(
    tp_id: str,
    *,
    priority: str = "P0",
    likelihood: int | None = 2,
    impact: int | None = 2,
    structural_type: str | None = None,
    rule_id: str | None = None,
) -> TestPointSchema:
    return TestPointSchema(
        id=tp_id,
        feature_id="F-1",
        dimension="functional_correctness",
        description=f"测试点 {tp_id}",
        priority=priority,
        likelihood=likelihood,
        impact=impact,
        structural_type=structural_type,
        rule_id=rule_id,
    )


def test_apply_p0_quota_caps_p0_to_quotakeeping_highest_risk():
    from src.testcase_generator.stages.test_points.node import apply_p0_quota

    # 10 个非结构化测试点，全 P0（risk 各异），quota=0.30 → 最多 3 个 P0
    tps = [
        _tp("TP-1", likelihood=3, impact=3),  # risk=9 最高
        _tp("TP-2", likelihood=3, impact=2),  # risk=6
        _tp("TP-3", likelihood=2, impact=3),  # risk=6
        _tp("TP-4", likelihood=2, impact=2),  # risk=4
        _tp("TP-5", likelihood=2, impact=2),  # risk=4
        _tp("TP-6", likelihood=1, impact=3),  # risk=3
        _tp("TP-7", likelihood=1, impact=2),  # risk=2
        _tp("TP-8", likelihood=2, impact=1),  # risk=2
        _tp("TP-9", likelihood=1, impact=1),  # risk=1
        _tp("TP-10", likelihood=1, impact=1),  # risk=1
    ]

    result = apply_p0_quota(tps, quota=0.30)

    p0 = [t for t in result if t.priority == "P0"]
    assert len(p0) <= 3  # 配额内
    # 保留的是 risk 最高者（TP-1 risk=9 必留）
    assert "TP-1" in {t.id for t in p0}


def test_apply_p0_quota_exempts_structural_coverage_points():
    from src.testcase_generator.stages.test_points.node import apply_p0_quota

    # 结构化覆盖点（structural_type/rule_id 非空）豁免配额，不被降级
    tps = [
        _tp("TP-1", likelihood=3, impact=3, structural_type="permission"),  # 结构化 P0 豁免
        _tp("TP-2", likelihood=3, impact=3, rule_id="R-001"),  # 规则锚点 P0 豁免
        _tp("TP-3", likelihood=1, impact=1),  # 非结构化 P0 risk=1
        _tp("TP-4", likelihood=1, impact=1),  # 非结构化 P0 risk=1
        _tp("TP-5", likelihood=1, impact=1),  # 非结构化 P0 risk=1
    ]

    result = apply_p0_quota(tps, quota=0.30)

    by_id = {t.id: t.priority for t in result}
    # 结构化覆盖点保持 P0（豁免）
    assert by_id["TP-1"] == "P0"
    assert by_id["TP-2"] == "P0"


def test_apply_p0_quota_does_not_touch_p2():
    from src.testcase_generator.stages.test_points.node import apply_p0_quota

    tps = [
        _tp("TP-1", priority="P2", likelihood=1, impact=1),
        _tp("TP-2", priority="P2", likelihood=1, impact=1),
    ]

    result = apply_p0_quota(tps, quota=0.30)

    # P2 不动
    assert all(t.priority == "P2" for t in result)


def test_apply_p0_quota_stable_order_for_same_risk():
    from src.testcase_generator.stages.test_points.node import apply_p0_quota

    # 4 个同 risk P0，quota=0.30 → 最多 1 个 P0（4*0.3=1.2→1），其余降 P1
    # 同 risk 稳定序：保留首个（原顺序）
    tps = [
        _tp("TP-1", likelihood=2, impact=2),
        _tp("TP-2", likelihood=2, impact=2),
        _tp("TP-3", likelihood=2, impact=2),
        _tp("TP-4", likelihood=2, impact=2),
    ]

    result = apply_p0_quota(tps, quota=0.30)

    p0_ids = {t.id for t in result if t.priority == "P0"}
    assert len(p0_ids) == 1
    # 同 risk 稳定序保留首条
    assert "TP-1" in p0_ids
