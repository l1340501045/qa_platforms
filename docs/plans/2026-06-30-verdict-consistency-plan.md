# 同构同判（verdict 判级抖动收敛）Implementation Plan

> **For agentic workers:** REQUIRED: 用 superpowers:executing-plans 执行；步骤用 `- [ ]` 勾选跟踪。
> 关联 spec：`docs/spec/2026-06-30-verdict-consistency-design.md`。**依赖 ④**（基于 ④ 之后的 `verifier.py`）。

**Goal:** 收敛 verdict 判级抖动：5a 判后聚类一致化（确定性、同 feature 高相似簇多数票统一）+ 5b conflict 多次投票（灰度、仅 conflict 子集）。**关时零回归、5a 不烧 PRD（离线/单测）、5b retry resume 验证。**

**Architecture:** 5a 在 `verify_cases` 的 `results` 聚合后加 `reconcile_verdicts`（在 ④ 门控之后）；5b 在 `_verify_batch` 对首轮 conflict 子集复判。两者各自灰度。

**Tech Stack:** Python 3.12 / difflib.SequenceMatcher / pydantic / pytest（asyncio_mode=auto，mock LLM）。

---

## 现状速查（对齐 ④ 之后代码）

- `stages/verify/verifier.py`：`_CaseVerdict` 含 ④ 的 same_entity/conflict_subject_*；`_verify_batch` 含 ④ 同实体门控并产出 `CaseVerification`；`verify_cases` 在 `for br in batch_results: results.update(br)` 聚合后直接 `return results`；`_VERDICT_BUCKET` 与 `_normalize_verdict` 已存在。**行号仅供代码搜索参考，以函数名和代码地标为准，避免改造后漂移。**
- `schemas/test_case.py`：`CaseVerification`（含 verdict/bucket/rationale/conflict_entity_mismatch…）。
- `stages/verify/node.py`：`verify_node` 构造 `VerifyCase`（feature_id = test_point→feature 映射）、调 `verify_cases`、`summarize`。
- `core/settings.py`：灰度开关区（conflict_entity_gate_enabled 等）。
- **mock 约定**：`monkeypatch.setattr(vmod,"get_llm_client",lambda:fake)`；5a 纯函数直接单测。
- **⚠️ 提交隔离**：工作树有大量其他未提交改动。每 Task 只 `git add` 本计划列出文件，**严禁 `-A`/`git add .`**。

## File Structure

- **Modify** `src/testcase_generator/stages/verify/verifier.py`（`reconcile_verdicts` 5a + `_verify_batch` conflict 复投 5b）
- **Modify** `src/platform_api/core/settings.py`（`verdict_reconcile_enabled`/`reconcile_sim`/`conflict_revote_enabled`/`revote_n`）
- **Create** `tests/testcase_generator/test_verdict_consistency.py`
- **Create** `scripts/reconcile_offline_eval.py`（5a 现有 3185 条离线评估）

---

## Chunk 1: 5a `reconcile_verdicts` 纯函数（TDD）

### Task 1: 一致化纯函数

**Files:** `verifier.py`、Test: `test_verdict_consistency.py`

- [x] **Step 0: settings 先行**——在 `settings.py` 增加 `verdict_reconcile_enabled: bool=False` + `reconcile_sim: float=0.92`，保证 Task 1 的 `sim=None` 默认分支单独提交也自洽。（注：最终阈值调整为 0.93、开关默认开，见 Task 4。）
- [x] **Step 1: 写失败测试**——给 `results: dict[case_id, CaseVerification]` + `cases: list[VerifyCase]`：
  - 同 feature、title 高相似的 3 条 verdict=[grounded, grounded, conflict] → 统一 grounded（多数票）、bucket 同步 main。
  - 平票 [conflict, grounded] → 取较严 conflict。
  - **mismatch 传播（自审关键）**：簇内 [conflict(entity_mismatch=True), conflict, conflict] → **不取 conflict**（簇内有 mismatch、剔除 conflict 候选），统一降级 ungrounded + 传播 mismatch（救 ④ 漏判的同簇 conflict）。
  - 不同 feature 的不并；title 不相似的不并；`feature_id=""` 的用例跳过一致化，避免跨 feature 空 key 误并。
