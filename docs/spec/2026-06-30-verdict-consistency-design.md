# 同构同判（verdict 判级抖动收敛）— 设计文档

> 状态：设计（brainstorming 产出）。承接 roadmap `2026-06-30-quality-alignment-roadmap.md` ⑤。
> **依赖 ④**：基于 ④ 之后的 `verifier.py`（同实体门控已在 `_verify_batch` 内）。
> 来源：batch `278c211f` 审查 —— 同构用例 verdict 判级分裂；2026 LLM-as-judge 调研。

## 1. 背景与问题

LLM-judge 单次判定不稳（调研：pairwise flip 13.6%、单次 fidelity 仅 86.6%、需 11+ 次投票才稳）。审查实证：**功能/断言相同的用例 verdict 分裂**——§7.2 行2(grounded) vs 行8(conflict) 断言逐字相同；批创A 模块40 行1(ungrounded) vs 行16(grounded) 同一 source_quote。

注意分工：**② 已治 provenance 同源一致**（同 quote 同 grounding）；**⑤ 治 verdict 同构一致**（同断言用例同 verdict）+ 降低单次抖动。二者互补、层次不同。

## 2. 现状（④ 之后，对齐代码）

- `verifier.py`：`_verify_batch`（行194-275）单条判定 + ④ 同实体门控（234-261）产出 `CaseVerification`；`verify_cases`（170-286）按 feature 分片并发、`results` 聚合（283-285）后直接 return。**无跨条 verdict 一致化、无多次投票**——每条单次 LLM verdict。
- `_VERDICT_BUCKET`（36-41）verdict→bucket 确定性映射。
- 严苛度优先级（rubric）：conflict > undefined > ungrounded > grounded。

## 3. 目标

①同构用例（同断言/高相似）verdict 一致；②降低单次 conflict 误判抖动。**5a 确定性一致化为主（零 LLM 成本）**、**5b conflict 多次投票为灰度增强**；不烧大 PRD（5a 离线/单测、5b retry resume）。

## 4. 方案

### 5a 判后聚类一致化（确定性，主）
`verify_cases` 的 `results` 聚合后、return 前，加 `reconcile_verdicts(results, cases)`：在**同 feature_id** 内，按 `title` 相似度（`SequenceMatcher ≥ reconcile_sim`，默认 0.93）聚簇；簇内 verdict 取**多数票**（平票取较严：conflict>undefined>ungrounded>grounded），同步改 bucket。**在 ④ 门控之后**（④ 先撤假 conflict，5a 再跨条统一）。**尊重并传播 ④ 的同实体门控（自审关键）**：簇内若有任一条 `conflict_entity_mismatch=True`（已确认概念混淆假矛盾），则该簇**从候选剔除 conflict**（同断言→同为假矛盾），在非 conflict 中取多数并传播 mismatch——既防 5a 把 ④ 降级的 ungrounded 拉回 conflict，又能把 LLM `same_entity` **漏判**的同簇 conflict 一并救下（5a 由此**增强** ④）。**衍生证据字段一致化（GPT Review 🔴#1 + 第二轮 🟡#2）**：改判时按新 verdict 同步衍生字段——降级（新 verdict≠conflict）清空 `conflicting_refs/cross_section_conflict/conflict_subject_*/prd_evidence`，避免 verdict=ungrounded 却残留冲突依据的自相矛盾（`prd_evidence` 清为空串而非 None：`export_task._review_row` 用 `.get("prd_evidence","")` 读它进待修正清单，None 会渲染成字面 "None"，空串才正确；`unsupported_assertions` 语义跨 verdict 兼容故保留）；升级（新 verdict=conflict）不伪造跨节冲突依据（`cross_section_conflict` 保持 False、`conflicting_refs` 保持空），仅靠 rationale 追溯，`summarize` 单列 `reconciled_conflict` 计数使其不混入 `cross_section_conflicts`、不污染 5b 观测基线。rationale 标记"同构一致化"用模块级常量 `_RECONCILE_RATIONALE_TAG` 在写入与 summarize 判定处共享，避免文案漂移导致计数静默失效（第二轮 🟡#1）。纯确定性、可单测/离线。

### 5b conflict 多次投票（灰度增强，治单次 noisy）
对首轮 `verdict=conflict` 的用例（判错代价最高、占比小），独立复判 `revote_n-1` 次（默认共 3 次），多数定 verdict（**平票取较严**），再走 ④ 门控。仅 conflict 子集 → 成本可控（grounded 多数不复判）。**成本口径**：每个含 conflict 的 batch 把 conflict 子集合并为 1 次 LLM 调用 ×(`revote_n-1`)（非每条单独复判，更省）；复判在单个 `async with semaphore` 内串行跑完 `revote_n-1` 次、持有信号量整个循环，会压低其他 batch 并发——属成本换稳定的权衡，YAGNI 暂不优化为并发复判。

## 5. 设计决策与权衡（自审）

