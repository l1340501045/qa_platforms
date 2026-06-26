# 质量门冲突澄清交互改造 Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans（或 subagent-driven-development）执行；步骤用 `- [ ]` 勾选跟踪。
> 关联 spec：`docs/spec/2026-06-26-gate-conflict-clarification-ux-design.md`（含 §7 两轮评审修订）。

**Goal:** 把质量门「冲突类」澄清问题从「一段糊在一起的纯文字 + 空输入框」改造成「结构化卡片（两方并排 + AI 推荐不预选 + 三选项裁决）+ 自动兜底」，顺带根治红框 `'未列'(Level 3)` bug 与前后端字段错配。

**Architecture:** comprehend 阶段让 LLM 结构化输出冲突（`ConflictDetail`：topic + 两方 location/statement/trust_level + 推荐）；新增字段全程走 JSONB 透传，在唯一序列化点（node.py:153）拼前端契约 dict；前端按 `question_type` 渲染卡片/纯文字/输入框；LLM 给不出有效定位时代码降级为纯文字冲突，零崩溃、零回归。

**Tech Stack:** Python 3.12 / pydantic / pytest（asyncio_mode=auto，mock LLM）；React 18 / Ant Design 5 / TypeScript（tsc + eslint，无组件测试基建）。

---

## 现状速查（对齐当前代码）

- `schemas/comprehension_report.py`：`SourceConflict`（source_a/source_b/trust_level/description/resolution，resolution 必填）、`OpenQuestion`（question_id/question/context/related_features/blocking）。
- `stages/comprehend/node.py`：
  - `ComprehensionLLMOutput.identified_conflicts: List[dict]`（无结构，行 48）。
  - `COMPREHEND_SYSTEM_PROMPT`（行 54-68）。
  - `_merge_conflicts`（行 251-282）：LLM 冲突用 `lc.get(..., 默认)` 兜底，`source_a` 默认 `"未知"`、trust_level 默认 3、resolution 默认 `"unresolved"`。
  - `_build_open_questions`（行 285-344）：冲突类 context 拼 `'{source_a}'(Level {trust}) 与 ...`（行 303-304）；盲区类来自 blind_spots。
  - 返回点 `q.model_dump()`（行 153）= **唯一**前端序列化点。
- `gate.py:41`：NO_GO 依赖 `conflict.resolution == "unresolved"`。
- 透传链：interrupt_node（graph.py:31-39 包 `{"open_questions": [...]}`）→ `_extract_open_questions_from_snapshot`（pipeline_task.py，取 `val["open_questions"]`）→ `on_pipeline_suspended`（callbacks.py，存 StageArtifact.open_questions JSONB）→ `get_batch_status`（generation_service.py:78-100，原样透传）→ `get_batch_detail`（batches.py:198）。
- 前端：`types/index.ts` `OpenQuestion={id,question,context,priority}`、`ClarifyAnswer={question_id,answer}`；`pages/Workbench/index.tsx` 弹窗渲染（行 415-448）+ `handleClarifySubmit`（行 170-180，用 `q.id`）。
- **mock LLM 模式**：`monkeypatch.setattr(node, "get_llm_client", lambda: fake)`，fake 实现 `async def generate_structured(self, system_prompt, user_content, output_schema, temperature=...)`。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动（MasterGo / feature-seg 等）。每次提交**只 `git add` 本计划列出的文件**，严禁 `git add -A/.`。

## File Structure

- **Modify** `src/testcase_generator/schemas/comprehension_report.py`（+ ConflictSide/ConflictDetail；SourceConflict/OpenQuestion 加可选字段）
- **Modify** `src/testcase_generator/stages/comprehend/node.py`（LLM schema/prompt、_merge_conflicts、_build_open_questions、_is_placeholder、序列化点）
- **Create** `tests/testcase_generator/test_comprehend_conflicts.py`（后端单测）
- **Modify** `web/src/types/index.ts`（OpenQuestion + ConflictDetail/ConflictSide）
- **Modify** `web/src/pages/Workbench/index.tsx`（按 question_type 渲染 + 选项化 + 提交转答案）

---

