# provenance 同源 quote 解析缓存 Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> 关联 spec：`docs/spec/2026-06-30-provenance-quote-cache-design.md`。

**Goal:** 让同一 `source_quote` 在一次 write_cases 运行内的 provenance 解析（status / 归属 ref / trust / 引文）唯一一致，消除"同源用例 grounding 抖动"。手段：抽 `_resolve_quote` 纯函数（行为不变）+ 加 `quote_cache`（key=归一化 quote）+ node 注入 batch 级缓存。**纯函数、零 LLM 成本、灰度内、关时零回归。**

**Architecture:** 不改对齐算法（`_align`/`_relocate`/`_find_section_by_quote`），只把 per-step 解析抽成可缓存纯函数；`derive_grounded_provenance` 新增 `quote_cache` 可选参；`node.py` 在 `_grounded_index` 旁建共享 `_quote_cache` 传入。

**Tech Stack:** Python 3.12 / pydantic v2 / pytest（asyncio_mode=auto，**纯确定性单测，不调 LLM**）。

---

## 现状速查（对齐当前代码）

- `stages/write_cases/provenance_tagger.py`：`_align`(行33)、`_relocate`(47)、`_find_section_by_quote`(67)、`build_section_index`(85)、`derive_grounded_provenance`(96)；per-step 解析循环 行106-140（ref 命中→`_find_section_by_quote` 兜底→`_relocate`→unresolved，累加 `counts` 101）；产物 `Provenance`(153-159)。
- `stages/write_cases/node.py`：`build_section_index` 行369（batch 级一次）；`derive_grounded_provenance(..., index=_grounded_index)` 行492-493；灰度 `settings.grounded_provenance_enabled`。
- **关键不变量**：抽函数后，关 grounded / 不传 cache 时，`derive_grounded_provenance` 输出必须逐字节不变。
- **mock 约定**：纯函数无需 mock LLM。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动。每个 Task 只 `git add` 本计划列出文件，**严禁 `-A` / `git add .`**。

## File Structure

- **Modify** `src/testcase_generator/stages/write_cases/provenance_tagger.py`（抽 `_resolve_quote` + `quote_cache` 参数）
- **Modify** `src/testcase_generator/stages/write_cases/node.py`（建 batch 级 `_quote_cache` 并传入）
- **Create** `tests/testcase_generator/test_provenance_quote_cache.py`（行为快照回归 + 同源一致 + 缓存命中）

---

## Chunk 1: 行为快照回归 + 抽 `_resolve_quote` 纯函数（不改行为）

### Task 1: 先写"现状行为快照"回归测试（防抽函数改坏）

**Files:** Create `tests/testcase_generator/test_provenance_quote_cache.py`

- [ ] **Step 1: 写覆盖五分支的快照测试**（verified / fuzzy / ref_corrected 跨章节 / relocated / unresolved），断言 `derive_grounded_provenance` 现状输出（`grounding` 计数 + `derived_from` + `trust_level` + `verbatim_excerpt`）。用轻量假对象构造 `llm_case`/`parsed_context`（参考 `test_grounded_provenance.py` 既有夹具风格）。
- [ ] **Step 2: 跑通**（绿——这是改造前基线）
Run: `uv run pytest tests/testcase_generator/test_provenance_quote_cache.py -k snapshot -v`
> ⚠️ 注意：`test_cache_same_quote_different_ref_consistent` 已随本文件落盘（属 Task 3 的 TDD 失败桩），Task1/Task2 阶段该测试预期红，用 `-k snapshot` 只跑五分支基线。至 Task 3 实现后整文件才全绿。
- [ ] **Step 3: Commit**
```bash
git add tests/testcase_generator/test_provenance_quote_cache.py
git commit -m "test(provenance): derive_grounded_provenance 五分支行为快照（抽函数前基线）"
```

### Task 2: 抽 `_resolve_quote` 纯函数（保持行为）

**Files:** `provenance_tagger.py`

- [ ] **Step 1: 抽函数**——把 行106-140 单 step 解析体抽成纯函数 `_resolve_quote(q, r, expected, index) -> ResolveResult`。
  - **⚠️ 自审关键：返回值必须能表达"双计数"分支**——`ref_corrected` 路径会同时 `counts["verified"|"fuzzy"]+1` **且** `counts["ref_corrected"]+1`（见现状 行124-125）。若返回单个 `status` 字符串会丢掉 `ref_corrected` 计数、抽函数即改坏行为。
  - 故返回结构：`counts_keys: list[str]`（本步要 +1 的 counts 键，可多个，如 `["fuzzy","ref_corrected"]`）+ `quote_text: str|None`（追加进 `quotes`；relocated 时为 fixed 句）+ `ref: str|None`（追加进 `refs`）+ `trust: int|None`（追加进 `trusts`）。
  - `derive_grounded_provenance` 循环改为：调 `_resolve_quote` → 按 `counts_keys` 累加 `counts`、对非 None 追加 `quotes/refs/trusts`。**不改任何阈值 / 分支顺序 / 累加口径**。
