# 用例生成 · 行业最佳实践对齐 路线图（长期记忆）

> **这是一份长期记忆文件。** 任何处理「用例生成质量 / 检索 / RAG / 最佳实践对齐」的会话，开始前应先读本文件找回目标与进度。上下文超限后也以本文件为准。

## 🎯 北极星目标

**让 qa_platforms 的测试用例生成全面对齐行业最佳实践（2026）。**

当前已产出的 `docs/plans/2026-06-22-hybrid-cross-feature-retrieval.md` 只是**「最佳落点」的第一部分（落点①）**，不是终点。完整目标是把下方 Gap 清单逐项补齐。

## 🧭 如何使用这份记忆

- 接手时：读「Gap 落点清单」看哪些 ✅done / 🟡doing / ⬜todo，按「推进路线」选下一步。
- 每完成一项：更新对应落点状态 + 关联的 plan/commit。
- 新调研结论：补进「行业最佳实践基线」或「Gap 清单」，保持本文件是唯一事实源。

---

## 行业最佳实践基线（2026，已调研，来源见会话记录）

**生产级 RAG（spec→test 场景）的成熟范式：**
`关键词(BM25/词项) ∥ 向量(dense) → RRF 融合(k=60) → cross-encoder 重排 → CoT 生成 → RAG-Triad 评估 → CI 回归门`

要点：
1. **Hybrid 检索**：关键词擅长精确词/标识符，向量擅长语义/释义；二者失败方向相反、互补。纯向量加关键词（或反之）是单项最高价值升级（recall@10 78%→91%）。
2. **RRF 融合**：按 rank 不按分（免归一化），k=60 稳健，小语料可降到 20。
3. **Cross-encoder 重排**：对融合后 top-50 精排 top-10，是检索精度最高价值改进。
4. **语义分块**：按语义边界而非固定字数切，保持 chunk 连贯。
5. **需求接地 + 可追溯**：用例验证「是否符合 spec」，需求ID↔用例双向追溯（监管/回归价值）。
6. **CoT 生成**：先定位章节→再定位行为→再写断言，分步推理降幻觉。
7. **多源检索**：PRD + 源码 + API 契约 + 技术方案 +（UI 场景）DOM/原型，用分隔符区分「做什么(doc)」与「在哪/怎么(结构)」。
8. **RAG-Triad 评估**：faithfulness（忠于上下文）/ answer relevance / context relevance；用 RAGAS/DeepEval 等自动化，接入 CI、回归超阈即 break build。
9. **检索 Golden Set**：100–200 条人工标注 query 测 Recall@10 / NDCG@10，作为调参（k、权重、pool）的尺子。

---

## 系统现状 · 强项（已对齐甚至超越一般实践，勿推倒）

> 本系统在「QA 专项深耕」上其实强于通用 RAG 教程，以下是资产，改造时只增强不破坏：

- **覆盖系统化**：test_points 阶段有维度矩阵（~43 维）+ 适用性裁剪 + 信号门控（只对文档有信号的维度展开，防灌水）。write_cases prompt 内置「覆盖维度清单 + 逆向联动必出项 + 高频误读纠正」。
- **事实接地 / 防假 oracle**：verify 阶段逐条核验「预期是否有 PRD 原文支撑」；section 带 scope（own/cross_ref/global_default）与 section_kind（spec/mock/future/flow/tbd/summary），无支撑只出「需求待确认」型用例。
- **溯源可追溯**：provenance（source_ref / source_quote / verbatim_excerpt）+ test_point_id ↔ 用例。
- **Gate 门控**：comprehend 后覆盖度不足 → LangGraph interrupt 人工澄清再续。
- **全局章节注入**：collect_global_sections 把 §5.0 全局规则等横切章节注入每个功能点。
- **跨章节规格检索**：CrossFeatureIndex（治「深层规格被折到别处→误判留白」）——**即落点①要 hybrid 化的对象**。
- **知识沉淀**：cheat sheet（QA 审核通过的避坑手册，注入 prompt）+ rule_extract（规则台账，灰度）。
- **生成质量评估**：golden_set_evaluator（AI 用例 vs 资深 QA 标准集，算覆盖度/遗漏率/新增价值率）。
- **反馈迭代**：单条 AI 重写（按 QA 意见，意见权威优先）+ 批量迭代。

---

## 系统 vs 最佳实践 · 对标矩阵

| 最佳实践维度 | 系统现状 | 差距 |
|---|---|---|
| Hybrid 检索（关键词+向量+RRF） | 仅关键词(CrossFeatureIndex) + 关联图(entity_relations)；向量(document_embeddings)已修好但**未接入生成** | 落点① |
| Cross-encoder 重排 | 无 | 落点② |
| 检索质量度量(Recall@10/NDCG + Golden Query) | 无（golden_set 评的是「生成用例」不是「检索」） | 落点③ |
| 生成质量度量(RAG-Triad faithfulness/context-relevance) | 有 verify(事实核验) + golden_set(覆盖度)，但未成体系化 RAG-Triad、未入 CI 回归门 | 落点③ |
| 语义分块 | vectorize 固定「heading + 1000字/100 overlap」切 | 落点④ |
| 大文档按需 RAG | parse 把 PRD 全文塞 LLM（11.7w 字已勉强） | 落点⑤ |
| CoT 显式分步 | write_cases 有强方法论 prompt，但非显式「先定位→再断言」CoT | 落点⑥ |
| 多源接地(源码/API契约/技术方案/DOM) | 主要 PRD + 关联文档 + 原型链接(Playwright)；技术方案/接口契约接入弱 | 落点⑦ |
| 需求接地 + 可追溯 | provenance + source_quote + test_point_id ↔ 用例 | ✅ 已对齐 |
| 反馈迭代闭环 | 单条重写 + 批量迭代（QA 意见权威） | ✅ 已对齐 |
| 覆盖系统化 + 防假 oracle | 维度矩阵 + 信号门控 + verify + scope/section_kind | ✅ 超越一般实践 |

