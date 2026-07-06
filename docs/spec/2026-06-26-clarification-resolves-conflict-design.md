# 澄清直接消解冲突（断澄清死循环）— 设计文档

> 状态：设计（brainstorming 产出，方案 A）。下一步：writing-plans 出实施计划。
> 关联：comprehend 质量门 NO_GO 澄清流程；上一轮改造 `docs/spec/2026-06-26-gate-conflict-clarification-ux-design.md`（冲突卡片化）。
> 方案选择（已与用户确认）：走**方案 A——澄清作为终局裁决直接消解对应冲突，resume 后不再重新识别**（非纯 prompt 的方案 B）。
> v2 修订：依据 critic 评审修正 1 Blocker（澄清答案双层嵌套）+ 4 Minor，详见 §7。

## 1. 背景与目标

### 1.1 现状问题（死循环根因）

用户对质量门冲突提交澄清后，**下一步又被要求裁决同样的冲突**，陷入死循环。根因链（已核对代码）：

1. `interrupt` 恢复后回到 comprehend 重新评估：`graph.py:84` `graph.add_edge("interrupt", "comprehend")`。
2. comprehend 重跑时，把用户澄清回答作为 **trust_level=3 的新信源**注入 LLM：`node.py:211-217`。
3. LLM 把「用户澄清」当成一个独立信源，与「原文」对比 → 发现两者不一致 → **报为新冲突** → 又 NO_GO → 又弹窗。
   - 实证：复跑截图里新一轮冲突描述为 `'...原文' vs '用户澄清 Q-002：...'`，即上一轮的澄清成了这一轮的冲突对象。
4. 这类「原文 vs 用户澄清」冲突，用户澄清那一方**无章节定位** → 触发上一轮的占位降级 → 显示为纯文字框（连带的「富文本框不友好」问题，是本死循环的副产物）。

**严重性**：高。除非某轮 LLM 偶然不报冲突，否则用户**永远走不完澄清、无法生成用例**。

> 关键事实：`evaluate_gate`（gate.py:38-44）只依据 `understanding_coverage` 与 `conflicts` 中是否有 `resolution=="unresolved"`；**盲区（blind_spots）不影响 gate**。故死循环纯由「冲突反复复现」造成。

### 1.2 目标

- 用户对某冲突的裁决 = **终局决定**，直接消解该冲突，resume 后不再重新识别它、不再就它弹窗。
- **彻底断循环**：澄清恢复后不重新调 LLM 做冲突识别（不重跑 = 不可能复现「澄清 vs 原文」冲突）。
- 加**安全阀**：澄清轮数上限，极端情况强制放行，杜绝任何残留死循环。
- 零回归：不触发澄清的批次（首次 GO/CONDITIONAL）行为完全不变。
- 前端**零改动**：澄清提交契约 `{question_id, answer}` 不变。

### 1.3 成功标准

- 用户裁决冲突后提交 → 流水线放行继续（或仅就**尚未裁决**的冲突再问一次），**不再就已裁决冲突重复发问**。
- 不再出现「原文 vs 用户澄清 Q-00X」这类自我指涉的新冲突。
- 多冲突可分轮裁决；全部裁决后必放行；轮数超限有兜底放行。
- 既有未触发冲突的批次、首次 comprehend 行为不变；全量测试通过。

## 2. 范围

**做**：
1. `OpenQuestion` 加 `conflict_id`（冲突类问题关联其来源 `SourceConflict.conflict_id`），`_build_open_questions` 填充。
2. 新增 `apply_clarification_node`（comprehend 阶段）：基于**首次持久化的 `comprehension_report`**，按用户裁决消解对应冲突，重新判 gate、产出剩余 open_questions——**不调 LLM**。
3. 图改造：`interrupt → apply_clarification`（替代 `interrupt → comprehend`）；`apply_clarification` 复用 `gate_router` 条件边 → `{rule_extract / interrupt}`。
4. gate 放行逻辑：冲突全消解后**不因 coverage 低再 NO_GO**（放行 GO/CONDITIONAL，交 verify 兜底）；仍有未裁决冲突且未超轮数 → NO_GO 再问；超轮数 → 强制放行。
5. `PipelineState` 加 `clarification_rounds`；`trust_order.yaml` 加 `max_clarification_rounds`（不硬编码）。
6. 删除 `_build_feature_matrix_llm` 内「`clarification_answers` 作为 trust_level=3 信源注入」死代码块（改边后该块不可达；删除使「不复现澄清-vs-原文冲突」成为结构性保证而非仅靠拓扑——Minor 4）。

