# UI 验收入口说明

## 目标

为周一 UI/UX 真实跑批验收补充一个入口说明页，让执行者从 `docs/acceptance/README.md` 就能找到：

- 小规模验收 PRD 样例。
- 真实跑批 runbook。
- 跑批后回填模板。
- GO / NO-GO 判断位置。

## 背景

当前关键材料分布在：

- `docs/acceptance/ux-small-batch-prd.md`
- `.trellis/tasks/archive/2026-07/07-04-ux-real-batch-first-use-acceptance/acceptance-runbook.md`
- `.trellis/tasks/archive/2026-07/07-04-ux-real-batch-first-use-acceptance/post-batch-report-template.md`
- `.trellis/tasks/07-04-qa-platform-ux-modernization/main-merge-readiness.md`

这些路径对开发者清楚，但对周一直接执行验收的人不够友好。

## 要求

- 新增 `docs/acceptance/README.md`。
- README 必须用业务语言说明执行顺序。
- README 必须链接到样例 PRD、runbook、回填模板和 main 合并准备清单。
- README 必须强调父任务仍未归档，等待真实小批次和首次上手验收结果。

## 不做

- 不改产品代码。
- 不改生成逻辑。
- 不新增脚本。
- 不重复 runbook 的全部细节。

## 验收标准

- `docs/acceptance/README.md` 存在。
- README 中能一眼看到周一执行顺序。
- README 中能找到所有关键链接。
- 有 `review.md` 批判性说明该入口页的价值和局限。
