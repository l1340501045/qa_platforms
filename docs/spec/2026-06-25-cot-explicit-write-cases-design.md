# 落点⑥ · CoT 显式化 + 溯源接地重构（grounded provenance）— 设计文档

> 状态：设计 v2「大改动」（brainstorming + 行业调研产出）。下一步：writing-plans 出实施计划 → 灰度实现 → 单 PRD before/after + 溯源度量验证。
> 关联：roadmap 落点⑥；行业最佳实践基线 11–15（生成溯源/引用接地）。

## 1. 背景与目标

两个问题叠加：
1. `write_cases` system prompt 方法论强，但**无显式分步推理**（一步从测试点蹦到用例 JSON，靠规则自把握）。
2. **provenance 有 bug**：用例级溯源由 `ProvenanceTagger` 事后启发式生成——`verbatim_excerpt = section.content[:200]`（章节前 200 字），`_section_matches` 靠 feature 名/dimension 词粗匹配 → **定位不准**，且其 `trust_level` 还喂 `ConfidenceScorer`，**连带把信任度/置信度算歪**。

现状有**两套并存的溯源**：
- 步骤级（LLM 自报）：`TestStep.source_quote/source_ref`——模型引用的真实原文，**可能准但无人校验**（可能编）。
- 用例级（tagger）：`Provenance.verbatim_excerpt`——**前 200 字，糙**。verify 关卡把两者当"claimed 提示"传入，但独立用真实章节复核出 `prd_evidence`，故 verify 判定不被带偏，只是收到**误导性提示**。

**目标**：用 CoT 让模型生成期精确定位原文 → 对其 `source_quote/source_ref` 做**代码校验** → 校验后的结果**派生用例级溯源**，取代 post-hoc tagger。让溯源**定位准、可校验、可度量、可回归**；并修正受牵连的 trust/confidence。

**成功标准**：
- 溯源度量（见 §4.6）before/after：引用精确率↑、span 对齐率↑、unresolved 率↓。
- 人工眼检：`verbatim_excerpt` 确实是支撑该用例断言的那句原文（claim 级），非章节前 200 字。
- **开关关闭时行为与现状逐字节一致**（零回归）；不改输出 Schema 主结构、不动 verify 判定逻辑/前端。

## 2. 行业最佳实践依据（2026 调研，见 roadmap 基线 11–15）

- **结构化绑定 > 事后追加**（RefWalk/FullCite）：post-hoc 套引用是公认反模式——正是当前 tagger 的问题。
- **引用即数据、代码校验三查**（Gemini 生产/Edtek）：①绑定 ②原文对齐（归一化后子串：精确=critical/模糊=warning）③逻辑支撑（NLI 或 LLM-judge）。
- **claim/span 级，非文档级**；**LLM 找对文档易、找准 span 难**（FullCite）→ 需修复闭环；**溯源度量**（AIS/ALCE 引用 P/R）。

## 3. 范围（大改动）

**做**：
1. CoT 分步推理纪律（prompt，灰度）。
2. 溯源重构：弃 `verbatim_excerpt=前200字` 启发式，改从步骤级 `source_quote/source_ref` **派生**用例级 provenance。
3. 三查校验：①绑定（source_ref→真实章节）②归一化 span 对齐（精确=verified / 模糊=fuzzy / 不中=unresolved）③逻辑支撑复用现有 verify（不重复造 NLI）。
4. span 失配修复闭环：unresolved → 在所引章节内模糊定位最相似句兜底（标 relocated）；仍不行 → 标 unresolved 并降级。
5. `ConfidenceScorer` 适配：引文 unresolved 多 → 降置信 + note。
6. 溯源度量尺子 `eval/provenance/`：引用精确率 / span 对齐率分布 / 有据断言绑定率，出报告，做 before/after 与回归。

**不做**：自部署 NLI 模型（verify 已承担逻辑支撑）；约束解码/引用语法；RTM 看板（产品向，后续）；改 verify 判定逻辑（只给它更准的 claimed 提示）；改 Provenance 主字段语义（仅新增可选 grounding 字段）。

## 4. 设计

### 4.1 灰度开关
- `settings.grounded_provenance_enabled: bool = False`（env 同名大写）。一个开关统管「CoT 纪律 + 生成期溯源派生&校验 + confidence 适配」整体——便于 before/after 干净对照。关 → CoT 段为空 + 仍用旧 tagger（现状逐字节不变）。

### 4.2 CoT 纪律段（prompt 常量）
`COT_REASONING_SECTION`：对每个测试点按 **定位原文 → 推行为 → 写可验证断言** 三步推理；强调 `source_quote` 必须**逐字摘录** requirement_context 原文、`source_ref` 指章节；定位不到 → 走既有「需求待确认」；**只输出用例 JSON，不输出推理过程**。复用上文 scope/section_kind 概念，不新增产出规则。