---

## 🗂 Gap 落点清单（唯一事实源，按价值排序）

状态图例：✅done 🟡doing/已出plan ⬜todo

- **① Hybrid 跨章节规格检索**（关键词 + 向量 + RRF）  🟡
  - 价值：**最高**。直击「深层规格漏召回 → 用例误判『需求待确认』空壳」（audit_v5 核心质量短板），是嵌入修复反哺生成质量的关键。
  - 产物：`docs/plans/2026-06-22-hybrid-cross-feature-retrieval.md`（plan 已出，待 Claude Code 执行）。
  - 落点对象：`CrossFeatureIndex`（write_cases / verify 共用）。

- **② 检索后 Cross-encoder 重排**  ⬜
  - 价值：高。hybrid 召回 top-50 → reranker 精排 top-10，是检索精度最高价值改进。
  - 前置：需确认自建网关是否提供 rerank 模型（如 bge-reranker / cohere-rerank 兼容端点）；否则需自部署或跳过。
  - 依赖：建立在①之后。

- **③ 质量度量体系（北极星的「尺子」）**  ⬜
  - 价值：**高**。没有度量就无法证明「质量变好」，是验收①②④⑤的基础。
  - 内容：(a) 检索 Golden Set（100–200 条标注 query 测 Recall@10/NDCG，给①②调 k/权重/pool）；(b) 生成 RAG-Triad（faithfulness / context-relevance，复用 verify 信号系统化）；(c) 接入 CI，回归超阈 break build；(d) 与现有 golden_set_evaluator 整合。

- **④ 语义分块**（vectorize_pipeline 改语义边界切）  ⬜
  - 价值：中。当前固定字数切会割裂语义，影响向量召回质量；接①后显效。
  - 落点对象：`src/knowledge_base/services/embedding/vectorize_pipeline.py::_split_into_chunks`。

- **⑤ 大 PRD 按需 RAG**（按测试点向量检索片段，替代全文硬塞）  ⬜
  - 价值：中。防超大 PRD 撑爆上下文/抬高成本；与①④协同（同一向量底座）。
  - 落点对象：parse / write_cases 的上下文组装。

- **⑥ CoT 显式化**（write_cases 分步：定位章节 → 定位行为 → 写可验证断言）  ⬜
  - 价值：中。已有强方法论，CoT 进一步降幻觉、提断言质量。
  - 落点对象：`write_cases/node.py` 的 system prompt。

- **⑦ 多源接地**（技术方案文档 / 接口契约接入检索；UI 场景原型/DOM）  ⬜
  - 价值：中（依场景）。技术方案/接口文档接入能让用例校验「接口契约/状态机/缓存/降级」等技术派生维度。
  - 落点对象：parse 的多源 RetrievalService + section 分类。

---

## 🛣 推进路线（建议顺序与依赖）

- **阶段 A · 质量杠杆 + 尺子（当前）**
  - 执行落点① hybrid（plan 已出）——直接修补质量短板。
  - 紧随/并行落点③ 度量体系——先把「尺子」立起来，否则①②的「变好」无法量化验证。
  - A/B 验证：同一 PRD 开/关 hybrid 各跑一次，对比「需求待确认」空壳率 + golden_set 覆盖度。
- **阶段 B · 检索增强**
  - 落点④ 语义分块（提升向量召回底座质量）→ 落点② cross-encoder 重排（精度跃升，依赖网关 rerank 能力调研）。
- **阶段 C · 规模与深化**
  - 落点⑤ 大 PRD 按需 RAG（防超大文档）、⑥ CoT 显式化、⑦ 多源接地（技术方案/接口契约）。

> 原则：每个落点都带灰度开关 + 可降级 + 先建度量再放量；只增强不破坏现有「覆盖系统化 / 事实接地 / 溯源」资产。

## 📌 进度日志

- **2026-06-22**
  - 修复嵌入链路：列维度 1536→1024（迁移 021）、批大小 2048→10、ORM 维度 1024（commit `0d24ca5`）；PRD 已可向量检索（197 切片，completed）。
  - 排查确认：**生成全链路此前完全不依赖向量检索**（走 PRD 全文 + 关键词词项 CrossFeatureIndex + 关联图）；`document_embeddings` 当前是「建好未接线」状态。→ 纠正了「嵌入失败影响生成质量」的早期误判。
  - 落点①：hybrid 检索 plan 产出 `docs/plans/2026-06-22-hybrid-cross-feature-retrieval.md`（待执行）。

## 🔧 维护说明

- 每完成一个落点：更新其状态（⬜→🟡→✅）+ 回填关联 plan 路径与 commit，并在「进度日志」追加一行。
- 新的调研结论：补进「行业最佳实践基线」或「对标矩阵」，保持本文件为唯一事实源。
- 关联文档：`findings.md`（研究证据）、`task_plan.md`（更宏观的架构记忆，若存在）、各落点 `docs/plans/*.md`。

