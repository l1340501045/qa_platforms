# UI父任务执行计划状态说明

## Goal

给父任务 `.trellis/tasks/07-04-qa-platform-ux-modernization/implement.md` 增加状态说明，避免早期未勾选执行计划被误读为当前 UI/UX 子任务尚未执行。

## Confirmed Facts

- 父任务当前状态为 `planning [22/22 done]`。
- 实际执行已经拆到子任务完成和归档，合并前状态以 `main-merge-readiness.md`、`final-integration-review.md` 和归档子任务为准。
- 父任务 `implement.md` 仍保留早期规划时的未勾选清单，这些清单是历史计划稿，不再是当前进度来源。

## Requirements

- R1：在父任务 `implement.md` 顶部增加状态说明。
- R2：说明不得篡改历史计划内容，只明确当前判断来源。
- R3：不得修改前端、API、worker 或 `src/testcase_generator/**`。

## Out of Scope

- 不重写父任务完整计划。
- 不逐项回填所有历史 checkbox。
- 不改变任何运行时代码。

## Acceptance Criteria

- [x] `implement.md` 顶部说明该文件是历史执行计划稿。
- [x] `implement.md` 明确当前状态以 `main-merge-readiness.md`、`final-integration-review.md` 和归档子任务为准。
- [x] 自审记录说明为什么不逐项勾选旧计划。
- [x] `src/testcase_generator/**` 无 diff。
