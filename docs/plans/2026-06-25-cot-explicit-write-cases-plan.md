# 落点⑥ CoT 显式化 + 溯源接地重构（grounded provenance）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> **大改动**：CoT 分步推理 + 弃 post-hoc「前200字」tagger，改生成期 source_quote/source_ref 派生&三查校验 + 失配修复 + confidence 适配 + 溯源度量尺子。

**Goal:** 修正 provenance 定位 bug——用 CoT 让模型生成期精确引用原文，对其 source_quote/source_ref 做代码三查（绑定/归一化span对齐/复用verify），校验后派生用例级溯源取代「章节前200字」启发式；溯源定位准、可校验、可度量、可回归。灰度默认关、零回归。

**Architecture:** 一个开关 `grounded_provenance_enabled` 统管。关→CoT 段空 + 旧 tagger（现状逐字节不变）。开→注入 CoT 纪律 + `derive_grounded_provenance`（归一化子串=verified / 模糊覆盖=fuzzy / 不中=unresolved→章节内修复定位）+ confidence 适配。新增 `eval/provenance/` 度量尺子做 before/after。

**Tech Stack:** Python 3.12, `get_llm_client().generate_structured`, pydantic, pytest（纯函数全可单测）。

> 设计依据：`docs/spec/2026-06-25-cot-explicit-write-cases-design.md`（已自审）；行业依据 roadmap 基线 11–15。

---

## 现状速查（实现前必读，已对齐当前代码）

- `write_cases/node.py`：`WRITE_CASES_SYSTEM_PROMPT`@88；拼装@398-400（`full_system_prompt = WRITE_CASES_SYSTEM_PROMPT + cheat_sheet_section + feedback_section + few_shot_section`）；后处理@466 `provenance = provenance_tagger.tag_provenance(tp, parsed_context)`、@467 `trust_level, confidence_note = confidence_scorer.score(provenance)`、@469-479 由 `llm_case.steps`（含 `source_quote/source_ref`）建 `TestStep`。调用 temperature=0.3（不动）。
- `write_cases/provenance_tagger.py`：`ProvenanceTagger.tag_provenance(test_point, parsed_context)` —— **bug 源**：`excerpt = section.content[:200]`（前200字）+ `_section_matches` 粗匹配。**保留旧类供开关关路径，新增生成期派生函数。**
- `write_cases/confidence_scorer.py`：`ConfidenceScorer.score(provenance)->(trust_level, note)`，note 按 trust_level 派生。
- `schemas/test_case.py`：`TestStep.source_quote/source_ref`（已有）；`Provenance(derived_from, source_section, verbatim_excerpt, trust_level)`；`GeneratedTestCase.provenance`。
- `verify`：把 step.source_quote 当 `claimed_source_quote`、`provenance.verbatim_excerpt` 当 `claimed_provenance_excerpt` 传入，但**独立用真实章节复核**出 prd_evidence → 本计划只提升其 claimed 提示质量，**不改 verify 判定**。
- 开关样式：`settings.py` 布尔默认关（紧邻 `cot...`/`feature_seg_llm_enabled`@116 一带）。
- **⚠️ 提交隔离**：工作树可能有其他未提交改动。提交**只 `git add` ⑥ 文件，勿 `git add -A/.`**。

## File Structure

- **Modify** `src/platform_api/core/settings.py`：`grounded_provenance_enabled: bool = False`。
- **Modify** `src/testcase_generator/schemas/test_case.py`：`Provenance` 加可选 `grounding: dict | None = None`。
- **Modify** `src/testcase_generator/stages/write_cases/node.py`：CoT 段常量 + 拼装 `cot_section`；后处理按开关选 `derive_grounded_provenance` vs 旧 `tag_provenance`。
- **Modify** `src/testcase_generator/stages/write_cases/provenance_tagger.py`：新增 `_normalize/_align/_relocate/derive_grounded_provenance`（保留旧 `ProvenanceTagger`）。
- **Modify** `src/testcase_generator/stages/write_cases/confidence_scorer.py`：unresolved → 追加 note。
- **Create** `tests/testcase_generator/test_grounded_provenance.py`：span 对齐三态 / 派生 / 修复 / confidence / 开关 wiring。
- **Create** `eval/provenance/{metrics.py,test_metrics.py,evaluate.py}`：溯源度量尺子。
- **Create**（验证）`.qa_probe/cot_before_after.py`：单 PRD 关/开对照（人工眼检 + 度量）。

