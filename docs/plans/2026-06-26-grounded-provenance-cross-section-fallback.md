# 落点⑥ 大文档溯源精确率修复（跨章节 quote 兜底）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。

**Goal:** 治大文档下 grounded provenance 的「ref 失配」根因——绑定失败时跨全章节按 quote 兜底定位，预期把引用对齐率从 47% 拉到 ~85–92%。仅改 write_cases 溯源派生，灰度不变（`grounded_provenance_enabled` 控制）、关时零回归、不动 verify/输出主结构。

**诊断依据（真实数据，2026-06-26）：** 对旧批次 `dd03218e`（漫剧 2686 用例，4221 个有引用步骤）分类：
- A_ok（ref 命中索引 + 对齐）：**47.0%**
- **B_refmiss（ref 未命中索引，但 quote 逐字在 PRD 某章节）：44.7%** ← 主因，引文是真的
- C_refhit_else：0.0%
- D_rewrite（quote 全 PRD 搜不到逐字 = 模型改写/凝练）：8.3%

根因：parse 把漫剧切成 **31 个粗章节**建索引；模型引用标的是**更细子章节号**（如 `§5.8.7`/`§5.0.5`），按 ref 在粗索引里找不到 → 误判 unresolved；但 quote 逐字就在对应粗章节正文里（样本：ref=`§5.8.7`、quote「商品池由后台从巨量同步…」确在 PRD）。→ **修「绑定只认章节号」为「兜底认内容」即可救回 B。**

> 数字口径说明：上面 44.7% 用「全文精确子串」判定（诊断脚本 `.qa_probe/diag_provenance.py`）。修复函数用「逐章节 _align（含 fuzzy）」口径，实际救回率以 Chunk 3 复测为准（预期 ≥ 该值，因 fuzzy 更宽）。

**Architecture:** `derive_grounded_provenance` 在「按 ref 命中 + align」失败后，新增**跨全章节扫描**（O(章节数)，漫剧仅 31）找首个能 verified/fuzzy 对齐 quote 的章节；命中则计为 verified/fuzzy，并**用命中章节真实 source_ref 回填**（修正模型写歪的 ref）。仍找不到才走现有 `_relocate`/unresolved。

**Tech Stack:** Python 3.12, pydantic, pytest（纯函数全可单测）。

---

## 现状速查（对齐当前代码 `provenance_tagger.py`）

- `_normalize`/`_bigrams`/`_align(quote, content)->verified|fuzzy|unresolved`、`_relocate(...)`：保留不动。
- `SectionIndex = dict[str, tuple[str, int]]`，`build_section_index` 当前 value=`(content, trust_level)`。**问题：丢了原始 source_ref**，跨章节救回无法回填正确 ref → 扩为三元组 `(content, trust_level, raw_ref)`。
- `derive_grounded_provenance(llm_case, parsed_context, *, index=None)`（line 75）：当前用 `sec[0]`(content)/`sec[1]`(trust)，**无解包 `a,b=sec`**，扩三元组兼容。绑定/对齐失败直接 `_relocate` 或 unresolved，**无跨章节兜底**。
- `counts = {"verified","fuzzy","relocated","unresolved"}` → 加 `"ref_corrected"`（B 类救回可观测）。
- 灰度开关 `grounded_provenance_enabled` 已存在（不新增）。
- **⚠️ 提交隔离**：工作树有其他未提交改动，提交**只 `git add` 本落点 2 个文件**，勿 `git add -A/.`。

## File Structure

- **Modify** `src/testcase_generator/stages/write_cases/provenance_tagger.py`
- **Modify** `tests/testcase_generator/test_grounded_provenance.py`
- **Create**（验证）`.qa_probe/verify_fallback.py`（可复用现有 `.qa_probe/diag_provenance.py` 改造）

---

## Chunk 1: 索引带 raw_ref + 跨章节兜底纯函数（TDD）

### Task 1: SectionIndex 扩三元组
- [ ] **Step 1**：改类型与构建：
```python
SectionIndex = dict[str, tuple[str, int, str]]  # norm_ref -> (content, trust_level, raw_ref)


def build_section_index(parsed_context) -> SectionIndex:
    """预建章节索引（每个 parsed_context 只需构建一次）。"""
    index: SectionIndex = {}
    for src in parsed_context.sources:
        for sec in src.sections:
            index[_normalize(sec.source_ref)] = (sec.content, src.trust_level, sec.source_ref)
    return index
```
- [ ] **Step 2**：`derive_grounded_provenance` 内 `sec[0]`/`sec[1]` 用法不变（三元组前两位兼容）。

