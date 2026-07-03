# 澄清直接消解冲突（断澄清死循环）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> 关联 spec：`docs/spec/2026-06-26-clarification-resolves-conflict-design.md`（含 §7 评审修订，方案 A）。

**Goal:** 治「澄清死循环」——用户裁决冲突后，新增 `apply_clarification_node` 基于**首次持久化的 comprehension_report** 按裁决消解对应冲突、**不重跑 LLM**、重判 gate；改图 `interrupt→apply_clarification→gate_router`。彻底杜绝「澄清回答 vs 原文」被反复识别为新冲突。

**Architecture:** 首次 comprehend（调 LLM 识别冲突）不变；恢复路径不再回 comprehend，而走纯函数式 apply_clarification——用 `question_id→conflict_id` 反查（同一份 report 全程稳定），把对应冲突 `resolution` 改为「用户裁决」，重判 gate（冲突全消解即放行、轮数安全阀兜底）。前端零改动。

**Tech Stack:** Python 3.12 / pydantic v2 / pytest（asyncio_mode=auto，**apply_clarification 不调 LLM、纯确定性单测**）。

---

## 现状速查（对齐当前代码）

- `schemas/comprehension_report.py`：`SourceConflict.conflict_id` 已存在（行 41）；`OpenQuestion`（行 61-71）**无** conflict_id（本计划新增）。
- `schemas/pipeline_state.py`：`clarification_answers`（行 33）、无 `clarification_rounds`（新增）。
- `stages/comprehend/node.py`：`_build_open_questions`（行 323-397，冲突分支 334-359）、`_open_question_to_payload`（行 309-320）、`_build_feature_matrix_llm` 内 `clarification_answers` 注入块（约行 211-217，**待删**）。
- `stages/comprehend/gate.py`：读 `gate_config`（行 14-19），有 `GO_THRESHOLD`/`NO_GO_THRESHOLD`/`MAX_OPEN_QUESTIONS`；`evaluate_gate` 只看 coverage+conflicts。
- `pipeline/graph.py`：`interrupt_node`（行 22-43，**不变**）、`graph.add_edge("interrupt", "comprehend")`（行 84，**待改**）、`gate_router` 条件边（行 74-81）。
- `pipeline/edges.py`：`gate_router` —— NO_GO→"interrupt"，GO/CONDITIONAL→"test_points"（不改）。
- `config/trust_order.yaml`：`gate_config` 段（加 `max_clarification_rounds`）。
- **⚠️ `clarification_answers` 双层嵌套**：`state["clarification_answers"]` == `{"clarification_answers": [{question_id, answer}, ...]}`（B1，apply_clarification 须归一化）。
- **mock 模式**：`monkeypatch.setattr(mod, "get_llm_client", lambda: fake)`。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动。每次只 `git add` 本计划文件，严禁 `-A/.`。

## File Structure

- **Modify** `src/testcase_generator/schemas/comprehension_report.py`（OpenQuestion +conflict_id）
- **Modify** `src/testcase_generator/schemas/pipeline_state.py`（+clarification_rounds）
- **Modify** `src/testcase_generator/config/trust_order.yaml`（+max_clarification_rounds）
- **Modify** `src/testcase_generator/stages/comprehend/gate.py`（导出 MAX_CLARIFICATION_ROUNDS）
- **Modify** `src/testcase_generator/stages/comprehend/node.py`（_build_open_questions 填 conflict_id；删澄清注入死代码）
- **Create** `src/testcase_generator/stages/comprehend/apply_clarification.py`（新节点）
- **Modify** `src/testcase_generator/pipeline/graph.py`（接节点 + 改边）
- **Create** `tests/testcase_generator/test_apply_clarification.py`（后端单测）

---

## Chunk 1: schema + state + 配置 + conflict_id 关联

### Task 1: schema / state / 配置 扩展

**Files:** `comprehension_report.py`、`pipeline_state.py`、`trust_order.yaml`、`gate.py`

- [ ] **Step 1: `OpenQuestion` 加 conflict_id**（comprehension_report.py，OpenQuestion 末尾）
```python
    conflict_id: str | None = Field(default=None, description="冲突类问题关联的 SourceConflict.conflict_id")
```

