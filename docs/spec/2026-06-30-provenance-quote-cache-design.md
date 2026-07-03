# provenance 同源 quote 解析缓存（同源一致性）— 设计文档

> 状态：设计（brainstorming 产出）。承接 roadmap `2026-06-30-quality-alignment-roadmap.md` ②。
> 下一步：writing-plans 出实施计划（执行交 Claude Code）。
> 来源：batch `278c211f` 审查 —— "同一 source_quote 在不同用例 grounding 不一致"。

## 1. 背景与问题

审查多族发现：**同一句 `source_quote`，在不同用例里 provenance 结果不一致**（如批创A 模块40 行1 vs 行16 引同一句、却一条溯源成功一条标"无支撑"）。

根因（已读代码确认）：`derive_grounded_provenance`（`provenance_tagger.py:96`）对每个 step 的 `source_quote` 现算现对齐（`_align`，纯函数）。同一句话只要：
- step 写的 `source_ref` 不同（命中索引到不同章节 content），或
- 一条走 ref 命中、另一条走跨章节兜底 `_find_section_by_quote`（命中不同章节），

就会得出**不同的 grounding 状态 / 归属 ref / trust**。`_align` 本身确定，但"喂给它的 content"因 ref/路径而异 → 同源不同判。

## 2. 边界（重要·诚实界定，自审收窄）

- **本步只治 provenance 层一致**：同一归一化 `source_quote` 的 `grounding` 统计、`derived_from`、`source_section`、`trust_level`、`verbatim_excerpt` 在**一次运行内**一致。
- **不直接治 verify 的 verdict 抖动**（`grounded/ungrounded/conflict`）——那是 verify 阶段 LLM 判定 + 章节召回的问题，归 roadmap ⑤（同构同判）+ verify 召回升级。
- **间接收益**：统一了 verify 看到的 provenance 输入（source_ref/excerpt 一致），对 verify 稳定有帮助，但**非充分**，不可在本 spec 夸大。

## 3. 现状（对齐代码）

- `write_cases/node.py:369`：`_grounded_index = build_section_index(parsed_context)`（batch 级建一次，已有共享模式）。
- `write_cases/node.py:492-493`：每条 case 调 `derive_grounded_provenance(llm_case, parsed_context, index=_grounded_index)`。
- `provenance_tagger.py`：`_align`(33)、`_relocate`(47)、`_find_section_by_quote`(67)、`derive_grounded_provenance`(96，per-step 循环 106-140，`counts` 101)。**无 quote 级缓存**。
- 灰度：`settings.grounded_provenance_enabled`（关时走旧 `ProvenanceTagger.tag_provenance`，本步不涉及）。

## 4. 目标

一次 write_cases 运行内，同一 `_normalize(source_quote)` 的**解析结果**（status / 归属 raw_ref / trust / 最终引文文本）唯一且一致 → 同源用例的 provenance 不再抖。

## 5. 方案

1. 把"单个 quote 的解析"从 `derive_grounded_provenance` 的 per-step 循环里**抽成纯函数** `_resolve_quote(q, r, expected, index) -> ResolveResult`（保持现有"ref 命中→跨章节兜底→relocate→unresolved"逻辑**逐字节不变**）。
2. `derive_grounded_provenance` 增加可选 `quote_cache: dict[str, ResolveResult] | None`：key = `_normalize(q)`，命中即复用、不重算。
3. `node.py` 在 `_grounded_index` 旁建一个 batch 级 `_quote_cache = {}`，传入每次 `derive_grounded_provenance` 调用，跨所有 case 共享。
4. 复用 `grounded_provenance_enabled` 灰度（仅其开时有缓存；关时旧路径不变）。

## 6. 设计决策与权衡（自审）

- **key 用 `quote` 而非 `(quote, ref)`**：只有忽略 LLM 写的 ref，才能消除"同句不同 ref→不同判"；以该 quote **首次解析的归属**为准。
- **顺序依赖瑕疵**：归属取决于该 quote 在遍历中首次出现时的解析（含其 ref）。→ **运行内一致达成**（主目标）；跨运行稳定性非本步目标，列为 future（可选确定性 tie-break：多路命中时取"更深章节号/更具体 ref"）。
- **幂等**：`_resolve_quote` 纯函数，即便 async 下偶尔重算也得同结果、无副作用。
- **`_resolve_quote` 返回需表达"双计数"**：`ref_corrected` 分支同时累加对齐态(`verified/fuzzy`)与 `ref_corrected`，故返回 `counts_keys: list[str]` 而非单 status，否则抽函数会丢计数（见 plan Task 2）。
- **`_relocate` 的 `expected` 依赖**：relocate 兜底用 `(quote, expected)`，同 quote 不同 expected 理论可得不同 fixed 句；缓存按 quote 以首次为准、忽略 expected 差异。影响小（relocate 占比低）、统一亦属同源一致；严格化可对 relocate 分支跳缓存（future）。

## 7. 范围

**做**：抽 `_resolve_quote` 纯函数 + `quote_cache` + node 接入 + 单测。

**不做（YAGNI）**：不改 `_align/_relocate/_find_section_by_quote` 算法本身；不改 verify；不改 dimension/优先级；不做跨运行持久化缓存；不碰关 grounded 的旧 `tag_provenance` 路径。

## 8. 验收

- 单测：同一 quote 出现在多条 case → `grounding`/`derived_from`/`trust_level` 完全一致。
- 回归：关 `grounded_provenance_enabled` 或不传 `quote_cache` 时，`derive_grounded_provenance` 输出与改造前**逐字节一致**（抽函数不改行为）。
- 缓存命中不重算（计数/打点断言）。
- 全量 `tests/testcase_generator/`（排除 integration）回归绿；ruff 干净；提交隔离。

## 9. 风险

- **抽函数误改行为** → 先写"现状行为快照"回归测试（多分支：verified/fuzzy/ref_corrected/relocated/unresolved），再抽函数、保持绿。
- **顺序依赖**（见 §6）→ 运行内一致即满足目标；跨运行稳定列 future。
- **边界被误读** → spec/PR 明确"不治 verify verdict 抖动"。
