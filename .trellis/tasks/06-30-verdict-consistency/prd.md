# 同构同判 verdict 判级一致性

## Goal

收敛测试用例核验阶段的 verdict 判级抖动：同一 feature 下高度同构的用例在判后保持一致 verdict，并对首轮 conflict 结果提供灰度复判能力，降低单次 LLM judge 误判带来的假 conflict。

## Requirements

- 在 `verify_cases` 聚合结果后支持确定性的判后一致化，仅在灰度开关 `verdict_reconcile_enabled` 打开时生效。
- 一致化只允许在相同 `feature_id` 内对标题高度相似的用例聚簇，默认相似度阈值为 `reconcile_sim=0.92`。
- 簇内 verdict 以多数票为准；平票时按 `conflict > undefined > ungrounded > grounded` 取更严结果，并同步更新 bucket。
- 若簇内任一结果存在 `conflict_entity_mismatch=True`，一致化必须剔除 conflict 候选，在非 conflict verdict 中投票，并向全簇传播 mismatch 标记，避免撤销已有同实体门控降级。
- 在 `_verify_batch` 中支持仅针对首轮 `conflict` 子集做多次复判，受 `conflict_revote_enabled` 和 `revote_n` 灰度控制；非 conflict 用例不得复判。
- 两个新能力默认关闭；关闭时不得改变现有核验行为。
- 提供聚焦单测覆盖 5a 一致化、5b conflict 复判、开关关闭路径。
- 提供离线评估脚本，读取 `.audit/<batch>/modules/*.cases.jsonl` 并统计一致化簇数、verdict 变更数，用于验证误聚类风险。
- 保持提交隔离，仅触碰原计划列出的文件：`src/testcase_generator/stages/verify/verifier.py`、`src/platform_api/core/settings.py`、`tests/testcase_generator/test_verdict_consistency.py`、`scripts/reconcile_offline_eval.py`，以及必要的 Trellis 任务文档。

## Acceptance Criteria

- [ ] 同 feature 高相似簇 `[grounded, grounded, conflict]` 被统一为 `grounded`，bucket 同步更新。
- [ ] 平票 `[conflict, grounded]` 按严苛序统一为 `conflict`。
- [ ] 含 `conflict_entity_mismatch=True` 的同构簇不会被统一回 conflict，而是降级到非 conflict 多数结果并传播 mismatch。
- [ ] 不同 feature 或标题不相似的用例不会被聚簇改判。
- [ ] 打开 `verdict_reconcile_enabled` 时 `verify_cases` 在同实体门控之后执行一致化；关闭时保持现状。
- [ ] 打开 `conflict_revote_enabled` 时只有首轮 conflict 用例会执行 `revote_n-1` 次复判，并以多数票覆盖首轮 verdict 后再走同实体门控。
- [ ] 两个灰度开关默认关闭，关闭路径测试通过。
- [ ] `uv run pytest tests/testcase_generator/test_verdict_consistency.py` 通过。
- [ ] `uv run ruff check src/testcase_generator/stages/verify/verifier.py src/platform_api/core/settings.py tests/testcase_generator/test_verdict_consistency.py scripts/reconcile_offline_eval.py` 通过。
- [ ] 离线脚本可运行 `uv run python scripts/reconcile_offline_eval.py 278c211f-6f25-4970-a425-9db94cbc8ff7` 并输出统计。

## Notes

- 来源计划：`docs/plans/2026-06-30-verdict-consistency-plan.md`。
- 关联设计：`docs/spec/2026-06-30-verdict-consistency-design.md`。
- 本任务属于复杂实现，需配套 `design.md` 与 `implement.md` 后再启动。
