# UI验收预检与Runbook一致性修正

## Goal

修正 UI/UX 真实验收资料中的可执行性问题，确保周一按 `docs/acceptance/runbook.md` 和 `scripts/ux_acceptance_preflight.py` 操作时不会因为文档口径过期或预检覆盖不全而误判。

## Confirmed Facts

- 当前最新提交已经超过运行态验收提交，`git log --oneline -5` 不再包含 `补齐当前HEAD运行态验收` 和 `归档当前HEAD运行态验收任务`。
- `docs/acceptance/runbook.md` 仍把这两条提交写进“最近提交包含”的期望，周一手工核对会误导。
- 当前验收目录已新增 `first-use-observation.md` 和 `evidence-ledger.md`，但 `scripts/ux_acceptance_preflight.py` 的 `ACCEPTANCE_FILES` 还只检查 4 个文件。

## Requirements

- R1：runbook 不应要求固定历史提交必须出现在最近 5 条提交里。
- R2：runbook 应改为检查当前分支、工作区干净、最近提交可追溯、生成核心无 diff。
- R3：预检脚本必须检查当前验收入口实际依赖的 6 个文件。
- R4：修改不能触碰前端、API、worker 或 `src/testcase_generator/**`。

## Out of Scope

- 不启动真实服务。
- 不跑真实 LLM 批次。
- 不调整 UI 页面。
- 不调整生成逻辑。

## Acceptance Criteria

- [x] `docs/acceptance/runbook.md` 不再包含会随提交数量变化而失效的固定最近提交要求。
- [x] `scripts/ux_acceptance_preflight.py` 检查 README、runbook、evidence ledger、观察表、回填模板、小规模 PRD。
- [x] `uv run python scripts/ux_acceptance_preflight.py --skip-runtime` 在当前干净工作区通过。
- [x] `python3 -m py_compile scripts/ux_acceptance_preflight.py` 通过。
- [x] 自审记录说明本次没有扩大到真实验收或生成核心。