**不做**：
- 改 clarify 提交接口契约（`{question_id, answer}` 不变）、前端弹窗（上一轮已完成）。
- 改首次 comprehend 的 LLM 识别逻辑、`evaluate_gate` 纯函数语义（仅在 apply_clarification 内决定放行策略）。
- 盲区类澄清的下游消费（澄清答案仍保留在 state，供后续，但本次不强制下游读取）。
- `SourceConflict` 主字段语义、上一轮的 `conflict_detail` 结构。

## 3. 设计

### 3.1 核心思路：基于「首次 report」消解，不重跑 LLM

首次 comprehend 已用 LLM 识别出**全部**冲突并随 checkpoint 持久化在 `state["comprehension_report"]`。澄清的本质是「对已识别冲突拍板」，无需重新理解全文。因此：

- **首次**：`comprehend`（调 LLM 识别冲突）→ gate NO_GO → `interrupt` 弹窗。（不变）
- **恢复**：`interrupt → apply_clarification`（**不调 LLM**）：取首次 report，按裁决把对应冲突 `resolution` 由 `"unresolved"` 改为 `"用户裁决：{answer}"` → 重新判 gate → 放行或就剩余冲突再 interrupt。

因全程基于**同一份首次 report**，`conflict_id` 始终稳定，`question_id → conflict_id` 关联可靠，**无需跨轮指纹匹配**。

### 3.2 数据模型

`OpenQuestion` 加（`schemas/comprehension_report.py`，可选、向后兼容）：
```python
conflict_id: str | None = Field(default=None, description="冲突类问题关联的 SourceConflict.conflict_id")
```

`PipelineState` 加（`schemas/pipeline_state.py`）：
```python
clarification_rounds: int  # 已执行的澄清轮数（防死循环安全阀）
```

`trust_order.yaml` 的 `gate_config` 加：
```yaml
  max_clarification_rounds: 3   # 澄清轮数上限；超过则强制放行（由 verify 兜底）
```

### 3.3 `_build_open_questions` 关联 conflict_id

冲突类问题构造时带上来源冲突 id（`node.py`，上一轮已在此分支）：
```python
OpenQuestion(..., question_type="conflict", severity="high",
            conflict_detail=conflict.conflict_detail,
            conflict_id=conflict.conflict_id)   # 新增
```
盲区类问题 `conflict_id=None`（默认）。

### 3.4 新节点 `apply_clarification_node`（`stages/comprehend/apply_clarification.py`）

输入：`state["comprehension_report"]`（首次持久化）、`state["clarification_answers"]`、`state["clarification_rounds"]`。

> ⚠️ **`clarification_answers` 形状是双层嵌套**（B1）：resume 经 `Command(resume={"clarification_answers": [...]})` → `interrupt()` 原样返回该 dict → `interrupt_node`（graph.py:40-41）再包一层 `return {"clarification_answers": clarification}`，故 `state["clarification_answers"]` 实为 `{"clarification_answers": [{question_id, answer}, ...]}`，**不是裸列表**。（旧 comprehend 把它整包塞进 LLM prompt、从不迭代，故双层嵌套一直无害潜伏。）

逻辑（**全程不调 `get_llm_client()`**——确定性、可单测、断循环的关键）：
1. `rounds = state.get("clarification_rounds", 0) + 1`。
2. **入口归一化形状**（后端单点，不碰前端/契约）：
   ```python
   raw = state.get("clarification_answers") or []
   answers = raw.get("clarification_answers", []) if isinstance(raw, dict) else raw
   ```
