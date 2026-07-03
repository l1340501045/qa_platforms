# 生成侧收敛（拆条上限 + 存在性合并 + P0 配额）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> 关联 spec：`docs/spec/2026-06-30-generation-convergence-design.md`。
> **三子项互不依赖、各自灰度**，可按 Chunk 独立交付。

**Goal:** 收敛生成侧虚胖：①每测试点用例数上限 ②存在性用例合并 ③P0 全局配额；**不丢覆盖、灰度可回退、关时零回归**；①②做后处理（现有 3185 条离线验、不烧 PRD），③单测 + 补落 likelihood/impact。

**Tech Stack:** Python 3.12 / pydantic / pytest（asyncio_mode=auto）。

---

## 现状速查（对齐当前代码）

- `write_cases/node.py`：`generate_cases`（248）；后处理救回拆条（478-491，无上限）；用例 `test_point_id` 多对一；用例 schema `GeneratedTestCase`（含 dimensions/steps/priority/duplicate_of）。
- `test_points/node.py`：`risk_to_priority`（132-141，`P0_MIN_RISK=6`）逐条；`GeneratedTestPoint.likelihood/impact`（42-45）；priority 赋值处（约 516-523）。
- `tasks/callbacks.py`：落 test_points（90-99，**未存 likelihood/impact**）；落 test_cases（含 priority/duplicate_of/review_status）。
- `dedup/clustering.py`：`_BOUNDARY_KW`（27-30）、`_normalize`（47）、safe_dedup 护栏（可复用思想/常量）。
- `core/settings.py`：灰度开关区。
- **mock 约定**：纯函数后处理直接单测；test_points 优先级纯函数单测。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动。每个 Task 只 `git add` 本计划列出文件，**严禁 `-A`/`git add .`**。

## File Structure

- **Create** `src/testcase_generator/stages/write_cases/convergence.py`（拆条上限 + 存在性合并 纯函数）
- **Modify** `src/testcase_generator/stages/write_cases/node.py`（生成后接入 4.1/4.2，灰度）
- **Modify** `src/testcase_generator/stages/test_points/node.py`（4.3 配额裁剪）
- **Modify** `src/testcase_generator/tasks/callbacks.py`（落 likelihood/impact）+ `models/testcase.py`（TestPoint 加列）+ alembic 迁移
- **Modify** `src/platform_api/core/settings.py`（3 开关 + 阈值）
- **Create** `tests/testcase_generator/test_generation_convergence.py`
- **Create** `scripts/convergence_offline_eval.py`（4.1/4.2 现有 3185 条离线评估）

---

## Chunk 1: 拆条上限（write_cases 后处理，纯函数 TDD）

### Task 1: `cap_cases_per_testpoint` 纯函数

**Files:** Create `convergence.py`、Test: `test_generation_convergence.py`

- [ ] **Step 1: 写失败测试**——某 test_point 有 6 条用例（含 2 条边界、3 个不同 dimension、1 条 rule 锚定），`cap_cases_per_testpoint(cases, n=3)` 后：≤3 条/该 tp、**边界与 rule 锚定条必被保留**、不同 dimension 尽量各留代表；另一 tp 仅 1 条 → 不动。
- [ ] **Step 2: 跑失败 → 实现**——按 `test_point_id` 分组；超 `n` 时按优先级保留：①rule_codes 非空 ②含 `_BOUNDARY_KW` ③dimension 去重各一 ④steps 最全；被裁用例返回"被裁 case_id → 保留代表 case_id"映射，调用方据此置 **`duplicate_of` 指向该 tp 保留代表**（与 dedup 同机制、可恢复、不硬删）。**护栏**：每 tp 至少留 1 条、每规则至少留 1 条。
- [ ] **Step 3: 跑通 + Commit**（add convergence.py test）。

---

## Chunk 2: 存在性合并（write_cases 后处理，纯函数 TDD）

### Task 2: `merge_existence_cases` 纯函数

**Files:** `convergence.py`、Test 同文件

- [ ] **Step 1: 写失败测试**——同 test_point 下 3 条"仅 1 步存在性"（"页面展示A"/"显示B"/"包含C"）→ 合并为 1 条，`expected_results` **含 A/B/C 三检查点**（不丢）；含判定步骤的用例（步数≥2 或含输入/校验）**不参与合并**。
- [ ] **Step 2: 跑失败 → 实现**——识别存在性：`len(steps)<=1` 且标题/预期匹配纯展示词（展示/显示/包含/存在/布局/默认选中…，无"输入/校验/拦截/错误"等判定词）；同 `(test_point_id, source_section)` 的存在性用例合并：preconditions 取并集、steps 合成 1 条"逐项核对页面元素"、expected_results 保留全部检查点。
- [ ] **Step 3: 跑通 + Commit**。

