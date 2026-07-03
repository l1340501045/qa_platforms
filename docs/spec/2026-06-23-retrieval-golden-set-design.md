# 落点③（最小版）· 检索 Golden Set 尺子 — 设计文档

> 状态：设计待评审（brainstorming 产出）。下一步：评审通过 → writing-plans 出实施计划。
> 关联：roadmap `docs/plans/testcase-generation-best-practice-roadmap.md` 落点③；hybrid 检索 `docs/plans/2026-06-22-hybrid-cross-feature-retrieval.md`（落点①，已实现）。

## 1. 背景与目标

落点①（hybrid 跨功能点检索）已实现并灰度（默认关）。一次性离线对照（`.qa_probe/retrieval_diff.py`）证明 hybrid 安全、对 IAP/IAA 链接绑定与数据权限等真·跨功能点规格有靶向价值，但在「全局注入已很强」的 PRD 上净增中等。

**问题**：要不要把 hybrid 放量、以及后续怎么调参（`rrf_k`/`pool`/cosine 下限）乃至上落点②（cross-encoder 重排），都缺一把**客观、可复用、便宜**的尺子。roadmap 原则：**先建度量再放量**。

**目标**：建检索质量尺子——一批标注好「应召回哪些章节」的 query，跑 Recall/NDCG 客观对比「关键词 vs hybrid」，据此决策；并作为后续调参/重排的回归基线。

**成功标准**：
- 一条命令产出「关键词 vs hybrid」的指标对照 + 逐条命中/漏召回明细。
- 同一脚本改开关/参数即可复测（可复用）。
- 据此能明确回答：hybrid 在正样本上 Recall 是否净增、在负样本上是否引入噪声。

## 2. 范围

**做（最小版）**：
- 检索 Golden Set 数据集（~60 条，YAML，可版本化）。
- 离线评估器：对每条 query 跑 `CrossFeatureIndex.query` 开/关两档（生产口径：排除自身+全局），算指标、出报告。

**不做（留给落点③后续，YAGNI）**：
- 生成侧 RAG-Triad（faithfulness/context-relevance）。
- 接入 CI 回归门。
- 与现有 `GoldenSetEvaluator`（评生成质量）整合。
- 不动生产代码、不改 hybrid 实现。

## 3. 数据：Golden Set

### 3.1 结构（YAML）

```yaml
- id: GS-06
  feature_id: F-013            # 关联功能点（探针类可空）
  group: iaa_iap_binding       # 所属依赖簇，便于审核与归因
  query: "付费直投/付费ROI 的链接类型是 IAP，提交时自动绑定 IAP 监测链接"
  expected_refs:               # 理应召回的章节（非自身、非全局）；负样本为空列表
    - "prd:漫剧批创初版功能PRD §7.2 提交时的绑定规则"
    - "prd:漫剧批创初版功能PRD §5.3 投放链接管理"
  polarity: positive           # positive=有跨章节依赖 / negative=应召回空（测噪声）
  note: "IAP/IAA 绑定规格散在 §5.3/§7.1/§7.2，互为跨引用"
```

### 3.2 关键语义

- **`expected_refs` 排除「功能点自身章节 + 全局章节」**：生产里这两类已分别注入（own + `collect_global_sections`），跨功能点检索的真正职责是找**别处的非全局规格**。尺子据此衡量才有意义。
- **相关性二值**（在/不在 `expected_refs`）：v1 够算 Recall；NDCG 用「命中即增益」简化版（不分级）。后续可升级分级。
- **负样本（`polarity: negative`，`expected_refs: []`）**：故意纳入「本就无需跨章节」的 query，用于测 hybrid「该闭嘴时会不会乱注入」。

### 3.3 规模与配比（~60 条）

| 组 | 数量 | 说明 |
|---|---|---|
| per-feature 忠实组 | ~22 | 每功能点 1 条，query = 该功能点测试点意图概括（贴近生产 per-feature 检索） |
| 按维度采样组 | ~28 | 每功能点采样 2–4 条不同维度的测试点当 query，优先 `access_control/state_transition/cross_system/api_contract/data_calculation`（更可能需跨章节） |
| 负样本组 | ~8 | 规格自洽或仅依赖全局章节的 query（如字数→§9.1 全局、商品库自洽） |
| 痛点探针 | ~5 | 手工补（监测链接 vs 投放链接、切换投放方式后链接重置等已知混淆点） |

