# UI真实跑批后审查

## Goal

基于用户已完成的真实跑批，审查当前 `feat/qa-platform-ux-modernization` 是否满足 UI/UX 合并前的核心证据要求：

- 真实批次是否完成且可审查。
- 上传资料类型、批次页、模块树、用例资产、搜索、导出是否符合 QA 日常动线。
- 新批次用例质量和模块树是否存在 UI/UX 造成的 P0/P1 回归。
- 是否可以进入 GO / FIX THEN GO / NO-GO / SPLIT OUT 判定。

本任务是审查任务，不实现新功能，不修改生成器逻辑，不修复导出相关脏改动。

## Requirements

- R1：先识别当前最新真实批次、对应 system/document/batch 状态和 `.audit` 审查包。
- R2：区分当前工作区已有导出相关脏改动与本审查任务产物，不提交或回滚非本任务改动。
- R3：审查 `.audit/<batch_id>/REPORT.md`、`index.json`、`modules/`，必要时抽样原始用例。
- R4：重点判断模块树是否按业务模块/分支组织，而不是 PRD 章节平铺。
- R5：重点判断用例是否存在明显灌水、重复、不可验证预期、步骤/预期不完整、与 PRD 脱节。
- R6：短步骤用例不天然判坏；只按断言清晰、预期可观察、来源可追溯来评价。
- R7：输出报告必须明确 GO / FIX THEN GO / NO-GO / SPLIT OUT 建议，并说明根因和行业最佳实践对齐方向。
- R8：不得修改 `src/testcase_generator/**`，不得改变平台运行代码。
- R9：产物必须包含批判性 review，说明证据边界和可能误判。

## Acceptance Criteria

- [x] 识别出本轮真实跑批 batch_id 和 `.audit` 路径。
- [x] 审查报告包含批次事实、模块树判断、用例质量判断、UI/UX 主链路判断。
- [x] 报告明确是否满足父任务合并前 GO 条件，以及缺失证据。
- [x] 自审记录说明本轮审查是否可能把生成策略问题误归因到 UI/UX。
- [x] `src/testcase_generator/**` 无 diff。

## Notes

- 当前工作区有导出相关未提交改动，审查时只读，不混入本任务提交。
