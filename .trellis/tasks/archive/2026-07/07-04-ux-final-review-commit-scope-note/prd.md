# UI最终审查提交口径修正

## Goal

修正父任务 `final-integration-review.md` 中 stale 的“最新收口提交”列表，避免后续 reviewer 误以为那组旧提交仍是当前 UI/UX 分支最新收口范围。

## Confirmed Facts

- `final-integration-review.md` 仍列出早期运行态验收、真实验收脚本、小规模 PRD、预检脚本等提交 hash。
- 之后又新增了证据台账、首次使用口径校准、预检/runbook 一致性、生成配置预检、预检测试、pytest 告警清理、父任务状态说明等提交。
- 手写“最新提交列表”会随每次提交迅速变旧，不适合作为长期权威来源。
- 用户澄清验收对象不是“新手 QA”，而是具备 QA 背景但第一次使用本平台的人；文档应避免把目标误写成测试基础教学。

## Requirements

- R1：移除或替换 stale 的固定“最新收口提交”列表。
- R2：明确具体提交应以 `git log --oneline` 为准。
- R3：保留分支、基线和 checkpoint 信息。
- R4：不得修改前端、API、worker 或 `src/testcase_generator/**`。
- R5：同步校准“首次使用平台的 QA”表述，避免被误读为“新手 QA”。

## Out of Scope

- 不重写完整 final review。
- 不改变合并判定。
- 不改运行代码。

## Acceptance Criteria

- [x] `final-integration-review.md` 不再把早期提交列表称为“最新收口提交”。
- [x] 文档说明具体提交以 `git log --oneline` 为准。
- [x] 自审记录说明为什么不继续手工维护 commit hash 列表。
- [x] 涉及首次使用平台验收的文档明确对象是“具备 QA 背景但首次使用平台的人”。
- [x] `src/testcase_generator/**` 无 diff。