---

## Chunk 3: write_cases 接入 4.1/4.2（灰度）

### Task 3: settings 开关 + node 接入

**Files:** `settings.py`、`write_cases/node.py`、Test 同文件

- [ ] **Step 1: settings**：`split_cap_enabled: bool=False` + `cases_per_tp_cap: int=3` + `existence_merge_enabled: bool=False`。
- [ ] **Step 2**：`generate_cases` 收尾（`all_test_cases` 汇总后）按开关调 `merge_existence_cases` → `cap_cases_per_testpoint`；被裁/被并的用例软标记（不进主集计数）。关时不动。
- [ ] **Step 3: 全量回归 + ruff + Commit**。

---

## Chunk 4: P0 配额（test_points）+ 落 likelihood/impact

### Task 4: `apply_p0_quota` 纯函数（TDD）

**Files:** `test_points/node.py`、Test 同文件

- [ ] **Step 1: 写失败测试**——一批 tp（likelihood/impact 各异，risk_to_priority 后 P0 占 60%），`apply_p0_quota(tps, quota=0.30)` 后 P0≤30% 且保留的是 **risk 最高**者，其余 P0 降 P1；P2 不动；同 risk 稳定序。
- [ ] **Step 2: 跑失败 → 实现**——统计 P0 数；若 > `quota*total`，按 `likelihood*impact` 降序、**超额的 risk 派生 P0 改 P1**。**结构化覆盖点豁免**：无 likelihood/impact 的（expander/rule_anchor/mandatory）赋最高 risk 或排除配额（保权限矩阵/状态机 P0），仅裁 risk 派生的边际 P0。补一条"结构化 P0 不被配额误降"的测试。
- [ ] **Step 3**：test_points node 在 priority 赋值后（约 516-523）按 `p0_quota_enabled` 调用。
- [ ] **Step 4: settings**：`p0_quota_enabled: bool=False` + `p0_quota: float=0.30`。
- [ ] **Step 5: 跑通 + Commit**。

### Task 5: 落 likelihood/impact（schema + 迁移）

**Files:** `models/testcase.py`、`tasks/callbacks.py`、alembic 迁移

- [ ] **Step 1**：`TestPoint` 模型加 `likelihood: int|None` / `impact: int|None` 列；`alembic revision --autogenerate`。
- [ ] **Step 2**：`callbacks.py` 落 test_points 时写入这两字段（来自 tp_data）。
- [ ] **Step 3**：`uv run alembic upgrade head` 冒烟；Commit（add 迁移 + 两文件）。

---

## Chunk 5: 离线评估（4.1/4.2，现有 3185 条，≈0 成本）

### Task 6: `convergence_offline_eval.py`

- [ ] **Step 1**：读 `.audit/<batch>/modules/*.cases.jsonl` → 跑 `merge_existence_cases` + `cap_cases_per_testpoint` → 打印：合并/裁剪条数、总量前后、每测试点条数分布；抽样核对未丢边界/规则/检查点。
- [ ] **Step 2: 运行**（零 LLM 成本）
Run: `uv run python scripts/convergence_offline_eval.py 278c211f-6f25-4970-a425-9db94cbc8ff7`
Expected：总量明显下降（趋向 ~2000）、每测试点 ≤3、抽样无丢覆盖。
- [ ] **Step 3**：结论记入 roadmap ⑥ 进度；Commit（add 脚本）。

---

## 总验收标准

- [ ] 4.1：每测试点 ≤ `cases_per_tp_cap`，边界/规则锚定/维度代表保留（单测 + 离线抽查）。
- [ ] 4.2：存在性合并保留全部检查点，判定型用例不被误并（单测）。
- [ ] 4.3：配额后 P0 ≤ `p0_quota` 且留 risk 最高者（单测）；test_points 落库含 likelihood/impact。
- [ ] 三开关关 → 逐字节现状（回归）。
- [ ] 离线评估总量趋向 ~2000、无丢覆盖。
- [ ] 全量（排除 integration）回归绿；ruff 干净；提交仅含各 Task 文件。

## 风险与回退

- **裁剪/合并丢覆盖** → 护栏（每 tp/每规则至少 1 条、边界保护、全检查点保留）+ 离线抽查 + 软标记可恢复；回退即关对应开关。
- **P0 配额误降高价值** → 严格 risk 降序 + 稳定序；阈值可配。
- **迁移风险**（Task 5 加列）→ 可空列、向后兼容；旧数据 NULL。
- **提交污染** → 每 Task 仅 `git add` 指定文件，绝不 `-A/.`。
