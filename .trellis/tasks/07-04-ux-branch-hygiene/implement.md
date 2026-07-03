# 阶段 A 执行计划

## 执行顺序

1. 基线确认
   - `git branch --show-current`
   - `git branch --all --verbose --no-abbrev`
   - `git log --oneline -10`
   - `python3 ./.trellis/scripts/task.py list --mine`

2. 脏区盘点
   - `git status --short`
   - `git diff --stat`
   - 对未跟踪大目录用 `find <dir> -maxdepth 2 -type f | head` 或 `du -sh` 摘要，不全量刷屏。

3. 分类报告
   - 写 `worktree-inventory.md`。
   - 分类必须覆盖所有 dirty top-level path。
   - 对每类写明建议动作和风险。

4. 提交计划
   - 写 `commit-plan.md`。
   - 每个 commit 包含 message、文件列表、原因。
   - 明确哪些文件不纳入任何 commit。

5. 等用户确认
   - 用户确认前不执行 `git add` 或 `git commit`。
   - 如果用户要求执行，按 commit-plan 精确 add 文件。

6. 批判性 review
   - 审查 `worktree-inventory.md` 是否覆盖所有 dirty top-level path。
   - 审查 `commit-plan.md` 是否存在把无关运行产物、缓存、审查输出误提交的风险。
   - 审查是否遗漏当前阶段性成果，导致后续 `feat/architecture-migration` checkpoint 不完整。
   - 审查是否仍有“需要用户决策”的项；有的话不得假装阶段 A 完成。

## 建议分类初稿

可先按当前观察做初稿，之后用命令核实：

- 生成质量/模块树成果：
  - `src/testcase_generator/**`
  - `tests/testcase_generator/**`
  - `scripts/convergence_offline_eval.py`
  - `scripts/audit_export.py`
  - `scripts/audit_global.py`
  - 相关 docs/spec/plans
- 平台 API/前端阶段成果：
  - `src/platform_api/**`
  - `tests/platform_api/**`
  - `web/src/**`
- Docker/运行基建：
  - `docker-compose.infra.yml`
  - `docs/run-infra-docker.md`
  - `scripts/start_platform_services.sh`
  - `.env.example`
  - `.gitignore`
- Trellis/agent 基建：
  - `.trellis/**`
  - `.agents/**`
  - `AGENTS.md`
- 不应直接提交的候选：
  - `.audit/**`，除非明确作为审查工具/样例资产提交
  - `logs/**`
  - `.runtime/**`
  - `.claude/**`、`.codex/**`、`.cursor/**`，除非确认为项目配置
  - `scripts/backups/**`

## 验证

- `git status --short` 与报告覆盖一致。
- `python3 ./.trellis/scripts/task.py validate 07-04-ux-branch-hygiene` 通过。
- 父任务仍显示 `[0/5 done]`，本任务仍是 planning，除非用户批准进入实施。

## Codex Inline 执行约束

```text
Active task: .trellis/tasks/07-04-ux-branch-hygiene

先读取本任务 prd.md/design.md/implement.md，再读取父任务 .trellis/tasks/07-04-qa-platform-ux-modernization/prd.md/design.md/implement.md。
只做脏工作区与分支治理盘点，不改业务代码。
不要 git add .，不要 commit，除非我明确确认 commit-plan。
不要回滚或删除未识别改动。
不要直接从 main 开 UI/UX 分支；先固化 feat/architecture-migration，再从 checkpoint 拉新分支。
输出 worktree-inventory.md、commit-plan.md 和 review.md。
```