### Task 2: `_find_section_by_quote`（TDD）
- [ ] **Step 1: 写测试（先失败）** 追加到 `test_grounded_provenance.py`：
```python
from src.testcase_generator.stages.write_cases.provenance_tagger import _find_section_by_quote


def _idx():
    return {
        "x": ("无关内容随便写点东西", 1, "PRD §1 概述"),
        "y": ("商品池由后台从巨量同步，本页不能新增编辑商品；如需新商品请到商品库配置。", 1, "PRD §5.8 批量创建广告"),
    }


def test_find_by_quote_hit():
    hit = _find_section_by_quote("商品池由后台从巨量同步", _idx())
    assert hit is not None
    raw_ref, content, trust = hit
    assert raw_ref == "PRD §5.8 批量创建广告"
    assert trust == 1


def test_find_by_quote_miss_on_fabricated():
    assert _find_section_by_quote("系统支持区块链上链存证", _idx()) is None
```
- [ ] **Step 2: 实现**：
```python
def _find_section_by_quote(quote: str, index: SectionIndex) -> tuple[str, str, int] | None:
    """绑定失败兜底：跨全章节找能对齐该 quote 的章节，返回 (raw_ref, content, trust_level)。
    治根因：模型引用的子章节号细于 parse 切分粒度，按 ref 对不上但 quote 逐字在某章节里。
    优先精确子串(verified)，无则取首个 fuzzy。"""
    fuzzy_hit = None
    for content, trust, raw_ref in index.values():
        status = _align(quote, content)
        if status == "verified":
            return raw_ref, content, trust
        if status == "fuzzy" and fuzzy_hit is None:
            fuzzy_hit = (raw_ref, content, trust)
    return fuzzy_hit
```
- [ ] **Step 3**：`uv run pytest tests/testcase_generator/test_grounded_provenance.py -q` → 新增 2 条过。

---

## Chunk 2: derive 接兜底 + 计数（灰度，零回归）

### Task 3: `derive_grounded_provenance` 接跨章节兜底
- [ ] **Step 1: 写测试（先失败）** 追加（ref 细于索引→跨章节救回 + 回填真实 ref）：
```python
def test_derive_ref_misfit_rescued():
    class _Step:
        def __init__(self, q, r):
            self.source_quote, self.source_ref, self.expected_result = q, r, "预期"
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

    ctx = _Ctx([_Src(1, [_Sec("PRD §5.8 批量创建广告", "商品池由后台从巨量同步，本页不能新增商品。")])])
    case = _Case([_Step("商品池由后台从巨量同步", "PRD §5.8.7")])  # ref 细于索引→对不上
    p = derive_grounded_provenance(case, ctx)
    assert p.grounding["unresolved"] == 0
    assert p.grounding.get("ref_corrected", 0) == 1
    assert "商品池由后台从巨量同步" in p.verbatim_excerpt
    assert p.derived_from == ["PRD §5.8 批量创建广告"]  # 回填真实 ref
```
- [ ] **Step 2: 改 `derive_grounded_provenance`**：
  - `counts` 初始化加 `"ref_corrected": 0`。
  - 主循环（line 85-109）改为：
```python
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
            trusts.append(sec[1])
            continue
        # ── 跨章节兜底（治 ref 失配，诊断 B≈44.7%）──
        hit = _find_section_by_quote(q, index)
        if hit:
            raw_ref, content, trust = hit
            counts[_align(q, content)] += 1   # verified 或 fuzzy
            counts["ref_corrected"] += 1
            quotes.append(q)
            refs.append(raw_ref)              # 回填真正命中的章节 ref
            trusts.append(trust)
            continue
        # ── 仍找不到 → relocate / unresolved（现状逻辑）──
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
```
- [ ] **Step 3**：`uv run pytest tests/testcase_generator/test_grounded_provenance.py -q` → 全过。
- [ ] **Step 4: 全量零回归**：`uv run pytest tests/testcase_generator/ -q` → 全绿。
- [ ] **Step 5: ruff**：`uv run ruff check src/testcase_generator/stages/write_cases/provenance_tagger.py tests/testcase_generator/test_grounded_provenance.py` 干净。
- [ ] **Step 6: Commit（只加本落点 2 文件）**：
```bash
git add src/testcase_generator/stages/write_cases/provenance_tagger.py tests/testcase_generator/test_grounded_provenance.py
git commit -m "fix(write-cases): grounded provenance 跨章节 quote 兜底，治大文档 ref 失配（落点⑥）"
```

---

## Chunk 3: 离线验证（确认救回率，不跑大 PRD）

### Task 4: 复用旧批次离线复测
- [ ] **Step 1**：`.qa_probe/verify_fallback.py`（可复制 `.qa_probe/diag_provenance.py` 改造）：parse 漫剧拿索引 → 对旧批次 `dd03218e` 每个有引用 step，跑「ref 命中 align 失败 → `_find_section_by_quote`」，统计 `A_ok + ref_corrected` 占比。
- [ ] **Step 2: 跑**：`uv run python .qa_probe/verify_fallback.py`
  Expected：对齐率从 47% 升到 **~85–92%**；残留 unresolved ≈ D_rewrite（~8%）。**此步离线、约 20 秒、不烧大 PRD。**
- [ ] **Step 3: 记录**：把前后对照写入 roadmap 落点⑥ + 进度日志（`ref_corrected` 占比 = 救回量）。

---

## 总验收标准
- [ ] `grounded_provenance_enabled` 关时行为逐字节不变、全量 `tests/testcase_generator/` 全绿。
- [ ] `test_grounded_provenance.py`：跨章节命中/未命中、ref 失配救回（回填真实 ref）全过。
- [ ] 离线复测：对齐率 47%→~85–92%（ref_corrected 救回 B 类）。
- [ ] 改动文件 ruff 干净；提交只含本落点 2 文件。

## 风险与回退
- **兜底误配**：优先 verified（精确子串）再 fuzzy，误配概率低；D（真改写）仍判 unresolved，不会被错救。
- **性能**：每失败 step O(章节数)，漫剧仅 31，可忽略。
- **灰度不变**：仍在 `grounded_provenance_enabled` 下；关闭即回退旧 tagger，零代码回滚。
- **不动下游**：仅改 write_cases 溯源派生；verify 判定/输出 Schema 主结构不变。
