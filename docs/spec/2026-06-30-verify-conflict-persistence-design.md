# verify 跨条款矛盾结果落库修复 — 设计文档

> 状态：设计（brainstorming 产出）。承接 roadmap `2026-06-30-quality-alignment-roadmap.md` ①。
> 下一步：writing-plans 出实施计划（执行交 Claude Code）。
> 来源：batch `278c211f` 审查 —— verify 矛盾扫描已生效但结果未落库。

## 1. 背景与问题

`verify` 的「跨条款矛盾扫描」（`verify_cross_section_conflict_enabled`，已上线）在 batch `278c211f` **实际产出了 64 个 `cross_section_conflict`** —— 证据是 worker 日志（`2026-06-30 14:59:30`）：

```
verify_node: {'total': 3185, 'conflict': 58, 'cross_section_conflicts': 64,
  'prd_conflict_list': [{'ref_a':'§5.6 标题包','quote_a':'组长/管理员可查看所有人的标题包',
                         'ref_b':'§10.2 数据权限规则','quote_b':'组长看本组'}, ...]}
```

但**导出的 `test_cases.verification` 里完全没有 `cross_section_conflict` 字段**（`.audit/278c211f` 全量 grep 0 命中）。即：矛盾算出来了、日志打了，却**未持久化到库** → 前端、导出、人工审查都看不到，矛盾扫描的成效被埋没。

这是 roadmap ① ——「观测解锁 + 落库修复」，零~极低成本，且是后续 ④⑤（重跑 verify 验证）能看到结果的前提。

## 2. 现象与数据流（静态链路全程正确）

```
verify_node:147-148  c.verification = CaseVerification(cross_section_conflict=...)   # 内存对象有字段
  → [LangGraph AsyncPostgresSaver checkpointer：verify→dedup 之间序列化 round-trip]   # ← 疑似丢失点
dedup_node:22,64-65,77  读 final_test_cases、仅改 duplicate_of、return            # 不动 verification
pipeline_task:99-103,132-138  final_state 累积 → on_pipeline_complete(c.model_dump())
callbacks:125,152  verification = case_data.get("verification") → 整体落 JSONB      # 有就落，无删旧
```

- schema 正确：`test_case.py` `CaseVerification.cross_section_conflict`(行56) / `conflicting_refs`(行59)；`GeneratedTestCase.verification: CaseVerification | None`(行91)。
- `callbacks` 落库正确：整 dict 落库（`verification or None`）。
- 故"字段没进库"不在 schema、不在 verify 产出、不在 callbacks，而在二者之间。

## 3. 根因假设（需复现确认，按可能性排序）

> **实施后注记（2026-06-30）**：实验证伪了假设 1 的核心机制。使用未配置 `allowed_msgpack_modules` 的默认 `JsonPlusSerializer()` 对 `_case_with_conflict()` 做 round-trip，结果 `cross_section_conflict=True`、`conflicting_refs` 完整，类型仍为 `GeneratedTestCase`——即**默认 serde 本就不丢新字段**。本次修复的实际价值是：**将 serde 显式注册为白名单模式，防止未来 `LANGGRAPH_STRICT_MSGPACK=true` 激活时静默降级为 dict**（届时漏注册的顶层类型会被 block 而非 warn）。`278c211f` 矛盾未落库的真实丢失点尚未通过 Task 0（dump checkpoint blob 取证）确认——已知修复路径是 `reverify_batch.py` 重跑 verify+落库，与 serde 是否为根因无关。

1. **【最可能】checkpointer 序列化 round-trip 丢失 `CaseVerification` 新增字段**。
   - 佐证 A：`verify` 在 `dedup` 之前，二者之间必经一次 checkpointer 持久化（`AsyncPostgresSaver`），`dedup_node` 收到的 `state["final_test_cases"]` 是反序列化后的对象。
   - 佐证 B：**老字段**（`verdict/bucket/rationale/prd_evidence`）**在库里存在**，只有 `verify` 阶段新增的 `cross_section_conflict/conflicting_refs` 丢 —— 指向"反序列化用了不含新字段的 schema 形态"。
   - 佐证 C：`provenance.grounding`（**dict 型**字段，如 `ref_corrected`）round-trip 不丢 → dict 稳定、pydantic 新字段易丢。
   - ⚠️ 注：实验已证伪此机制（见上方注记），真实丢失点待 Task 0 取证。
