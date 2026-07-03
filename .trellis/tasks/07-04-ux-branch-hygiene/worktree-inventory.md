# 阶段 A 脏工作区盘点

## 结论摘要

当前工作区不能直接拉 `feat/qa-platform-ux-modernization`。它混合了至少 6 类成果/产物：

- 生成质量与模块树阶段成果：应保护，但需要分组提交和验证。
- 平台 API/前端资产树展示契约：不是纯 UI 美化，属于模块树/用例资产成果的一部分。
- Docker/本机运行基础设施：可保留，应单独提交。
- Trellis 项目流程资产：可保留，但工具平台目录需要筛选。
- 审查导出、日志、pid、备份：不应进入 checkpoint。
- 已处理 P0 配额默认值：按用户此前真实跑批配置，`p0_quota_enabled` 默认改为 `False`。
- 已按保守策略处理平台本地配置：`.claude/.codex/.cursor` 不进入 checkpoint，只保留 `.agents` 与 `.trellis` 的项目通用流程资产。
- 仍需后续单独决策：`.audit` 校准包是否转成正式 fixture。

推荐策略：

```text
feat/architecture-migration
  1. 先提交可审阶段成果和基础设施
  2. 排除运行/审查/备份产物
  3. 建 checkpoint/architecture-migration-pre-ux
  4. 从 checkpoint 拉 feat/qa-platform-ux-modernization
```

## 证据快照

- 当前分支：`feat/architecture-migration`
- 当前任务：`.trellis/tasks/07-04-ux-branch-hygiene`
- 当前任务状态：`in_progress`
- `git status --short`：约 117 项未提交变化
- `git diff --stat`：41 个已跟踪文件变更，约 `1817 insertions(+), 731 deletions(-)`
- 大目录体量：
- `.audit`：72M，已通过本阶段 `.gitignore` 治理从 `git status` 中排除
  - `scripts/backups`：100M
  - `.trellis`：1.2M
  - `.agents`：300K
- `.claude`：412K，已按保守策略作为本地工具状态 ignored
- `.cursor`：388K，已按保守策略作为本地工具状态 ignored
- `.codex`：68K，已按保守策略作为本地工具状态 ignored

## Top-level 覆盖清单

| Top-level path | 当前状态 | 分类 | 建议 |
|---|---:|---|---|
| `.env.example` | modified | Docker/运行基建 | 保留，随 infra commit 提交 |
| `.gitignore` | modified | 仓库治理 | 保留，并建议补充运行产物 ignore |
| `docs/` | modified/deleted/untracked | 阶段性成果文档 | 分组提交，不和 UI/UX 大改混在一起 |
| `src/` | modified/untracked | 生成质量/模块树/API 契约 | 保留，但需按功能分组验证 |
| `tests/` | modified/untracked | 阶段成果测试 | 随对应源码提交 |
| `web/` | modified | 用例资产树展示契约 | 多数属于模块树/质量资产展示，不是 UI/UX 大重构 |
| `scripts/` | untracked | 审查/迁移/运行工具 + 备份 | 工具脚本可保留，`scripts/backups` 不提交 |
| `docker-compose.infra.yml` | untracked | Docker 基础设施 | 保留，随 infra commit 提交 |
| `AGENTS.md` | untracked | 项目协作规范 | 保留，随 Trellis/agent commit 提交 |
| `.trellis/` | untracked | Trellis 项目流程与任务 | 保留核心流程/任务；排除 runtime/local 状态 |
| `.agents/` | untracked | Trellis skills | 倾向保留 |
| `.claude/` | 初始 untracked；现已 ignored | Claude 平台配置 | 默认不进 checkpoint |
| `.codex/` | 初始 untracked；现已 ignored | Codex 平台配置 | 默认不进 checkpoint |
| `.cursor/` | 初始 untracked；现已 ignored | Cursor 平台配置 | 默认不进 checkpoint |
| `.audit/` | 初始 untracked, 72M；现已 ignored | 审查导出/校准产物 | 不要整目录提交；如需样例，转正式 fixture |
| `.runtime/` | 初始 untracked；现已 ignored | 运行 pid/log | 不提交 |
| `logs/` | 初始 pid untracked；现 pid 已 ignored | 运行日志/pid | 不提交 pid；日志已被 `*.log` 忽略 |

## 应保留的阶段性成果

### 1. 生成质量与收敛策略

相关路径：