3. 建 `question_id → conflict_id` 映射（遍历 `report.open_questions`，取冲突类问题的 `conflict_id`）。
4. 对 `answers` 里每个 `{question_id, answer}`：
   - 经映射拿到 `conflict_id` → 在 `report.conflicts` 命中该 conflict → 设 `resolution=f"用户裁决：{answer}"`、`resolution_basis="user_clarification"`。
   - `conflict_id` 为空（盲区类答案）或匹配不到 → 跳过消解（防御，不报错；盲区答案处理见 §3.7）。
5. 计算 `remaining = [c for c in report.conflicts if c.resolution == "unresolved"]`。
6. **放行决策**：
   - `remaining` 非空 且 `rounds < max_clarification_rounds` → `gate_result="NO_GO"`，`open_questions = _build_open_questions(blind_spots=[], conflicts=remaining, ...)`（**`blind_spots=[]`**：只就未裁决冲突再问，不重复追问首轮已列盲区——Minor 2）。
   - 否则（无未裁决冲突 **或** 轮数已达上限）→ 放行：`gate_result = "GO" if coverage>=GO_THRESHOLD else "CONDITIONAL"`，`open_questions=[]`，**不因 coverage 低而 NO_GO**（用户已尽力裁决，继续生成、verify 兜底）。
   - **轮数超限强制放行时**：把 `remaining` 里残留 unresolved 冲突标 `resolution="超澄清轮数上限，强制放行"`、`resolution_basis="forced_release"`，保持 report 自洽、便于 verify/审计识别（Minor 3）。
7. 回写更新后的 `comprehension_report`（消解后的 conflicts、新 gate_result、剩余 open_questions）。
8. 返回 `{comprehension_report, gate_result, open_questions:[_open_question_to_payload(q) ...], clarification_rounds: rounds, current_stage:"comprehend"}`。

### 3.5 图改造（`graph.py`）

```python
graph.add_node("apply_clarification", apply_clarification_node)
# 原：graph.add_edge("interrupt", "comprehend")
graph.add_edge("interrupt", "apply_clarification")
graph.add_conditional_edges(
    "apply_clarification", gate_router,
    {"test_points": "rule_extract", "interrupt": "interrupt"},
)
```
`gate_router` 复用不改（它读 `state["gate_result"]`，apply_clarification 已产出）。`interrupt_node` 不变（仍返回 `clarification_answers`）。

### 3.6 前端

**零改动**。澄清提交仍是 `{question_id, answer}`；`apply_clarification` 在后端用 `question_id` 反查 `conflict_id`。上一轮的卡片/选项化弹窗照常工作。

### 3.7 盲区类澄清处理（告知性，Minor 1）

apply_clarification 只消解冲突。盲区类澄清答案：
- 不触发 LLM 重评覆盖度（不重跑 LLM 是断循环前提），不影响 gate（gate 不看 blind_spots）。
- 答案仍随 `clarification_answers` 留存于 state（不丢失），下游消费列为后续（out of scope）。
- 即本版盲区澄清是「告知性」的——用户补充被记录但不改变放行判定，属相对旧行为的**有意范围收窄**（见 §5）。

## 4. 验证

- **零回归**：首次 GO/CONDITIONAL（不触发 interrupt）路径不经过 apply_clarification，行为不变；全量 `tests/testcase_generator/`（排除需 DB 的 integration）通过。
- **后端单测**（确定性，**不调 LLM**，新建 `tests/testcase_generator/test_apply_clarification.py`）：
  - 裁决全部冲突 → gate 放行（GO/CONDITIONAL）、`open_questions==[]`、对应 conflict `resolution` 带「用户裁决」。
  - 只裁决部分 → 仍 NO_GO，`open_questions` 只剩未裁决冲突、且不含已裁决项。
  - 轮数达 `max_clarification_rounds` 仍有未裁决 → 强制放行（CONDITIONAL）。
  - coverage 低但冲突已全消解 → 放行（不因 coverage NO_GO）。
  - `question_id` 匹配不到 / conflict_id 为空 → 跳过、不报错。
  - **B1 形状覆盖**：分别用「双层嵌套 `{"clarification_answers":[...]}`」与「裸列表 `[...]`」两种输入，断言都能正确反查 conflict_id 并消解（防止单测用错形状导致假绿）。
  - **断言 apply_clarification 不调用 LLM**（monkeypatch `get_llm_client` 抛错以反证）。
  - `_build_open_questions` 冲突类问题带 `conflict_id`。