- [x] **Step 2: 跑失败 → 实现** `reconcile_verdicts(results, cases, *, sim=None) -> dict[case_id, CaseVerification]`：
  - 按非空 `feature_id` 分组；组内用 `SequenceMatcher(None, norm(title_a), norm(title_b)).ratio() >= sim`（默认 `settings.reconcile_sim`=0.93）并查集聚簇；
  - 簇内 verdict 取**多数票**（`Counter`），平票按严苛序 `conflict>undefined>ungrounded>grounded` 取较严；
  - **mismatch 协同（关键）**：簇内若有 `conflict_entity_mismatch=True`，则从候选**剔除 conflict**（同断言即同概念混淆假矛盾），在非 conflict 中取多数、并把 mismatch 传播给全簇——防 5a 撤销 ④ 降级、且救 LLM same_entity 漏判的同簇 conflict；
  - 改写簇内每条 `verdict` + `bucket=_VERDICT_BUCKET[...]`，rationale 追加"（同构一致化：簇内多数 → X）"；保留既有字段。
  - 纯函数、确定。
- [x] **Step 3: 跑通 + Commit**（add verifier.py test）。

---

## Chunk 2: verify_cases 接入 5a（灰度）

### Task 2: settings + 接入

**Files:** `settings.py`、`verifier.py`、Test 同文件

- [x] **Step 1: 确认 settings**：`verdict_reconcile_enabled` + `reconcile_sim` 已在 Task 1 Step 0 落地。
- [x] **Step 2**：`verify_cases` 在 `for br in batch_results: results.update(br)` 之后、`return results` 之前：`if settings.verdict_reconcile_enabled: results = reconcile_verdicts(results, cases)`。**位置在 ④ 门控之后**（④ 在 _verify_batch 内、已先执行）。
- [x] **Step 3: 写测试**——`verify_cases` mock 出分裂 verdict，开关开 → 一致化生效；关 → 现状。
- [x] **Step 4: 回归 + ruff + Commit**：
  - `uv run pytest tests/testcase_generator/test_verdict_consistency.py tests/testcase_generator/test_conflict_entity_gate.py tests/testcase_generator/test_verify_cross_section.py`
  - `uv run pytest tests/testcase_generator --ignore=tests/testcase_generator/integration`
  - `uv run ruff check src/testcase_generator/stages/verify/verifier.py src/platform_api/core/settings.py tests/testcase_generator/test_verdict_consistency.py scripts/reconcile_offline_eval.py`

---

## Chunk 3: 5b conflict 多次投票（灰度增强）

### Task 3: conflict 子集复判

**Files:** `verifier.py`、`settings.py`、Test 同文件

- [x] **Step 1: settings**：`conflict_revote_enabled: bool=False` + `revote_n: int=3`。（注：最终默认值改为 True，见 Task 5。）
- [x] **Step 2: 写测试**——mock LLM：首轮某条 conflict，复判 2 次返回 [grounded, grounded] → 多数定 grounded（再走 ④ 门控）；非 conflict 不复判（断言 LLM 调用次数）。
- [x] **Step 3: 实现**——`_verify_batch` 得到首轮 verdicts 后，若 `conflict_revote_enabled`：对 `verdict==conflict` 的 case 子集再调 `revote_n-1` 次（同 prompt、复用 semaphore），按 case 收集多数 verdict 覆盖首轮，再进入 ④ 门控 + 构造 CaseVerification。仅 conflict 子集复判。
- [x] **Step 4: 跑通 + 回归 + Commit**（同 Task 2 Step 4 命令）。

---

## Chunk 4: 验证（5a 离线 + 5b resume）

### Task 4: 5a 离线评估

**Files:** Create `scripts/reconcile_offline_eval.py`

