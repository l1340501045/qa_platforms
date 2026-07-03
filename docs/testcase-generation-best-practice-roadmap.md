# 用例生成 · 行业最佳实践对齐 路线图（长期记忆）

> **这是一份长期记忆文件。** 任何处理「用例生成质量 / 检索 / RAG / 最佳实践对齐」的会话，开始前应先读本文件找回目标与进度。上下文超限后也以本文件为准。

## 🎯 北极星目标

**让 qa_platforms 的测试用例生成全面对齐行业最佳实践（2026），且对任意领域 PRD 都稳——这是一个通用系统，不是为某一份 PRD 调出来的。**

> **通用性铁律**（2026-06-23 修正）：任何调参/结论不得只凭单份 PRD；检索/分类逻辑不得绑定领域词表。先跨多份代表性 PRD 度量，再放量。

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
10. **跨数据集评估（通用性）**：度量须覆盖多份不同领域/结构的文档，避免单文档过拟合；通用检索/分类不应依赖领域专属词表，应由模型语义判定。

**生成溯源 / 引用接地（spec→test 的审计命根，2026-06-25 调研补充）：**
11. **结构化绑定 > 事后追加**：生成期让模型把每条断言绑定到 source（quote+章节），而非事后给整段套引用——后者是公认反模式（RefWalk/FullCite：systemic attribution failures）。
12. **引用即数据、代码校验三查**（Gemini 生产 / Edtek 2026）：①绑定（source_ref 指真实章节）②原文对齐（source_quote 归一化后是该章节子串：精确命中=critical 防编造 / 仅模糊=warning 记漂移）③逻辑支撑（NLI 或 LLM-judge——本系统由 verify 关卡承担）。
13. **claim/span 级，非文档级**：每条断言绑"具体那一句"；文档/章节级（更别提"前 N 字"）不够。
14. **LLM 找对文档易、找准 span 难**（FullCite 实证）→ span 对不齐要有修复闭环（让模型重引 / 章节内模糊定位兜底），不能直接丢。
15. **溯源度量**（AIS / ALCE 引用 precision-recall）：引用精确率、span 对齐率、有据断言绑定率——确定性、便宜，应进 eval 尺子做 before/after 与回归。

---

## 系统现状 · 强项（已对齐甚至超越一般实践，勿推倒）

> 本系统在「QA 专项深耕」上其实强于通用 RAG 教程，以下是资产，改造时只增强不破坏。**注：这些资产本身是领域无关的（通用），是真正可迁移的底子。**

- **覆盖系统化**：test_points 阶段有维度矩阵（~43 维）+ 适用性裁剪 + 信号门控（只对文档有信号的维度展开，防灌水）。write_cases prompt 内置「覆盖维度清单 + 逆向联动必出项 + 高频误读纠正」。【通用】
- **事实接地 / 防假 oracle**：verify 阶段逐条核验「预期是否有 PRD 原文支撑」；section 带 scope（own/cross_ref/global_default）与 section_kind（spec/mock/future/flow/tbd/summary），无支撑只出「需求待确认」型用例。【通用】
- **溯源可追溯**：provenance（source_ref / source_quote / verbatim_excerpt）+ test_point_id ↔ 用例。【通用】
- **Gate 门控**：comprehend 后覆盖度不足 → LangGraph interrupt 人工澄清再续。【通用】
- **全局章节注入**：collect_global_sections 把 §5.0 全局规则等横切章节注入每个功能点。原「写死关键词过拟合」问题已由落点⑧（LLM 语义判定 is_global，灰度）解决，关键词保留为兜底。
- **跨章节规格检索**：CrossFeatureIndex（治「深层规格被折到别处→误判留白」）——落点①已 hybrid 化。【通用】
- **知识沉淀**：cheat sheet（QA 审核通过的避坑手册，注入 prompt）+ rule_extract（规则台账，灰度）。【通用】
- **生成质量评估**：golden_set_evaluator（AI 用例 vs 资深 QA 标准集，算覆盖度/遗漏率/新增价值率）。【通用】
- **反馈迭代**：单条 AI 重写（按 QA 意见，意见权威优先）+ 批量迭代。【通用】

