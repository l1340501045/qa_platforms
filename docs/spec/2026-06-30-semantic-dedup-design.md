# 语义去重升级（hybrid：embedding 语义 + 词法）— 设计文档

> 状态：设计（brainstorming 产出）。承接 roadmap `2026-06-30-quality-alignment-roadmap.md` ③。
> 下一步：writing-plans 出实施计划（执行交 Claude Code）。
> 来源：batch `278c211f` 审查（灌水大头）+ 2026 行业调研（hybrid 语义+词法去重）。

## 1. 背景与问题

灌水是本批最大的"非对错"问题：1134 测试点 → **3185 用例（2.81×）**、存在性凑数 807、实际近重复远超系统标记的 263。

根因（已读代码确认）：`dedup/clustering.py` 的 `find_duplicates` 是**纯词面去重**（`SequenceMatcher` 字符序列比 + `bigram` 倒排找候选）。它抓不到**"换措辞的同义近重复"**——如"组长可看全员"vs"投放组长能查看所有成员"，字面差异大、语义相同。审查实证：**标题骨架完全雷同仅 37 组**，正是词面去重的天花板；而各族精读发现的语义重复远多于此（创意素材 137→~65、§5.2.2 5 规则→35 用例…）。

## 2. 现状（对齐代码）

- `dedup/clustering.py`：`find_duplicates`（行60）三层——①结构化占位折叠（按 test_point）②同 tp+同维度 `SequenceMatcher≥0.80`（行148-164）③词面 bigram 倒排候选 + `SequenceMatcher≥0.88/跨维0.84`（行166-195）；护栏：`safe_dedup` rule 锚定 union-find（绝不删某规则最后一条，行101-113）+ 边界值 `_protected`（数字集不同+边界关键词，行144-146）。**文件注释明示"不依赖外部 embedding，可复现、可离线验证"——有意设计，须保留。**
- `dedup/node.py`：`dedup_node`（async）构造 `DedupCase` 调 `find_duplicates`（`safe_dedup_enabled` 灰度）。
- embedding 基建：`EmbeddingClient.embed_batch(list[str]) -> list[vector]`（async；见 `knowledge_base/services/embedding/vectorize_pipeline.py:54`），写 pgvector。

## 3. 目标

加**语义相似层**，抓词面抓不到的换措辞同义近重复；预期 **3185 → ~2000**；**保留全部现有护栏**（边界值/规则锚定/占位）；**灰度可回退、关时逐字节现状**；`find_duplicates` **保持纯同步函数、可离线确定性单测**。

## 4. 方案

1. `find_duplicates` 增加可选入参 `embeddings: dict[str, list[float]] | None`（case_id → 向量）：
   - **有**：在现有词面候选之外，**额外**按语义近邻生成候选——**全局两两**（非仅 test_point 组内，因灌水大头是跨 test_point/跨模块的换措辞重复，如"更新时间口径跨 5 模块测 16 次"）；**同 test_point 用 `semantic_threshold`(0.86)、跨 test_point 用更严的 `semantic_cross_tp_threshold`(0.90) 且建议同维度**（仿词面 pass 的"跨维严/同维松"，控误折叠）。候选**同样过** `_protected`（边界保护）+ `safe_dedup` 护栏后再 `_union`。
   - **无**：完全现状路径（向后兼容、可复现）。
2. `dedup_node`（async）：`semantic_dedup_enabled` 时调 `EmbeddingClient().embed_batch([title+text…])` 算各用例向量 → 传入 `find_duplicates`；**embedding 调用失败 → 降级为纯词面**（warning，不阻断 dedup）。
3. `settings`：`semantic_dedup_enabled`（默认 False，灰度）+ `semantic_dedup_threshold`（同 test_point，默认 0.86）+ `semantic_dedup_cross_tp_threshold`（跨 test_point，默认 0.90）。
4. **纯函数边界**：向量在 node 外部算好、作参数传入，`find_duplicates` 仍纯同步——单测传固定向量即确定可复现，不破坏 clustering 的"可离线"原则。

## 5. 设计决策与权衡（自审）

- **保纯函数可复现**：embedding 不进 `find_duplicates`（只接收向量）；关开关/不传向量 = 现状逐字节。
- **护栏全保留**：语义候选与词面候选**共用** `_protected` + `safe_dedup` + 占位结构折叠，绝不因语义相似绕过边界/规则保护。
- **候选规模 + 跨组（自审修正 A）**：灌水大头是**跨 test_point/跨模块**的换措辞重复，故语义候选须**全局**、不能只在 test_point 组内。用 **numpy 矩阵化**算 cosine（向量堆叠成 `M`、L2 归一化、`S=M@M.T`、取上三角超阈值对，~1e7 可接受），**不可纯 python 双循环**（太慢）。跨 test_point 用更严阈值（0.90）+ 建议同维度控误折叠；量大再上 MinHash/ANN（future）。
- **软标记可恢复**：仍只标 `duplicate_of`（不硬删）；阈值保守（0.86）避免误折叠。
- **灰度依赖**：建议 `semantic_dedup_enabled` 在 `safe_dedup_enabled` 开时才生效（复用 rule 护栏，防误折叠最后一条）。

## 6. 范围

**做**：`find_duplicates` 加 `embeddings` 入参 + 语义候选（过护栏）；`dedup_node` 算向量传入 + 灰度 + 降级；`settings` 开关与阈值；单测 + 离线 3185 条压缩验证。

**不做（YAGNI）**：不改现有词面/护栏算法本身；不删现有三层；不引入 LSH/ANN（future）；不做硬删（仍软标记）；不动 verify/生成/dimension。

## 7. 验收

- **离线**：用现有 `.audit/278c211f/.../cases.jsonl`（3185 条）算向量跑 `find_duplicates`，`duplicate` 数显著 > 现状 263、总量压到 ~2000；**抽查折叠对确为真同义**（非误折叠）。
- **护栏**：边界值对（"1000 行" vs "999 行"）、规则最后一条 不被语义误折叠（单测）。
- **零回归**：关 `semantic_dedup_enabled` 或不传 `embeddings` → 与改造前逐字节一致。
- 单测确定（固定向量）；全量（排除 integration）回归绿；ruff 干净；提交隔离。

## 8. 风险

- **误折叠**（语义近但实为不同边界/不同实体）→ `_protected` + 保守阈值 + 软标记可恢复 + 离线抽查兜底；语义候选**不放宽**边界保护。
- **embedding 成本/非确定** → 灰度 + 降级 + 离线向量可缓存；`find_duplicates` 本身确定。
- **O(n²) 规模** → 分组降规模 + numpy；量大 future LSH。