---

## Chunk 1: 开关 + CoT 段（灰度，零回归）

### Task 1: 灰度开关
- [ ] **Step 1**：`settings.py` 新增：
```python
    # ── CoT 显式化 + 溯源接地（落点⑥·大改动）─────────────────────────────────
    # 关：write_cases 行为不变（用旧 provenance tagger）。开：加 CoT 分步纪律 +
    # 生成期 source_quote/source_ref 派生&校验取代「前200字」启发式 + confidence 适配。
    # 仅改 write_cases 溯源链，不动 verify 判定/输出主结构。默认关。
    grounded_provenance_enabled: bool = False
```
- [ ] **Step 2**：`uv run python -c "from src.platform_api.core.settings import settings; print(settings.grounded_provenance_enabled)"` → `False`。

### Task 2: CoT 段 + 拼装 + wiring 单测（TDD）
- [ ] **Step 1: 写 wiring 单测（先失败）** `tests/testcase_generator/test_grounded_provenance.py`（首段）：
```python
from src.testcase_generator.stages.write_cases import node as wc


def test_cot_section_constant_nonempty():
    assert isinstance(wc.COT_REASONING_SECTION, str) and "显式分步推理纪律" in wc.COT_REASONING_SECTION
    assert "只输出最终用例 JSON" in wc.COT_REASONING_SECTION
```
- [ ] **Step 2: 加 `COT_REASONING_SECTION`**（紧跟 `WRITE_CASES_SYSTEM_PROMPT` 之后）：
```python
COT_REASONING_SECTION = """

【显式分步推理纪律（CoT —— 写每个测试点的用例前，先在心里按此顺序走一遍，再下笔）】
对每个测试点，严格按三步推理，但**只输出最终用例 JSON，不要输出推理过程本身**：
1. 定位：在 requirement_context 中找到支撑该行为的具体章节与原文（优先 scope=own，其次 cross_ref，再 global_default）。
   · 找到 → 把**逐字摘录的原文**填入该步 source_quote、所在章节填入 source_ref；
   · 找不到任何明文支撑 → 按上文「需求待确认」唯一用例处理，不要进入第 2/3 步编造。
2. 推行为：仅从第 1 步定位到的原文推导应覆盖的行为面（正常/边界/异常逆向/状态机/联动，以原文为准），不外推未授予的范围。
3. 写断言：每个行为面写成可观测、可验证的 expected_result，并确保 source_quote 是 requirement_context 里**真实存在、可逐字找到**的片段（不要改写/凝练，否则系统校验会判为存疑）。
顺序铁律：先有「定位到的原文」才允许写确定断言。此纪律只组织推理、不改变上文产出规则与输出 Schema。"""
```
- [ ] **Step 3: 拼装插入**（@398-400）：
```python
                cot_section = COT_REASONING_SECTION if settings.grounded_provenance_enabled else ""
                full_system_prompt = (
                    WRITE_CASES_SYSTEM_PROMPT + cot_section + cheat_sheet_section + feedback_section + few_shot_section
                )
```
- [ ] **Step 4**：`uv run pytest tests/testcase_generator/test_grounded_provenance.py -q` → 该条 pass。
- [ ] **Step 5: 全量零回归**：`uv run pytest tests/testcase_generator/ -q` → 全绿（开关关 → cot_section="" → 拼装不变）。
- [ ] **Step 6: Commit（只加 ⑥ 文件）**：`git add src/platform_api/core/settings.py src/testcase_generator/stages/write_cases/node.py tests/testcase_generator/test_grounded_provenance.py && git commit -m "feat(write-cases): CoT 分步纪律 + grounded_provenance 开关（落点⑥ Chunk1，灰度零回归）"`

---

## Chunk 2: 溯源派生 + 三查校验（重写 tagger，TDD）

### Task 3: Schema 加可选 grounding 字段
- [ ] **Step 1**：`schemas/test_case.py` `Provenance` 加：
```python
    grounding: dict | None = Field(default=None, description="溯源校验统计 {verified,fuzzy,relocated,unresolved}；None=未启用 grounded 模式")
```
- [ ] **Step 2**：`uv run pytest tests/testcase_generator/ -q` → 全绿（可选字段，向后兼容）。

