# verify 跨条款矛盾结果落库修复 Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> 关联 spec：`docs/spec/2026-06-30-verify-conflict-persistence-design.md`。

**Goal:** 让 `verify` 已产出的 `cross_section_conflict` + `conflicting_refs`（batch 278c211f 日志实测 64 个）**正确落库到 `test_cases.verification`**；先复现定位丢失层，再针对性修复，单测保 round-trip，最后用 `retry` 从 verify 阶段 resume 在**不重新生成**的前提下验证现有批次矛盾透出。

**Architecture:** 静态链路（verify_node 回挂 → checkpointer round-trip → dedup → on_pipeline_complete model_dump → callbacks 整体落 JSONB）各环正确，丢失在 verify→dedup 之间的 `AsyncPostgresSaver` 序列化 round-trip（最可能）。Chunk 1 用两层定位测试钉死丢失层；Chunk 2 按结果最小修复；Chunk 3 单测 + resume 观测。

**Tech Stack:** Python 3.12 / pydantic v2 / langgraph (AsyncPostgresSaver) / pytest（asyncio_mode=auto）。

---

## 现状速查（对齐当前代码）

- `schemas/test_case.py`：`CaseVerification`（行46-61，`cross_section_conflict` 行56、`conflicting_refs` 行59）；`GeneratedTestCase.verification: CaseVerification | None`（行91-93）；`Provenance.grounding: dict | None`（行71，dict 型，round-trip 不丢——对照证据）。
- `stages/verify/node.py`：`verify_node` 行102；回挂 `c.verification = verifications.get(key)` 行147-148；`return {"final_test_cases": final_cases, ...}` 行153-157。
- `stages/verify/verifier.py`：`_conflict = bool(v.cross_section_conflict and _refs)` 行192；构造 `CaseVerification(cross_section_conflict=_conflict, conflicting_refs=_refs)` 行193-201；`summarize` 行216-244 产出 `cross_section_conflicts` 计数（日志来源）。
- `stages/dedup/node.py`：读 `state["final_test_cases"]` 行22；仅设 `c.duplicate_of` 行64-65；`return {"final_test_cases": final_cases,...}` 行77-81（不动 verification）。
- `tasks/pipeline_task.py`：`astream` 累积 `final_state.update(node_output)` 行99-103；`on_pipeline_complete(final_cases=[c.model_dump() ...])` 行132-138。
- `tasks/callbacks.py`：`on_pipeline_complete` 行40；`verification = case_data.get("verification") or {}` 行125；`verification=verification or None` 整体落库 行152（**纯 INSERT，无删旧**）。
- `pipeline/persistence.py`：`open_async_checkpointer` 用 `AsyncPostgresSaver.from_conn_string`（行34-49），默认 serde。
- `services/retry_service.py`：`retry_batch` 仅接受 `failed/pending`（行39-49）；`_resume_pipeline(batch, from_stage)` 行96-112 发 `run_pipeline` 带 `resume_from`。
- **mock 约定**：`monkeypatch.setattr(mod, "get_llm_client", lambda: fake)`；集成测试需 PostgreSQL。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动。每个 Task 只 `git add` 本计划明确列出的文件，**严禁 `-A` / `git add .`**。

## File Structure

- **Create** `tests/testcase_generator/test_verify_conflict_persistence.py`（复现+定位+回归单测）
- **Modify**（按 Chunk 1 定位结果，二选一/或叠加）：
  - `src/testcase_generator/pipeline/persistence.py`（若 serde 丢字段 → 配置/注册 serde）
  - 或 `src/testcase_generator/stages/verify/node.py` / `pipeline/graph.py`（若需稳定通道回填）
- **Create** `scripts/reverify_batch.py`（验证脚手架：对指定 batch 从 verify 阶段 resume，仅重跑 verify→落库；不进主流程）

---

## Chunk 1: 复现 + 定位丢失层（先现场取证，再 TDD）

### Task 0: 案发现场取证 —— 直接查 278c211f 的 checkpoint blob（最直接，先做）

**Files:** Create `scripts/dump_checkpoint.py`（仅排查用，可后续删）

- [ ] **Step 1**：从 Postgres checkpoint 表读 batch `278c211f`（thread_id=batch_id）verify 之后 / dedup 前后的 checkpoint，打印 `final_test_cases[0].verification` 的 keys。
- [ ] **Step 2: 判读并钉死路径**：
  - checkpoint 里**有** `cross_section_conflict` → 序列化没丢，问题在 checkpoint→落库读取/`model_dump` 链 → 只走 **路径 B**（Task 2 / Chunk 2 路径 B）。
  - checkpoint 里**无** → 丢在 verify→checkpoint 序列化 → 只走 **路径 A**（Task 1 / Chunk 2 路径 A）。
