# 结构化覆盖（权限矩阵 + 状态转移）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:subagent-driven-development 或 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选。
> 关联 spec：`docs/spec/2026-06-29-structural-coverage-design.md`。线 B（3 线之一，最大）。

**Goal:** 从 PRD 抽「权限矩阵 + 状态机」结构定义 → 有界展开成测试点 → 纳入覆盖闸；嵌入 test_points 不改图拓扑，灰度 `structural_coverage_enabled` 默认关、零回归。

**Architecture:** 仿 `rule_extract`/`rule_anchor` 的「确定性锚点 + 覆盖闸」模式。结构化抽取器（LLM）产出 `PermissionMatrix`/`StateMachine` → `expander` 有界展开成带 `structural_type`/`structural_key` 的 `TestPointSchema` → test_points 末尾追加 → `compute_structural_coverage` 进 AuditReport + backfill。

**Tech Stack:** Python 3.12 / pydantic v2 / LangGraph / pytest（asyncio_mode=auto）/ yaml。

---

## 现状速查（对齐当前代码）
- `schemas/test_point.py:10-22`：`TestPointSchema`（有 `rule_id: str | None`，仿之加 structural 字段）。
- `stages/test_points/node.py:567-586`：rule 锚点在 :571-581 追加、:583 return；结构化点在 return 前、rule 锚点之后追加。
- `stages/test_points/rule_anchor.py:67-101`：`build_rule_anchored_test_points` —— **builder 参考模板**。
- `stages/rule_extract/extractor.py`：`extract_rules` —— **LLM 抽取参考模板**（`generate_structured`）。
- `stages/review/node.py:262-285`：`compute_rule_coverage(rules, test_points, covered_tp_ids)` → `rule_cov_fields` 进 `AuditReport(**rule_cov_fields)`；仿之加 structural。
- `stages/review/backfill_node.py:105`：`if settings.rule_coverage_gate_enabled and rules:` 定向回填。
- `schemas/audit_report.py:41`：规则覆盖字段（加 structural_coverage 默认值）。
- **⚠️ 提交隔离**：工作树多有其他未提交改动，每次只 `git add` 本计划文件，严禁 `-A`。
- **落库约束**：不为 structural_type/key 加 DB 列（无迁移）——仅运行期 state + 覆盖闸内存判定。

## File Structure
- **Create** `stages/test_points/structural/__init__.py` / `schemas.py` / `permission_extractor.py` / `state_extractor.py` / `expander.py`
- **Modify** `schemas/test_point.py`、`schemas/audit_report.py`、`core/settings.py`
- **Modify** `stages/test_points/node.py`、`stages/review/node.py`、`stages/review/backfill_node.py`
- **Create** `tests/testcase_generator/test_structural_coverage.py`

---

## Chunk 1: 地基（schema + 字段 + 开关）

### Task 1: structural schemas + TestPointSchema 字段 + settings（TDD）

**Files:** Create `stages/test_points/structural/schemas.py`、`__init__.py`；Modify `schemas/test_point.py`、`core/settings.py`；Test: `tests/testcase_generator/test_structural_coverage.py`

- [ ] **Step 1: 写失败测试**
```python
"""结构化覆盖单测。"""
from __future__ import annotations

def test_structural_schemas_parse():
    from src.testcase_generator.stages.test_points.structural.schemas import (
        Grant, PermissionMatrix, StateMachine, Transition,
    )
    pm = PermissionMatrix(
        roles=["管理员", "投手"], resources=["账户"],
        grants=[Grant(role="投手", resource="账户", operation="改他人", effect="deny", source_quote="投手不可改他人账户")],
    )
    assert pm.grants[0].effect == "deny"
    sm = StateMachine(name="任务", states=["待执行", "执行中"],
                      transitions=[Transition(src="待执行", dst="执行中", event="开始", source_quote="点开始")])
    assert sm.transitions[0].dst == "执行中"


def test_test_point_has_structural_fields():
    from src.testcase_generator.schemas.test_point import TestPointSchema
    tp = TestPointSchema(id="TP-001", feature_id="F1", dimension="access_control",
                         description="x", priority="P0",
                         structural_type="permission", structural_key="perm:投手:账户:改他人")
    assert tp.structural_type == "permission"
    assert TestPointSchema(id="T", feature_id="F", dimension="d", description="x", priority="P2").structural_type is None
```