- [ ] **Step 2: `PipelineState` 加 clarification_rounds**（pipeline_state.py，clarification_answers 行下方）
```python
    clarification_rounds: int  # 已执行澄清轮数（防死循环安全阀）
```

- [ ] **Step 3: `trust_order.yaml` 的 `gate_config` 加**
```yaml
  max_clarification_rounds: 3   # 澄清轮数上限；超过强制放行（verify 兜底）
```

- [ ] **Step 4: `gate.py` 导出常量**（紧随 MAX_OPEN_QUESTIONS 之后）
```python
MAX_CLARIFICATION_ROUNDS: int = _gate_config.get("max_clarification_rounds", 3)
```

- [ ] **Step 5: 冒烟**

Run: `uv run python -c "from src.testcase_generator.stages.comprehend.gate import MAX_CLARIFICATION_ROUNDS; from src.testcase_generator.schemas.comprehension_report import OpenQuestion; print(MAX_CLARIFICATION_ROUNDS, OpenQuestion(question_id='Q',question='q',context='c').conflict_id)"`
Expected: 打印 `3 None`。

- [ ] **Step 6: Commit**
```bash
git add src/testcase_generator/schemas/comprehension_report.py src/testcase_generator/schemas/pipeline_state.py src/testcase_generator/config/trust_order.yaml src/testcase_generator/stages/comprehend/gate.py
git commit -m "feat(comprehend): OpenQuestion+conflict_id / state+clarification_rounds / 配置 max_clarification_rounds"
```

### Task 2: `_build_open_questions` 冲突类填 conflict_id（TDD）

**Files:** `node.py`、Test: `tests/testcase_generator/test_apply_clarification.py`

- [ ] **Step 1: 写失败测试**（新建测试文件）
```python
"""澄清消解冲突（方案 A）— conflict_id 关联 / apply_clarification。"""
from __future__ import annotations

from src.testcase_generator.schemas.comprehension_report import (
    ComprehensionReport,
    OpenQuestion,
    SourceConflict,
)
from src.testcase_generator.stages.comprehend import node as cnode


def _conflict(cid="C-001", res="unresolved"):
    return SourceConflict(
        conflict_id=cid, description="角色名字数：'≤50' vs '不限'",
        source_a="§5.6.1", source_a_trust_level=1, source_b="§9.2 表", source_b_trust_level=1,
        resolution=res, resolution_basis="x",
    )


def test_build_open_questions_carries_conflict_id():
    qs = cnode._build_open_questions(
        blind_spots=[], conflicts=[_conflict()], features=[], max_questions=10
    )
    assert qs[0].question_type == "conflict"
    assert qs[0].conflict_id == "C-001"
```

- [ ] **Step 2: 跑测试看失败**
Run: `uv run pytest tests/testcase_generator/test_apply_clarification.py::test_build_open_questions_carries_conflict_id -v`
Expected: FAIL（conflict_id 为 None）。

- [ ] **Step 3: node.py 冲突分支补 conflict_id**（_build_open_questions 行 346-356 的 OpenQuestion 构造内加一行）
```python
                    conflict_detail=conflict.conflict_detail,
                    conflict_id=conflict.conflict_id,   # 新增
```

- [ ] **Step 4: 跑测试看通过**
Run: `uv run pytest tests/testcase_generator/test_apply_clarification.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**
```bash
git add src/testcase_generator/stages/comprehend/node.py tests/testcase_generator/test_apply_clarification.py
git commit -m "feat(comprehend): open_questions 冲突类带 conflict_id（供澄清反查消解）"
```

---

## Chunk 2: apply_clarification 节点（TDD，核心）+ 删死代码

### Task 3: 实现 `apply_clarification_node`（TDD）

**Files:** Create `stages/comprehend/apply_clarification.py`、Test 同上文件

- [ ] **Step 1: 写失败测试**（追加到同一文件；`ComprehensionReport`/`OpenQuestion` 已在 Task 2 顶部统一导入，此处**不再新增模块级 import**，仅追加函数，避免 ruff E402/I001）
```python
def _report(conflicts, coverage=0.9):
    oqs = [
        OpenQuestion(question_id=f"Q-{i+1:03d}", question="q", context="c", blocking=True,
                     question_type="conflict", severity="high", conflict_id=c.conflict_id)
        for i, c in enumerate(conflicts)
    ]
    return ComprehensionReport(
        gate_result="NO_GO", understanding_coverage=coverage,
        feature_matrix=[], conflicts=conflicts, blind_spots=[], open_questions=oqs,
    )


