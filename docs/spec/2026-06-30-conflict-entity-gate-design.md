# 同实体门控（治概念混淆型假 conflict）— 设计文档

> 状态：设计（brainstorming 产出）。承接 roadmap `2026-06-30-quality-alignment-roadmap.md` ④。
> 下一步：writing-plans 出实施计划（执行交 Claude Code）。
> 来源：batch `278c211f` 审查 —— §7.2 的 15 条「假 conflict」（verify 把不同实体当同一字段判矛盾）。

## 1. 背景与问题

§7.2「监测链接绑定」15 条用例被判 `verdict=conflict`（最大单点假矛盾）。根因：用例断言的是**监测链接**（§7.2 自动绑定预置 hash），verify 却拿**投放链接**（§5.8.3 用户单选）来反驳——**两个不同实体**，verify 当成同一字段判了矛盾。

更关键的是：现有 `rubric.py` `VERIFY_SYSTEM_PROMPT` 的「高频误读专项核对」里**已有硬编码概念区分**（"投放方式 vs 竞价策略是不同字段"、emoji 处理…）——这正是"**不通用的概念词典**"雏形：换个电商 PRD 就失效。§7.2 没被硬编码覆盖，于是误判。

## 2. 现状（对齐代码）

- `rubric.py`：`VERIFY_SYSTEM_PROMPT`（行9-35）定义 verdict 判据；conflict = "断言与 PRD 明文相反"（行13）；判定原则里**硬编码**专项（行21「投放方式≠竞价策略」等）。`CROSS_SECTION_CONFLICT_INSTRUCTION`（行37-46）是 PRD 自相矛盾扫描（与 verdict **解耦**，是另一回事，**不是** §7.2 问题）。
- `verifier.py`：`_CaseVerdict`（行78-85，含 verdict / cross_section_conflict / conflicting_refs）；`_normalize_verdict`（92-96）；后处理构造 `CaseVerification`（约行179-201）；verdict→bucket 确定性映射 `_VERDICT_BUCKET`（34-39，conflict→to_fix）。
- `test_case.py`：`CaseVerification`（46-61）；`CrossSectionConflictRef`（37-43）。
- §7.2 的 15 条是 **`verdict=conflict`（→ bucket=to_fix）**，与 `cross_section_conflict` 无关。

## 3. 目标

用**通用的「同实体门控」**取代硬编码概念区分：**判 conflict 前必须确认"用例断言的对象/字段"与"PRD 反驳条款的对象/字段"是同一实体**；不同实体（监测链接 ≠ 投放链接）→ 不构成 conflict，按实际支撑判 grounded/ungrounded/undefined。零领域词、广告/电商通用。预期 §7.2 的 15 条不再误判 conflict。

## 4. 方案

1. **rubric 加"同实体前置"硬规则**（泛化、并逐步替代行21 等硬编码 case）：判 conflict 必须满足"用例与 PRD 条款约束**同一对象/字段**"；不同对象 → 非 conflict。并要求**判 conflict 时结构化输出**：`conflict_subject_case`（用例讲的对象）、`conflict_subject_prd`（PRD 反驳条款讲的对象）、`same_entity`（二者是否同一实体）。
2. **schema**：`_CaseVerdict` + `CaseVerification` 加 `conflict_subject_case: str` / `conflict_subject_prd: str` / `conflict_entity_mismatch: bool`（落库观测）。
3. **确定性后处理门控**（`conflict_entity_gate_enabled` 灰度，不全靠 LLM 自觉）：对 `verdict=conflict` 的用例——若 `same_entity=False` **或** 词法兜底 `_same_entity(subject_case, subject_prd)=False`（**字符集 Jaccard < 0.5**，即核心限定词差异大）→ 判为「概念混淆假矛盾」：**verdict 降级为 `ungrounded`**（移出 to_fix → needs_spec）、`conflict_entity_mismatch=True`、rationale 标注"原 conflict 因对象不一致（X≠Y）撤销，待人工确认是否其实 grounded"。
   > ⚠️ 自审：`_same_entity` **不能用"有无公共 token"**——"监测链接"与"投放链接"共享"链接"会被误判同实体、门控失效。须用字符集 **Jaccard**：监测链接∩投放链接={链,接}、并集 6 → 0.33 < 0.5 → 不同实体；"标题包名称字数"自身 =1 → 同实体（不误伤真 conflict）。
4. 关 `conflict_entity_gate_enabled` 时行为不变。

## 5. 设计决策与权衡（自审）

- **门控双保险**：主力在 rubric（让 LLM 判 conflict 前过"同实体"关、结构化输出 subject）；后处理用 `same_entity` + **词法兜底**（subject 无公共 token）撤销，防 LLM 仍误判。
- **为何词法兜底（Jaccard）而非 embedding**："监测链接" vs "投放链接" 都含"链接"，embedding cosine 偏高、判不出"不同实体"；用**字符集 Jaccard**（≈0.33<0.5）反而能凭限定词差异判出不同实体，且确定、可单测、零成本。注意 Jaccard **不可退化为"有无公共 token"**（共享"链接"会误判同实体）。embedding 作 future 可选增强，不在本步（也避免与 ③ 耦合）。
- **降级到 `ungrounded` 而非 `grounded`（保守）**：§7.2 那 15 条其实是 grounded，但后处理无法确认其支撑，故保守降 `ungrounded`（needs_spec、移出"必须修"）+ 标记待人工；"撤销后二次重判为 grounded"列 future（需多一次 LLM 调用）。
- **不误伤真 conflict**：真 conflict（如标题包名"50字 vs 30字"，同实体"标题包名称字数"）`same_entity=True` 且 subject 有公共 token → 不降级。须测试覆盖。
- **逐步退役硬编码**：rubric 行21 等领域专项可在门控稳定后收敛为通用规则（future，不在本步删，避免回归风险）。

## 6. 范围

**做**：rubric 同实体规则 + 输出字段；`_CaseVerdict`/`CaseVerification` 加 3 字段；`_same_entity` 词法兜底 + 后处理门控；`conflict_entity_gate_enabled` 开关；单测 + 已知 §7.2 fixture 端到端 + retry resume 观测。

**不做（YAGNI）**：不删现有硬编码专项（future 收敛）；不引入 embedding（future）；不做"撤销后二次重判 grounded"（future）；不动 cross_section_conflict 扫描 / 生成 / dedup。

## 7. 验收

- 已知 §7.2 fixture（用例断言"监测链接=预置 hash"、PRD 给"投放链接单选"）：mock LLM 输出 `same_entity=False` → 门控把 verdict 从 conflict 降为 ungrounded、`conflict_entity_mismatch=True`（单测）。
- 词法兜底：LLM 误填 `same_entity=True` 但 subject 无公共 token → 仍撤销（单测）。
- **不误伤**：真 conflict（同实体 subject 有公共 token）→ 不降级（单测）。
- 关 `conflict_entity_gate_enabled` → 逐字节现状（回归）。
- 观测：对 `278c211f` retry resume 重跑 verify（① 已修落库，几刀），§7.2 的 15 条 to_fix 显著下降。
- 全量回归绿；ruff 干净；提交隔离。

## 8. 风险

- **LLM `same_entity` 仍误判** → 词法兜底 + deepseek 跨族 + 保守降级（不会把真 conflict 误撤，因其同实体）。
- **降级粒度**（ungrounded vs grounded）→ 保守降 ungrounded + 标记待人工；二次重判 future。
- **词法兜底误判同义词为不同实体**（如"监测链接" vs "tracking 链接"）→ 偏保守（多撤销）但不致命；conflict 降级仅进 needs_spec、可人工恢复。