2. **【次】`GeneratedTestCase.model_dump()` 或落库映射在某条件下漏字段**（已静态排除大部分，但复现时一并验证）。

## 4. 目标

- `verify` 产出的 `cross_section_conflict` + `conflicting_refs` **正确持久化到 `test_cases.verification`**。
- **不重新生成**即可让现有 batch（如 `278c211f`）的矛盾透出（通过 `retry` 从 verify 阶段 resume，仅重跑 verify→落库，约几刀）。
- 零回归：不改 verify 判定逻辑 / 矛盾扫描 rubric / 生成。

## 5. 方案

0. **现场取证优先（比构造测试更直接、先做）**：直接 dump batch `278c211f` 落在 Postgres 的 checkpoint blob（`AsyncPostgresSaver`），查 verify 之后 / dedup 前后的 `final_test_cases[0].verification` 是否含 `cross_section_conflict`。**一步钉死丢失点**——checkpoint 里有→丢在 checkpoint→落库之间；无→丢在 verify→checkpoint 序列化。
   > 注意：§3 的"老字段留、新字段丢"在"serde 把对象序列化成 dict 全量"时其实**并不自洽**（dict 全量不该丢新字段），所以**不能仅凭该推断**，必须现场取证。真实丢失点也可能是"落库取到的 final_cases 不是 verify 回挂后的同批对象（快照/累积时序）"——取证可一并排除。
1. **再以 TDD 复现定位**：两层定位测试确定丢失层 ——
   - 落库层：构造含 `cross_section_conflict` 的 `case_data` dict → 走 `on_pipeline_complete` 落库 → 断言库内 `verification` 含字段。
   - serde 层：用 LangGraph checkpointer 的序列化器对含 `cross_section_conflict` 的 `GeneratedTestCase` 做 dumps→loads round-trip → 断言字段保留。
2. **按定位修复**：
   - 若 serde 丢（最可能）：确保 `GeneratedTestCase`/`CaseVerification` 经 checkpointer round-trip 完整（修序列化器用 `model_dump` 全量 / 或显式注册类型 / 或将 verify 结果同时写入稳定的 per-case dict 通道由落库回填）。
   - 若落库层丢：修 `model_dump` 调用或落库映射。
3. **单测**覆盖 round-trip + 落库保字段。
4. **观测验证**：对 `278c211f` 用 `retry` 从 verify 阶段 resume（仅重跑 verify→dedup→export→落库），导出确认 `cross_section_conflict` ≈ 64 进库（成本几刀，非 $100）。

## 6. 范围

**做**：复现定位 + 按定位修序列化/落库 + 单测 + 现有批次 resume 观测验证。

**不做（YAGNI）**：不改 verify 判定/矛盾扫描 rubric；不改生成（write_cases/test_points）；不动 dedup 逻辑；不为此重跑大 PRD 全链路（用 resume 即可）。

## 7. 验收

- 单测：含 `cross_section_conflict=true` 的用例经 checkpointer round-trip + 落库后，字段与 `conflicting_refs` 完整保留。
- `278c211f` 经 verify resume 后重新导出，`test_cases.verification` 含 `cross_section_conflict`，数量 ≈ 64（与日志一致）。
- 全量 `tests/testcase_generator/`（排除 integration）回归绿；改动文件 ruff 干净。
- 提交隔离：仅含本特性文件。

## 8. 风险

- **serde 修复影响其它 checkpoint 字段** → 复现测试覆盖 round-trip 全字段；灰度上无开关（属修复），以单测+resume 观测兜底。
- **resume 触发条件**：`retry_batch` 仅接受 `failed/pending`；`278c211f` 为 `pending_review`。观测验证需走一个"对指定 batch 从 verify 重跑"的最小入口（plan 中作为验证脚手架，不进主流程）。
- **【自审新增·重要】`on_pipeline_complete` 非幂等**：落库为纯 INSERT、无删旧（`callbacks.py:108-155`）。故任何 resume/retry 重跑都会**重复插入用例**（3185→6370）。reverify 观测前**必须先清该 batch 旧 test_cases/test_points/rules**，否则数据翻倍污染。治本可顺带把 `on_pipeline_complete` 改为"先删后插/upsert"——本计划至少在 reverify 脚本里先清旧（见 plan Task 4 Step 0）。