- **图集成**（沿用既有 skip 策略，如可跑则验 interrupt→apply_clarification→gate 路由）。
- **端到端手验**：复跑含冲突 PRD → 裁决 → 不再就已裁决冲突复弹 → 放行继续。

## 5. 风险与缓解

- **改图拓扑（interrupt 回环改向）** → interrupt/resume 仍是 LangGraph 标准机制（interrupt_node 不变，仅其后继边改向）；apply_clarification 纯函数式、可单测；保留 `gate_router` 不改。
- **盲区类澄清「告知性」降级（Minor 1）** → 本版盲区答案不重评 coverage、不下游消费（§3.7）；相对旧「盲区回灌 LLM 抬升覆盖度」是有意功能降级，由 verify 兜底质量。
- **既有边角：低覆盖+无冲突+无盲区的永久挂起（非本 spec 引入、不在覆盖范围）** → `evaluate_gate` 在 coverage<阈值且无冲突无盲区时返回 NO_GO 但 `open_questions=[]`，前端 `openQuestions.length>0` 才弹窗 → 永久 suspended、apply_clarification 够不着。既有缺陷（coverage<0.2 极罕见），本次仅记录不治理。
- **question_id↔conflict_id 失配** → 基于同一份首次 report、conflict_id 全程稳定；失配时跳过该答案（防御）+ 轮数安全阀兜底。
- **覆盖度低被放行的质量风险** → 由既有 verify 关卡标「需求待确认」兜底（与现有 NO_GO 阈值 0.2 放行哲学一致）。
- **state 新增字段** → `clarification_rounds` 默认 0；`OpenQuestion.conflict_id` 默认 None；JSONB/checkpoint 向后兼容。

## 6. 验收标准

- [ ] 裁决冲突后提交 → 不再就已裁决冲突复弹；全部裁决后流水线放行继续。
- [ ] 不再出现「原文 vs 用户澄清 Q-00X」自我指涉冲突（apply_clarification 不调 LLM，从机制上杜绝）。
- [ ] 部分裁决 → 仅就剩余未裁决冲突再问一次；轮数超 `max_clarification_rounds` → 强制放行。
- [ ] 冲突全消解后即使 coverage 低也放行（verify 兜底），不再因 coverage NO_GO 卡澄清。
- [ ] 首次 comprehend / 未触发冲突批次行为不变；全量（排除 integration）测试通过；改动文件 ruff 干净。
- [ ] 前端无改动；澄清提交契约不变。
- [ ] 提交仅含本次相关文件（隔离工作树其他未提交改动）。

## 7. 评审修订记录（v1→v2，依据 critic 对照真实代码）

- **B1（Blocker）**：`state["clarification_answers"]` 实为双层嵌套 `{"clarification_answers":[...]}`（resume `Command` + `interrupt_node` 各包一层），裸列表迭代会崩（批次 FAILED）或裁决全丢。**修**：apply_clarification 入口归一化形状 + 单测覆盖两种形状（§3.4 step 2 / §4）。
- **Minor 1**：盲区类澄清答案收而不用、低覆盖会被首轮放行。**修**：明确盲区澄清为告知性、仅留存不影响 gate（§3.7 / §5）。
- **Minor 2**：第二轮 `_build_open_questions` 若传 `report.blind_spots` 会重复追问已答盲区。**修**：重建剩余问题时 `blind_spots=[]`，只问未裁决冲突（§3.4 step 6）。
- **Minor 3**：轮数超限强制放行后 report 处于「gate=GO 但仍有 unresolved 冲突」不一致态。**修**：强制放行时把残留冲突标 `resolution_basis="forced_release"`（§3.4 step 6）。
- **Minor 4**：死循环根因代码（澄清作 trust_level=3 信源注入）改边后成不可达死代码、根因仍在。**修**：删除该注入块，结构性杜绝（§2 第 6 条）。
- **What's Missing（既有边角，仅记录）**：低覆盖+无冲突+无盲区 → NO_GO 但无 open_questions → 永久挂起，不在本次覆盖范围（§5）。
