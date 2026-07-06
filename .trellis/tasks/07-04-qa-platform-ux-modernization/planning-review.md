# QA 平台 UI/UX 重构规划产物批判性 Review

## Review 时间点

规划阶段，尚未 `task.py start`，尚未进入实现。

## 已做对的地方

- 目标没有被缩小成“修几个前端 bug”：父任务仍覆盖 QA 工作流、信息架构、视觉体验、主流程安全和行业最佳实践。
- 已把任务拆成 A-E 五个可独立验收阶段：
  - A 脏工作区与分支基线治理。
  - B 主流程安全 UX 快修。
  - C 用例资产树与共享浏览器。
  - D 信息架构与视觉重构。
  - E 运行态验收与发布回归。
- 子任务已全部挂到父任务下，并且 base branch 已统一为 `feat/architecture-migration`。
- 已修正执行主体：后续由 Codex inline 主会话规划并执行，不交给 Claude Code，不派发 implement/check 子代理。
- 已把“每次 Trellis 流程产物都要批判性 review”写回父任务 PRD/design/implement。
- 阶段 A 有完整 `prd.md/design.md/implement.md`，能直接作为前置门禁执行。
- 阶段 B 有完整 `prd.md/design.md/implement.md`，范围被约束在真实 bug 和低风险 UX 修复，没有提前吞掉 C/D 的大重构。

## 还不够好的地方

- C/D/E 目前只有 PRD，还不能启动实现；它们必须在对应阶段开始前补 `design.md` 和 `implement.md`，否则容易变成模糊大改。
- 父任务虽然有行业调研，但还没有真正用 Playwright/浏览器跑一次当前页面；这是因为当前 `3000/8000` 服务未启动。阶段 E 前必须补运行态证据。
- 阶段 A 仍未实际产出 `worktree-inventory.md` 和 `commit-plan.md`，因此目前还不能创建 `feat/architecture-migration` checkpoint 和 UI/UX 重构分支。
- 当前仓库还有其他 Trellis 任务处于 `in_progress/planning`，这些阶段性成果和 UI/UX 重构的边界尚未被用户确认。
- 父任务仍处于 planning；如果现在直接改业务代码，会违反 Trellis 流程。

## 偏离风险

- 最大风险不是 UI 设计，而是脏工作区：如果跳过阶段 A，UI/UX 分支会混入生成质量、模块树、Docker、Trellis 基建和运行产物，后续 review 无法判断问题归因。
- 阶段 B 的“树默认折叠/滚动”很容易被做成共享组件重构；必须克制，只做低风险修复，把递归模块树留给阶段 C。
- 阶段 D 的视觉重构如果先做，会掩盖系统统计、上传类型、树行为这些真实业务问题；所以 D 必须排在 B/C 后面。
- “不改变后端所有逻辑”需要更精确理解：阶段 B 会改平台 API 展示契约和校验，但不改 `src/testcase_generator` 生成核心逻辑。这一点需要在执行报告里反复说明。

## 分支策略修正后的自审

用户纠正“不能直接在 main 分支开发”是正确的。原规划把 `main` 写成直接开发基线，风险偏高：当前 `feat/architecture-migration` 已经承载大量阶段性成果，如果绕过它从 `main` 拉 UI/UX 分支，会丢失成果上下文；如果直接把大改压到 `main`，又会破坏用户想要的纯净主干。

修正后的最低风险方案是 stacked workflow：

```text
main
  └─ feat/architecture-migration
       └─ checkpoint/architecture-migration-pre-ux
            └─ feat/qa-platform-ux-modernization
```

这个方案的优点是：

- 保留当前 `feat/architecture-migration` 阶段性成果，不把它当成可丢弃临时分支。
- checkpoint 提供清晰回退锚点，UI/UX 大改失败时可以直接废弃 `feat/qa-platform-ux-modernization`。
- `main` 仍保持最终集成目标，不承担规划/试错过程中的脏改动。

这个方案仍有两个代价：

- 阶段 A 必须认真做盘点和 commit-plan，不能跳过；否则 checkpoint 本身也会不干净。
- 后续合入 `main` 时需要单独 review `feat/architecture-migration` 与 UI/UX 分支的累计差异，不能默认整包合并。

## 是否可以进入实现

当前不建议直接进入整体 UI/UX 实现。

建议下一步只启动阶段 A：`.trellis/tasks/07-04-ux-branch-hygiene`。

阶段 A 的目标不是写代码，而是产出：

- `worktree-inventory.md`
- `commit-plan.md`
- `review.md`

只有阶段 A review 通过，才能判断：

- 哪些现有成果固化到 `feat/architecture-migration` checkpoint。
- 哪些内容留给 UI/UX 分支。
- 哪些运行/审查产物不提交。
- UI/UX 分支从哪个 checkpoint 创建；最终何时、以什么方式再合入 `main`。

## Review 结论

规划方向正确，但未达到“全任务可开工”。达到可开工的最小下一步是阶段 A，而不是阶段 B/C/D。

如果用户批准进入实施，应执行：

```bash
python3 ./.trellis/scripts/task.py start 07-04-ux-branch-hygiene
```

然后按阶段 A 的 `implement.md` 做只读盘点和报告，不改业务代码。
