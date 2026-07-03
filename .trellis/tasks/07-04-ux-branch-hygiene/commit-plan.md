# 阶段 A 提交计划

## 总原则

- 禁止 `git add .`。
- 禁止把 `.audit/`、`logs/`、`.runtime/`、`scripts/backups/` 整体加入。
- 先提交 `feat/architecture-migration` 阶段成果，再创建 `checkpoint/architecture-migration-pre-ux`。
- UI/UX 大工程分支只能从 checkpoint 拉。
- 每个 commit 前后都执行 `git status --short`，确认只 staged 目标文件。

## 推荐提交顺序

### Commit 1：Trellis 项目流程与当前任务规划

建议 message：

```text
chore(trellis): add project workflow and ux modernization plans
```

建议文件：

- `AGENTS.md`
- `.agents/skills/trellis-before-dev/SKILL.md`
- `.agents/skills/trellis-brainstorm/SKILL.md`
- `.agents/skills/trellis-break-loop/SKILL.md`
- `.agents/skills/trellis-channel/**`
- `.agents/skills/trellis-check/SKILL.md`
- `.agents/skills/trellis-continue/SKILL.md`
- `.agents/skills/trellis-finish-work/SKILL.md`
- `.agents/skills/trellis-meta/**`
- `.agents/skills/trellis-session-insight/**`
- `.agents/skills/trellis-spec-bootstrap/**`
- `.agents/skills/trellis-start/SKILL.md`
- `.agents/skills/trellis-update-spec/SKILL.md`
- `.trellis/.gitignore`
- `.trellis/.template-hashes.json`
- `.trellis/.version`
- `.trellis/agents/**`
- `.trellis/config.yaml`
- `.trellis/scripts/**`
- `.trellis/spec/**`
- `.trellis/tasks/06-30-verdict-consistency/**`
- `.trellis/tasks/07-01-generation-convergence/**`
- `.trellis/tasks/07-01-test-asset-module-tree-alignment/**`
- `.trellis/tasks/07-02-testcase-oracle-guard-alignment/**`
- `.trellis/tasks/07-04-qa-platform-ux-modernization/**`
- `.trellis/tasks/07-04-ux-branch-hygiene/**`
- `.trellis/tasks/07-04-ux-critical-flow-safety-fixes/**`
- `.trellis/tasks/07-04-ux-case-asset-browser/**`
- `.trellis/tasks/07-04-ux-information-architecture-visual/**`
- `.trellis/tasks/07-04-ux-runtime-verification-release/**`
- `.trellis/workflow.md`

暂不建议加入：

- `.trellis/workspace/**`
- `.trellis/.developer`
- `.trellis/.runtime/**`
- `.trellis/**/*.DS_Store`