## Chunk 1: 后端 schema + 冲突结构化 + 字段链路（TDD）

### Task 1: schema 扩展（向后兼容，只增不删）

**Files:**
- Modify: `src/testcase_generator/schemas/comprehension_report.py`

- [ ] **Step 1: 加 `ConflictSide` / `ConflictDetail`，并给 `SourceConflict`/`OpenQuestion` 加可选字段**

在文件顶部 `from typing import Literal` 已存在。新增：

```python
class ConflictSide(BaseModel):
    """冲突一方"""
    location: str = Field(default="", description="章节定位，如 '§5.6.1' / '§9.2 表'；定位不到留空")
    statement: str = Field(default="", description="该处说法")
    trust_level: int = Field(default=1, ge=1, le=5, description="信任等级（同文档跨章节时两方相同）")


class ConflictDetail(BaseModel):
    """结构化冲突（前端选项化渲染；亦作 LLM identified_conflicts 元素）"""
    topic: str = Field(description="冲突点标题，如 '角色名称字数上限'")
    side_a: ConflictSide
    side_b: ConflictSide
    recommendation: Literal["side_a", "side_b", "neither"] = Field(description="AI 推荐方")
    recommendation_reason: str = Field(default="", description="推荐理由（一句话）")
```

`SourceConflict` 末尾加：
```python
    conflict_detail: "ConflictDetail | None" = Field(default=None, description="结构化时有；规则法/降级时 None")
```

`OpenQuestion` 末尾加：
```python
    question_type: Literal["conflict", "blind_spot"] = Field(default="blind_spot", description="问题类型判别")
    conflict_detail: "ConflictDetail | None" = Field(default=None, description="冲突且结构化时才有")
    severity: Literal["high", "medium", "low"] = Field(default="medium", description="透传前端 priority")
```

（**硬要求**：`ConflictSide`/`ConflictDetail` **必须定义在** `SourceConflict`/`OpenQuestion` **之前**。本文件有 `from __future__ import annotations`，引号字符串注解并不能让 Pydantic v2 解析尚未定义的类，顺序错了 Step 2 冒烟会立即报错。）

- [ ] **Step 2: 跑导入冒烟**

Run: `uv run python -c "from src.testcase_generator.schemas.comprehension_report import ConflictDetail, ConflictSide, SourceConflict, OpenQuestion; print(OpenQuestion(question_id='Q', question='q', context='c').question_type)"`
Expected: 打印 `blind_spot`（默认值生效，旧构造不传新字段不报错 → 向后兼容）。

- [ ] **Step 3: Commit**

```bash
git add src/testcase_generator/schemas/comprehension_report.py
git commit -m "feat(comprehend): 冲突澄清 schema 扩展 ConflictDetail + OpenQuestion 判别字段"
```

### Task 2: `_is_placeholder` 共享占位判定（TDD 纯函数）

**Files:**
- Modify: `src/testcase_generator/stages/comprehend/node.py`
- Test: `tests/testcase_generator/test_comprehend_conflicts.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/testcase_generator/test_comprehend_conflicts.py`：
```python
"""质量门冲突澄清改造 — comprehend 冲突结构化 / 兜底 / 字段链路。"""
from __future__ import annotations

import pytest

from src.testcase_generator.stages.comprehend import node as cnode


def test_is_placeholder():
    for s in ["", "  ", "未列", "未知", "N/A", "n/a", "无", "null", None]:
        assert cnode._is_placeholder(s) is True
    for s in ["§5.6.1", "§9.2 表", "PRD 支付功能"]:
        assert cnode._is_placeholder(s) is False
```

- [ ] **Step 2: 跑测试看失败**

Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py::test_is_placeholder -v`
Expected: FAIL（`_is_placeholder` 未定义）。

- [ ] **Step 3: 实现 `_is_placeholder`**

在 `node.py` 加（放近 `_merge_conflicts` 处）：
```python
_PLACEHOLDER_TOKENS = {"未列", "未知", "n/a", "na", "无", "null", "none", "待定", "-", "—"}