- [ ] **Step 2: 跑失败** — `uv run pytest tests/testcase_generator/test_structural_coverage.py -v` → FAIL（模块/字段不存在）

- [ ] **Step 3: 实现 schemas.py**
```python
"""权限矩阵 / 状态机 结构化定义 schema（LLM 抽取输出）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Grant(BaseModel):
    role: str
    resource: str
    operation: str = Field(default="访问", description="操作，如 增删改查/改他人")
    effect: Literal["allow", "deny"] = "allow"
    source_quote: str = Field(default="", description="PRD 原文依据")


class PermissionMatrix(BaseModel):
    roles: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    grants: list[Grant] = Field(default_factory=list)


class Transition(BaseModel):
    src: str
    dst: str
    event: str = ""
    guard: str = ""
    source_quote: str = Field(default="")


class StateMachine(BaseModel):
    name: str
    states: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
```
（`__init__.py` 空文件）

- [ ] **Step 4: TestPointSchema 加字段**（`schemas/test_point.py`，`rule_id` 之后）
```python
    structural_type: str | None = Field(default=None, description="结构化覆盖类型 permission/state_machine；普通点为 None")
    structural_key: str | None = Field(default=None, description="结构化点唯一标识（格子/转移），用于覆盖闸")
```

- [ ] **Step 5: settings 加开关**（`core/settings.py`，规则锚定链开关附近）
```python
    # ── 结构化覆盖（落点⑫·线B）：权限矩阵 + 状态机有界展开 + 覆盖闸 ──────────
    structural_coverage_enabled: bool = False
    structural_extract_concurrency: int = 2
```

- [ ] **Step 6: 跑测试通过 + Commit**
```bash
uv run pytest tests/testcase_generator/test_structural_coverage.py -v   # PASS
git add src/testcase_generator/stages/test_points/structural/__init__.py src/testcase_generator/stages/test_points/structural/schemas.py src/testcase_generator/schemas/test_point.py src/platform_api/core/settings.py tests/testcase_generator/test_structural_coverage.py
git commit -m "feat(test_points): 结构化覆盖 schema + TestPointSchema 字段 + 灰度开关"
```

---

## Chunk 2: 抽取器（LLM）

### Task 2: 权限矩阵 + 状态机抽取器

**Files:** Create `structural/permission_extractor.py`、`state_extractor.py`；Test: 追加

- [ ] **Step 1: 写测试（mock LLM）**
```python
async def test_permission_extractor_parses(monkeypatch):
    from src.testcase_generator.stages.test_points.structural import permission_extractor as pe
    from src.testcase_generator.stages.test_points.structural.schemas import PermissionMatrix, Grant

    class _Fake:
        async def generate_structured(self, **kw):
            return PermissionMatrix(roles=["投手"], resources=["账户"],
                grants=[Grant(role="投手", resource="账户", operation="改他人", effect="deny", source_quote="q")])
    monkeypatch.setattr(pe, "get_llm_client", lambda: _Fake())
    pm = await pe.extract_permission_matrix("§10 权限：投手不可改他人账户")
    assert pm.grants[0].effect == "deny"
```

