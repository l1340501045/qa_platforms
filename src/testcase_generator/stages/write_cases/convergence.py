"""生成侧收敛后处理：拆条上限 + 存在性合并。

纯函数、确定、可单测、可离线评估。关时调用方不调用，逐字节现状。
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from src.platform_api.core.settings import Settings
from src.testcase_generator.schemas.test_case import GeneratedTestCase, TestStep
from src.testcase_generator.stages.dedup.clustering import _BOUNDARY_KW

# 存在性用例：步数 ≤1 且标题/预期为纯展示断言（无判定词）
_EXISTENCE_KW = re.compile(r"展示|显示|包含|存在|布局|默认选中|呈现|可见|列出|提供")
_JUDGEMENT_KW = re.compile(r"输入|校验|拦截|错误|失败|提交|保存|删除|修改|触发|校对|验证|检查")

# 边界数字提取（与 dedup.clustering._NUM 等价，避免跨模块 import 私有常量）
_NUM = re.compile(r"\d+(?:\.\d+)?")

# 边界形态分类：从 _BOUNDARY_KW 命中的关键词派生 kind，让无数字边界形态（为空/超长/
# 最大/最小等）也能互相区分，避免塌缩成同一组 atoms 被误裁。顺序无关——每个命中的 kind
# 独立生成一个 atom。覆盖 _BOUNDARY_KW 全部关键词，未命中任何子类时仅保留 ``boundary`` 兜底。
_BOUNDARY_KINDS: list[tuple[str, re.Pattern[str]]] = [
    ("empty", re.compile(r"为空|空态|空值")),
    ("overlong", re.compile(r"超长|超量|超出|(?<!不)超过|溢出|越界")),
    ("max", re.compile(r"上限|最大|至多|不超过")),
    ("min", re.compile(r"下限|最小|至少")),
    ("exact", re.compile(r"恰好|刚好|等于")),
    ("critical", re.compile(r"临界")),
    ("first", re.compile(r"第一|首条|起始")),
    ("last", re.compile(r"末条|最后|最末|结尾")),
]

# 贪心最大新增覆盖权重：维度新增必须压过 boundary bonus，保证维度多样性优先
_DIM_WEIGHT = 1000  # 每个新维度 atom
_OTHER_ATOM_WEIGHT = 100  # 每个新非维度 atom（boundary_num/source 等，boundary 本身见下）
_BOUNDARY_BONUS = 20  # boundary 语义加权（仅作 tie-break，不能压过维度新增）
_PRIORITY_WEIGHT = 10  # priority 加权
_PRIORITY_SCORE = {"P0": 4, "P1": 3, "P2": 2, "P3": 1}


def _case_text(case: GeneratedTestCase) -> str:
    """拼接 case 全量文本用于边界/数字检测：title + expected_results + steps.expected_result。

    boundary 检测必须覆盖标题之外的预期/步骤预期，否则只命中标题的边界 case 会被漏识别。
    """
    parts = [case.title or ""]
    parts.extend(case.expected_results or [])
    for s in case.steps:
        parts.append(s.expected_result or "")
    return " ".join(parts)


def _case_coverage_atoms(case: GeneratedTestCase) -> set[str]:
    """计算单条 case 的覆盖 atoms。

    - ``dim:<dimension>``：遍历 **全部** ``case.dimensions``（去空、保序去重），不只看首维。
    - ``boundary``：文本（title+expected+steps）命中 ``_BOUNDARY_KW`` 的边界/异常语义。
    - ``boundary_kind:<kind>``：边界形态类别（empty/overlong/max/min/exact/critical/first/last），
      从命中的边界关键词派生。让无数字边界形态（"为空" vs "超长" vs "最大"）也能互相区分，
      避免塌缩成同一组 atoms 被误裁。仅 boundary case 才生成。
    - ``boundary_num:<sorted nums>``：边界 case 中出现的数字集合（如 ``20`` vs ``1000``），
      避免把不同边界值全当同一种边界。仅 boundary case 才生成。
    - ``source:<section>``：``provenance.source_section``，保护同 TP 跨章节来源多样性。

    不把完整 title 当高权重 atom——多数 case title 天然不同，高权重化会让选择退化为原始序。
    """
    atoms: set[str] = set()
    for dim in case.dimensions:
        dim = (dim or "").strip()
        if dim:
            atoms.add(f"dim:{dim}")

    text = _case_text(case)
    if _BOUNDARY_KW.search(text):
        atoms.add("boundary")
        # 边界形态分类：每个命中的 kind 生成独立 atom，区分"为空"/"超长"/"最大"等无数字形态
        for kind, pattern in _BOUNDARY_KINDS:
            if pattern.search(text):
                atoms.add(f"boundary_kind:{kind}")
        # 数字集合语义：去重后 sorted，避免同一数字重复出现（如标题+预期都含 20 → 20,20,20）
        # 制造假覆盖，挤掉真正不同的边界值。set 保证 20 与 20/20/20 等价。
        nums = sorted(set(_NUM.findall(text)))
        if nums:
            atoms.add(f"boundary_num:{','.join(nums)}")

    section = (case.provenance.source_section or "").strip()
    if section:
        atoms.add(f"source:{section}")

    return atoms


def cap_cases_per_testpoint(
    cases: Sequence[GeneratedTestCase],
    *,
    n: int,
) -> list[GeneratedTestCase]:
    """每测试点用例数上限裁剪（覆盖保持优先选择）。

    按 test_point_id 分组，组内超 n 时按 **贪心最大新增覆盖** 选 n 条代表，而非固定排序取前 N：
    每轮从剩余 case 中选「新增覆盖 atom 得分最高」者，维度新增（1000/atom）压过边界加权
    （20），避免边界值垄断全部名额。被裁用例**原地置 duplicate_of** 指向该 tp 保留代表
    （与 dedup 同机制、软标记可恢复、不硬删），不进返回列表。护栏：每 tp 至少留 1 条。

    注：write_cases 阶段用例不携带 rule_id（规则锚定在 test_points 层），故不按"规则锚定"
    保留——provenance.derived_from 是来源章节引用（非规则码，几乎所有用例都有），不可作
    规则锚定判据。规则级覆盖由 test_points 的 rule_id + 4.3 配额结构化豁免保证。
    """
    if n < 1:
        raise ValueError("cases_per_tp_cap 必须 ≥1")

    by_tp: dict[str, list[GeneratedTestCase]] = defaultdict(list)
    for c in cases:
        by_tp[c.test_point_id].append(c)

    kept: list[GeneratedTestCase] = []
    for tp_id, tp_cases in by_tp.items():
        if len(tp_cases) <= n:
            kept.extend(tp_cases)
            continue

        # 预计算每条 case 的 atoms 与原始输入序（用于同分稳定 tie-break）
        indexed = list(enumerate(tp_cases))
        atoms_of = {id(c): _case_coverage_atoms(c) for _, c in indexed}
        index_of = {id(c): i for i, c in indexed}

        selected: list[GeneratedTestCase] = []
        covered: set[str] = set()
        remaining = list(tp_cases)
        while len(selected) < n and remaining:
            best = None
            best_score = None
            for c in remaining:
                c_atoms = atoms_of[id(c)]
                new_atoms = c_atoms - covered
                new_dim = sum(1 for a in new_atoms if a.startswith("dim:"))
                new_other = len(new_atoms) - new_dim
                is_bdy = "boundary" in c_atoms
                priority = _PRIORITY_SCORE.get(c.priority, 1)
                # 维度新增(1000) > 非维度 atom(100) > boundary bonus(20) > priority(10)
                # > steps/expected 完整度 > 原始输入序(负 eps，早出现优先)
                score = (
                    new_dim * _DIM_WEIGHT
                    + new_other * _OTHER_ATOM_WEIGHT
                    + (_BOUNDARY_BONUS if is_bdy else 0)
                    + priority * _PRIORITY_WEIGHT
                    + len(c.steps)
                    + len(c.expected_results)
                    - index_of[id(c)] * 1e-6
                )
                if best is None or score > best_score:
                    best = c
                    best_score = score
            assert best is not None  # remaining 非空 ⇒ 必选中一条
            selected.append(best)
            covered |= atoms_of[id(best)]
            remaining.remove(best)

        kept_set = {c.id for c in selected}
        kept.extend(selected)

        # 被裁用例软标记 duplicate_of 指向该 tp 保留代表（取 selected 首条作代表）
        representative = selected[0].id
        for c in tp_cases:
            if c.id not in kept_set:
                c.duplicate_of = representative

    return kept


@dataclass(frozen=True)
class CapCoverageDebt:
    """cap 裁剪产生的覆盖债务：cap 不足以容纳所有独立覆盖时的显式报告。

    仅当被裁 case 携带 kept 集未覆盖的新 atom 时才算 debt（has_debt=True）；
    若被裁 case 都是同维度/同边界/同章节的纯冗余（无新 atom），has_debt=False——
    这是真重复裁剪，不是覆盖丢失。
    """

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


def analyze_cap_coverage_debt(
    tp_cases: Sequence[GeneratedTestCase],
    kept_cases: Sequence[GeneratedTestCase],
) -> CapCoverageDebt:
    """分析单个 test_point 的 cap 覆盖债务。

    入参 ``tp_cases`` 应为该 TP 裁剪**前**的全量用例，``kept_cases`` 为裁剪后保留集。
    比对两侧 coverage atoms：被裁 case 独有的 dim/boundary_kind/boundary_num/source 即为 dropped 覆盖。
    被 ``cap_cases_per_testpoint`` 原地置过 ``duplicate_of`` 的对象仍属"裁剪前"全集。
    """
    if not tp_cases:
        # 空 TP 无债务；test_point_id 取空串占位（调用方按 TP 分组调用，不应传入空集）
        return CapCoverageDebt(
            test_point_id="",
            total=0,
            kept_ids=[],
            dropped_ids=[],
            dropped_dimensions=[],
            dropped_boundary_atoms=[],
            dropped_source_sections=[],
        )

    tp_id = tp_cases[0].test_point_id
    kept_ids = {c.id for c in kept_cases}
    kept_atoms: set[str] = set()
    for c in kept_cases:
        kept_atoms |= _case_coverage_atoms(c)

    dropped_dims: list[str] = []
    dropped_boundary: list[str] = []
    dropped_source: list[str] = []
    dropped_ids: list[str] = []
    seen_dropped_atoms: set[str] = set()  # 去重，避免同维度多条被裁重复计入
    for c in tp_cases:
        if c.id in kept_ids:
            continue
        dropped_ids.append(c.id)
        for atom in _case_coverage_atoms(c) - kept_atoms:
            if atom in seen_dropped_atoms:
                continue
            seen_dropped_atoms.add(atom)
            if atom.startswith("dim:"):
                dropped_dims.append(atom[len("dim:") :])
            elif atom.startswith("boundary_num:"):
                dropped_boundary.append(atom[len("boundary_num:") :])
            elif atom.startswith("boundary_kind:"):
                dropped_boundary.append(atom[len("boundary_kind:") :])
            elif atom.startswith("source:"):
                dropped_source.append(atom[len("source:") :])

    return CapCoverageDebt(
        test_point_id=tp_id,
        total=len(tp_cases),
        kept_ids=[c.id for c in kept_cases],
        dropped_ids=dropped_ids,
        dropped_dimensions=dropped_dims,
        dropped_boundary_atoms=dropped_boundary,
        dropped_source_sections=dropped_source,
    )


def _is_existence_case(case: GeneratedTestCase) -> bool:
    """存在性用例：步数 ≤1 且标题/预期为纯展示断言（命中展示词、不含判定词）。

    保守识别——含输入/校验/拦截/错误等判定语义的用例不算存在性，避免误并判定型用例。
    """
    if len(case.steps) > 1:
        return False
    text = f"{case.title or ''} {case.expected_results}"
    if not _EXISTENCE_KW.search(text):
        return False
    # 含判定词则不算纯存在性
    if _JUDGEMENT_KW.search(text):
        return False
    return True


def merge_existence_cases(cases: Sequence[GeneratedTestCase]) -> list[GeneratedTestCase]:
    """同 (test_point_id, source_section) 的存在性用例合并为 1 条"页面元素核对"用例。

    合并规则：preconditions 取并集、steps 合成 1 条"逐项核对页面元素"、expected_results
    **保留全部检查点**（不丢覆盖）、dimensions/provenance 取首条。判定型用例（步数≥2 或含
    判定词）不参与合并，原样保留。单条存在性组也原样保留（无可合并对象）。
    """
    merged: list[GeneratedTestCase] = []
    existence_groups: dict[tuple[str, str], list[GeneratedTestCase]] = defaultdict(list)
    seen_ids: set[str] = set()

    # 第一遍：分存在性组与非存在性（非存在性直接保留）
    for c in cases:
        if _is_existence_case(c):
            key = (c.test_point_id, c.provenance.source_section)
            existence_groups[key].append(c)
        else:
            merged.append(c)
            seen_ids.add(c.id)

    # 第二遍：每组 ≥2 条才合并，单条原样保留
    for (tp_id, section), group in existence_groups.items():
        if len(group) < 2:
            for c in group:
                merged.append(c)
                seen_ids.add(c.id)
            continue

        # 合并为 1 条：取首条作基底
        base = group[0]
        all_checks: list[str] = []
        preconditions: list[str] = []
        for c in group:
            # 检查点：优先取 expected_results，兜底取 steps 的 expected_result
            if c.expected_results:
                all_checks.extend(c.expected_results)
            elif c.steps:
                all_checks.append(c.steps[0].expected_result)
            for pc in c.preconditions:
                if pc not in preconditions:
                    preconditions.append(pc)

        # steps 合成 1 条"逐项核对页面元素"
        combined_step = TestStep(
            step_number=1,
            action="逐项核对页面元素",
            input_data="",
            expected_result="；".join(all_checks),
        )
        merged.append(
            base.model_copy(
                update={
                    "preconditions": preconditions,
                    "steps": [combined_step],
                    "expected_results": all_checks,
                    "title": f"{tp_id} 页面元素核对（{section}）",
                }
            )
        )

    return merged


def apply_convergence(
    cases: Sequence[GeneratedTestCase],
    settings: Settings,
) -> list[GeneratedTestCase]:
    """生成侧收敛后处理入口（roadmap ⑥，灰度、关时逐字节现状）。

    顺序：先存在性合并（同 tp 同 section 的纯展示用例合 1 条、保留全部检查点）→
    再拆条上限（每 tp 裁剪到 cap、被裁软标记 duplicate_of）。合并减条后再裁剪更准。
    两开关均关时原样返回（逐字节现状）。
    """
    result = list(cases)
    if settings.existence_merge_enabled:
        result = merge_existence_cases(result)
    if settings.split_cap_enabled:
        result = cap_cases_per_testpoint(result, n=settings.cases_per_tp_cap)
    return result