> **规模理由**：roadmap 基线 100–200，但本 PRD 仅 28 候选章节 / 22 功能点，独立检索情形有限，硬冲 100+ 会同簇冲样本冗余、n 虚高。~60 是「增独立信号又不灌水」的性价比点。真要统计级需跨多 PRD，属后续。

### 3.4 金标准产出方式（已定：AI 起草 + 人工审核）

1. AI 用 `.qa_probe/retrieval_diff.py` 结果 + 候选章节内容判定，**按依赖簇**起草 `expected_refs`（同簇 query 继承簇标注）。
2. 用户审「簇逻辑」（不是 60 条单标）：通过 / 改 / 调簇边界。
3. 定稿写入 `eval/retrieval/golden_set.yaml`。

**待用户定的簇边界（起草时确认）**：
- 权限簇铺多广：仅以权限为主的功能点（F-008/09/11/28/29）挂 §10.2，还是所有含 `access_control` 测试点的功能点都挂？
- hub 功能 F-010（批创核心）：9 个配置区联动章节全列进 expected，还是只列最关键 2–3 个？

## 4. 评估器

### 4.1 取数（复用 `retrieval_diff.py` 路径）

- 复跑 `parse_node`（读 DB + 便宜的 section_kind 分类，不碰生成/视觉）拿忠实 `parsed_context`。
- 按 `feature_id` 还原生产 exclude_keys（自身 + 全局），与生产口径一致。

### 4.2 流程

对每条 golden query：
1. 关开关 → `CrossFeatureIndex.query`（纯关键词）→ 召回列表。
2. 开开关 → `CrossFeatureIndex.query`（hybrid）→ 召回列表（候选向量 build 时算一次缓存）。
3. 比对 `expected_refs` 算指标。

### 4.3 指标

**正样本（`polarity: positive`）**：
- **Recall@3**（生产 top_k，最贴决策）、**Recall@10**（趋势）。
- **NDCG@10**（二值增益，看排序质量）。
- **MRR**（首个相关项的排名倒数）。

**负样本（`polarity: negative`）**：
- **噪声率** = 返回 ≥1 章节的占比（越低越好）。对比关键词 vs hybrid，验证 hybrid 不引入噪声。

### 4.4 产出

- 终端摘要：关键词 vs hybrid 的各指标对照（含正/负样本分开）。
- `eval/retrieval/report.md`：逐条 query 的 expected / 关键词召回 / hybrid 召回 / 命中漏召回标注。

### 4.5 文件

```
eval/retrieval/
  golden_set.yaml     # 金标准数据集（~60）
  evaluate.py         # 评估器（离线，CLI）
  report.md           # 评估产出（gitignore 或保留快照，实施时定）
```

## 5. 决策口径（尺子怎么用）

- **放量倾向**：hybrid 在正样本 Recall@10 / NDCG@10 净增明显，且负样本噪声率不升 → 倾向开。
- **需调参**：正样本有增但负样本噪声率上升 → 先加 cosine 下限 / 调 `rrf_k` / 缩 `pool` 复测。
- **不放量**：正样本无净增 → 维持关，重审 query 构造或落点②。
- **铁律**：aggregate 数字（n≈60，置信区间偏宽）只看方向；最终结合「逐条漏召回明细」人工判断。

## 6. 风险与边界

- **小样本**：n≈60，CI 偏宽，aggregate 仅指示方向 → 以逐条明细兜底；不宣称统计显著。
- **单 PRD**：只覆盖这一份 PRD 的检索情形 → 结论对该类文档有效；跨域泛化需后续多 PRD。
- **金标准偏差**：AI 起草可能带模型偏好 → 靠人工审簇逻辑校正；负样本和痛点探针提供独立校验。
- **query 口径**：golden query 用「概括/具体」而非生产的「全功能点测试点拼接」，更利诊断；如需完全贴生产，可加一档「生产 concat query」复测（v1 不强制）。

## 7. 验收标准

- [ ] `eval/retrieval/golden_set.yaml` ~60 条，经用户审核定稿。
- [ ] `uv run python eval/retrieval/evaluate.py` 一条命令出指标对照 + `report.md`。
- [ ] 报告区分正/负样本，给出关键词 vs hybrid 的 Recall@3/@10、NDCG@10、MRR、噪声率。
- [ ] 据此能给出「放量 / 调参 / 不放量」的明确建议。