---

## 系统 vs 最佳实践 · 对标矩阵

| 最佳实践维度 | 系统现状 | 差距 |
|---|---|---|
| Hybrid 检索（关键词+向量+RRF） | 已实现+灰度（默认关），单 PRD 尺子验证 Recall@3 0.30→0.85 | 落点①（待跨PRD验证后放量） |
| Cross-encoder 重排 | 无 | 落点② |
| 检索质量度量(Recall@10/NDCG + Golden Query) | **单 PRD 尺子已建**（eval/retrieval/），尚未跨 PRD | 落点③（升级跨PRD） |
| 生成质量度量(RAG-Triad faithfulness/context-relevance) | 有 verify(事实核验) + golden_set(覆盖度)，但未成体系化 RAG-Triad、未入 CI 回归门 | 落点③ |
| **通用性 / 跨领域鲁棒性** | 全局判定可 LLM 语义化(⑧a✅)、切分可 LLM 大纲化(⑧b✅)，均灰度；调参/结论仍只 1 份 PRD | 落点⑧✅(灰度待放量)；剩 ③升级跨PRD（缺PRD阻塞） |
| 语义分块 | vectorize 固定「heading + 1000字/100 overlap」切 | 落点④ |
| 大文档按需 RAG | parse 把 PRD 全文塞 LLM（11.7w 字已勉强） | 落点⑤ |
| CoT 显式分步 | write_cases 有强方法论 prompt，但非显式「先定位→再断言」CoT | 落点⑥ |
| 多源接地(源码/API契约/技术方案/DOM) | PRD+关联文档；技术方案/接口契约/通用原型 DOM 接入仍弱 | 落点⑦🟡（待重新设计） |
| 需求接地 + 可追溯 | provenance + source_quote + test_point_id ↔ 用例 | ✅ 已对齐 |
| 反馈迭代闭环 | 单条重写 + 批量迭代（QA 意见权威） | ✅ 已对齐 |
| 覆盖系统化 + 防假 oracle | 维度矩阵 + 信号门控 + verify + scope/section_kind | ✅ 超越一般实践 |

---

## 🗂 Gap 落点清单（唯一事实源，按价值排序）

状态图例：✅done 🟡doing/已出plan ⬜todo

- **⑧ 去领域绑定（通用化，通用性根因）**  ✅（两部分均已实现+灰度默认关）
  - 价值：**最高（决定换 PRD 是否掉质量）**。已拔掉两处过拟合：①全局章节靠写死关键词识别；②功能点切分死认 `##` 层级。
  - 已完成 (a) 全局判定改 LLM `section_classifier` 语义判 `is_global`（关键词兜底）—— `global_section_llm_enabled`，commit 03a350a。
  - 已完成 (b) 切分改 LLM 大纲分段（嵌套 PRD 也能切，深层内容折叠保全）—— `feature_seg_llm_enabled`，commit a1b7979..7c8a2a6，plan `docs/plans/2026-06-23-feature-segmentation-llm-plan.md`。
  - ⚠️ 均灰度默认关，放量同样受「先跨 PRD 度量」铁律约束。

- **③ 跨 PRD 质量度量体系（北极星的「尺子」，须跨领域）**  🟡
  - 价值：**最高**。没度量无法证明「变好」；**单份 PRD 的尺子会导致调参过拟合**——通用系统必须跨多份代表性 PRD 度量。
  - 已完成：单 PRD 检索尺子 `eval/retrieval/`（candidates.json 冻结候选 + golden_set.yaml 54 条 + metrics.py + evaluate.py 算 Recall@3/@10、NDCG@10、MRR、负样本噪声率）。设计 `docs/spec/2026-06-23-retrieval-golden-set-design.md`、计划 `docs/plans/2026-06-23-retrieval-golden-set-ruler.md`。
  - 待办：(a) 推广到 2–3 份不同领域 PRD 形成跨领域回归套件 ——⚠️**当前阻塞：库内仅 1 份真实 PRD（漫剧 11.7w 字），需用户补充其他领域 PRD**；(b) 生成 RAG-Triad；(c) 接入 CI；(d) 与 golden_set_evaluator 整合。