- [x] **Step 1**：读 `.audit/<batch>/modules/*.cases.jsonl`（含 verification.verdict + title；历史 audit 多数无生产态 `feature_id`）→ 跑 `reconcile_verdicts` → 打印被一致化簇数、verdict 变更数；缺 `feature_id` 时使用 module 文件名近似 feature/章节粒度，**不得回退到 `test_point_id`**（粒度过细，会切散同 feature 跨测试点的 verdict 分裂）。
- [x] **Step 2: 运行**（零成本）
Run: `uv run python scripts/reconcile_offline_eval.py 278c211f-6f25-4970-a425-9db94cbc8ff7`
- [x] **Step 3: 启用闸门**：抽样核对未误并不同断言，重点检查"平票改判"、"升级为 conflict"、"grounded 被挤出 main"的簇；对新增 conflict 簇给出真/假判定，形成 `verdict_reconcile_enabled` 的 GO/NO-GO 结论（假阳为主则不启用或调整策略）。结论记入 roadmap ⑤ 进度；Commit。
  - **结论**：3185 条 / 15 簇改判，14 簇正确、1 簇误聚类（IAP 35宏参数 vs IAA 30宏参数，相似度 0.9231 刚过 0.92）。决断阈值 0.92→0.93（切散误簇、保留 14 真同构簇，changed 15→13、conflict +8→+7）；`verdict_reconcile_enabled` 经离线验证后默认开启。详见 roadmap ⑤。

### Task 5: 5b resume 观测（几刀，最小真实 LLM 验证）
- [x] 风险确认：`scripts/reverify_batch.py` 会在 verify+dedup 成功后重写该 batch 的 test_cases/test_points/rules 落库数据；仅对可丢弃的验证批次执行，且需要 `DATABASE_URL`、PostgreSQL、LLM 网关配置可用。
- [x] 设置 `conflict_revote_enabled=true` + `revote_n=3`（保留其他灰度按当前验证目标配置）。**已落实**：两开关默认值改为 `True`（5a 离线评估已确认 0.93 阈值安全；5b 仅 conflict 子集成本可控）。
- [ ] 分别在 `conflict_revote_enabled=false` / `true` 下运行 `uv run python scripts/reverify_batch.py 278c211f-6f25-4970-a425-9db94cbc8ff7`（或保留一份关开对照日志）。**未执行**：环境就绪，但 `reverify_batch.py` 会删除重写 batch 278c211f 已落库数据（test_cases=3185/test_points=1141），按用户决断暂不真实跑。
- [x] 记录并对比：`verify_node` 日志里的 `by_verdict.conflict`（不是脚本摘要里的 `cross_section_conflicts`）、§7.2 假 conflict 是否继续下降、真 conflict 抽样是否未被误撤。若需要首轮→复判翻转率，应先在复判处补 flip 调试日志；若成本或环境不允许执行，需在交付说明中明确"未做 5b 真实 LLM 观测"。**结论**：未做 5b 真实 LLM 观测，已在 roadmap ⑤ 与本计划明确标注；用户表示"没准一会儿要跑"，开关默认开以便随时执行。

---

## 总验收标准

- [x] 5a：同 feature 高相似簇 verdict 多数票统一、bucket 同步、平票取较严（单测）。
- [x] 5a 不误并：不同 feature / 空 feature_id / title 不相似 → 不动（单测 + 离线抽查）。
- [x] 5b：conflict 子集复判多数定 verdict、非 conflict 不复判（单测断言调用次数）；5a/5b 双开关同开时，先复判再一致化的组合路径有单测覆盖。
- [x] 两开关关 → 逐字节现状（单测显式 monkeypatch=False 覆盖；注：生产默认值已改为开，关态由测试显式构造）。
- [x] 非 integration 回归绿：`uv run pytest tests/testcase_generator --ignore=tests/testcase_generator/integration`（288 passed）；ruff 干净；提交仅含各 Task 文件。

## 风险与回退

- **5a 误聚类改判** → 高阈值 0.92 + 同 feature 限定 + 多数票（非取最严）+ 离线抽查；回退即关 `verdict_reconcile_enabled`。
- **5a 平票取严放大假 conflict / 挤出 grounded** → 这是"平票更保守"的有意取舍；必须在离线抽样中专项检查平票改判、升级 conflict、grounded→needs_spec 的簇，必要时调整策略或关 `verdict_reconcile_enabled`。
- **空 feature_id 跨功能误并** → `reconcile_verdicts` 跳过空 `feature_id`，离线脚本缺生产态 `feature_id` 时只能用 module 文件名近似，不用 `test_point_id`。
- **5a 与 ④ 顺序** → 固定 ④（batch 内）先、5a（聚合后）后。
- **5b 成本/抖动** → 仅 conflict 子集、n=3、灰度可关。
- **提交污染** → 每 Task 仅 `git add` 指定文件，绝不 `-A/.`。