- [ ] **Step 3**：把取证结论写进本节，**后续只做 A 或 B 一条线**（省返工）。先于构造测试做，因为 §3 的"老字段留新字段丢"推断在"序列化为 dict 全量"时并不自洽，必须以现场取证为准。

### Task 1: serde 层 round-trip 测试（路径 A：取证指向序列化写入丢失时）

**Files:** Create `tests/testcase_generator/test_verify_conflict_persistence.py`

- [ ] **Step 1: 写测试**——用 checkpointer 实际使用的序列化器，对含 `cross_section_conflict` 的 `GeneratedTestCase` 做 dumps→loads，断言字段保留。
```python
"""verify 矛盾结果落库 — 复现/定位/回归。"""
from __future__ import annotations

from src.testcase_generator.schemas.test_case import (
    CaseVerification, CrossSectionConflictRef, GeneratedTestCase, Provenance,
)


def _case_with_conflict() -> GeneratedTestCase:
    return GeneratedTestCase(
        id="TC-0001", test_point_id="TP-001", title="t", priority="P0",
        provenance=Provenance(source_section="§x", verbatim_excerpt="e", trust_level=1),
        verification=CaseVerification(
            verdict="grounded", bucket="main",
            cross_section_conflict=True,
            conflicting_refs=[CrossSectionConflictRef(
                ref_a="§5.6", quote_a="组长可查看所有人", ref_b="§10.2", quote_b="组长看本组")],
        ),
    )


def test_langgraph_serde_preserves_cross_section_conflict():
    # ⚠️ 自审修正：必须用 AsyncPostgresSaver 实际使用的 serde（线上一致），而非假设 JsonPlusSerializer。
    # 离线快验可临时用 JsonPlusSerializer，但结论须与 Task 0 现场取证交叉印证后才采信。
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serde = JsonPlusSerializer()  # TODO(执行者): 替换为 open_async_checkpointer() 内的 cp.serde 做 async round-trip
    case = _case_with_conflict()
    payload = {"final_test_cases": [case]}
    type_, blob = serde.dumps_typed(payload)
    restored = serde.loads_typed((type_, blob))
    rc = restored["final_test_cases"][0]
    v = rc.verification if hasattr(rc, "verification") else rc["verification"]
    cs = getattr(v, "cross_section_conflict", None) if not isinstance(v, dict) else v.get("cross_section_conflict")
    assert cs is True, "checkpointer serde 丢失了 cross_section_conflict（定位到 serde 层）"
```

- [ ] **Step 2: 跑测试看结果**（这是定位，不预设红绿）
Run: `uv run pytest tests/testcase_generator/test_verify_conflict_persistence.py::test_langgraph_serde_preserves_cross_section_conflict -v`
- **FAIL** → 丢失点在 checkpointer serde（走 Chunk 2 路径 A）。
- **PASS** → serde 没问题，丢失在落库层（继续 Task 2 定位）。

- [ ] **Step 3: 记录定位结论**到 plan（勾选 A 或 B），不 commit 实现代码（仅可先 commit 该定位测试）。

### Task 2: 落库层测试（serde 若 PASS 才需深查此层）

**Files:** 同测试文件

- [ ] **Step 1: 写测试**——构造含字段的 `case_data` dict（即 `c.model_dump()` 形态），mock session 收集 `add` 的 `TestCase`，断言其 `verification` 含 `cross_section_conflict`。
```python
async def test_on_pipeline_complete_persists_cross_section_conflict(monkeypatch):
    from src.testcase_generator.tasks import callbacks as cb

    added = []

    class _FakeSession:
        def add(self, obj): added.append(obj)
        async def flush(self): ...
        async def commit(self): ...
        async def execute(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...

    monkeypatch.setattr(cb, "async_session_factory", lambda: _FakeSession())

    case = _case_with_conflict().model_dump()
    await cb.on_pipeline_complete(
        batch_id="00000000-0000-0000-0000-000000000001",
        final_cases=[case], audit_report={}, test_points=[], rules=[],
    )
    tc = [o for o in added if o.__class__.__name__ == "TestCase"][0]
    assert (tc.verification or {}).get("cross_section_conflict") is True
```

- [ ] **Step 2: 跑** → PASS 说明 `model_dump`+落库无问题（坐实丢在 serde）；FAIL 说明落库层也有份。
- [ ] **Step 3: Commit 定位测试**
```bash
git add tests/testcase_generator/test_verify_conflict_persistence.py
git commit -m "test(verify): 复现/定位 cross_section_conflict 落库丢失（serde + 落库两层）"
```

---

## Chunk 2: 按定位修复（TDD）