def _is_placeholder(s: str | None) -> bool:
    """判定来源/章节定位是否为空或占位串（用于冲突卡片降级）。"""
    if s is None:
        return True
    t = s.strip().lower()
    return t == "" or t in _PLACEHOLDER_TOKENS
```

- [ ] **Step 4: 跑测试看通过**

Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py::test_is_placeholder -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/testcase_generator/stages/comprehend/node.py tests/testcase_generator/test_comprehend_conflicts.py
git commit -m "feat(comprehend): 加 _is_placeholder 共享占位判定"
```

### Task 3: LLM 结构化输出 schema + prompt

**Files:**
- Modify: `src/testcase_generator/stages/comprehend/node.py`

- [ ] **Step 1: 改 `ComprehensionLLMOutput.identified_conflicts` 为结构化**

`node.py` 顶部已 import `SourceConflict` 等；补 import `ConflictDetail`。把（行 48）：
```python
    identified_conflicts: List[dict] = Field(default_factory=list, description="识别到的信源冲突列表")
```
改为：
```python
    identified_conflicts: List[ConflictDetail] = Field(default_factory=list, description="结构化信源冲突列表")
```

并把 `_build_feature_matrix_llm` 的返回注解（`node.py:162`）`tuple[list[FeatureUnderstanding], float, list[dict]]` 末位 `list[dict]` 改为 `list[ConflictDetail]`，保持类型贯通名副其实。

- [ ] **Step 2: 补 `COMPREHEND_SYSTEM_PROMPT`（行 54-68）冲突结构化要求**

在 prompt 第 3、5 条之后追加（保持原有信任顺序说明）：
```
冲突结构化输出要求（identified_conflicts 每个元素）：
- topic：冲突点简短标题。
- side_a / side_b：各含 location（章节号/表名，如 "§5.6.1"、"§9.2 表"）、statement（该处说法原文要点）、trust_level（同文档跨章节冲突时两方相同）。
- 同一文档不同章节自相矛盾，也必须上报，两方 trust_level 相同。
- location 尽量填真实章节号/表名；【禁止】编造 "未列"/"N/A"/"未知" 等占位词；确实定位不到时把 location 留空（""），仍要上报该冲突（由系统降级处理），不要因定位不清而漏报。
- recommendation：side_a / side_b / neither；recommendation_reason：一句话理由（依据信任顺序/更具体/常识）。
```

- [ ] **Step 3: 跑导入冒烟**

Run: `uv run python -c "from src.testcase_generator.stages.comprehend.node import ComprehensionLLMOutput; print(ComprehensionLLMOutput.model_fields['identified_conflicts'].annotation)"`
Expected: 打印含 `ConflictDetail` 的 List 类型，不报错。

- [ ] **Step 4: Commit**

```bash
git add src/testcase_generator/stages/comprehend/node.py
git commit -m "feat(comprehend): identified_conflicts 结构化 + prompt 要求章节定位与推荐"
```

### Task 4: `_merge_conflicts` 结构化映射 + resolution 解耦 + 占位降级（TDD）

**Files:**
- Modify: `src/testcase_generator/stages/comprehend/node.py`
- Test: `tests/testcase_generator/test_comprehend_conflicts.py`

- [ ] **Step 1: 写失败测试**

追加到 `test_comprehend_conflicts.py`：
```python
from src.testcase_generator.schemas.comprehension_report import ConflictDetail, ConflictSide
from src.testcase_generator.stages.comprehend.blind_spot_detector import BlindSpotDetector


def _detail(loc_a="§5.6.1", loc_b="§9.2 表"):
    return ConflictDetail(
        topic="角色名称字数上限",
        side_a=ConflictSide(location=loc_a, statement="必填 / ≤50字", trust_level=1),
        side_b=ConflictSide(location=loc_b, statement="必填 / 不限字数", trust_level=1),
        recommendation="side_a",
        recommendation_reason="角色名是展示字段",
    )


def test_merge_structured_conflict_maps_and_unresolved():
    out = cnode._merge_conflicts([_detail()], features=[], sources=[], detector=BlindSpotDetector())
    assert len(out) == 1
    c = out[0]
    assert c.source_a == "§5.6.1" and c.source_b == "§9.2 表"
    assert c.source_a_trust_level == 1 and c.source_b_trust_level == 1
    assert c.resolution == "unresolved"          # 与 recommendation 解耦，保证 NO_GO 触发
    assert c.conflict_detail is not None and c.conflict_detail.topic == "角色名称字数上限"


def test_merge_placeholder_location_degrades_detail():
    out = cnode._merge_conflicts([_detail(loc_a="未列", loc_b="")], features=[], sources=[], detector=BlindSpotDetector())
    assert out[0].conflict_detail is None         # 占位 → 降级为纯文字冲突
    assert out[0].resolution == "unresolved"      # 仍触发 NO_GO，不静默丢弃
```