- [ ] **Step 2-4: 实现 `permission_extractor.py`**（state_extractor 同构）
```python
"""从 PRD 文本抽权限矩阵（LLM）。失败安全降级返回空矩阵。"""
from __future__ import annotations

import logging

from src.testcase_generator.services.llm_client import get_llm_client
from src.testcase_generator.stages.test_points.structural.schemas import PermissionMatrix

logger = logging.getLogger(__name__)

_SYS = """你是权限建模专家。从给定 PRD 文本抽取角色×资源权限矩阵。
- roles：所有出现的角色（如 管理员/组长/投手）。
- resources：受权限控制的资源/模块（账户/商品/标题包/任务…）。
- grants：每条「某角色对某资源的某操作 允许/拒绝」，effect=allow|deny，附 source_quote（PRD 原文）。
只抽 PRD 明确写了的权限，不臆造。严格按 JSON Schema 输出。"""


async def extract_permission_matrix(prd_text: str) -> PermissionMatrix:
    try:
        return await get_llm_client().generate_structured(
            system_prompt=_SYS, user_content=prd_text,
            output_schema=PermissionMatrix, temperature=0.1,
        )
    except Exception as e:  # noqa: BLE001 — 抽取失败安全降级，不阻断流水线
        logger.warning("权限矩阵抽取失败，降级空矩阵: %s", e)
        return PermissionMatrix()
```
`state_extractor.py`：`extract_state_machines(prd_text) -> list[StateMachine]`，schema 用 `class _SMList(BaseModel): machines: list[StateMachine]`，prompt 指引抽状态/转移/event/guard + source_quote，失败返回 `[]`。

- [ ] **Step 5: Commit**
```bash
git add src/testcase_generator/stages/test_points/structural/permission_extractor.py src/testcase_generator/stages/test_points/structural/state_extractor.py tests/testcase_generator/test_structural_coverage.py
git commit -m "feat(test_points): 权限矩阵/状态机 LLM 抽取器（失败安全降级）"
```

---

## Chunk 3: 有界展开 + 集成

### Task 3: expander 有界展开（TDD）

**Files:** Create `structural/expander.py`；Test: 追加

- [ ] **Step 1: 写测试**
```python
def test_expand_permission_bounded():
    from src.testcase_generator.stages.test_points.structural.schemas import PermissionMatrix, Grant
    from src.testcase_generator.stages.test_points.structural.expander import expand_permission
    pm = PermissionMatrix(roles=["管理员","投手"], resources=["账户"],
        grants=[Grant(role="投手",resource="账户",operation="改他人",effect="deny",source_quote="q")])
    tps = expand_permission(pm, start_idx=0)
    # 至少 1 个明确格子 + 等价类代表；都带 structural_type/key、唯一
    assert all(t.structural_type == "permission" for t in tps)
    assert len({t.structural_key for t in tps}) == len(tps)


def test_expand_state_machine_bounded():
    from src.testcase_generator.stages.test_points.structural.schemas import StateMachine, Transition
    from src.testcase_generator.stages.test_points.structural.expander import expand_state_machine
    sm = StateMachine(name="任务", states=["待执行","执行中","完成"],
        transitions=[Transition(src="待执行",dst="执行中",event="开始",source_quote="q"),
                     Transition(src="执行中",dst="完成",event="结束",source_quote="q")])
    tps = expand_state_machine(sm, start_idx=0)
    # 每个合法转移 ≥1 + 关键非法转移（终态后操作）
    assert sum(1 for t in tps if "->" in (t.structural_key or "")) >= 2
```