async def test_apply_resolves_all_and_releases_nested_shape():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001")])
    state = {
        "comprehension_report": report,
        # B1：双层嵌套形状（真实 resume 链路）
        "clarification_answers": {"clarification_answers": [{"question_id": "Q-001", "answer": "以 §5.6.1 为准"}]},
    }
    out = await apply_clarification_node(state)
    assert out["gate_result"] in ("GO", "CONDITIONAL")
    assert out["open_questions"] == []
    assert out["clarification_rounds"] == 1
    assert "用户裁决" in out["comprehension_report"].conflicts[0].resolution


async def test_apply_accepts_bare_list_shape():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001")])
    state = {"comprehension_report": report,
             "clarification_answers": [{"question_id": "Q-001", "answer": "x"}]}  # 裸列表
    out = await apply_clarification_node(state)
    assert out["gate_result"] in ("GO", "CONDITIONAL")


async def test_apply_partial_keeps_remaining_no_blind_spots():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001"), _conflict("C-002")])
    state = {"comprehension_report": report,
             "clarification_answers": {"clarification_answers": [{"question_id": "Q-001", "answer": "x"}]}}
    out = await apply_clarification_node(state)
    assert out["gate_result"] == "NO_GO"
    assert len(out["open_questions"]) == 1  # 只剩 C-002，不含盲区


async def test_apply_round_limit_force_release():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001")])
    state = {"comprehension_report": report, "clarification_rounds": 3,
             "clarification_answers": {"clarification_answers": []}}  # 没答，但轮数已达上限
    out = await apply_clarification_node(state)
    assert out["gate_result"] in ("GO", "CONDITIONAL")  # 强制放行
    assert out["comprehension_report"].conflicts[0].resolution_basis == "forced_release"


async def test_apply_low_coverage_still_releases_when_no_conflict():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001")], coverage=0.1)
    state = {"comprehension_report": report,
             "clarification_answers": {"clarification_answers": [{"question_id": "Q-001", "answer": "x"}]}}
    out = await apply_clarification_node(state)
    assert out["gate_result"] == "CONDITIONAL"  # 冲突消解后即便 coverage 低也放行


def test_apply_module_does_not_import_llm():
    # 结构性保证：apply 模块根本不碰 LLM（断循环的根本，比 monkeypatch 名副其实）
    import inspect
    from src.testcase_generator.stages.comprehend import apply_clarification as mod
    assert "get_llm_client" not in inspect.getsource(mod)