- [ ] **Step 2: 跑测试看失败**

Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py -k merge -v`
Expected: FAIL（当前 `_merge_conflicts` 把 ConflictDetail 当 dict 用 `lc.get` 会出错/不符）。

- [ ] **Step 3: 重写 `_merge_conflicts` 的 LLM 分支（行 265-280）**

把现有 `for lc in llm_conflicts:` 循环体替换为（接收 `ConflictDetail` 对象，而非 dict）：
```python
    for detail in llm_conflicts:
        counter += 1
        cid = f"C-{counter:03d}"
        if cid in existing_ids:
            continue
        placeholder = _is_placeholder(detail.side_a.location) or _is_placeholder(detail.side_b.location)
        rule_conflicts.append(
            SourceConflict(
                conflict_id=cid,
                description=f"{detail.topic}：'{detail.side_a.statement}' vs '{detail.side_b.statement}'",
                source_a=detail.side_a.location or "",
                source_a_trust_level=detail.side_a.trust_level,
                source_b=detail.side_b.location or "",
                source_b_trust_level=detail.side_b.trust_level,
                resolution="unresolved",  # 与 recommendation 解耦
                resolution_basis="llm_structured_detection",
                conflict_detail=None if placeholder else detail,
            )
        )
```
（`llm_conflicts` 现在是 `list[ConflictDetail]`；函数签名 type hint 同步改为 `list[ConflictDetail]`。）

- [ ] **Step 4: 跑测试看通过**

Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py -k merge -v`
Expected: PASS（2 条）。

- [ ] **Step 5: Commit**

```bash
git add src/testcase_generator/stages/comprehend/node.py tests/testcase_generator/test_comprehend_conflicts.py
git commit -m "feat(comprehend): _merge_conflicts 结构化映射 + resolution 解耦 + 占位降级"
```

### Task 5: `_build_open_questions` 透传 detail + question_type + severity + context 安全拼接（TDD）

**Files:**
- Modify: `src/testcase_generator/stages/comprehend/node.py`
- Test: `tests/testcase_generator/test_comprehend_conflicts.py`

- [ ] **Step 1: 写失败测试**

追加：
```python
from src.testcase_generator.schemas.comprehension_report import SourceConflict


def test_build_questions_conflict_carries_detail_and_type():
    conflicts = [SourceConflict(
        conflict_id="C-001", description="角色名称字数上限：'≤50字' vs '不限字数'",
        source_a="§5.6.1", source_a_trust_level=1, source_b="§9.2 表", source_b_trust_level=1,
        resolution="unresolved", resolution_basis="x", conflict_detail=_detail(),
    )]
    qs = cnode._build_open_questions(blind_spots=[], conflicts=conflicts, features=[], max_questions=10)
    q = qs[0]
    assert q.question_type == "conflict" and q.severity == "high"
    assert q.conflict_detail is not None
    assert "§5.6.1" in q.context and "Level 1" in q.context     # 正向：真实章节+等级
    assert "未列" not in q.context and "Level 3" not in q.context  # 负向：无占位坏值


def test_build_questions_placeholder_source_safe_context():
    conflicts = [SourceConflict(
        conflict_id="C-001", description="某冲突", source_a="未列", source_a_trust_level=3,
        source_b="未列", source_b_trust_level=3, resolution="unresolved", resolution_basis="x",
        conflict_detail=None,
    )]
    qs = cnode._build_open_questions(blind_spots=[], conflicts=conflicts, features=[], max_questions=10)
    assert qs[0].question_type == "conflict"
    assert "未列" not in qs[0].context and "Level 3" not in qs[0].context  # 占位 → 安全文案
```