### 4.3 溯源派生 + 三查校验（重写 `provenance_tagger.py`）
新增 `derive_grounded_provenance(llm_case, parsed_context) -> Provenance`：
- 建索引：`source_ref(归一化) → section.content`（全 sources 的 sections）。
- 逐 step：
  - **①绑定**：step.source_ref 能否匹配到真实 section（归一化章节标识）。
  - **②span 对齐**：`_normalize(quote)` 是否 ⊆ `_normalize(section.content)`？精确=`verified`；否则 token 集合/序列相似度 ≥阈值=`fuzzy`；都不行=`unresolved`。归一化处理全/半角、空白、引号。
  - **③逻辑支撑**：交给下游 verify（本模块不做），但把 verified/fuzzy 的 quote 作为更准的 `claimed_source_quote` 提示传下去。
- 派生用例级 `Provenance`：
  - `derived_from` = 去重的有效 source_ref；`source_section` = 主 source_ref；
  - `verbatim_excerpt` = 拼接的 **verified/fuzzy 的真实 quote**（claim 级，**不再 first-200**）；全 unresolved → `"[未能对齐原文：N 处引文存疑]"`；
  - `trust_level` = 命中 sections 的 min trust（无命中→沿用 feature/兜底）；
  - 新增 `grounding`（可选）：每步对齐状态计数 `{verified, fuzzy, unresolved, relocated}`。

### 4.4 span 失配修复闭环
`unresolved` 时，在 step.source_ref 所指章节（取不到则全 sections）里，用相似度找与 `expected_result`/原 quote 最匹配的句子作兜底 excerpt，标 `relocated`（FullCite：找文档易、找 span 难，故兜底定位）。

### 4.5 confidence 适配（`confidence_scorer.py`）
`score(provenance)` 增项：若 `provenance.grounding.unresolved > 0` → 在 note 追加「N 处断言引文未对齐原文，建议人工核对」；trust_level 仍按信源仲裁。

### 4.6 溯源度量尺子（新 `eval/provenance/`）
离线脚本（复用 `eval/` 模式）：对一份已生成批次/或现跑两档，算：
- **引用精确率** = span 对齐(verified+fuzzy) 步数 / 有 source_quote 的步数；
- **span 对齐分布**：verified / fuzzy / relocated / unresolved 占比；
- **有据断言绑定率** = 确定断言用例中含有效 quote 的比例。
纯函数指标抽 `metrics.py` 可单测；出 `report.md`。给大改动 before/after 与回归一把数字尺子（呼应"先度量"铁律）。

### 4.7 Schema
`Provenance` 主字段（derived_from/source_section/verbatim_excerpt/trust_level）复用、语义不变；仅**新增可选** `grounding: dict | None = None`（默认 None，下游忽略即兼容）。`TestStep.source_quote/source_ref` 已存在。**输出主结构不变 → 不动下游消费**。

## 5. 验证
- **零回归**：开关关 → `cot_section=""` + 走旧 tagger 路径 → write_cases 行为逐字节不变；全量 `tests/testcase_generator/` 全绿。
- **单测**（确定性，不调 LLM）：`_normalize` / span 对齐三态（verified/fuzzy/unresolved）/ derive_grounded_provenance（mock case+context）/ 修复 relocated / confidence note 追加 / 度量纯函数。
- **before/after**（开关关/开各跑一份真实 doc）：用 §4.6 度量对比引用精确率↑、unresolved↓；人工眼检 verbatim_excerpt 真支撑断言、无推理泄漏进 JSON。

## 6. 风险与缓解
- **LLM span 不精**（FullCite 实证）→ 模糊匹配 + 章节内修复兜底 + 度量监控。
- **归一化漏边界**（全半角/特殊字符）→ 两级（精确 critical / 模糊 warning）+ 阈值可调。
- **非确定性**（prompt 改）→ 灰度默认关 + 度量 before/after，放量受铁律约束。
- **不动 verify 判定**：只提升其 claimed 提示质量；verify 仍独立复核。

## 7. 验收标准
- [ ] `grounded_provenance_enabled` 默认关；关时 write_cases 逐字节不变、全量测试全绿。
- [ ] span 对齐 / 派生 provenance / 修复 / confidence / 度量 纯函数单测全过。
- [ ] 开关开 before/after：引用精确率↑、unresolved↓（度量实证）；verbatim_excerpt 为 claim 级真实原文（人工眼检）。
- [ ] Provenance 主结构与下游消费未变；verify 判定逻辑未改；改动文件 ruff 干净。
- [ ] 提交只含 ⑥ 相关文件。
