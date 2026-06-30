# 同实体门控（治概念混淆型假 conflict）Implementation Plan

> **状态：已执行**（commit `1b31c16`…`5010803` + GPT Review 修复 commit）。Task 1–4 已落地并测试绿；Task 5（resume 重跑观测）按用户决定暂缓，留待后续手动验证。下方行号为执行前快照，已过期，勿按行号二次定位。
> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> 关联 spec：`docs/spec/2026-06-30-conflict-entity-gate-design.md`。

**Goal:** 用通用「同实体门控」治概念混淆型假 conflict（§7.2 的 15 条最典型）：判 conflict 必须"用例对象 = PRD 反驳条款对象"，不同实体则撤销。rubric 加规则 + 结构化输出 subject + 确定性后处理门控（词法兜底）。**灰度可回退、关时零回归、不烧大 PRD（单测 + fixture + retry resume 观测）。**

**Architecture:** rubric 加"同实体前置"硬规则（抽成独立常量 `CONFLICT_ENTITY_GATE_INSTRUCTION`，**仅当 `conflict_entity_gate_enabled` 开时注入**——关时 rubric 层也逐字节现状）并要求 conflict 输出 `conflict_subject_case/conflict_subject_prd/same_entity`；`_CaseVerdict`+`CaseVerification` 加字段；verifier 后处理对 `verdict=conflict` 仅当 LLM 明确 `same_entity=False` 时降级 ungrounded + 标 `conflict_entity_mismatch`，词法 `_same_entity` 作佐证但不覆盖 LLM 的同实体判断（防误伤真 conflict）。

**Tech Stack:** Python 3.12 / pydantic v2 / pytest（asyncio_mode=auto，mock LLM）。

---

## 现状速查（对齐当前代码）

- `stages/verify/rubric.py`：`VERIFY_SYSTEM_PROMPT`（行9-35，conflict 标准 行13、硬编码专项 行21）；`CROSS_SECTION_CONFLICT_INSTRUCTION`（37-46，**与本计划无关**，勿动）。
- `stages/verify/verifier.py`：`_CaseVerdict`（行78-85）；`_normalize_verdict`（92-96）；`verify_cases` system_prompt 拼接（147-149）；`_verify_batch` 内 `generate_structured`（166-172）；后处理构造 `CaseVerification`（约行179-201，`v=by_id.get`、`verdict=_normalize_verdict(v.verdict)`、`CaseVerification(...)`）。
- `schemas/test_case.py`：`CaseVerification`（46-61）；`Verdict` 枚举（24）；`_VERDICT_BUCKET` 在 verifier（34-39，conflict→to_fix）。
- `core/settings.py`：灰度开关区（`verify_cross_section_conflict_enabled` 等）。
- **mock 约定**：`monkeypatch.setattr(vmod, "get_llm_client", lambda: fake)`，fake 返回构造好的 `_VerifyLLMOutput`。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动。每个 Task 只 `git add` 本计划列出文件，**严禁 `-A`/`git add .`**。

## File Structure

- **Modify** `src/testcase_generator/schemas/test_case.py`（`CaseVerification` 加 3 字段）
- **Modify** `src/testcase_generator/stages/verify/verifier.py`（`_CaseVerdict` 加字段 + `_same_entity` + 后处理门控）
- **Modify** `src/testcase_generator/stages/verify/rubric.py`（同实体前置规则 + 输出字段说明）
- **Modify** `src/platform_api/core/settings.py`（`conflict_entity_gate_enabled` + `conflict_entity_jaccard_threshold: float = 0.5`）
- **Create** `tests/testcase_generator/test_conflict_entity_gate.py`

---

## Chunk 1: schema 加字段（TDD）

### Task 1: `CaseVerification` + `_CaseVerdict` 加 3 字段

**Files:** `test_case.py`、`verifier.py`、Test: `tests/testcase_generator/test_conflict_entity_gate.py`

