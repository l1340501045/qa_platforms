"""落点⑥ CoT 显式化 + 溯源接地 grounded provenance 单元测试"""

from src.testcase_generator.stages.write_cases import node as wc
from src.testcase_generator.stages.write_cases.provenance_tagger import (
    _align,
    _normalize,
    derive_grounded_provenance,
)


def test_cot_section_constant_nonempty():
    assert isinstance(wc.COT_REASONING_SECTION, str) and "显式分步推理纪律" in wc.COT_REASONING_SECTION
    assert "只输出最终用例 JSON" in wc.COT_REASONING_SECTION


# ── Task 4: 归一化 + span 对齐 ──────────────────────────────────────────────────


def test_normalize_fullwidth_punct_space():
    assert _normalize("（１）审核 通过！") == _normalize("(1) 审核通过")
    assert _normalize("审核状态：待提审") == "审核状态待提审"


def test_align_verified_ignores_punct_and_space():
    sec = "字段：审核状态。取值：待提审、审核通过、审核不通过。"
    assert _align("审核状态 取值 待提审", sec) == "verified"


def test_align_fuzzy_minor_typo():
    sec = "责编可通过或驳回，驳回须填写原因。"
    assert _align("责编可通过或驳回驳回需填写原因", sec) == "fuzzy"


def test_align_unresolved_on_paraphrase_or_fabrication():
    sec = "责编可通过或驳回，驳回须填写原因。"
    assert _align("系统支持支付宝微信银联三种支付", sec) == "unresolved"
    assert _align("驳回流程大致需要走个审批", sec) == "unresolved"


# ── Task 5: 修复定位 + 派生 provenance ──────────────────────────────────────────


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


def _ctx():
    return _Ctx([_Src(1, [_Sec("PRD §3.2 审核", "责编可通过或驳回，驳回须填写原因。")])])


def test_derive_verified_quote_becomes_excerpt():
    case = _Case([_Step("驳回须填写原因", "PRD §3.2 审核")])
    p = derive_grounded_provenance(case, _ctx())
    assert "驳回须填写原因" in p.verbatim_excerpt
    assert p.grounding["verified"] == 1
    assert p.source_section == "PRD §3.2 审核"


def test_derive_unresolved_flags_not_fabricates():
    case = _Case([_Step("系统支持三种支付方式", "PRD §3.2 审核")])
    p = derive_grounded_provenance(case, _ctx())
    assert p.grounding["unresolved"] >= 1
    assert "存疑" in p.verbatim_excerpt or p.grounding["relocated"] >= 1


def test_derive_no_quote_gives_pending_excerpt():
    """待确认用例（steps 无 source_quote）应标记为"需求待确认"而非"存疑"。"""
    step = _Step("", "PRD §3.2 审核")  # source_quote 为空
    case = _Case([step])
    p = derive_grounded_provenance(case, _ctx())
    assert "需求待确认" in p.verbatim_excerpt
    assert "存疑" not in p.verbatim_excerpt


def test_derive_relocated_success_path():
    """引文被 _align 判 unresolved 但章节内有相似句 → relocated 成功。"""
    # 长章节多句话，quote 是其中一句的改写（非子串、bigram 覆盖 <0.8），但 SequenceMatcher 对单句 >0.6
    section = "系统支持文章发布功能。文章状态包括草稿、待审核、已发布。审核驳回须填写原因。结果通知到作者邮箱。"
    ctx = _Ctx([_Src(1, [_Sec("PRD §4.1 发布", section)])])
    case = _Case([_Step("审核驳回须填写原因和备注", "PRD §4.1 发布")])
    p = derive_grounded_provenance(case, ctx)
    assert p.grounding["relocated"] >= 1
    assert "驳回" in p.verbatim_excerpt
    assert "PRD §4.1 发布" in p.derived_from
    assert p.trust_level == 1


# ── Task 7: confidence 适配 ─────────────────────────────────────────────────────


def test_confidence_note_flags_unresolved():
    from src.testcase_generator.schemas.test_case import Provenance
    from src.testcase_generator.stages.write_cases.confidence_scorer import ConfidenceScorer

    p = Provenance(
        derived_from=["x"],
        source_section="x",
        verbatim_excerpt="e",
        trust_level=1,
        grounding={"verified": 0, "fuzzy": 0, "relocated": 0, "unresolved": 2},
    )
    _lvl, note = ConfidenceScorer().score(p)
    assert note and "未对齐" in note
