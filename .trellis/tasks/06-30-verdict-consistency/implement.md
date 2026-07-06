# 同构同判 verdict 判级一致性执行计划

## 执行原则

- 使用 TDD：每个能力先补失败测试，再实现。
- 每个阶段只改计划列出的文件，禁止 `git add -A` / `git add .`。
- 新开关默认关闭，先保证关闭路径零回归。
- 任务启动后先设置隔离 worktree，再改业务代码。

## 文件范围

- 修改：`src/testcase_generator/stages/verify/verifier.py`
- 修改：`src/platform_api/core/settings.py`
- 新增：`tests/testcase_generator/test_verdict_consistency.py`
- 新增：`scripts/reconcile_offline_eval.py`

## 步骤 1：5a `reconcile_verdicts` 纯函数

- [x] 在 `tests/testcase_generator/test_verdict_consistency.py` 编写失败测试：
  - 同 feature、高相似标题的 `[grounded, grounded, conflict]` 统一为 `grounded`。
  - `[conflict, grounded]` 平票统一为更严的 `conflict`。
  - 含 `conflict_entity_mismatch=True` 的 conflict 簇剔除 conflict 候选，统一到非 conflict 结果，并传播 mismatch。
  - 不同 feature 不合并，标题不相似不合并。
- [x] 在 `verifier.py` 实现 `reconcile_verdicts(results, cases, *, sim=None)`：
  - 按 `feature_id` 分组。
  - 用 `SequenceMatcher` 和并查集聚簇。
  - 多数票统一 verdict，平票取更严。
  - 同步 `bucket`，追加中文 rationale 说明，保留既有字段。
- [x] 运行 `uv run pytest tests/testcase_generator/test_verdict_consistency.py -k reconcile`。

## 步骤 2：5a 接入 `verify_cases`

- [x] 在 `settings.py` 增加 `verdict_reconcile_enabled: bool = False` 与 `reconcile_sim: float = 0.92`。
- [x] 在 `verify_cases` 聚合 `results` 后、return 前按开关调用 `reconcile_verdicts(results, cases)`。
- [x] 补 `verify_cases` mock 测试：
  - 开关打开时一致化生效。
  - 开关关闭时保持原 verdict。
- [x] 运行 `uv run pytest tests/testcase_generator/test_verdict_consistency.py`。

## 步骤 3：5b conflict 子集复判

- [x] 在 `settings.py` 增加 `conflict_revote_enabled: bool = False` 与 `revote_n: int = 3`。
- [x] 先写测试：
  - 首轮 conflict，复判结果 `[grounded, grounded]` 时最终采用 `grounded`。
  - 非 conflict 用例不复判，通过 LLM 调用次数断言。
  - 复判后仍进入同实体门控。
- [x] 在 `_verify_batch` 中实现 conflict 子集复判：
  - 首轮 verdict 完成后筛选 conflict case。
  - 追加 `revote_n-1` 次同 prompt 调用。
  - 按 case 汇总投票，多数票覆盖首轮 verdict。
  - 再执行既有同实体门控并构造 `CaseVerification`。
- [x] 运行 `uv run pytest tests/testcase_generator/test_verdict_consistency.py`。

## 步骤 4：离线评估脚本

- [x] 新建 `scripts/reconcile_offline_eval.py`：
  - 读取 `.audit/<batch>/modules/*.cases.jsonl`。
  - 提取 case id、feature/title、verification verdict。
  - 调用 `reconcile_verdicts`。
  - 输出被一致化簇数、verdict 变更数和示例。
- [x] 运行 `uv run python scripts/reconcile_offline_eval.py 278c211f-6f25-4970-a425-9db94cbc8ff7`。
- [x] 将离线结论追加到 `docs/2026-06-30-quality-alignment-roadmap.md` 的 ⑤ 进度位置。

## 步骤 5：质量检查

- [x] 运行 `uv run pytest tests/testcase_generator/test_verdict_consistency.py`。
- [x] 运行 `uv run ruff check src/testcase_generator/stages/verify/verifier.py src/platform_api/core/settings.py tests/testcase_generator/test_verdict_consistency.py scripts/reconcile_offline_eval.py`。
- [x] 如有必要，运行与 verify 相关的现有测试。
- [x] 检查 `git diff`，确认无计划外文件改动。

## 提交策略

- 若按原计划逐段提交，每次只 stage 当前段相关文件。
- 若 Trellis 完成阶段统一提交，则提交前再次确认仅包含计划范围文件与必要任务文档。