- [ ] **Step 2-4: 实现 `expander.py`**（参考 `rule_anchor.py` 构造 TestPointSchema）
```python
"""权限矩阵/状态机 → 有界展开成 TestPointSchema（带 structural_type/key）。"""
from __future__ import annotations

from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.test_points.structural.schemas import PermissionMatrix, StateMachine

_FEATURE = "STRUCTURAL"  # 结构化点不绑具体 feature（或按 resource/machine 映射，二期细化）


def _tp(idx: int, dim: str, desc: str, key: str, stype: str, quote: str) -> TestPointSchema:
    return TestPointSchema(
        id=f"TP-{idx:03d}", feature_id=_FEATURE, dimension=dim, description=desc,
        priority="P0", derived_from=[quote] if quote else [],
        structural_type=stype, structural_key=key,
    )


def expand_permission(pm: PermissionMatrix, start_idx: int) -> list[TestPointSchema]:
    out: list[TestPointSchema] = []
    seen: set[str] = set()
    i = start_idx
    # 1) PRD 明确格子
    for g in pm.grants:
        key = f"perm:{g.role}:{g.resource}:{g.operation}"
        if key in seen:
            continue
        seen.add(key)
        i += 1
        verb = "应被拒绝" if g.effect == "deny" else "应被允许"
        out.append(_tp(i, "access_control",
            f"{g.role} 对「{g.resource}」执行「{g.operation}」{verb}", key, "permission", g.source_quote))
    # 2) 每资源补「有权/无权」等价类代表（基于 grants 推断；无法推断则跳过）
    for res in pm.resources:
        allow_roles = [g.role for g in pm.grants if g.resource == res and g.effect == "allow"]
        deny_roles = [g.role for g in pm.grants if g.resource == res and g.effect == "deny"]
        for label, roles, verb in (("有权", allow_roles, "应被允许"), ("无权", deny_roles, "应被拒绝")):
            if roles:
                key = f"perm:{label}:{res}"
                if key not in seen:
                    seen.add(key); i += 1
                    out.append(_tp(i, "access_control",
                        f"{label}角色（{roles[0]}）访问「{res}」{verb}（等价类代表）", key, "permission", ""))
    return out


def expand_state_machine(sm: StateMachine, start_idx: int) -> list[TestPointSchema]:
    out: list[TestPointSchema] = []
    i = start_idx
    terminal = {s for s in sm.states if not any(t.src == s for t in sm.transitions)}
    # 1) 每个合法转移（0-switch）
    for t in sm.transitions:
        i += 1
        key = f"state:{sm.name}:{t.src}->{t.dst}"
        out.append(_tp(i, "state_transition",
            f"{sm.name}：在「{t.src}」触发「{t.event}」应转移到「{t.dst}」"
            + (f"（守卫：{t.guard}）" if t.guard else ""), key, "state_machine", t.source_quote))
    # 2) 关键非法转移：终态后再触发任一 event
    events = sorted({t.event for t in sm.transitions if t.event})
    for s in sorted(terminal):
        if events:
            i += 1
            key = f"state:{sm.name}:{s}->illegal"
            out.append(_tp(i, "state_transition",
                f"{sm.name}：终态「{s}」后再触发「{events[0]}」应被拒绝/无效（非法转移）",
                key, "state_machine", ""))
    return out
```

> **自审补充（feature 映射，🔴 重要）**：上面 `_tp` 用假 `feature_id="STRUCTURAL"`——write_cases 按 `feature_context.get(feature_id,[])`（node.py:392）取上下文，假 feature → **上下文为空 → 结构化用例缺 PRD 依据、verify 易判 ungrounded**（为补覆盖反产低质量用例）。**必须修**：
> - `expand_permission(pm, start_idx, features)` / `expand_state_machine(sm, start_idx, features)` 加 `features` 参数（传 `parsed_context.features`）。
> - 新增 `_match_feature(hint, features)`：按 hint（permission 用 `g.resource`、state_machine 用 `sm.name`）在 features 里模糊匹配（`hint in f.name or hint in f.description`），命中返回 `f.id`，否则回退 `features[0].id`（仍有上下文），features 空才用 "STRUCTURAL"。
> - `_tp` 加 `feature_id` 参数；展开时 `feature_id=_match_feature(...)`。
> - 测试加：`expand_permission` 传入含「账户」feature 的列表，断言权限点 `feature_id` 映射到该 feature 而非 "STRUCTURAL"。

