"""provenance_tagger: derive_grounded_provenance 五分支行为快照 + quote_cache 一致性测试"""

from src.testcase_generator.stages.write_cases.provenance_tagger import derive_grounded_provenance


# ── 共用测试夹具 ──────────────────────────────────────────────────────────────────


class _Step:
    def __init__(self, q, r, er="预期"):
        self.source_quote, self.source_ref, self.expected_result = q, r, er
        self.step_number, self.action, self.input_data = 1, "a", "i"


class _Case:
    def __init__(self, steps):
        self.steps = steps


class _Sec:
    def __init__(self, ref, content):
        self.source_ref, self.heading, self.content = ref, ref, content


class _Src:
    def __init__(self, trust, secs):
        self.trust_level, self.sections = trust, secs


class _Ctx:
    def __init__(self, sources):
        self.sources, self.features = sources, []


# ── Chunk 1 Task 1: 五分支行为快照（抽函数前基线）────────────────────────────────


def test_snapshot_verified():
    """quote 是章节内容归一化子串 → verified 分支。"""
    ctx = _Ctx([_Src(1, [_Sec("PRD §1 审核", "责编可通过或驳回，驳回须填写原因。")])])
    case = _Case([_Step("驳回须填写原因", "PRD §1 审核")])
    p = derive_grounded_provenance(case, ctx)
    assert p.grounding == {"verified": 1, "fuzzy": 0, "relocated": 0, "unresolved": 0, "ref_corrected": 0}
    assert p.derived_from == ["PRD §1 审核"]
    assert p.trust_level == 1
    assert "驳回须填写原因" in p.verbatim_excerpt


def test_snapshot_fuzzy():
    """quote bigram 覆盖率 ≥ 0.8 但非子串（一字之差 须→需）→ fuzzy 分支。"""
    ctx = _Ctx([_Src(2, [_Sec("PRD §2 流程", "责编可通过或驳回，驳回须填写原因。")])])
    case = _Case([_Step("责编可通过或驳回驳回需填写原因", "PRD §2 流程")])
    p = derive_grounded_provenance(case, ctx)
    assert p.grounding == {"verified": 0, "fuzzy": 1, "relocated": 0, "unresolved": 0, "ref_corrected": 0}
    assert p.derived_from == ["PRD §2 流程"]
    assert p.trust_level == 2
    assert "责编可通过或驳回驳回需填写原因" in p.verbatim_excerpt


def test_snapshot_ref_corrected():
    """step ref 细于索引（§5.8.7 vs §5.8）→ 跨章节兜底救回，同时计 verified + ref_corrected。"""
    ctx = _Ctx([_Src(1, [_Sec("PRD §5.8 广告", "商品池由后台从巨量同步，本页不能新增商品。")])])
    case = _Case([_Step("商品池由后台从巨量同步", "PRD §5.8.7")])
    p = derive_grounded_provenance(case, ctx)
    assert p.grounding == {"verified": 1, "fuzzy": 0, "relocated": 0, "unresolved": 0, "ref_corrected": 1}
    assert p.derived_from == ["PRD §5.8 广告"]
    assert p.trust_level == 1
    assert "商品池由后台从巨量同步" in p.verbatim_excerpt


def test_snapshot_relocated():
    """ref 正确但 quote 是改写版（bigram 覆盖 <0.8）+ 跨章节未中 → relocate 兜底成功。"""
    section = "系统支持文章发布功能。文章状态包括草稿、待审核、已发布。审核驳回须填写原因。结果通知到作者邮箱。"
    ctx = _Ctx([_Src(1, [_Sec("PRD §4.1 发布", section)])])
    case = _Case([_Step("审核驳回须填写原因和备注", "PRD §4.1 发布")])
    p = derive_grounded_provenance(case, ctx)
    assert p.grounding == {"verified": 0, "fuzzy": 0, "relocated": 1, "unresolved": 0, "ref_corrected": 0}
    assert p.derived_from == ["PRD §4.1 发布"]
    assert p.trust_level == 1
    assert "驳回" in p.verbatim_excerpt


def test_snapshot_unresolved():
    """ref 有匹配章节但 quote 完全无关，跨章节 + relocate 均失败 → unresolved。"""
    ctx = _Ctx([_Src(3, [_Sec("PRD §1 概述", "系统架构说明。")])])
    case = _Case([_Step("系统支持区块链溯源存证功能", "PRD §1 概述")])
    p = derive_grounded_provenance(case, ctx)
    assert p.grounding == {"verified": 0, "fuzzy": 0, "relocated": 0, "unresolved": 1, "ref_corrected": 0}
    assert p.derived_from == ["unresolved"]
    assert p.trust_level == 3
    assert "存疑" in p.verbatim_excerpt


# ── Chunk 2 Task 3: quote_cache 同源一致性（TDD——先写失败，实现后变绿）──────────


def test_cache_same_quote_different_ref_consistent():
    """同一 quote 配不同 source_ref，传共享 quote_cache → 两条结果一致 + 只算一次。"""
    ctx = _Ctx([_Src(1, [_Sec("PRD §1 审核", "责编可通过或驳回，驳回须填写原因。")])])
    quote = "驳回须填写原因"
    # case1: ref 正确 → verified
    case1 = _Case([_Step(quote, "PRD §1 审核")])
    # case2: ref 不存在于索引 → 会走跨章节兜底（也应 verified）
    case2 = _Case([_Step(quote, "PRD §9.9 不存在")])

    cache: dict = {}
    p1 = derive_grounded_provenance(case1, ctx, quote_cache=cache)
    p2 = derive_grounded_provenance(case2, ctx, quote_cache=cache)

    # 同源一致
    assert p1.grounding == p2.grounding
    assert p1.derived_from == p2.derived_from
    assert p1.trust_level == p2.trust_level

    # 缓存命中：两次调用，quote 只被解析一次（cache 有且只有 1 个 key）
    assert len(cache) == 1