> 依据 Chunk 1 结论选路径。**路径 A（serde，最可能）**：

### Task 3A: 修 checkpointer 序列化保 pydantic 新字段

**Files:** `src/testcase_generator/pipeline/persistence.py`（+必要时 serde 配置）

- [ ] **Step 1**：让 Task 1 的 serde round-trip 测试转绿。候选实现（按侵入度从低到高，取最小可行）：
  - (a) 为 `AsyncPostgresSaver` 显式传入对 pydantic v2 用 `model_dump`/`model_validate` 全量往返的序列化器；
  - (b) 若 LangGraph 版本默认即应保留、实为类型重建用了 dict —— 在 `dedup`→`export`→落库链路改为消费 dict 形态并 `CaseVerification.model_validate` 重建（确保新字段不丢）；
  - (c) 兜底：`verify_node` 同时把 per-case 矛盾写入稳定 dict 通道（`state["verify_conflicts"]: {case_id: {...}}`），`on_pipeline_complete` 落库时若 `verification` 缺字段则从该通道回填。
- [ ] **Step 2**：Task 1 测试转绿；不破坏其它 checkpoint 往返（补一条"round-trip 全字段一致"断言）。
- [ ] **Step 3: Commit**（只 add persistence.py / 相关文件 + 测试）。

> **路径 B（落库层，仅 Task 2 FAIL 时）**：修 `pipeline_task.py` 的 `model_dump` 调用或 `callbacks` 映射，使 `verification` 全字段落库；Task 2 测试转绿后 commit。

---

## Chunk 3: 验证脚手架 + 现有批次观测（省钱验证，不跑大 PRD）

### Task 4: `reverify_batch.py` —— 对指定 batch 从 verify 阶段 resume

**Files:** Create `scripts/reverify_batch.py`

- [ ] **Step 0（必须·防重复落库）**：reverify 前**先删该 batch 的旧 test_cases/test_points/rules**——`on_pipeline_complete` 是纯 INSERT 无删旧（`callbacks.py:108-155`），不清旧会重复插入（3185→6370）。可选治本：本 Task 顺带把 `on_pipeline_complete` 改为"先按 batch_id 删后插"使其幂等（二选一并记录；改主流程需补幂等单测）。
- [ ] **Step 1**：脚本读 batch_id，复用 `RetryService._resume_pipeline`/`_send_pipeline_task` 的方式从 `verify` 阶段 resume（绕开 `retry_batch` 的 `failed/pending` 限制，仅用于验证；不改主流程的 retry 语义）。仅重跑 `verify→dedup→export→落库`，**不重新生成**。
- [ ] **Step 2: 运行**（成本几刀，非 $100）
Run: `uv run python scripts/reverify_batch.py 278c211f-6f25-4970-a425-9db94cbc8ff7`
Expected：日志再次出现 `cross_section_conflicts: N`；落库后 `test_cases.verification` 含 `cross_section_conflict`。
- [ ] **Step 3: 用审查导出脚本复核**
Run: `uv run python scripts/audit_export.py 278c211f-6f25-4970-a425-9db94cbc8ff7`（overview）
Expected：能在用例 verification 中看到 `cross_section_conflict`（数量与日志一致，≈64）。
- [ ] **Step 4: Commit**（只 add scripts/reverify_batch.py）。

---

## 总验收标准

- [ ] Chunk 1 两层定位测试明确丢失层并记录。
- [ ] 修复后 serde round-trip 单测绿（含 `cross_section_conflict` + `conflicting_refs` 完整保留 + 全字段一致）。
- [ ] 落库单测绿（`on_pipeline_complete` 后 `TestCase.verification` 含字段）。
- [ ] `reverify_batch.py` 对 `278c211f` resume 后，导出 verification 含 `cross_section_conflict`（≈64），**未重新生成**。
- [ ] 全量 `tests/testcase_generator/`（排除 integration）回归绿；改动文件 ruff 干净。
- [ ] 提交仅含本计划列出的文件。

## 风险与回退

- **serde 改动波及其它 checkpoint 往返** → "round-trip 全字段一致"断言兜底；回退即还原 persistence.py。
- **路径 (c) 稳定通道** 作为 serde 难改时的低风险兜底（不动 serde，仅落库回填）。
- **reverify 脚本误触主流程** → 脚本独立、仅用于验证，不接入 API/正常 retry；标注 only-for-verification。
- **【自审】`on_pipeline_complete` 非幂等** → resume/retry 重跑会重复落库（3185→6370）；reverify 前必须清旧（Task 4 Step 0），或改 upsert。
- **提交污染** → 每 Task 仅 `git add` 指定文件，绝不 `-A/.`。
