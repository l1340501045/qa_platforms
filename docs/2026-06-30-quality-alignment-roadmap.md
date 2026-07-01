# 用例质量对齐行业最佳实践 · 五件套实施路线图

> 状态：路线图（决策已定）。承接：batch `278c211f` 多智能体审查（`.audit/278c211f-6f25-4970-a425-9db94cbc8ff7/REPORT.md`）+ 2026 行业调研。
> 执行：逐项出 spec→plan→自审→交 Claude Code。
> 位置说明：本文件放 `docs/` 根（文件名在 `docs/plans/` 下会被规范化回根，故固定置根）。

## 背景与关键约束

- 审查结论修正后的真相：用例生成本身质量不差（真错 ≈0.9%、真臆造 ≈0）；"效果不太好"主因是 **verify/溯源误判**（部分已被现有机制覆盖，只是结果未落库）+ **灌水（拆条/存在性凑数/去重失效，约 1/4–1/3）** + 几类 LLM-judge 固有抖动。
- **成本铁律**：大 PRD 全链路生成 ≈ **$100/次**。故：能用「单测 / 现有 3185 条离线 / 只重跑 verify」验证的，**绝不跑大 PRD**；$100 只在最终验收烧 **1 次**。
- **现成资产**：`.audit/278c211f-.../modules/*.cases.jsonl`（3185 条完整用例 JSON）= 现成离线测试夹具；`retry` 已支持从 stage `resume`（走 checkpoint，含 `parsed_context`）= 重跑 verify 的省钱手段。

## 五件套 · 实施顺序与成本

| 序 | 项 | 根因 | 行业最佳实践对齐 | 验证方式 | 成本 | 烧大 PRD |
|---|---|---|---|---|---|---|
| ① | **verify 矛盾结果落库修复**（+观测解锁） | 序列化 round-trip 丢 `cross_section_conflict` | —（工程修复） | 单测 round-trip + retry resume 重跑 verify 观测 | 0~几刀 | 否 |
| ② | **同源判定缓存** | 同 `source_quote` 判定不一致 | 判定确定性优先 | 纯函数单测 | 0 | 否 |
| ③ | **语义去重升级** | bigram 抓不到换措辞同义 | embedding+词法 hybrid / 阈值分层 / 可恢复 | 现有 3185 条离线跑 | ≈0（仅 embedding） | 否 |
| ④ | **同实体门控**（替代概念词典） | verify 把不同实体当同一字段判矛盾 | 两阶段：语义相似度+实体重叠（S3CDA / coreference） | retry resume 重跑 verify（仅 conflict+抽样） | 几刀 | 否 |
| ⑤ | **同构同判** | LLM-judge 单次判定抖动 | 多次投票 + 一致性度量（多篇 2026 arXiv） | retry resume 重跑 verify | 几刀 | 否 |
| ⑥ | **生成侧收敛**（拆条上限/存在性合并/P0 配额） | 每测试点 2.81 条、存在性凑数 807、P0 60% | risk 排序 + 配额 | 小 PRD/单模块预验 | 中 | 小 PRD |
| 终验 | 全链路回归 | — | — | **1 次大 PRD 全链路**，对比 baseline | **$100 ×1** | 是 |

## 成本分布（$100 只烧 1 次）

- **① ② ③**：零~极低（单测 / embedding / 现有数据离线）。
- **④ ⑤**：低（`retry` 从 verify 阶段 resume，只重跑 verify→落库，约几刀；或写小脚本只重核 58 条 conflict + 抽样，更省）。
- **⑥**：中（先用小 PRD 或截取大 PRD 2~3 模块预验生成侧规则）。
- **终验**：所有改动合入后，**唯一 1 次** $100 大 PRD 全链路，对比 baseline（矛盾透出 / 灌水 3185→~2000 / 判级稳 / §7.2 假矛盾撤销）。

## 灌水收敛 · 行业最佳实践对齐清单（③ 的依据）

| 行业最佳实践（2026） | 现状 | 要补 |
|---|---|---|
| hybrid：embedding 语义 + 词法(Jaccard/fuzzy) | `safe_dedup` 仅 bigram 词法 | **加 embedding 语义层** |
| 阈值分层：>0.85 候选/可恢复，=1.0 才自动 | 直接标 `duplicate_of` | 加分层 |
| 软标记可恢复 + coverage 不回退校验 | `duplicate_of` 软标记 ✓ | 加折叠前覆盖校验 |
| 按 requirement/test_point 分组比对 | rule 锚定护栏 ✓ | 保持 |
| 大规模 HDBSCAN/MinHash LSH 降 O(n²) | 无 | 3185 规模可先阈值，量大再上 |
| 语义熵/grounding 验证非幻觉 | verify grounding ✓ | 复用 |

结论：现有"规则锚定 + 软标记可恢复"已踩中最佳实践，**缺口仅在把相似度从 bigram 升级为 embedding+词法 hybrid**，且 embedding 基建现成（`knowledge_base/services/embedding`）。

## 行业调研出处（节选）

- 去重：TC_Deduplicator（sentence-transformers + fuzzy/TF-IDF/Jaccard + HDBSCAN）、tdcommons AI test redundancy framework、testless、TestPlanIt（fuzzy gate→LLM 语义二次判）。
- LLM-as-judge 抖动：arXiv 2606.19544（Reliability without Validity）、2606.13685（Coin Flip Judge，pairwise flip 13.6%、需 11+ 投票）、EMNLP2025 Rating Roulette、LangChain Align Evals。
- 需求矛盾/同实体：Springer ALICE（formal logic+LLM, actor-action）、S3CDA（语义相似度+实体重叠两阶段）、RE20 DeepCoref（coreference）。

