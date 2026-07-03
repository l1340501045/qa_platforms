# 阶段 A 技术设计：脏工作区与分支基线治理

## 设计原则

- 保护用户成果优先，宁可多列“需确认”，也不误删/误提交。
- 只读盘点优先，所有写操作必须是任务文档或用户确认后的 git 操作。
- 分类要能支撑后续分支策略，而不是只做文件清单。

## 数据来源

- `git status --short`
- `git diff --stat`
- `git branch --all --verbose --no-abbrev`
- `git log --oneline -10`
- 任务目录：
  - `.trellis/tasks/07-01-generation-convergence`
  - `.trellis/tasks/07-01-test-asset-module-tree-alignment`
  - `.trellis/tasks/07-02-testcase-oracle-guard-alignment`
  - `.trellis/tasks/07-04-qa-platform-ux-modernization`
- 运行产物目录：
  - `.audit/`
  - `logs/`
  - `.runtime/`
  - `scripts/backups/`

## 分类模型

| 分类 | 判断规则 | 建议 |
|---|---|---|
| 阶段性成果 | 与已审查/已计划的生成质量、模块树、Docker 基建、Trellis 基建相关 | 单独 commit 到 `feat/architecture-migration`，形成 UI/UX 前置 checkpoint |
| UI/UX 候选 | 只影响前端体验、非生成核心 API 展示契约 | 进入 UI/UX 分支 |
| 临时产物 | 日志、缓存、运行备份、审查输出、IDE 状态 | 不提交或补 `.gitignore` |
| 需用户决策 | 无法从代码判断归属，或可能是手工资产 | 报告中列明，不自动处理 |

## 输出文件建议

可写在父任务或本子任务下：

- `.trellis/tasks/07-04-ux-branch-hygiene/worktree-inventory.md`
- `.trellis/tasks/07-04-ux-branch-hygiene/commit-plan.md`

## 风险控制

- 不使用 `git add .`。
- 不使用 `git reset --hard`。
- 不使用 `git checkout -- <file>`。
- 对未跟踪目录只列摘要；大目录如 `.audit/` 不展开全部文件，避免报告噪声。
- 如果发现某个改动同时属于生成质量和 UI 展示，归入“需用户决策”。
- 不直接从 `main` 开 UI/UX 分支；先确认 `feat/architecture-migration` 干净基线，再从 checkpoint 拉分支。