```

- [ ] **Step 2: 跑测试看失败**
Run: `uv run pytest tests/testcase_generator/test_apply_clarification.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现 `apply_clarification.py`**
```python
"""Gate NO_GO 澄清恢复 — 基于首次 report 消解冲突，不重跑 LLM（断死循环，方案 A）。"""
from __future__ import annotations

import logging

from src.testcase_generator.schemas.comprehension_report import ComprehensionReport
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.stages.comprehend.gate import (
    GO_THRESHOLD,
    MAX_CLARIFICATION_ROUNDS,
    MAX_OPEN_QUESTIONS,
)
from src.testcase_generator.stages.comprehend.node import (
    _build_open_questions,
    _open_question_to_payload,
)

logger = logging.getLogger(__name__)


async def apply_clarification_node(state: PipelineState) -> dict:
    """按用户裁决消解首次 report 的对应冲突，重判 gate。全程不调 LLM。"""
    report: ComprehensionReport = state["comprehension_report"]
    rounds = state.get("clarification_rounds", 0) + 1

    # B1：clarification_answers 双层嵌套 → 入口归一化
    raw = state.get("clarification_answers") or []
    answers = raw.get("clarification_answers", []) if isinstance(raw, dict) else raw

    qid_to_cid = {q.question_id: q.conflict_id for q in report.open_questions if q.conflict_id}
    conflicts_by_id = {c.conflict_id: c for c in report.conflicts}

    for ans in answers:
        if not isinstance(ans, dict):
            continue
        cid = qid_to_cid.get(ans.get("question_id"))
        if not cid:
            continue  # 盲区类 / 匹配不到 → 跳过（Minor 1：盲区告知性）
        conflict = conflicts_by_id.get(cid)
        if conflict is not None:
            conflict.resolution = f"用户裁决：{ans.get('answer', '')}"
            conflict.resolution_basis = "user_clarification"

    remaining = [c for c in report.conflicts if c.resolution == "unresolved"]

    if remaining and rounds < MAX_CLARIFICATION_ROUNDS:
        gate_result = "NO_GO"
        open_questions = _build_open_questions(
            blind_spots=[], conflicts=remaining, features=[], max_questions=MAX_OPEN_QUESTIONS
        )  # blind_spots=[]：不重复追问盲区（Minor 2）
    else:
        if remaining:  # 轮数超限强制放行 → 标记残留，保持 report 自洽（Minor 3）
            for c in remaining:
                c.resolution = "超澄清轮数上限，强制放行"
                c.resolution_basis = "forced_release"
        gate_result = "GO" if report.understanding_coverage >= GO_THRESHOLD else "CONDITIONAL"
        open_questions = []

    report.gate_result = gate_result
    report.open_questions = open_questions

    logger.info(
        "apply_clarification: round=%d, remaining=%d, gate=%s", rounds, len(remaining), gate_result
    )

    return {
        "comprehension_report": report,
        "gate_result": gate_result,
        "open_questions": [_open_question_to_payload(q) for q in open_questions],
        "clarification_rounds": rounds,
        "current_stage": "comprehend",
    }
```

- [ ] **Step 4: 跑测试看通过**
Run: `uv run pytest tests/testcase_generator/test_apply_clarification.py -v`
Expected: 全 PASS（含 B1 两形状、部分裁决、轮数安全阀、低覆盖放行、不调 LLM）。

- [ ] **Step 5: Commit**
```bash
git add src/testcase_generator/stages/comprehend/apply_clarification.py tests/testcase_generator/test_apply_clarification.py
git commit -m "feat(comprehend): apply_clarification 按裁决消解冲突（不调 LLM，断澄清死循环）"
```

### Task 4: 删除澄清作信源的死代码（Minor 4）

**Files:** `node.py`

- [ ] **Step 1: 删注入块体 + 更新过时 docstring**（_build_feature_matrix_llm，node.py）
  - 删除约行 211-217 的注入块体：
```python
    # 注入澄清回答作为补充信源（信任等级 3 = 用户口述）
    if clarification_answers:
        user_content_dict["clarification_answers"] = { ... }
```
  - **只走「删块体、保留未用形参」这一条路径**：`clarification_answers` 形参与 comprehend_node 调用处传参（node.py:101/108）**保持不动**——形参变未用，但 ruff `select` 不含 ARG、且 comprehend_node 局部仍被传出 → **不报 F841/ARG**。**切勿半截清理**（删形参须同时删调用处传参，否则 TypeError）。
  - 更新 `_build_feature_matrix_llm` docstring（node.py:173-177）：移除「将 clarification_answers 注入 LLM prompt 重算覆盖度」表述，改为「方案 A 后澄清不再回 comprehend；此函数仅首次理解使用」。

- [ ] **Step 2: 冒烟 + 不破坏首次 comprehend 单测**
Run: `uv run pytest tests/testcase_generator/test_comprehend_conflicts.py -q`
Expected: 全 PASS（首次 comprehend 行为不变）。

- [ ] **Step 3: Commit**
```bash
git add src/testcase_generator/stages/comprehend/node.py
git commit -m "refactor(comprehend): 删除澄清作 trust_level3 信源注入死代码（方案 A 结构性杜绝循环）"
```

---

## Chunk 3: 图改造

### Task 5: 接 apply_clarification 节点 + 改边