- **5a 多数票（非"取最严"）**：取最严会把同簇的 grounded 拉成 ungrounded/conflict、过度保守且可能制造假 conflict；多数票更平衡，平票才取较严。
- **5a 在 ④ 之后**：④（batch 内单条撤假 conflict）→ 5a（聚合后跨条统一），顺序明确、不互相覆盖。
- **5a 用 SequenceMatcher 而非 embedding**：确定、零成本、不依赖 ③（③ 的去重簇在 dedup 阶段、晚于 verify）；限定**同 feature** 降误聚类。
- **5a 阈值保守（0.93）**：只统一"高度同构"，避免把"同 feature 但不同断言"误并。离线评估发现 0.92 会把 IAP(35宏参数) 与 IAA(30宏参数) 这类仅差产品代号/数值的高相似标题误并（相似度 0.9231），0.93 切散该误簇且保留全部真同构簇。
- **5b 仅 conflict 子集复判**：与 ②（provenance）、④（门控）正交；成本为每个含 conflict 的 batch 合并 1 次调用 ×(`revote_n-1`)，非 conflict×(n-1) 逐条。
- **5a 与 ④ 协同（自审关键）**：5a 多数票**不可撤销 ④ 的降级**——簇内有 `conflict_entity_mismatch=True` 时，从候选**剔除 conflict**（同断言即同概念混淆），按非 conflict 多数票统一 + 传播 mismatch。这样既防 5a 把 ④ 降级的 ungrounded 拉回 conflict，又能救 LLM `same_entity` 漏判的同簇 conflict（5a 增强 ④）。mismatch 标记保留于 rationale 可追溯。

## 6. 范围

**做**：5a `reconcile_verdicts` 纯函数 + verify_cases 接入（灰度 `verdict_reconcile_enabled`）；5b conflict 多次投票（灰度 `conflict_revote_enabled` + `revote_n`）；单测 + 5a 离线 + 5b retry resume 观测。

**不做（YAGNI）**：不改 ④ 门控 / ② provenance / rubric 判据；不做全量多次投票（仅 conflict）；不引入 embedding（5a 用 SequenceMatcher）；不跨 feature 一致化（防误并）。

## 7. 验收

- 5a 单测：同 feature 高相似簇 verdict 分裂（如 grounded/grounded/conflict）→ 多数票统一为 grounded；平票取较严；bucket 同步。
- 5a 离线：现有 3185 条跑 5a，统计被一致化的簇数 + 抽查未把不同断言误并。
- 5b：retry resume 重跑（几刀），conflict 复判后稳定性提升、抽查无新误判。
- **零回归**：两开关关 → 逐字节现状。
- **不误伤**：真 conflict 同构簇 → 统一为 conflict（多数票）。
- 全量回归绿；ruff 干净；提交隔离。

## 8. 风险

- **5a 误聚类**（同 feature 不同断言被并改判）→ 高阈值 0.93 + 同 feature 限定 + 离线抽查；可调阈值。
- **title 相似度是断言同构的弱代理（GPT Review 🟡#3）**：5a 用 title 相似度近似"断言同构"，但 title 相似 ≠ 断言同构——既有假阳（IAP/IAA 标题 0.9231 相似却不同实体，靠 0.92→0.93 切散），也会有假阴（同断言不同措辞的 title 低于阈值漏并）。**0.93 是针对 IAP/IAA 单一案例调出的经验阈值，非一劳永逸**：每跑新 batch 必须离线抽查新增 conflict 簇（plan Task 4 闸门已固化），出现新的"仅差关键数值/代号但 >0.93"误并或"同断言 <0.93"漏并时调整阈值或策略。受"不引入 embedding"约束，title 作为确定性近似可接受。
- **多数票平票** → 明确"平票取较严"规则。
- **unverified 不参与同构补齐（GPT Review 🟡#4，有意取舍）**：`unverified`（LLM 漏判/batch 失败）语义是"未核验"，不参与聚簇投票、也不被同簇多数补齐——避免把漏判伪装成已判。让其停留 unverified/main 等人工看，比用相似用例的 verdict 猜测更安全。
- **5b 默认开但未真实观测（GPT Review 🟡#2）**：5b 无法离线评估（需真实 LLM），默认开启是"未评估的主动决策"（用户决断：能力就绪、随时可跑），成本为每个含 conflict batch 额外 (`revote_n-1`) 次合并调用。待 Task 5 关/开对比 `by_verdict.conflict` 通过后视情保留或回退置 False。
- **5a 改判字段一致性（GPT Review 🔴#1）**：5a 双向改判须同步衍生证据字段（降级清空 conflict 依据、升级不伪造 refs），`summarize` 单列 `reconciled_conflict` 避免 5a 升级出的 conflict 污染 `cross_section_conflicts`/`by_verdict.conflict` 的 5b 观测基线。
- **5b 成本** → 仅 conflict 子集、n 默认 3、灰度可关。
- **与 ④ 顺序** → 固定 ④ 在前（batch 内）、5a 在后（聚合后）。