- **① Hybrid 跨章节规格检索**（关键词 + 向量 + RRF）  🟡（已实现+灰度，待跨PRD验证后放量）
  - 价值：**最高**。直击「深层规格漏召回 → 用例误判『需求待确认』空壳」。
  - 产物：`docs/plans/2026-06-22-hybrid-cross-feature-retrieval.md`（已实现并提交 commit e7d730a..c939a3c）；开关 `hybrid_cross_retrieval_enabled` 默认关。
  - 单 PRD 尺子验证：Recall@3 关键词 0.30 → hybrid 0.85（权限簇盲区救回）；但负样本噪声率高（向量路无相似度下限）。**已用数据否决「cosine 下限」方案**（单主题 PRD 信噪相似度重叠，阈值无法分离）。**放量决定待跨 PRD 复测。**

- **② 检索后 Cross-encoder 重排**  ⬜
  - 价值：高。hybrid 召回 top-50 → reranker 精排 top-10，是检索精度最高价值改进。
  - 前置：需确认自建网关是否提供 rerank 模型（如 bge-reranker / cohere-rerank 兼容端点）；否则需自部署或跳过。
  - 依赖：建立在①之后，用跨 PRD 尺子验证。

- **④ 语义分块**（vectorize_pipeline 改语义边界切）  ⬜
  - 价值：中。当前固定字数切会割裂语义，影响向量召回质量；接①后显效。
  - 落点对象：`src/knowledge_base/services/embedding/vectorize_pipeline.py::_split_into_chunks`。

- **⑤ 大 PRD 按需 RAG**（按测试点向量检索片段，替代全文硬塞）  ⬜
  - 价值：中。防超大 PRD 撑爆上下文/抬高成本；与①④协同（同一向量底座）。
  - 落点对象：parse / write_cases 的上下文组装。

- **⑥ CoT 显式化 + 溯源接地重构（grounded provenance）**  ✅（实现+灰度+单 PRD e2e 验证，2026-06-25）
  - 价值：高。原 provenance bug（post-hoc tagger 取前 200 字、定位不准、连带 trust/confidence 算歪）已修。CoT 让生成期精确引用 → 三查校验后派生溯源取代 post-hoc tagger。**不依赖检索放量/新 PRD。**
  - 实现：CoT 分步纪律 + 溯源派生&三查（绑定/归一化 span 对齐/复用 verify）+ span 修复 + confidence 适配 + 溯源度量尺子。7 commits、3 轮 GPT review、161 单测、灰度零回归。开关 `grounded_provenance_enabled`（默认关）。
  - **e2e 验证（自签书全图，⑥ ON）**：80 步 74 有引用；引用精确率 69/74=**0.93**（verified57/fuzzy12/unresolved5/relocated0）。新旧对照决定性——旧 tagger 给每条用例同一段无关「前 200 字」；新 grounded 给每条 claim 级真实支撑原文。
  - 落点对象：`write_cases/{node,provenance_tagger,confidence_scorer}.py`、`eval/provenance/`；design/plan `docs/{spec,plans}/2026-06-25-cot-explicit-write-cases-*`。
  - 待办：放量（`.env` `GROUNDED_PROVENANCE_ENABLED=true`）；可选第二遍 OFF 全跑量化 CoT 对 source_quote 命中率的增益。

- **⑦ 多源接地**（技术方案文档 / 接口契约接入检索；UI 场景原型/DOM）  🟡（待重新设计）
  - 待办：技术方案文档 / 接口契约 / 通用原型 DOM 接入检索（校验接口契约/状态机/缓存/降级等技术派生维度），不再包含已废弃的特定设计工具识别链路。

---