### Task 4: 归一化 + span 对齐纯函数（TDD）
- [ ] **Step 1: 写测试（先失败）** 追加到 `test_grounded_provenance.py`：
```python
from src.testcase_generator.stages.write_cases.provenance_tagger import _align, _normalize


def test_normalize_fullwidth_punct_space():
    # 全角→半角、去标点空白后等价
    assert _normalize("（１）审核 通过！") == _normalize("(1) 审核通过")
    assert _normalize("审核状态：待提审") == "审核状态待提审"


def test_align_verified_ignores_punct_and_space():
    sec = "字段：审核状态。取值：待提审、审核通过、审核不通过。"
    # 模型引用省了标点/加了空格 → 归一化后仍是子串 → verified
    assert _align("审核状态 取值 待提审", sec) == "verified"


def test_align_fuzzy_minor_typo():
    sec = "责编可通过或驳回，驳回须填写原因。"
    # 模型把"须"误成"需"（近形/同音小错）→ 非精确子串，但 bigram 覆盖高 → fuzzy
    assert _align("责编可通过或驳回驳回需填写原因", sec) == "fuzzy"


def test_align_unresolved_on_paraphrase_or_fabrication():
    sec = "责编可通过或驳回，驳回须填写原因。"
    assert _align("系统支持支付宝微信银联三种支付", sec) == "unresolved"   # 无关=编造
    assert _align("驳回流程大致需要走个审批", sec) == "unresolved"        # 改写非逐字 → 判存疑
```
- [ ] **Step 2: 实现**（`provenance_tagger.py` 顶部）：
```python
import re

# 比对用：仅保留 中文 + 字母数字（去标点/空白/引号），全角先转半角、转小写
_KEEP = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


def _normalize(s: str) -> str:
    """比对用归一化：全角→半角、小写、仅保留中文+字母数字（标点/空白一律去掉）。"""
    if not s:
        return ""
    s = "".join(chr(ord(c) - 0xFEE0) if "！" <= c <= "～" else c for c in s)
    return _KEEP.sub("", s.lower())


def _bigrams(norm: str) -> set[str]:
    return {norm[i : i + 2] for i in range(len(norm) - 1)} if len(norm) >= 2 else ({norm} if norm else set())


def _align(quote: str, section_content: str, *, threshold: float = 0.8) -> str:
    """'verified'（归一化子串）/ 'fuzzy'（quote bigram 被章节覆盖≥阈值）/ 'unresolved'。"""
    nq, nc = _normalize(quote), _normalize(section_content)
    if not nq:
        return "unresolved"
    if nq in nc:
        return "verified"
    bq, bc = _bigrams(nq), _bigrams(nc)
    if not bq:
        return "unresolved"
    coverage = len(bq & bc) / len(bq)
    return "fuzzy" if coverage >= threshold else "unresolved"
```
- [ ] **Step 3**：`uv run pytest tests/testcase_generator/test_grounded_provenance.py -q` → 对齐测试过（阈值不合再微调 `threshold`）。