- [ ] **Step 2: 跑测试看失败**

Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py -k build_questions -v`
Expected: FAIL。

- [ ] **Step 3: 改 `_build_open_questions` 冲突分支（行 296-308）**

把冲突 `OpenQuestion(...)` 构造替换为：
```python
    for conflict in conflicts:
        if conflict.resolution == "unresolved":
            q_counter += 1
            a_ok = not _is_placeholder(conflict.source_a)
            b_ok = not _is_placeholder(conflict.source_b)
            if a_ok and b_ok:
                ctx = (
                    f"'{conflict.source_a}'(Level {conflict.source_a_trust_level}) 与 "
                    f"'{conflict.source_b}'(Level {conflict.source_b_trust_level}) 描述不一致"
                )
            else:
                ctx = "同一文档内存在描述不一致，需人工确认以哪处为准"
            questions.append(
                OpenQuestion(
                    question_id=f"Q-{q_counter:03d}",
                    question=f"信息冲突需要人工裁决：{conflict.description}",
                    context=ctx,
                    related_features=[],
                    blocking=True,
                    question_type="conflict",
                    severity="high",
                    conflict_detail=conflict.conflict_detail,
                )
            )
            if len(questions) >= max_questions:
                return questions
```

盲区分支（行 312-342）给每个盲区 `OpenQuestion` 补 `question_type="blind_spot", severity=blind_spot.severity`。

- [ ] **Step 4: 跑测试看通过**

Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py -k build_questions -v`
Expected: PASS（2 条）。

- [ ] **Step 5: Commit**

```bash
git add src/testcase_generator/stages/comprehend/node.py tests/testcase_generator/test_comprehend_conflicts.py
git commit -m "feat(comprehend): open_questions 带 question_type/severity/detail + context 安全拼接"
```

### Task 6: 序列化转换点（node.py:153）拼前端契约 dict（TDD）

**Files:**
- Modify: `src/testcase_generator/stages/comprehend/node.py`
- Test: `tests/testcase_generator/test_comprehend_conflicts.py`

- [ ] **Step 1: 写失败测试**

追加（直接测纯转换 helper，避免跑整个 node）：
```python
def test_to_frontend_dict_aligns_fields():
    q = cnode.OpenQuestion(
        question_id="Q-001", question="q", context="c", blocking=True,
        question_type="conflict", severity="high", conflict_detail=_detail(),
    )
    d = cnode._open_question_to_payload(q)
    assert d["id"] == "Q-001" and d["question_id"] == "Q-001"   # 双键对齐前端 q.id + 保留审计
    assert d["priority"] == "high"
    assert d["question_type"] == "conflict"
    assert d["conflict_detail"]["topic"] == "角色名称字数上限"   # 已 model_dump
```

- [ ] **Step 2: 跑测试看失败**

Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py -k frontend_dict -v`
Expected: FAIL（`_open_question_to_payload` 未定义）。

- [ ] **Step 3: 实现 helper + 接到返回点**

加 helper：
```python
def _open_question_to_payload(q: OpenQuestion) -> dict:
    """唯一前端序列化点：把 OpenQuestion 拼成前端契约 dict（model_dump 不会凭空加键）。"""
    return {
        "id": q.question_id,
        "question_id": q.question_id,
        "question": q.question,
        "context": q.context,
        "priority": q.severity,  # severity 与前端 priority 同枚举，直映射
        "question_type": q.question_type,
        "conflict_detail": q.conflict_detail.model_dump() if q.conflict_detail else None,
        "blocking": q.blocking,
    }
```
把返回点（行 153）：
```python
        "open_questions": [q.model_dump() for q in open_questions] if open_questions else [],
```
改为：
```python
        "open_questions": [_open_question_to_payload(q) for q in open_questions],