- [ ] **Step 5: Commit**
```bash
git add src/testcase_generator/stages/test_points/structural/expander.py tests/testcase_generator/test_structural_coverage.py
git commit -m "feat(test_points): 权限/状态机有界展开 + feature 映射（避免结构化点缺上下文）"
```

### Task 4: 集成 test_points_node

**Files:** Modify `stages/test_points/node.py`

- [ ] **Step 1: 末尾追加结构化点**（:582 `return` 之前、rule 锚点追加之后）
```python
    if settings.structural_coverage_enabled:
        from src.testcase_generator.stages.test_points.structural.permission_extractor import extract_permission_matrix
        from src.testcase_generator.stages.test_points.structural.state_extractor import extract_state_machines
        from src.testcase_generator.stages.test_points.structural.expander import expand_permission, expand_state_machine
        prd_text = "\n".join(
            f"{sec.heading}\n{sec.content}" for src_ in parsed_context.sources for sec in src_.sections
        )
        pm = await extract_permission_matrix(prd_text)
        sms = await extract_state_machines(prd_text)
        struct_tps = expand_permission(pm, start_idx=len(test_points), features=parsed_context.features)
        for sm in sms:
            struct_tps.extend(expand_state_machine(sm, start_idx=len(test_points) + len(struct_tps), features=parsed_context.features))
        test_points.extend(struct_tps)
        for idx, tp in enumerate(test_points, start=1):
            tp.id = f"TP-{idx:03d}"
        logger.info("test-points: 追加 %d 个结构化覆盖点（权限 %d 格 / 状态机 %d）",
                    len(struct_tps), len(pm.grants), len(sms))
```

- [ ] **Step 2: 冒烟（开关关零影响）** — `uv run pytest tests/testcase_generator/ -k test_points -q` → PASS

- [ ] **Step 3: Commit**
```bash
git add src/testcase_generator/stages/test_points/node.py
git commit -m "feat(test_points): 集成结构化覆盖点（开关控制，关时零影响）"
```

---

## Chunk 4: 覆盖闸扩展

### Task 5: compute_structural_coverage + AuditReport

**Files:** Modify `schemas/audit_report.py`、`stages/review/node.py`；Test: 追加

- [ ] **Step 1: 写测试**
```python
def test_compute_structural_coverage():
    from src.testcase_generator.schemas.test_point import TestPointSchema
    from src.testcase_generator.stages.review.rule_gate import compute_structural_coverage
    tps = [TestPointSchema(id="TP-001", feature_id="S", dimension="access_control", description="x",
                           priority="P0", structural_type="permission", structural_key="perm:投手:账户:改他人")]
    cov = compute_structural_coverage(tps, covered_tp_ids={"TP-001"})
    assert cov["structural_total"] == 1 and cov["structural_covered"] == 1
    cov2 = compute_structural_coverage(tps, covered_tp_ids=set())
    assert cov2["structural_covered"] == 0 and "perm:投手:账户:改他人" in cov2["uncovered_structural_keys"]
```

- [ ] **Step 2: AuditReport 加字段**（`schemas/audit_report.py`，仿规则覆盖字段，全给默认值零回归）
```python
    structural_total: int = 0
    structural_covered: int = 0
    structural_coverage: float = 1.0
    uncovered_structural_keys: list[str] = Field(default_factory=list)
```