### Task 5: 修复定位 + 派生 provenance（TDD）
- [ ] **Step 1: 写测试（先失败）** 追加：
```python
from src.testcase_generator.stages.write_cases.provenance_tagger import derive_grounded_provenance


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
    assert "驳回须填写原因" in p.verbatim_excerpt          # claim 级真实原文，非前200字
    assert p.grounding["verified"] == 1
    assert p.source_section == "PRD §3.2 审核"


def test_derive_unresolved_flags_not_fabricates():
    case = _Case([_Step("系统支持三种支付方式", "PRD §3.2 审核")])
    p = derive_grounded_provenance(case, _ctx())
    assert p.grounding["unresolved"] >= 1
    assert "存疑" in p.verbatim_excerpt or p.grounding["relocated"] >= 1   # 不编造
```
- [ ] **Step 2: 实现 `derive_grounded_provenance` + `_relocate`**：
```python
from difflib import SequenceMatcher

from src.testcase_generator.schemas.test_case import Provenance


def _relocate(quote: str, expected: str, section_content: str | None) -> str | None:
    """章节内找与 quote/expected 最相似的句子作兜底（FullCite：找 span 难→修复定位）。"""
    if not section_content:
        return None
    target = _normalize(quote or expected)
    if not target:
        return None
    best, best_sent = 0.0, None
    for sent in re.split(r"[。；;\n]", section_content):
        s = sent.strip()
        if not s:
            continue
        r = SequenceMatcher(None, target, _normalize(s)).ratio()
        if r > best:
            best, best_sent = r, s
    return best_sent if best >= 0.6 else None


def derive_grounded_provenance(llm_case, parsed_context) -> Provenance:
    """从 step 级 source_quote/source_ref 派生用例级溯源 + 三查校验（绑定/对齐/修复）。"""
    index: dict[str, tuple[str, int]] = {}
    for src in parsed_context.sources:
        for sec in src.sections:
            index[_normalize(sec.source_ref)] = (sec.content, src.trust_level)

    counts = {"verified": 0, "fuzzy": 0, "relocated": 0, "unresolved": 0}
    quotes: list[str] = []
    refs: list[str] = []
    trusts: list[int] = []

    for step in llm_case.steps:
        q = (getattr(step, "source_quote", None) or "").strip()
        r = (getattr(step, "source_ref", None) or "").strip()
        if not q:
            continue
        sec = index.get(_normalize(r)) if r else None
        status = _align(q, sec[0]) if sec else "unresolved"
        if status in ("verified", "fuzzy"):
            counts[status] += 1
            quotes.append(q)
            if r:
                refs.append(r)
            if sec:
                trusts.append(sec[1])
        else:
            fixed = _relocate(q, getattr(step, "expected_result", ""), sec[0] if sec else None)
            if fixed:
                counts["relocated"] += 1
                quotes.append(fixed)
                if r:
                    refs.append(r)
                if sec:
                    trusts.append(sec[1])
            else:
                counts["unresolved"] += 1

    derived_from = list(dict.fromkeys(refs))
    if quotes:
        excerpt = " / ".join(quotes)[:300]
    else:
        excerpt = f"[未能对齐原文：{counts['unresolved']} 处引文存疑，待人工核对]"
    trust_level = min(trusts) if trusts else (
        min((s.trust_level for s in parsed_context.sources), default=5)
    )
    return Provenance(
        derived_from=derived_from or ["unresolved"],
        source_section=derived_from[0] if derived_from else "unresolved",
        verbatim_excerpt=excerpt,
        trust_level=trust_level,
        grounding=counts,
    )
```
- [ ] **Step 3**：`uv run pytest tests/testcase_generator/test_grounded_provenance.py -q` → 全过。
- [ ] **Step 4: ruff** 改动文件干净。
- [ ] **Step 5: Commit**：`git add src/testcase_generator/schemas/test_case.py src/testcase_generator/stages/write_cases/provenance_tagger.py tests/testcase_generator/test_grounded_provenance.py && git commit -m "feat(write-cases): 生成期溯源派生+三查校验+修复定位（落点⑥ Chunk2）"`

---

## Chunk 3: 接线 + confidence 适配（灰度，零回归）

### Task 6: node.py 后处理按开关选派生
- [ ] **Step 1**：顶部 import `derive_grounded_provenance`；后处理@466 改：
```python
                    if settings.grounded_provenance_enabled:
                        provenance = derive_grounded_provenance(llm_case, parsed_context)
                    else:
                        provenance = provenance_tagger.tag_provenance(tp, parsed_context)
                    trust_level, confidence_note = confidence_scorer.score(provenance)
```
- [ ] **Step 2: 全量零回归**：`uv run pytest tests/testcase_generator/ -q` → 全绿（开关关走旧 tagger）。

### Task 7: confidence 适配
- [ ] **Step 1: 写测试（先失败）** 追加：
```python
def test_confidence_note_flags_unresolved():
    from src.testcase_generator.schemas.test_case import Provenance
    from src.testcase_generator.stages.write_cases.confidence_scorer import ConfidenceScorer
    p = Provenance(derived_from=["x"], source_section="x", verbatim_excerpt="e", trust_level=1,
                   grounding={"verified": 0, "fuzzy": 0, "relocated": 0, "unresolved": 2})
    _lvl, note = ConfidenceScorer().score(p)
    assert note and "未对齐" in note
```
- [ ] **Step 2: 改 `confidence_scorer.score`**——在返回前，若 `provenance.grounding` 有且 `unresolved>0`，把提示并入 note：
```python
        base_note = <现有按 level 派生的 note>
        g = getattr(provenance, "grounding", None)
        if g and g.get("unresolved", 0) > 0:
            warn = f"{g['unresolved']} 处断言引文未对齐原文，建议人工核对"
            base_note = f"{base_note}；{warn}" if base_note else warn
        return level, base_note
```
（把现有四分支 note 收敛到 `base_note` 变量再统一追加。）
- [ ] **Step 3**：`uv run pytest tests/testcase_generator/test_grounded_provenance.py tests/testcase_generator/ -q` → 全绿。
- [ ] **Step 4: ruff + Commit**：`git add src/testcase_generator/stages/write_cases/node.py src/testcase_generator/stages/write_cases/confidence_scorer.py tests/testcase_generator/test_grounded_provenance.py && git commit -m "feat(write-cases): grounded provenance 接线 + confidence 适配（落点⑥ Chunk3，灰度零回归）"`