```

- [ ] **Step 4: 跑测试看通过 + 本文件全绿**

Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/testcase_generator/stages/comprehend/node.py tests/testcase_generator/test_comprehend_conflicts.py
git commit -m "feat(comprehend): 序列化点拼前端契约 dict，校准 id/priority/detail 字段链路"
```

---

## Chunk 2: 前端弹窗改造（tsc + lint + 手动验证，无组件测试基建）

### Task 7: 前端类型扩展

**Files:**
- Modify: `web/src/types/index.ts`

- [ ] **Step 1: 加 ConflictSide/ConflictDetail，扩展 OpenQuestion**

在 `OpenQuestion`（行 269-274）附近：
```typescript
export interface ConflictSide {
  location: string;
  statement: string;
  trust_level: number;
}

export interface ConflictDetail {
  topic: string;
  side_a: ConflictSide;
  side_b: ConflictSide;
  recommendation: 'side_a' | 'side_b' | 'neither';
  recommendation_reason: string;
}

export interface OpenQuestion {
  id: string;
  question: string;
  context: string;
  priority: 'high' | 'medium' | 'low';
  question_type?: 'conflict' | 'blind_spot';   // 新增，可选（兼容旧数据）
  conflict_detail?: ConflictDetail | null;       // 冲突且结构化时有
}
```

- [ ] **Step 2: 类型检查**

Run（在 `web/`）: `npm run build`
Expected: tsc 通过（如纯类型新增无消费者报错）。

- [ ] **Step 3: Commit**

```bash
git add web/src/types/index.ts
git commit -m "feat(web): OpenQuestion 加 question_type/conflict_detail 类型"
```

### Task 8: 弹窗按 question_type 渲染 + 选项化 + 推荐 + 提交转答案

**Files:**
- Modify: `web/src/pages/Workbench/index.tsx`

- [ ] **Step 1: 加「选项→答案文本」纯函数 + 选项状态**

文件内（组件外）加纯函数，便于阅读与未来测试：
```typescript
export function answerFromChoice(q: OpenQuestion, choice: string, custom: string): string {
  const d = q.conflict_detail;
  if (choice === 'side_a' && d) return `以 ${d.side_a.location} 为准：${d.side_a.statement}`;
  if (choice === 'side_b' && d) return `以 ${d.side_b.location} 为准：${d.side_b.statement}`;
  return custom.trim();
}
```
组件内加状态：`const [choices, setChoices] = useState<Record<string, string>>({});`（key=q.id）。
**重置（防二次挂起残留预选，违反「不预选」）**：在提交成功处（与 `setClarifyAnswers({})` 同处，约 index.tsx:190）及 Modal `onCancel`（行 419）都补 `setChoices({})`。

- [ ] **Step 2: 改 Modal 渲染（行 427-447）按 question_type 分支**

（先在文件顶部 antd import 补 `Radio`；若用卡片布局再补 `Card`。当前 import 无这两者。）

冲突类（`q.question_type === 'conflict'` 且 `q.conflict_detail`）：渲染 topic 标题 + 两方并排（`location`/`statement`，用两个 `Card`/列）+ 推荐提示条（`💡 AI 推荐：以 {side_a/side_b.location} 为准 — {recommendation_reason}`；`recommendation==='neither'` 显示「AI 倾向：两者均需修正，建议自定」，**不预选**）+ `Radio.Group`（value=`choices[q.id]`，选项 side_a/side_b/custom）；选 `custom` 才显示 `TextArea`。
冲突类但 `!conflict_detail`：纯文字 `question` + `context` + `TextArea`（冲突语义，不用盲区文案）。
盲区类（其余）：`TextArea` + `placeholder="请给出明确结论，例：以 ≤50 字为准"`。

- [ ] **Step 3: 改 `handleClarifySubmit`（行 171-180）用 answerFromChoice**

```typescript
    const answers: ClarifyAnswer[] = openQuestions.map((q) => ({
      question_id: q.id,
      answer:
        q.question_type === 'conflict' && q.conflict_detail
          ? answerFromChoice(q, choices[q.id] ?? '', clarifyAnswers[q.id] ?? '')
          : (clarifyAnswers[q.id] ?? ''),
    }));
```
非空校验沿用现状（冲突类未选且未填 → 视为未作答拦截）。

