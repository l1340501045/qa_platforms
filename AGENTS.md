<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## Git 工作流约定（保护阶段性成果）

本项目默认按“先保护成果，再做大改动”的方式使用 git。用户不需要判断技术细节，AI 需要主动把风险翻译成分支、提交、合并动作。

### 1. 什么时候开新分支

- **要开新分支**：UI/UX 重构、架构迁移、生成链路策略调整、数据库/接口契约变化、会影响主流程的大改动。
- **要开新分支**：当前分支已有阶段性成果，但下一步是不确定探索，或可能需要整体回退。
- **可以不开新分支**：只改文档、只补小测试、只修明确小 bug，且改动范围很小、可直接验证。
- **禁止直接在 `main` 做大改动**：`main` 应保持可部署、可交付；大工程先从当前稳定成果分支或 checkpoint 分支拉出。
- 开分支前必须先看 `git status --short`，确认哪些改动属于当前成果，哪些不该带到新分支。

### 2. 什么时候提交 commit

- 一个 commit 应表达一个清晰成果，例如“修复模块树审查导出”“补充 JSON 容错测试”“移除废弃原型接入”。
- 能独立验证的阶段性成果应及时 commit，避免几小时工作混在一个巨大脏区里。
- 提交前必须确认：
  - 不使用 `git add .`，只精确 add 本次提交需要的文件。
  - `git diff --cached --name-status` 与本次提交目的一致。
  - 能跑的测试/检查已经跑过；不能跑要说明原因。
- commit message **使用中文**，可以保留常见前缀，例如：
  - `feat(模块): 中文说明`
  - `fix(模块): 中文说明`
  - `test(模块): 中文说明`
  - `docs(模块): 中文说明`
  - `chore(模块): 中文说明`

### 3. 什么时候合并

- 合并前必须有清晰结论：这个分支解决了什么问题、验证了什么、还有什么风险。
- 合并到 `main` 前必须做一次 review，重点看：
  - 主流程“完整生成测试用例”是否仍然通。
  - 是否混入运行产物、审查输出、缓存、临时文件。
  - 是否带入已废弃功能或用户明确不要的功能。
  - 新增配置是否有默认值、文档和可回退路径。
- 大工程优先使用“阶段分支 → checkpoint → UI/UX 或功能分支 → review → main”的路径，不把未确认探索直接压进 `main`。

### 4. 默认保护规则

- 不回滚用户或其他 agent 的改动，除非用户明确要求。
- 不删除未识别文件，先分类说明。
- 遇到脏工作区时，先盘点并分组，再决定提交、搁置还是开新分支。
- 如果用户说“保留阶段性成果”，AI 应优先通过小步 commit 和 checkpoint 分支保护，而不是把所有改动留在工作区。
