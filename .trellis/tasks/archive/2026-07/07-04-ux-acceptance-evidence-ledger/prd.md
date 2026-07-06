# UI验收证据台账

## Goal

补齐 UI/UX 合并前的证据台账，让周一真实跑批、首次使用平台 QA 演练和 `.audit` 审查结果能按同一张表回填、判断和复核。

这不是新增产品功能，也不是重新规划 UI；它只服务当前 `feat/qa-platform-ux-modernization` 分支的最终验收，避免“文档都写了”被误当成“证据已成立”。

## Confirmed Facts

- 创建本任务前，父任务 `07-04-qa-platform-ux-modernization` 已完成 17/17 个子任务，但仍缺三类硬证据：
  - 当前 HEAD 在公司 LLM 网关下跑出新的小规模真实批次；
  - 具备 QA 背景但首次使用平台的人完成任务演练；
  - 新批次导出 `.audit/<batch_id>/` 并完成质量/模块树审查。
- `docs/acceptance/runbook.md` 已说明操作步骤。
- `docs/acceptance/post-batch-report-template.md` 已说明跑完后贴给 Codex 的字段。
- 缺少一份面向 GO / NO-GO 的证据台账，把“待收集证据、执行命令、通过标准、当前状态、责任人”集中起来。

## Requirements

- R1：新增 `docs/acceptance/evidence-ledger.md`，列出合并前必须成立的证据项。
- R2：台账必须区分：
  - 已有本地证据；
  - 周一待补的外部证据；
  - 不能作为完成证据的间接材料。
- R3：台账必须覆盖：
  - 分支与主流程保护；
  - 运行环境；
  - 小规模真实批次；
  - 首次使用平台 QA 演练；
  - `.audit` 审查包；
  - GO / FIX THEN GO / NO-GO / SPLIT OUT 判定。
- R4：台账必须明确“给 Codex 的最小交付包”，让用户跑完后不用猜该贴哪些信息。
- R5：更新 `docs/acceptance/README.md` 和 `docs/acceptance/runbook.md`，让台账成为执行入口之一。
- R6：修改只限文档和 Trellis 任务记录；不能触碰前端、API、worker 或 `src/testcase_generator/**`。

## Out of Scope

- 不启动服务。
- 不跑真实 LLM 批次。
- 不做真人演练。
- 不修改自动化测试用例生成逻辑。
- 不新增前端页面。

## Acceptance Criteria

- [x] `docs/acceptance/evidence-ledger.md` 存在，并能单独指导用户判断哪些证据还缺。
- [x] `README.md` 的执行顺序引用 evidence ledger。
- [x] `runbook.md` 在跑批前/跑批后提示同步更新台账。
- [x] 自审记录说明该台账没有把流程复杂化到阻碍主流程，也没有把未完成证据包装成完成。
- [x] `src/testcase_generator/**` 无 diff。