- [ ] **Step 4: 类型检查**

Run（在 `web/`）: `npm run build`
Expected: tsc 通过。

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Workbench/index.tsx
git commit -m "feat(web): 质量门弹窗按 question_type 渲染冲突卡片 + 选项化裁决 + 推荐提示"
```

---

## Chunk 3: 验证与收尾

### Task 9: 后端全量回归 + ruff

- [ ] **Step 1: comprehend 单测全绿**

Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py -v`
Expected: 全 PASS。

- [ ] **Step 2: 全量零回归**

Run: `uv run pytest tests/testcase_generator/ -q`
Expected: 全绿（重点确认 integration/test_real_graph、test_full_pipeline 等不受 schema 改动影响）。

> **覆盖盲区（既有基建限制，非本计划缺陷）**：唯二覆盖 NO_GO→interrupt→open_questions 端到端的集成测试（`test_full_pipeline.py:199`、`test_real_graph.py:232`）当前均 `@pytest.mark.skip`。故「全量绿」**不**校验挂起链路端到端；该链路靠本 Chunk 新单测（逐函数）+ Task 10 手验兜底。

- [ ] **Step 3: ruff**

Run: `uv run ruff check src/testcase_generator/stages/comprehend/node.py src/testcase_generator/schemas/comprehension_report.py tests/testcase_generator/test_comprehend_conflicts.py`
Expected: 干净。

### Task 10: 前端校验 + 手动验证清单

- [ ] **Step 1: tsc**

Run（在 `web/`）: `npm run build`
Expected: tsc 通过。

- [ ] **Step 2: 手动验证清单**（前端无组件测试基建，以手验兜底）

  - 用 mock/真实触发一个含同文档跨章节冲突的批次 → 弹窗出现冲突卡片（两方并排 + 推荐不预选 + 三选项）。
  - 选「以 §x 为准」→ 提交 → 流水线恢复继续。
  - 选「都不对，我来定」→ 展开输入框 → 填写提交。
  - 构造无 conflict_detail 的冲突（占位降级）→ 走纯文字冲突 + 输入框，不崩、无「未列/Level 3」。
  - 多个问题 → 各自独立作答互不覆盖。

### Task 11: 收尾确认（提交隔离已在各 Task 完成）

- [ ] **Step 1: 确认仅本计划文件被提交**

Run: `git log --oneline -8` 与 `git status`
Expected: 本次 commits 只含 `comprehension_report.py` / `node.py` / `test_comprehend_conflicts.py` / `web/src/types/index.ts` / `web/src/pages/Workbench/index.tsx`；工作树其余既有未提交改动未被裹入。

---

## 总验收标准

- [ ] 同文档跨章节冲突触发时，弹窗以「卡片 + 两方并排 + AI 推荐（不预选）+ 三选项」呈现。
- [ ] context 正向显示真实章节+等级；占位/空时安全文案，**不含**「未列/未知/(Level 3)」。
- [ ] AI 未给结构化 / 规则法冲突 → 按 question_type 走纯文字冲突或盲区输入框，不崩、文案语义正确。
- [ ] 多问题各自独立作答互不覆盖；`question_id` 正确回传、流水线恢复。
- [ ] `resolution` 与 `recommendation` 解耦，NO_GO 触发不受影响。
- [ ] 全量 `tests/testcase_generator/` 全绿；后端改动文件 ruff 干净；前端 `npm run build`(tsc) 通过。
- [ ] 提交仅含本计划 5 个文件。

## 风险与回退

- **LLM 不稳定/吐占位** → schema + prompt 双约束 + `_is_placeholder` 降级；occluded 时退纯文字冲突，不崩。
- **schema 改动牵连下游** → 全为可选新增字段（默认值），旧构造/旧 JSONB 兼容；Task 9 全量回归把关。
- **前端无测试基建** → 本次用 tsc + lint + 手动清单；纯逻辑（answerFromChoice）抽出便于将来补测，不在本计划引入 vitest（避免范围蔓延）。
- **提交污染** → 每 Task 仅 `git add` 指定文件，绝不 `-A/.`。