- [ ] **Step 3: 实现 compute_structural_coverage + 接入 review_node**（**自审修正：`compute_rule_coverage`/`DEFAULT_RULE_COVERAGE` 在 `review/rule_gate.py:15,23` 不在 node.py**——`compute_structural_coverage` 与 `DEFAULT_STRUCTURAL_COVERAGE` 放 `rule_gate.py`，`review/node.py` 顶部 import 它们，仿 :262-285 rule 块接入）
```python
DEFAULT_STRUCTURAL_COVERAGE = {"structural_total": 0, "structural_covered": 0,
                               "structural_coverage": 1.0, "uncovered_structural_keys": []}


def compute_structural_coverage(test_points, covered_tp_ids) -> dict:
    struct = [tp for tp in test_points if getattr(tp, "structural_type", None)]
    total = len(struct)
    covered_keys = {tp.structural_key for tp in struct if tp.id in covered_tp_ids}
    uncovered = sorted({tp.structural_key for tp in struct if tp.id not in covered_tp_ids})
    return {"structural_total": total, "structural_covered": len(covered_keys),
            "structural_coverage": (len(covered_keys) / total) if total else 1.0,
            "uncovered_structural_keys": uncovered}
```
review_node 内（rule_cov_fields 之后）：
```python
    struct_cov_fields = dict(DEFAULT_STRUCTURAL_COVERAGE)
    if settings.structural_coverage_enabled:
        struct_cov_fields = compute_structural_coverage(test_points, covered_tp_ids)
```
`AuditReport(..., **rule_cov_fields, **struct_cov_fields)`。

- [ ] **Step 4: 跑测试 + Commit**
```bash
uv run pytest tests/testcase_generator/test_structural_coverage.py -q   # PASS
git add src/testcase_generator/schemas/audit_report.py src/testcase_generator/stages/review/rule_gate.py src/testcase_generator/stages/review/node.py tests/testcase_generator/test_structural_coverage.py
git commit -m "feat(review): 结构化覆盖度量进 AuditReport（compute_structural_coverage 放 rule_gate）"
```

### Task 6: backfill 识别结构化未覆盖点

**Files:** Modify `stages/review/backfill_node.py`

- [ ] **Step 1: backfill 纳入 uncovered_structural**（:105 rule_coverage_gate 块附近）
让 backfill 的「待回填测试点」集合并入 `audit_report.uncovered_structural_keys` 对应的测试点（按 structural_key 反查 test_point.id）。优雅降级：`structural_coverage_enabled` 开即纳入，与 `rule_coverage_gate_enabled` 解耦（structural 自有判定）。
```python
    if settings.structural_coverage_enabled and audit_report.uncovered_structural_keys:
        struct_uncovered_ids = [tp.id for tp in test_points
                                if getattr(tp, "structural_key", None) in set(audit_report.uncovered_structural_keys)]
        # 并入现有 backfill 目标集（与规则未覆盖点同样处理：定向重生成对应用例）
        ...（沿用本函数既有「按 tp_id 定向回填」路径）
```

- [ ] **Step 2: 全量 review/backfill 回归** — `uv run pytest tests/testcase_generator/ -k "review or backfill or structural" -q` → PASS

- [ ] **Step 3: Commit**
```bash
git add src/testcase_generator/stages/review/backfill_node.py
git commit -m "feat(backfill): 结构化未覆盖点纳入定向回填（与 rule 链解耦）"
```

---

## Chunk 5: 真实验证

### Task 7: 真实抽取 smoke（人工核对，不入 CI）

- [ ] **Step 1**: 临时 `STRUCTURAL_COVERAGE_ENABLED=true`，写一次性脚本/inline：取漫剧 PRD（§10 权限 + §5.9.3 任务状态机章节文本）跑 `extract_permission_matrix` / `extract_state_machines`（真实 LLM），打印矩阵+状态机+展开测试点。
- [ ] **Step 2**: 人工核对——角色（管理员/组长/投手）、资源、grants 是否抽对；任务状态机 states/transitions 是否齐；展开点是否覆盖关键格子/转移。
- [ ] **Step 3**: 若抽取明显漏/错，调 `_SYS` prompt（不改架构）。

## Execution Handoff
执行：Chunk 1→2→3→4→5 顺序；每 Task TDD（红→绿→commit）；**提交隔离只 add 本计划文件**。
执行后真实 smoke 核对抽取质量；新批次（开 `structural_coverage_enabled`）跑完看 `audit_report.structural_coverage`。