验证：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 ./.trellis/scripts/task.py validate 07-04-ux-branch-hygiene
PYTHONDONTWRITEBYTECODE=1 python3 ./.trellis/scripts/task.py list --mine
```

### Commit 2：Docker 基础设施与本机最新代码启动路径

建议 message：

```text
chore(infra): add docker infrastructure runbook
```

建议文件：

- `.env.example`
- `.gitignore`
- `docker-compose.infra.yml`
- `docs/run-infra-docker.md`
- `scripts/start_platform_services.sh`

本阶段已补充 `.gitignore` 规则，需随本 commit 提交：

```gitignore
.audit/
.runtime/
logs/*.pid
scripts/backups/
.claude/
.codex/
.cursor/
.trellis/workspace/
```

验证：

```bash
docker compose -f docker-compose.infra.yml config
```

### Commit 3：特定设计工具原型回灌（已废弃，不再保留）

当前结论：

- 用户已明确不要该特定设计工具相关方案和代码。
- 原先已提交过的专属 tooling 已用后续清理提交移除：
  - `b91be2b`：移除专属原型 tooling
  - `c3cd932`：移除残留计划文案
- 后续 checkpoint 不包含该设计工具的识别、抓取、回灌或相关方案文档。

### Commit 4：生成运行配置与默认质量开关

建议 message：

```text
feat(testcase): add runtime generation quality config
```

建议文件：

- `src/platform_api/core/settings.py`
- `src/testcase_generator/pipeline/config.py`
- `web/src/services/batchApi.ts`
- `tests/testcase_generator/test_pipeline_generation_config.py`

已处理：

- `p0_quota_enabled` 改回 `False`。
- 理由：这是用户此前指定的真实跑批配置；保留 `p0_quota` 能力但不默认启用。

验证：

```bash
uv run pytest tests/testcase_generator/test_pipeline_generation_config.py
```

### Commit 5：Oracle Guard 与核验问题类型

建议 message：

```text
feat(verify): add oracle guards and review issue typing
```

建议文件：

- `src/testcase_generator/stages/verify/guards.py`
- `src/testcase_generator/stages/verify/node.py`
- `src/testcase_generator/stages/verify/rubric.py`
- `src/testcase_generator/stages/verify/verifier.py`
- `src/testcase_generator/schemas/test_case.py`
- `tests/testcase_generator/test_oracle_guards.py`
- `tests/testcase_generator/test_conflict_entity_gate.py`
- `tests/testcase_generator/test_verdict_consistency.py`
- `tests/testcase_generator/test_verify_cross_section.py`
- `tests/testcase_generator/test_apply_clarification.py`

验证：

```bash
uv run pytest tests/testcase_generator/test_oracle_guards.py tests/testcase_generator/test_conflict_entity_gate.py tests/testcase_generator/test_verdict_consistency.py tests/testcase_generator/test_verify_cross_section.py tests/testcase_generator/test_apply_clarification.py
```

### Commit 6：生成侧收敛、边界覆盖与优先级校准

建议 message：

```text
feat(write-cases): add convergence cap and priority calibration
```

建议文件：

- `src/testcase_generator/stages/write_cases/convergence.py`
- `src/testcase_generator/stages/write_cases/length_check.py`
- `src/testcase_generator/stages/write_cases/node.py`
- `src/testcase_generator/stages/write_cases/priority_calibration.py`
- `src/testcase_generator/schemas/test_point.py`
- `src/testcase_generator/stages/test_points/node.py`
- `src/testcase_generator/stages/test_points/critical_flow.py`
- `src/testcase_generator/services/critical_flows.py`
- `src/testcase_generator/services/assertion_quality.py`
- `src/testcase_generator/services/prd_facts.py`
- `scripts/convergence_offline_eval.py`
- `tests/testcase_generator/test_generation_convergence.py`
- `tests/testcase_generator/test_case_priority_calibration.py`
- `tests/testcase_generator/test_critical_flow_anchors.py`
- `tests/testcase_generator/test_assertion_quality.py`
- `tests/testcase_generator/test_prd_facts.py`
- `tests/testcase_generator/test_priority_risk.py`
- `tests/testcase_generator/test_test_points_batching.py`
- `tests/testcase_generator/test_write_cases_cheat_sheet.py`
- `tests/testcase_generator/integration/test_full_pipeline.py`
- `tests/testcase_generator/integration/test_real_graph.py`

验证：

```bash
uv run pytest tests/testcase_generator/test_generation_convergence.py tests/testcase_generator/test_case_priority_calibration.py tests/testcase_generator/test_critical_flow_anchors.py tests/testcase_generator/test_assertion_quality.py tests/testcase_generator/test_prd_facts.py
```

### Commit 7：模块树分类与用例资产浏览契约

建议 message：

```text
feat(case-tree): align case assets to business module tree
```

建议文件：

- `src/testcase_generator/services/module_tree_classifier.py`
- `src/platform_api/api/v1/systems.py`
- `src/platform_api/repositories/testcase_repo.py`
- `src/platform_api/services/case_tree_service.py`
- `tests/platform_api/test_case_tree_service.py`
- `tests/platform_api/test_case_tree_integration.py`
- `tests/testcase_generator/test_audit_export_module_tree.py`
- `scripts/audit_export.py`
- `scripts/audit_global.py`
- `web/src/components/CaseTreeReview.tsx`
- `web/src/pages/CaseLibrary/index.tsx`
- `web/src/pages/Workbench/index.tsx`
- `web/src/types/index.ts`

验证：

```bash
uv run pytest tests/platform_api/test_case_tree_service.py tests/platform_api/test_case_tree_integration.py tests/testcase_generator/test_audit_export_module_tree.py
```

前端验证：

```bash
cd web
npm run lint
npm run typecheck
npm run build
```

### Commit 8：质量路线图与阶段文档整理

建议 message：

```text
docs(quality): align roadmap and architecture notes
```

建议文件：

- `docs/2026-06-30-semantic-dedup-review-notes.md`
- `docs/testcase-generation-best-practice-roadmap.md`
- `docs/plans/2026-06-23-feature-segmentation-llm-plan.md`
- `docs/plans/2026-06-25-cot-explicit-write-cases-plan.md`
- `docs/plans/2026-06-26-clarification-resolves-conflict-plan.md`
- `docs/plans/2026-06-26-grounded-provenance-cross-section-fallback.md`
- `docs/plans/2026-06-29-quality-patches-plan.md`
- `docs/plans/2026-06-29-structural-coverage-plan.md`
- `docs/plans/2026-06-30-generation-convergence-plan.md`
- `docs/plans/2026-06-30-verify-conflict-persistence-plan.md`
- `docs/spec/2026-06-23-retrieval-golden-set-design.md`
- `docs/spec/2026-06-25-cot-explicit-write-cases-design.md`
- `docs/spec/2026-06-26-clarification-resolves-conflict-design.md`
- `docs/spec/2026-06-26-gate-conflict-clarification-ux-design.md`
- `docs/spec/2026-06-29-quality-patches-design.md`
- `docs/spec/2026-06-30-conflict-entity-gate-design.md`
- `docs/spec/2026-06-30-generation-convergence-design.md`
- `docs/spec/2026-06-30-provenance-quote-cache-design.md`
- `docs/spec/2026-06-30-semantic-dedup-design.md`

同时处理：

- `docs/plans/testcase-generation-best-practice-roadmap.md` 删除。

验证：

```bash
rg -n "TODO|未完成|待补|main 分支开发" docs .trellis/tasks/07-04-qa-platform-ux-modernization .trellis/tasks/07-04-ux-branch-hygiene
```

## 暂不提交清单

以下路径不进入任何 commit：

- `.audit/**`
- `.runtime/**`
- `logs/*.pid`
- `logs/*.log`
- `scripts/backups/**`
- `.trellis/.developer`
- `.trellis/.runtime/**`
- `.trellis/workspace/**`
- `.claude/**`
- `.codex/**`
- `.cursor/**`
- `**/.DS_Store`

以下路径需要用户决策后再提交：

- `.audit/*-module-tree-calibration/**` 是否转为正式 fixture

## Checkpoint 创建条件

只有满足下面条件后，才创建：

```text
checkpoint/architecture-migration-pre-ux
```

条件：

- 上述 commit 中用户确认要保留的阶段成果已提交。
- `.audit/`、`scripts/backups/`、`logs/`、`.runtime/` 未进入 commit。
- `p0_quota_enabled` 默认值已改为 `False` 并完成验证。
- `git status --short` 中只剩用户明确允许保留的本地产物，或工作区干净。
- 关键测试通过，至少包括：
  - `uv run pytest tests/platform_api/test_case_tree_service.py tests/platform_api/test_case_tree_integration.py`
  - `uv run pytest tests/testcase_generator/test_generation_convergence.py tests/testcase_generator/test_oracle_guards.py`
  - `cd web && npm run build`

## 后续分支命令草案

仅在用户确认 commit-plan 并完成提交后执行：

```bash
git switch feat/architecture-migration
git status --short
git branch checkpoint/architecture-migration-pre-ux
git switch -c feat/qa-platform-ux-modernization
```

如 `git status --short` 仍有未识别业务改动，不创建 UI/UX 分支。