- [ ] **Step 2: 跑 Task 1 快照 + 既有 `test_grounded_provenance.py`**
Run: `uv run pytest tests/testcase_generator/test_provenance_quote_cache.py tests/testcase_generator/test_grounded_provenance.py -k "snapshot or test_grounded" -v`
Expected: 全绿（行为逐字节不变）。cache 测试此阶段仍为预期红，由 `-k` 排除。
- [ ] **Step 3: Commit**
```bash
git add src/testcase_generator/stages/write_cases/provenance_tagger.py
git commit -m "refactor(provenance): 抽 _resolve_quote 纯函数（行为不变，为缓存铺路）"
```

---

## Chunk 2: 加 `quote_cache`（同源一致）

### Task 3: `derive_grounded_provenance` 加 `quote_cache` 参数（TDD）

**Files:** `provenance_tagger.py`、Test 同文件

- [ ] **Step 1: 写失败测试**——同一 quote 配**不同 source_ref** 出现在两条 case，传共享 `quote_cache`，断言两条 `grounding`/`derived_from`/`trust_level` 一致；且第二次命中缓存（用计数器/桩验证 `_resolve_quote` 只对该 quote 算一次）。
- [ ] **Step 2: 跑失败**
Run: `uv run pytest tests/testcase_generator/test_provenance_quote_cache.py -k cache -v`
Expected: FAIL（当前无 cache 参数 / 两条不一致）。
- [ ] **Step 3: 实现**——`derive_grounded_provenance(..., quote_cache: dict | None = None)`；循环内 `key=_normalize(q)`，`if quote_cache is not None and key in quote_cache: 复用 else: 调 _resolve_quote 并存入`。
- [ ] **Step 4: 跑通 + 回归**（Task1/2 + grounded 既有测试仍绿）
- [ ] **Step 5: Commit**
```bash
git add src/testcase_generator/stages/write_cases/provenance_tagger.py tests/testcase_generator/test_provenance_quote_cache.py
git commit -m "feat(provenance): derive_grounded_provenance 加 quote_cache（同源 quote 解析一致）"
```

---

## Chunk 3: node 接入 batch 级缓存

### Task 4: `node.py` 建并传入 `_quote_cache`

**Files:** `node.py`

- [ ] **Step 1**：`_grounded_index = ...`（行369）旁加 `_quote_cache: dict = {}`（`derive_grounded_provenance` 仅在 `grounded_provenance_enabled` 为真时被调——行492——无需 None 分支）；行493 调用改 `derive_grounded_provenance(llm_case, parsed_context, index=_grounded_index, quote_cache=_quote_cache)`。
- [ ] **Step 2: 编译冒烟 + 全量回归**
Run: `uv run pytest tests/testcase_generator/ -q --ignore=tests/testcase_generator/integration`
Expected: 全绿。
- [ ] **Step 3: ruff**
Run: `uv run ruff check src/testcase_generator/stages/write_cases/provenance_tagger.py tests/testcase_generator/test_provenance_quote_cache.py`
> ⚠️ `node.py` 含 16 个存量 E501（prompt 长文本行，改动前已存在），扫全目录会 exit 1。验证口径为「本次改动行无新增违规」：用 `git diff HEAD~1 -- src/.../node.py | grep '^+'` 核查新增行均不超长。
- [ ] **Step 4: Commit**
```bash
git add src/testcase_generator/stages/write_cases/node.py
git commit -m "feat(write_cases): provenance 注入 batch 级 quote_cache（同源一致）"
```

---

## 总验收标准

- [ ] 同一 quote（不同 ref）跨多条 case → `grounding`/`derived_from`/`trust_level` 完全一致。
- [ ] 缓存命中不重算（计数断言）。
- [ ] 关 `grounded_provenance_enabled` 或不传 `quote_cache` → 行为与改造前逐字节一致（Task1 快照 + 既有 `test_grounded_provenance.py` 全绿）。
- [ ] 全量（排除 integration）回归绿；`provenance_tagger.py` + 测试文件 ruff 干净（`node.py` 存量 E501 预存、本次改动行无新增）。
- [ ] 提交仅含本计划列出文件。

## 风险与回退

- **抽函数改坏行为** → Task 1 五分支快照先行兜底；回退即还原 provenance_tagger.py。
- **顺序依赖**（同 quote 归属取决于首次出现）→ 运行内一致即达标；跨运行确定性 tie-break 列 future，不在本计划。
- **边界误读** → 本计划只统一 provenance；verify verdict 抖动归 roadmap ⑤，PR 描述需注明。
- **【自审】`_relocate` 的 expected 依赖** → relocate 兜底用 `(quote, expected)`，同 quote 不同 expected 理论可得不同 fixed 句；缓存按 quote 以"首次"为准、忽略 expected 差异。relocate 是"ref 未中 + 跨章节未中"的兜底的兜底、占比低，统一亦属"同源一致"，可接受；如需严格可对 relocate 分支跳缓存（future）。
- **提交污染** → 每 Task 仅 `git add` 指定文件，绝不 `-A/.`。
