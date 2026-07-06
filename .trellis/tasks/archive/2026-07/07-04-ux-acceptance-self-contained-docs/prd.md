# UI 验收资料自包含化

## 目标

把真实跑批 runbook 和跑批后回填模板复制到 `docs/acceptance/`，让周一验收入口不依赖 `.trellis/tasks/archive/...` 路径。

## 背景

当前 `docs/acceptance/README.md` 已经是验收入口，但其中两个关键链接仍指向 Trellis 归档目录：

- 真实跑批 runbook
- 跑批后回填模板

这些路径对开发协作可追溯，但对实际执行验收不够直接。`docs/acceptance/` 应成为自包含入口目录。

## 要求

- 新增 `docs/acceptance/runbook.md`。
- 新增 `docs/acceptance/post-batch-report-template.md`。
- 更新 `docs/acceptance/README.md`，使用相对链接指向本目录文件。
- 保留 Trellis 归档文件作为历史记录，不删除、不搬迁。
- 补充自审说明。

## 不做

- 不改产品代码。
- 不改生成逻辑。
- 不跑真实批次。
- 不把 docs 版 runbook 写成新的事实来源；GO / NO-GO 仍以 main 合并准备清单为准。

## 验收标准

- `docs/acceptance/README.md`、`runbook.md`、`post-batch-report-template.md`、`ux-small-batch-prd.md` 组成自包含验收包。
- README 中关键链接都可以在 `docs/acceptance/` 内直接打开。
- 有 `review.md` 说明价值和重复文档的维护风险。