**Files:** `graph.py`

- [ ] **Step 1: import + 注册节点 + 改边**
  - 顶部 import：`from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node`
  - 注册：`graph.add_node("apply_clarification", apply_clarification_node)`
  - 把 `graph.add_edge("interrupt", "comprehend")`（行 84）改为 `graph.add_edge("interrupt", "apply_clarification")`
  - 新增条件边（复用 gate_router）：
```python
    graph.add_conditional_edges(
        "apply_clarification", gate_router,
        {"test_points": "rule_extract", "interrupt": "interrupt"},
    )
```

- [ ] **Step 2: 编译冒烟**
Run: `uv run python -c "from src.testcase_generator.pipeline.graph import build_pipeline; g=build_pipeline(); print('apply_clarification' in g.nodes)"`
Expected: 打印 `True`，无编译错误。

- [ ] **Step 3: Commit**
```bash
git add src/testcase_generator/pipeline/graph.py
git commit -m "feat(pipeline): interrupt→apply_clarification→gate_router，澄清恢复不再回 comprehend"
```

---

## Chunk 4: 验证与收尾

### Task 6: 后端全量回归 + ruff
- [ ] **Step 1: 本特性单测全绿**
Run: `uv run pytest tests/testcase_generator/test_apply_clarification.py tests/testcase_generator/test_comprehend_conflicts.py -v`
Expected: 全 PASS。
- [ ] **Step 2: 全量零回归（排除需 DB 的 integration）**
Run: `uv run pytest tests/testcase_generator/ -q --ignore=tests/testcase_generator/integration`
Expected: 全绿。
- [ ] **Step 3: ruff**
Run: `uv run ruff check src/testcase_generator/stages/comprehend/ src/testcase_generator/pipeline/graph.py tests/testcase_generator/test_apply_clarification.py`
Expected: 干净。

### Task 7: 手动端到端验证（需重启 worker）
- [ ] **Step 1**：重启 Celery worker（加载新代码）+ 刷新前端。
- [ ] **Step 2**：对含同文档跨章节冲突的 PRD 新建批次 → 触发质量门 → 裁决冲突 → 提交。
  Expected：**不再就已裁决冲突复弹**；全部裁决后流水线放行继续；不再出现「原文 vs 用户澄清 Q-00X」。

### Task 8: 提交隔离确认
- [ ] **Step 1**：`git log --oneline -6` 与 `git status`，确认仅本计划文件入提交，工作树其他改动未被裹入。

---

## 总验收标准
- [ ] 裁决冲突后不再复弹已裁决项；全部裁决后放行继续。
- [ ] 不再出现「原文 vs 用户澄清」自我指涉冲突（apply_clarification 不调 LLM，机制杜绝）。
- [ ] 部分裁决 → 仅就剩余冲突再问（不含盲区）；轮数超 `max_clarification_rounds` → 强制放行 + 残留标 `forced_release`。
- [ ] 冲突全消解后即便 coverage 低也放行；首次 comprehend / 未触发冲突批次行为不变。
- [ ] B1 两种形状（双层嵌套 / 裸列表）单测均覆盖并通过。
- [ ] 全量（排除 integration）测试全绿；改动文件 ruff 干净；前端零改动。
- [ ] 提交仅含本计划文件。

## 风险与回退
- **改图回环** → interrupt_node 不变、gate_router 复用；apply_clarification 纯函数可单测；回退即把边改回 `interrupt→comprehend`。
- **依赖 checkpoint 反序列化 report 为 Pydantic 对象** → apply 就地 mutate `report.conflicts[i].resolution` 要求反序列化后仍是 `SourceConflict` 对象（既有管线对 parsed_context/comprehension_report 已依赖此 Pydantic 往返）；单测用新建对象、集成测试 skip，**反序列化路径无自动覆盖**，属既有继承假设。
- **clarification_answers 形状** → 入口归一化兼容双层/裸列表，单测双覆盖。
- **盲区告知性降级** → 有意范围收窄，verify 兜底（spec §5）。
- **提交污染** → 每 Task 仅 `git add` 指定文件，绝不 `-A/.`。