- `src/testcase_generator/pipeline/config.py`
- `src/testcase_generator/schemas/test_case.py`
- `src/testcase_generator/schemas/test_point.py`
- `src/testcase_generator/stages/comprehend/node.py`
- `src/testcase_generator/stages/dedup/node.py`
- `src/testcase_generator/stages/review/backfill_node.py`
- `src/testcase_generator/stages/review/node.py`
- `src/testcase_generator/stages/rule_extract/node.py`
- `src/testcase_generator/stages/test_points/node.py`
- `src/testcase_generator/stages/test_points/critical_flow.py`
- `src/testcase_generator/stages/verify/node.py`
- `src/testcase_generator/stages/verify/rubric.py`
- `src/testcase_generator/stages/verify/verifier.py`
- `src/testcase_generator/stages/verify/guards.py`
- `src/testcase_generator/stages/write_cases/convergence.py`
- `src/testcase_generator/stages/write_cases/length_check.py`
- `src/testcase_generator/stages/write_cases/node.py`
- `src/testcase_generator/stages/write_cases/priority_calibration.py`
- `src/testcase_generator/services/assertion_quality.py`
- `src/testcase_generator/services/critical_flows.py`
- `src/testcase_generator/services/prd_facts.py`

相关测试：

- `tests/testcase_generator/test_assertion_quality.py`
- `tests/testcase_generator/test_case_priority_calibration.py`
- `tests/testcase_generator/test_critical_flow_anchors.py`
- `tests/testcase_generator/test_generation_convergence.py`
- `tests/testcase_generator/test_oracle_guards.py`
- `tests/testcase_generator/test_pipeline_generation_config.py`
- `tests/testcase_generator/test_prd_facts.py`
- 以及已有修改的 `tests/testcase_generator/test_*.py`、integration 测试。

判断：

- 这是当前 `feat/architecture-migration` 的核心阶段成果，应先固化。
- 已消除一个配置风险：`settings.py`、`pipeline/config.py`、`web/src/services/batchApi.ts` 已按用户此前指定的真实跑批配置改为 `p0_quota_enabled=False`。

建议：

- 保留源码和测试。
- 提交前跑非集成生成器测试。
- 保留 P0 配额能力，但默认/前端触发配置不启用；后续如要治理 P0 泛滥，应单独开关评估。

### 2. 模块树与用例资产组织

相关路径：

- `src/testcase_generator/services/module_tree_classifier.py`
- `src/platform_api/services/case_tree_service.py`
- `src/platform_api/repositories/testcase_repo.py`
- `src/platform_api/api/v1/systems.py`
- `tests/platform_api/test_case_tree_service.py`
- `tests/platform_api/test_case_tree_integration.py`
- `tests/testcase_generator/test_audit_export_module_tree.py`
- `scripts/audit_export.py`
- `scripts/audit_global.py`
- `web/src/components/CaseTreeReview.tsx`
- `web/src/pages/CaseLibrary/index.tsx`
- `web/src/pages/Workbench/index.tsx`
- `web/src/types/index.ts`

判断：

- 这些变更不是“新版 UI/UX 重构”，而是把用例资产从 `source_section` 平铺转向“业务模块 -> 分支”的阶段成果。
- 它与 UI/UX 父任务相关，但应作为 `feat/architecture-migration` 的前置基线，而不是留到 UI 分支里才出现。

风险：

- 当前前端仍有 `CaseTreeReview` 与 `CaseLibrary` 重复实现，后续 UI/UX 阶段 C 还需要抽共享组件。
- 当前后端返回 `branches[]` 仍是一层列表，只是 `branch_path` 已有数组；后续阶段 C 还需前端递归归一化。

建议：

- 保留并单独提交。
- 提交前至少跑 `tests/platform_api/test_case_tree_service.py` 和相关前端 build/typecheck。

### 3. MasterGo 存量回灌

相关路径：

- `src/testcase_generator/stages/parse/mastergo_fetch.py`
- `scripts/mastergo_backfill.py`
- `tests/testcase_generator/test_mastergo_backfill.py`
- `docs/plans/2026-06-23-mastergo-prototype-source-plan.md`
- `docs/spec/2026-06-23-mastergo-prototype-source-design.md`
- `.gitignore` 中 `.mastergo_session/` 和 `backup_*.content.md`

判断：

- 这是存量 PRD/原型规格回灌工具，不属于 UI/UX 重构。
- 但对生成质量和历史资料补全有价值，应作为独立阶段成果提交。

建议：

- 单独提交。
- `.mastergo_session/` 绝不能提交，当前 `.gitignore` 已覆盖。

### 4. Docker/本机运行基建

相关路径：