- [ ] **Step 1: 写失败测试**——`CaseVerification(conflict_subject_case="监测链接", conflict_subject_prd="投放链接", conflict_entity_mismatch=True)` 可构造；默认值 `""/""/False`（向后兼容）。
- [ ] **Step 2: 跑失败** → FAIL。
- [ ] **Step 3: 实现**——`test_case.py` `CaseVerification` 末尾加：
```python
    conflict_subject_case: str = Field(default="", description="（verdict=conflict 时）用例断言所约束的对象/字段")
    conflict_subject_prd: str = Field(default="", description="（verdict=conflict 时）PRD 反驳条款所约束的对象/字段")
    conflict_entity_mismatch: bool = Field(default=False, description="conflict 双方非同一实体（疑似概念混淆假矛盾，已被同实体门控降级）")
```
`verifier.py` `_CaseVerdict` 加 `conflict_subject_case: str=""` / `conflict_subject_prd: str=""` / `same_entity: bool=True`（默认 True：不开门控/未输出时不误撤）。
- [ ] **Step 4: 跑通 + Commit**（add test_case.py verifier.py test 文件）。

---

## Chunk 2: rubric 同实体前置规则

### Task 2: rubric 加规则 + 输出字段说明

**Files:** `rubric.py`

- [ ] **Step 1**：把"同实体前置"硬规则抽成**独立常量** `CONFLICT_ENTITY_GATE_INSTRUCTION`（仿 `CROSS_SECTION_CONFLICT_INSTRUCTION` 写法，**不写入 `VERIFY_SYSTEM_PROMPT`**），内容由 verifier 在 `conflict_entity_gate_enabled` 开时拼接注入——关时 rubric 层也逐字节现状（GPT-1 修复：避免关开关仍受 rubric 引导的行为漂移）：
```
   【附加规则 · 同实体前置（判 conflict 的必要条件）】
   - 只有当"用例断言所讲的对象/字段"与"你要引以反驳的 PRD 条款所讲的对象/字段"是【同一实体】时，才可判 conflict。若二者是不同对象（如用例讲"监测链接"、PRD 条款讲"投放链接"；或不同字段/不同页面/不同投放方式），**不构成 conflict**——应按该用例的实际 PRD 支撑情况判 grounded / ungrounded / undefined。
   - 判 conflict 时必须结构化输出：conflict_subject_case（用例讲的对象）、conflict_subject_prd（PRD 反驳条款讲的对象）、same_entity（二者是否同一实体；不是同一实体时 same_entity=false，并改判为 grounded/ungrounded/undefined）。
   - 其余 verdict 这三字段留默认（空串 / true）。
```
- [ ] **Step 2**：verifier 注入逻辑加 `if settings.conflict_entity_gate_enabled: system_prompt += CONFLICT_ENTITY_GATE_INSTRUCTION`；冒烟（import 不报错）。
- [ ] **Step 3: Commit**（add rubric.py verifier.py）。

---

## Chunk 3: 后处理门控（TDD，核心）

### Task 3: `_same_entity` 词法兜底 + 门控降级

**Files:** `verifier.py`、`settings.py`、Test 同文件

- [ ] **Step 1: settings**：加 `conflict_entity_gate_enabled: bool = False` + `conflict_entity_jaccard_threshold: float = 0.5`（词法兜底阈值，可配）。
- [ ] **Step 2: 写失败测试**（mock LLM 输出）——
  - §7.2 型：`verdict=conflict, conflict_subject_case="监测链接", conflict_subject_prd="投放链接", same_entity=False` → 门控开 → 结果 `verdict=ungrounded`、`conflict_entity_mismatch=True`、bucket=needs_spec。
  - 词法不覆盖 LLM 同实体判断（GPT-3 修复）：`same_entity=True` 但 subject="监测链接"/"投放链接"（字符集 Jaccard≈0.33<0.5）→ **不降级**（尊重 LLM 的 same_entity=True，防误伤）。词法仅作 rationale 佐证。
  - `same_entity=False` 即便词法判同实体（subject 高重叠）→ 仍降级（尊重 LLM 判定）。
  - **不误伤**（含同实体但措辞分歧大边界）：真 conflict `conflict_subject_case="标题字数上限", conflict_subject_prd="字数"`（Jaccard 低但 same_entity=True）→ **不降级**。
  - 关门控：`conflict_entity_gate_enabled=False` → 逐字节现状（conflict 不动，rubric 段落也不注入）。
  - rubric 注入因果链（GPT-1 修复）：关门控时 `CONFLICT_ENTITY_GATE_INSTRUCTION` 不进 system_prompt，开时才进。