---

## Chunk 4: 溯源度量尺子 + 验证

### Task 8: 度量纯函数（TDD）
- [ ] **Step 1**：`eval/provenance/metrics.py` —— 纯函数：
  - `citation_precision(cases) = (verified+fuzzy+relocated) 步 / 有 source_quote 步`
  - `alignment_distribution(cases) -> {verified,fuzzy,relocated,unresolved} 占比`
  - `grounded_assertion_rate(cases) = 含有效 quote 的确定断言用例 / 确定断言用例`
  （输入用各 case 的 `provenance.grounding` + steps；纯字典运算。）
- [ ] **Step 2**：`eval/provenance/test_metrics.py` 断言上述函数（构造小样例）；`uv run python eval/provenance/test_metrics.py` → all passed。

### Task 9: before/after 验证（人工眼检 + 度量）
- [ ] **Step 1**：`.qa_probe/cot_before_after.py` —— 对一份真实 doc，在 `grounded_provenance_enabled` 关/开各跑一次生成（复用 `tests/testcase_generator/integration/` 调流水线的方式，或触发 `run_pipeline`；用 monkeypatch/env 切开关），落盘两份用例，调 `eval/provenance/metrics` 打印对照：引用精确率、对齐分布、有据断言绑定率。
- [ ] **Step 2: 跑**：`uv run python .qa_probe/cot_before_after.py`（需 LLM_API_KEY+DB，缺则提示跳过）。Expected（人工判读）：开后 引用精确率↑、unresolved↓；抽查 `verbatim_excerpt` 确是支撑该断言的原句（非前200字）；无推理过程泄漏进 JSON 字段。
- [ ] **Step 3: 记录**：把度量对照 + 眼检结论写入 roadmap 落点⑥（🟡→✅ 或维持🟡待放量）+ 进度日志。
- [ ] **Step 4: Commit**：`git add eval/provenance/ && git commit -m "feat(eval): 溯源度量尺子 citation precision/对齐分布（落点⑥ Chunk4）"`

---

## 总验收标准

- [ ] `grounded_provenance_enabled` 默认关；关时 write_cases 逐字节不变、全量 `tests/testcase_generator/` 全绿。
- [ ] `test_grounded_provenance.py`：归一化 / span 三态 / 派生 / 修复 / confidence / wiring 全过。
- [ ] `eval/provenance/test_metrics.py` 通过。
- [ ] 开关开 before/after：引用精确率↑、unresolved↓（度量实证）；verbatim_excerpt 为 claim 级真实原文（眼检）；无推理泄漏进 JSON。
- [ ] Provenance 主结构与下游消费未变（仅加可选 grounding）；verify 判定逻辑未改；改动文件 ruff 干净。
- [ ] **提交隔离**：每次 commit 只含 ⑥ 相关文件。

## 风险与回退

- **LLM span 不精**（FullCite 实证）→ 模糊覆盖 + `_relocate` 章节内兜底 + 度量监控；仍不中只标 unresolved，绝不编造。
- **归一化/阈值边界**→ 两级（精确 verified / 模糊 fuzzy），`threshold` 可调；单测覆盖典型中文场景。
- **非确定性**（prompt 改）→ 灰度默认关 + 度量 before/after，放量受「先跨 PRD 度量」铁律约束。
- **不动 verify 判定**：只提升 claimed 提示质量；verify 仍独立复核出 prd_evidence。
- **即时回退**：`GROUNDED_PROVENANCE_ENABLED=false`（默认即关）→ CoT 段空 + 旧 tagger，零代码回滚。
- **提交污染风险**：工作树有其他未提交改动 → 每次 `git add` 用显式文件路径（勿 `git add -A/.`）。