## 🗂 Gap 落点清单 · 用例质量侧（2026-06-29 批次 `0c9b63e6` 审查新增）

> 来源：漫剧 11.7w 字 PRD / 2252 用例 多智能体审查 + 行业最佳实践对照（`.audit/0c9b63e6-28cd-4efc-ae2e-0c9cbed9a9bb/{REPORT.md,findings/14_行业最佳实践对照.md}`）。与 ①–⑧（检索/RAG 侧）正交：这些是「用例质量 / verify / 覆盖 / 规范」侧。

- **⑨ verify 跨族核验 + 跨条款矛盾扫描**  🟡（已出 spec+plan，待执行）
  - 价值：高、不依赖检索放量/新 PRD。消除 verify family bias（generator/verify 同为 `claude-opus-4-6` → 自评偏袒）+ 抓 PRD 内部自相矛盾（cherry-pick）。
  - 产物：`docs/{spec,plans}/2026-06-29-verify-crossfamily-conflict-scan-*`。落点：`llm_client`(+`model` 参数)、`verify/{verifier,rubric}`、`settings`(+`llm_verify_model`/`verify_cross_section_conflict_enabled`)。

- **⑩ 优先级体系（risk=可能性×影响；P0<30% 配额）**  ⬜
  - 价值：高、ROI 高、纯收敛不依赖新 PRD。审查：**P0 占 49.7%**，优先级无区分度。业界：1–3 标度（1–10 会全变 7）；P0/P1/P2=每提交/每日/按需；可接历史回归数据动态化。
  - 落点对象：`test_points`/`write_cases` 优先级分配。

- **⑪ 维度命名统一（单一 enum）**  ⬜
  - 价值：中、ROI 高、纯收敛。审查：**98 个维度标签中英两套并存**（`functional_correctness`↔`正常流`、`boundary_value`↔`边界值`），破坏按维度统计/筛选/覆盖度量。
  - 落点对象：维度词表（`test_points` 维度矩阵）+ 生成期校验为单一 enum。

- **⑫ 结构化覆盖技术（决策表 / 状态转移 N-switch / 权限矩阵 / RTM 缺口闸）**  ⬜
  - 价值：**最高**（直击审查最大黑洞：权限矩阵零覆盖、状态机转移漏、端到端联动缺）。工作量大。
  - 与 `rule-anchored-coverage`（规则锚，规则覆盖率不下降）协同但不等价——后者锚「规则」，本项是 ISTQB「黑盒设计技术」显式枚举 + 缺口闸。
  - 落点对象：`test_points`「应覆盖点」枚举。

- **⑬ 占位用例分流（undefined → 需求澄清清单产物）**  ⬜
  - 价值：中。审查：大量 `undefined`「待 PM 澄清」混在用例集稀释可执行率（unresolved 72% 等）。
  - 落点对象：verify/export —— 抽成独立「需求澄清清单」交 PM，不混进可执行用例。

- **⑭ 两个小项**  ⬜
  - 图片影子重复：带 `section_hint` 的图被重复生成成「未定位图」用例（审查 97 条）；落点 parse 按 section_hint 归位、取消未定位图独立生成（graphrag 让「看得到图」，本项治「别重复看」）。
  - 边界值自校验：LLM 数中文字数会错（声称 21 字实为 19）；落点 `write_cases` 生成「N 字符」用例时程序校验实际字符数。

### ⚠️ 开关债（已实现但未启用 —— 审查发现）

- **规则锚定链** `rule_extract → rule_driven_testpoints → rule_coverage_gate → safe_dedup`：四开关代码**均已实现**（`rule_extract/node.py:26`、`test_points/node.py:575`、`review/{node.py:266,backfill_node.py:105}`、`dedup/{node.py:62,clustering.py:102}`），但 `.env` **全默认关** → 本批 0 rules。
  - 对应审查「冗余去重失效 / 联动·权限覆盖弱」：dedup **基础 bigram 去重一直在跑**（本批折叠 167 条），但 `safe_dedup` 护栏 + `rule_coverage_gate` 覆盖闸**需整条链按依赖顺序开启才生效**——只开 `safe_dedup` 无 rule_id 锚点会空转。
  - 启用受「先跨 PRD 度量再放量」铁律约束。plan `docs/plans/2026-06-15-rule-anchored-coverage.md`。

