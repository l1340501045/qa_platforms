# 阶段 A：脏工作区与分支基线治理 PRD

## 目标

在任何 UI/UX 重构开始前，把当前巨大脏工作区和分支状态梳理清楚，保护已有阶段性成果，并为后续 `feat/qa-platform-ux-modernization` 建立干净基线。

## 背景

父任务：`.trellis/tasks/07-04-qa-platform-ux-modernization`

当前事实：

- 当前分支为 `feat/architecture-migration`。
- 父任务本次开发基线为 `feat/architecture-migration`；`main` 只作为最终纯净集成目标。
- 工作区存在大量未提交改动，覆盖生成器、平台 API、前端、Docker/Trellis 基建、审查脚本、日志和审查产物。
- 用户明确要求：当前阶段性成果要保留；这么大的 UI/UX 重构必须新拉分支；最终 main 应是纯净、别人可部署使用的项目。

## 范围

### 必做

- 只做盘点、分类、提交计划、分支策略，不做 UI/UX 代码实现。
- 读取当前 dirty files、分支、最近提交和未跟踪目录。
- 将 dirty files 分类为：
  - `阶段性成果，应保留/提交`
  - `UI/UX 重构候选，应进入后续分支`
  - `运行/审查/缓存产物，不应提交`
  - `需用户决策`
- 对每组给出原因、风险、建议目标分支或处理方式。
- 明确 `.audit/`、`logs/`、`.runtime/`、临时 IDE/agent 目录是否进入仓库。
- 给出 batched commit 计划，但不执行 commit，除非用户明确确认。
- 不允许 `git add .`，不允许回滚用户或其他代理留下的改动。
- UI/UX 重构分支必须从 `feat/architecture-migration` 的用户确认干净 checkpoint 创建，建议 checkpoint 为 `checkpoint/architecture-migration-pre-ux`。
- `main` 不作为本次 UI/UX 直接开发分支；最终合入 `main` 需要单独 review。

### 不做

- 不改业务代码。
- 不启动真实批次。
- 不改 LLM/pipeline/生成器逻辑。
- 不删除未识别文件。

## 验收标准

- 产出一份 `worktree-inventory.md` 或等价报告，列出所有 dirty path 的分类和建议。
- 产出一份 `commit-plan.md` 或等价提交计划，明确每个 commit 的文件列表和 commit message。
- 用户能基于报告回答：哪些固化到 `feat/architecture-migration` checkpoint、哪些留待 UI/UX、哪些不提交、最终哪些再进 `main`。
- 在用户确认前，仓库没有发生 add/commit/revert。
- 父任务仍处于 planning，后续子任务不得绕过阶段 A。

## 依赖

无前置技术依赖；这是所有后续子任务的前置门禁。

## 完成后下一步

用户确认提交/分支策略后，才能启动阶段 B：`.trellis/tasks/07-04-ux-critical-flow-safety-fixes`。