## 进度

- [x] batch 278c211f 审查 + REPORT + 看板
- [x] 行业调研
- [x] 五件套顺序与成本策略（本文档）
- [x] ① spec + plan + 自审 →（Claude Code）**已执行完成** ✅
- [x] ② spec + plan + 自审（`2026-06-30-provenance-quote-cache-*`）← 执行中（Claude Code）
- [x] ③ spec + plan + 自审（`2026-06-30-semantic-dedup-*`）→（Claude Code）**已执行完成** ✅
  - 离线评估（3185 条，`scripts/dedup_offline_eval.py`）：纯词面 duplicate 228 / unique 2957（7.2%）→ hybrid duplicate 1494 / **unique 1691**（46.9%），优于 ~2000 目标。
  - 抽样 10 个仅语义折叠对：7 真同义、3 误折叠（含 1 边界值对 #2「10条不拆 vs 12条拆3包」）——误折叠靠软标记可恢复 + 生产 safe_dedup 护栏兜底；阈值 0.86 对"数字集不同但语义极近"偏松，量大时可上调。
  - GPT Review 修复 🔴-1（`same_tp` 引用循环外残留变量 `c`，破坏确定性）+ 补 3 回归测试（末条 feature_id 空的同 tp 折叠、降级时词面仍折叠、离线 228 golden 对拍）。重跑离线评估：结果与修复前逐字节一致（末条恰好非空、bug 未触发），修复消除"依赖末条状态"的偶然性。
- [x] ④ spec + plan + 自审（`2026-06-30-conflict-entity-gate-*`）→（Claude Code）**已落地代码，待观测** ✅
  - 同实体门控（rubric `CONFLICT_ENTITY_GATE_INSTRUCTION` 抽离受开关控制 + 后处理 `same_entity=False` 降级，词法 Jaccard 作佐证不覆盖 LLM 同实体判断）。14 单测绿、全量回归 273 passed。
  - GPT Review 修复 🔴-1（rubric 未受开关控制→抽独立常量仅开时注入，关时 rubric 层也零回归）+ 🟡-3（词法兜底不再覆盖 LLM `same_entity=True`，防误伤同实体但措辞分歧大的真 conflict）。
  - 待观测：Task 5 对 `278c211f` resume 重跑 verify（开关开），确认 §7.2 to_fix 显著下降、未误伤真 conflict——按用户决定暂缓，留待手动执行。
- [x] ⑥ spec + plan + 自审（`2026-06-30-generation-convergence-*`）← 待交 Claude Code
- [x] ⑤ spec + plan + 自审（`2026-06-30-verdict-consistency-*`，基于 ④ 后 verifier）→（Cursor）**已落地代码，待观测** ✅
  - 5a 离线评估（3185 条，`scripts/reconcile_offline_eval.py`）：audit JSONL 无生产态 `feature_id`，脚本使用 module 文件名近似 feature/章节粒度。**抽样 GO/NO-GO 已完成**：原阈值 0.92 下 changed_clusters=15 / changed_verdicts=15，14 簇改判正确（真同构抖动收敛：`32__提交时的绑定规则` 模块 7 对逐字同构用例 grounded/conflict 分裂统一为 conflict；6 对 grounded/ungrounded 平票取严统一为 ungrounded），但 **1 簇误聚类**——`验证IAP预置链接含35宏参数`(grounded) 与 `验证IAA预置链接含30宏参数`(conflict) 相似度 0.9231 刚过 0.92 被误并，grounded 被错误升级为 conflict（IAP/IAA 是不同产品、宏参数数也不同）。**决断**：阈值 0.92→**0.93**（切散该误簇且保留全部 14 真同构簇，changed 15→13、conflict +8→+7）；`verdict_reconcile_enabled` 经离线验证后**默认开启**。⚠️ 0.93 是针对 IAP/IAA 调出的经验阈值，每跑新 batch 必离线抽查新增 conflict 簇。
  - 5b 已提供 `conflict_revote_enabled` + `revote_n` 灰度复判能力，**默认已开启**（仅 conflict 子集、成本可控）；真实 LLM resume 观测**暂未做**（环境就绪但 `reverify_batch.py` 会删除重写该 batch 已落库数据 test_cases=3185/test_points=1141，按用户决断暂不跑），留待后续手动观测 by_verdict.conflict 翻转率。⚠️ 5b 默认开是"未评估的主动决策"（5b 无法离线评估、与 5a"评估后开"标准不对齐），待 Task 5 关/开对比通过后视情保留或回退。
  - **GPT Review 修复 🔴#1**：5a 改判只更 verdict/bucket/rationale/mismatch 四字段、衍生证据字段（`conflicting_refs/cross_section_conflict/subject`）不随 verdict 变更，产出 verdict=ungrounded 却残留 conflict 依据的自相矛盾数据，且 5a 升级出的 conflict 污染 `summarize` 的 `by_verdict.conflict`（5b 观测基线）。修复：5a 双向改判同步衍生字段（降级清空 conflict 依据、升级不伪造 refs 保持 `cross_section_conflict=False`）；`summarize` 单列 `reconciled_conflict` 计数使 5a 升级 conflict 不混入 `cross_section_conflicts`。补 3 单测锁定，全量回归 291 passed。
- [x] **五件套 spec/plan 全部配齐** ✅；下一步：各项执行完 → 跑 1 次大 PRD 终验对比 baseline（$100 ×1）