---

## 🛣 推进路线（建议顺序与依赖）

- **阶段 A · 通用性地基** —— ✅ 大部完成
  - 落点⑧ 去领域绑定（全局判定 LLM 化 + 切分通用化）：✅ 实现+灰度。
  - 落点③升级 跨 PRD 度量：⛔ **阻塞**——库内仅 1 份干净 PRD（自签书已被原型回灌污染），需用户补充其他领域 PRD 后开工。
  - 原则：**先跨 PRD 度量、再放量；任何调参不得只凭单份 PRD**。
- **阶段 B · 不被放量卡的生成增强（当前可做）**
  - 落点⑥ CoT 显式化（write_cases 分步推理）—— 直接提断言质量，不依赖检索放量/新 PRD，单 PRD 即可验。**← 当前主攻。**
- **阶段 C · 检索增强（每步用跨 PRD 尺子验证，待补 PRD 解阻）**
  - 落点④ 语义分块 → 落点② cross-encoder 重排（先调研网关 rerank 能力）→ 落点①/④ 放量决策；落点⑤ 大 PRD 按需 RAG。

> 原则：每个落点都带灰度开关 + 可降级 + **先跨 PRD 度量再放量**；只增强不破坏现有「覆盖系统化 / 事实接地 / 溯源」资产；**不引入领域专属硬编码**。

## 📌 进度日志

- **2026-06-29**
  - 批次 `0c9b63e6`（漫剧 2252 用例）多智能体审查 + 行业最佳实践对照（产物 `.audit/0c9b63e6-.../{REPORT.md,findings/}`）。
  - 新增**用例质量侧 Gap ⑨–⑭**：⑨ verify 跨族+矛盾扫描（已出 spec/plan）、⑩ 优先级体系、⑪ 维度命名统一、⑫ 结构化覆盖技术、⑬ 占位用例分流、⑭ 图片影子重复+边界值自校验。
  - 登记**「开关债」**：规则锚定链四开关均已实现但默认关（本批 0 rules）→「冗余去重/覆盖弱」根因之一；启用需整条链 + 跨 PRD 铁律。
  - **更正**：`grounded_provenance_enabled` / `hybrid_cross_retrieval_enabled` / `cheat_sheet_*` 在 `.env` 实为 **true**（此前误把 `generation_config=null` 当默认关）。
  - **线 A/B/C 推进**：⑨ verify 跨族+矛盾扫描（代码已实现+提交 `b887d4e..d141609`+`1c35ee4`）；⑩ 优先级 risk + ⑪ 维度 enum 收敛（线A，已实现+两轮review采纳+提交 `72d9b85..b380428`，③离线验证维度 98→28、other 1%）；⑫ 结构化覆盖（线B，spec/plan `docs/{spec,plans}/2026-06-29-structural-coverage-*`，**待执行**）；⑬ 占位分流 + ⑭ 图归位/边界自校验（线C，spec/plan `docs/{spec,plans}/2026-06-29-quality-patches-*`，**待执行**）。
- **2026-06-25**
  - 落点⑧ 收口：功能点切分通用化（LLM 大纲分段）✅ 实现+灰度（commit a1b7979..7c8a2a6；12 单测 + 全量 157 passed 零回归；深层 container/未标标题折叠保内容、顶层 meta 降级防杀全树）。至此⑧两部分（全局判定+切分）均完成。
  - 路线图校正：⑦/⑧/切分 标实际状态。启动**落点⑥**——当前无新 PRD、检索侧放量受铁律阻塞，⑥ 是收益不被卡的最高 ROI 项。
  - 落点⑥ 升级为「大改动」：实测确认 provenance 有 bug（post-hoc tagger 取前 200 字、定位不准、连带 trust/confidence 算歪）；调研行业溯源/引用接地最佳实践（见基线 11–15）→ 方案＝CoT + 生成期溯源派生&三查校验 + 修复闭环 + 溯源度量尺子。
  - 落点⑥ ✅ 收口：7 commits、3 轮 GPT review、161 单测、灰度零回归。单 PRD e2e（自签书全图）实证引用精确率 0.93、新旧溯源对照决定性（旧=每条同一无关前 200 字，新=每条 claim 级真实原文）。待放量（.env 开开关）。