- [ ] **Step 3: 实现**——
  - 纯函数 `_same_entity(a: str, b: str) -> bool`：归一化（仿 clustering `_normalize`：去标点/小写/保留中日韩字母）取**字符集**，算 **Jaccard = |A∩B| / |A∪B|**；`Jaccard >= 阈值 → True（同实体）`、`< 阈值 → False（不同实体）`。**⚠️ 禁止退化为"有无公共 token"**（"监测链接"∩"投放链接"={链,接} 非空，但 Jaccard=2/6=0.33<0.5 → 须判不同实体）。任一为空串 → 返回 True（无法判定、保守不撤，防误伤真 conflict）。阈值取 `settings.conflict_entity_jaccard_threshold`。
  - 后处理（构造 `CaseVerification` 处）：`if settings.conflict_entity_gate_enabled and verdict=="conflict":` **仅当 `v.same_entity is False`** → `verdict="ungrounded"`、`bucket=needs_spec`、`conflict_entity_mismatch=True`、rationale 前缀标注撤销原因；词法 `_same_entity` 仅作佐证写入 rationale，**不单独触发降级**（`same_entity=True` 时不撤，防词法误伤同实体但措辞分歧大的真 conflict）。
  - 把 `conflict_subject_case/prd` 透传进 `CaseVerification`（落库观测）。
- [ ] **Step 4: 跑通 + 全量回归**
Run: `uv run pytest tests/testcase_generator/test_conflict_entity_gate.py tests/testcase_generator/ -q --ignore=tests/testcase_generator/integration`
- [ ] **Step 5: ruff + Commit**（add verifier.py settings.py test）。

---

## Chunk 4: 端到端 fixture + 现有批次观测

### Task 4: 已知 §7.2 fixture 端到端（开关因果链）

**Files:** Test 同文件

- [ ] **Step 1**：仿 `test_verify_cross_section.py` 的 fixture 端到端——构造监测链接用例 + §5.8.3/§7.1.1 章节，mock client 依 `same_entity`/subject 产出，断言"门控开→§7.2 型 conflict 被降级 / 关→保持 conflict"。
- [ ] **Step 2: 跑通 + Commit**。

### Task 5: 现有批次观测（不烧大 PRD）

- [ ] **Step 1**：`conflict_entity_gate_enabled=true` + 用 ① 的 `scripts/reverify_batch.py`（若已落地）或同法，对 `278c211f` 从 verify 阶段 resume 重跑（仅 verify→落库，几刀）。
- [ ] **Step 2**：导出对比——§7.2 模块 `verdict=conflict`（to_fix）数显著下降、转 needs_spec 且 `conflict_entity_mismatch=True`；抽查未误伤真 conflict（标题包字数等仍 conflict）。
- [ ] **Step 3**：结论记入 roadmap ④ 进度。

---

## 总验收标准

- [x] §7.2 型（不同实体，`same_entity=False`）`verdict=conflict` → 门控降级 ungrounded + `conflict_entity_mismatch=True`（单测 + fixture）。
- [x] 词法佐证：`same_entity=False` 时词法 Jaccard 写入 rationale 作佐证；`same_entity=True` 时词法不覆盖（不误伤同实体但措辞分歧大的真 conflict）。
- [x] **不误伤**：真 conflict（`same_entity=True`，含 subject 措辞分歧大/Jaccard 低）→ 不降级。
- [x] 关 `conflict_entity_gate_enabled` → 逐字节现状（后处理不动 + rubric `CONFLICT_ENTITY_GATE_INSTRUCTION` 不注入）。
- [ ] `278c211f` resume 重跑后 §7.2 to_fix 显著下降、未误伤真 conflict。（Task 5，暂缓待手动观测）
- [x] 全量（排除 integration）回归绿；ruff 干净；提交仅含本计划文件。

## 风险与回退

- **LLM same_entity 误判** → 仅当 LLM 明确 `same_entity=False` 才降级；`same_entity=True` 一律不撤（词法不覆盖），确保真 conflict（同实体）不被误撤；回退即关开关（rubric + 后处理双关闭）。
- **降级粒度**（ungrounded 而非 grounded）→ 保守 + 标记待人工；二次重判 grounded 列 future。
- **词法兜底不再单独触发降级** → 仅作 `same_entity=False` 的佐证；"LLM 误填 same_entity=True 但实为不同实体"的漏网情况由 rubric 同实体前置规则 + 人工复核 needs_spec 兜底（保守、可恢复）。
- **rubric 抽离受开关控制** → 关开关时 `CONFLICT_ENTITY_GATE_INSTRUCTION` 不注入，rubric 层也逐字节现状（完整回退无需 revert）。
- **提交污染** → 每 Task 仅 `git add` 指定文件，绝不 `-A/.`。