- `.env.example`
- `docker-compose.infra.yml`
- `docs/run-infra-docker.md`
- `scripts/start_platform_services.sh`
- `.gitignore`

判断：

- 这部分解决“基础设施进 Docker、API/worker/frontend 用最新本地代码跑”的问题。
- 应保留，因为后续 UI/UX 浏览器验收依赖可复现启动方式。

建议：

- 单独提交。
- 本阶段已在 `.gitignore` 补充：
  - `.runtime/`
  - `logs/*.pid`
  - `.audit/`
  - `scripts/backups/`
  - `.claude/settings.local.json`
  - `.DS_Store` 已有全局规则，但未跟踪目录整体进入时仍要注意不 add。
- 本阶段已补上述运行产物/本地配置 ignore 规则；后续应随 infra commit 提交。

### 5. Trellis/agent 项目流程

相关路径：

- `AGENTS.md`
- `.agents/skills/trellis-*/**`
- `.trellis/.gitignore`
- `.trellis/.template-hashes.json`
- `.trellis/.version`
- `.trellis/agents/**`
- `.trellis/config.yaml`
- `.trellis/scripts/**`
- `.trellis/spec/**`
- `.trellis/tasks/**`
- `.trellis/workflow.md`

判断：

- 当前项目已经依赖 Trellis 组织需求、规划、执行和 review，核心流程资产应该保留。
- `.trellis/workspace/**` 更像个人/会话工作区，不一定适合提交到干净主干。

建议：

- 保留 `.trellis` 核心脚本、spec、tasks、workflow。
- `.trellis/workspace/**` 已按默认策略忽略，不进 checkpoint；任务文档已经在 `.trellis/tasks` 中。

## 不应直接提交的产物

### 1. `.audit/`

现状：

- 目录体量约 72M。
- 包含多个 batch 的审查导出、REPORT、modules、findings、calibration 包。

建议：

- 不要整目录提交。
- 若后续需要保留“Cursor 多智能体审查方式”的样例，只提炼为小型 fixture 或文档，例如：
  - `tests/fixtures/audit/<sample>/...`
  - `docs/audit-review-workflow.md`
- `.audit/0627...-module-tree-calibration` 看起来有校准价值，但仍不应直接用隐藏运行目录提交。

### 2. `scripts/backups/`

现状：

- 约 100M。
- 包含 Postgres dump、MinIO tgz、Redis tgz。

建议：

- 绝不提交。
- 作为本机恢复点保留即可。
- 加入 `.gitignore`。

### 3. `logs/` 与 `.runtime/`

现状：

- `logs/celery.pid`
- `logs/platform_api.pid`
- `.runtime/api.pid`
- `.runtime/frontend.pid`
- `.runtime/worker.pid`
- `.runtime/logs/*.log`

建议：

- 不提交。
- `*.log` 已忽略，但 pid 没有完整忽略。
- 加入 `.runtime/` 与 `logs/*.pid`。

### 4. 平台私有配置目录

路径：

- `.claude/`
- `.codex/`
- `.cursor/`

判断：

- 这些目录可能对多工具协作有价值，但也可能污染“别人 clone 后即可部署”的项目主线。
- `.claude/settings.local.json` 明显属于本地配置，不应提交。
- `.DS_Store` 不应提交。

建议：

- 需要用户决策。
- 如果提交，只提交通用 agent/command/hook 模板，排除 local settings 和系统文件。

## 已处理与待处理决策

1. `p0_quota_enabled` 的最终默认值。
   - 已处理：默认值/前端触发配置改为 `False`。
   - 理由：用户此前真实跑批配置要求 `False`；保留功能但默认不启用，等真实跑批对比后再决定是否开启。

2. `.audit` 中是否有必须长期保留的校准资产。
   - 建议：不提交 `.audit` 原目录；若要保留，后续整理成小 fixture。

3. `.claude/.codex/.cursor` 是否进入仓库。
   - 已按保守策略处理：先不进入 checkpoint；只保留 `.agents` 与 `.trellis` 的项目通用部分。

4. `.trellis/workspace` 是否进入仓库。
   - 已按保守策略处理：默认不进；任务文档已经在 `.trellis/tasks` 中，workspace journal 不应成为发布主线要求。

## 阶段 A 当前判断

可以继续按 commit plan 精确提交，但还不能创建 checkpoint。原因：

- `p0_quota_enabled` 冲突已解决，但改动尚未提交和验证。
- `.audit`、备份、平台私有配置、`.trellis/workspace` 已通过 `.gitignore` 排除。
- 当前阶段成果应分组提交并跑对应验证，而不是一次性 `git add .`。