- **2026-06-24**
  - NO_GO 阈值 0.6→0.2（commit 94ed7c9）：短/精炼 PRD 不再被 comprehend 闸拦死。
- **2026-06-23**
  - 落点① 验证：轻量检索对照（`.qa_probe/retrieval_diff.py`）+ 新建检索尺子（`eval/retrieval/`）实测 —— hybrid 在真实大 PRD 上 Recall@3 0.30→0.85（权限簇盲区救回，关键词召回为 0 的功能点被向量补回），但负样本噪声率高（向量路恒填满 top_k）。
  - **数据否决「cosine 下限」**：单主题 PRD 信噪相似度重叠（信号中位 0.69 / 噪声中位 0.50 且最高 0.69），阈值无法分离 → 该旋钮在本类文档无效（多领域 PRD 可能仍有效，故保留为默认关可配置项，勿写死否决）。
  - 落点③ 单 PRD 尺子建成（设计/计划/实现见 `docs/spec/` 与 `eval/retrieval/`）。
  - **战略修正（通用性）**：识别出过拟合根因 —— ①全局识别写死领域关键词（投放方式/监测链接）；②调参/结论只用 1 份 PRD。新增**落点⑧（去领域绑定）**并提为最高优先；③升级为「跨 PRD」。排查确认库内**仅 1 份真实 PRD**，跨 PRD 度量待补充其他领域文档。
- **2026-06-22**
  - 修复嵌入链路：列维度 1536→1024（迁移 021）、批大小 2048→10、ORM 维度 1024（commit `0d24ca5`）；PRD 已可向量检索（197 切片，completed）。
  - 排查确认：**生成全链路此前完全不依赖向量检索**（走 PRD 全文 + 关键词词项 CrossFeatureIndex + 关联图）；`document_embeddings` 当前是「建好未接线」状态。→ 纠正了「嵌入失败影响生成质量」的早期误判。
  - 落点①：hybrid 检索 plan 产出 `docs/plans/2026-06-22-hybrid-cross-feature-retrieval.md`（后已实现）。

## ⚠️ 已知问题（非落点，待排期）

- **网关残缺/截断 JSON**（健壮性）：`get_llm_client().generate_structured` 偶发收到不完整 JSON（典型报错 `Expecting ',' delimiter: line 1 column N`），导致 write_cases 子批 / verify 批 / 图片描述 解析失败。现有「重试 + 子批隔离」兜底，但偶发仍丢少量用例/核验/图述。
  - 证据：⑥ e2e 自签书全跑（1 个 write_cases 子批 + 1 个 verify 批失败）；早前「图片描述失败 …diagram-3.png: Expecting ',' delimiter」同源。
  - 建议：在 `generate_structured` 层加 JSON 容错（截断/尾部修复、二次重解析、失败时更强约束的重试提示），不依赖单次返回即完整。影响所有结构化 LLM 调用，价值面广。

## 🔧 维护说明

- 每完成一个落点：更新其状态（⬜→🟡→✅）+ 回填关联 plan 路径与 commit，并在「进度日志」追加一行。
- 新的调研结论：补进「行业最佳实践基线」或「对标矩阵」，保持本文件为唯一事实源。
- 关联文档：`findings.md`（研究证据）、`task_plan.md`（更宏观的架构记忆，若存在）、各落点 `docs/plans/*.md`、`docs/spec/*.md`、尺子 `eval/retrieval/`。
