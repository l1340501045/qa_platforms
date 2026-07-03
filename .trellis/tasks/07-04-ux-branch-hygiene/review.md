# 阶段 A 批判性 Review

## Review 结论

阶段 A 目前完成了“盘点与提交计划”的核心产物，但还没有达到“可以创建 checkpoint”的状态。

原因不是流程没走完，而是当前工作区确实有三类风险必须先处理：

1. **配置意图冲突已处理**：`p0_quota_enabled` 原先默认是 `True`，但用户此前指定真实跑批配置为 `False`；本阶段已按真实跑批配置改为默认 `False`。
2. **特定设计工具范围判断已校正**：我最初把专属回灌工具误归为“可保留阶段成果”；用户最新决策是全部不要。已用独立提交删除方案、代码、测试、配置与残留文案。
3. **运行产物过大且不可提交**：`.audit` 72M、`scripts/backups` 100M，不能进入干净基线；本阶段已补 `.gitignore` 防误提交。
4. **平台工具配置边界已按保守策略处理**：`.claude/.codex/.cursor` 不进入 checkpoint，只保留 `.agents` 与 `.trellis` 的项目通用流程资产。

## 对 worktree-inventory 的自审

做得对的地方：

- 覆盖了所有 dirty top-level path，没有只盯 `src/` 和 `web/`。
- 把 `web/src/components/CaseTreeReview.tsx`、`CaseLibrary`、`Workbench` 识别为“模块树/用例资产契约成果”，而不是简单归类成 UI/UX 重构。
- 明确了 `.audit` 和 `scripts/backups` 的体量，避免它们被误提交。
- 把 `p0_quota_enabled` 冲突列成决策项并完成处理，这是后续真实跑批能否可信的关键。

还不够好的地方：

- 目前是路径级分类，还没有逐个文件做语义 review；例如 `src/platform_api/core/settings.py` 同时承载 oracle、convergence、P0 配额多个主题，后续 commit 时可能需要接受一个较大的 mixed config commit。
- `.trellis/workspace`、`.claude/.codex/.cursor` 当前被忽略；如果用户未来希望把多平台工具配置产品化，需要另起小任务整理模板，不能从本地状态目录直接提交。

## 对 commit-plan 的自审

做得对的地方：

- 没有建议 `git add .`。
- 把 Trellis、infra、verify、convergence、case-tree、docs 分开，后续 review 能定位问题来源。
- 明确了哪些路径暂不提交。
- 把 checkpoint 创建条件写成硬门禁，而不是默认“写完报告就可以拉分支”。

风险：

- 原计划曾建议保留一个特定设计工具链路，这是错误分类；已经按用户决策改为删除，但这说明后续每个“看似有价值”的历史工具都必须重新过一遍产品范围，不应因为已有代码就自动保留。
- Commit 4/5/6/7 之间存在少量同文件跨主题耦合，尤其是：
  - `src/platform_api/core/settings.py`
  - `src/testcase_generator/schemas/test_case.py`
  - `src/testcase_generator/stages/test_points/node.py`
  - `web/src/types/index.ts`
- 如果后续追求完美拆 commit，可能需要 `git add -p` 或临时补丁拆分；这比整文件提交更容易出错。
- 更稳的策略是按本计划先做“主题尽量分组的整文件提交”，再靠 commit message 和 review 解释少量耦合。

## 是否偏离 UI/UX 大目标

没有偏离。现在看似在做 Git/任务治理，但这是 UI/UX 大重构的前置条件。

如果跳过阶段 A，直接开始 UI 改造，会出现两个严重问题：

- UI 分支会混入生成质量、模块树、Docker、Trellis、审查产物，后续无法判断某个问题来自 UI 改动还是生成策略改动。
- `feat/architecture-migration` 的阶段成果可能被覆盖或丢失，最终也无法保证 `main` 是可部署的干净项目。

## 建议下一步

先不要创建 checkpoint，也不要开 UI/UX 分支。

下一步应该是一个小而明确的治理动作：

1. 按 commit-plan 执行精确提交。
2. 跑关键测试。
3. 工作区干净后创建 checkpoint 和 UI/UX 分支。

## 当前阶段状态

- 阶段 A 可进入“等待用户确认提交/配置决策”。
- 阶段 B/C/D/E 仍不得启动。
- 父任务仍不应标记完成。

## 验证记录

已通过：

```bash
uv run pytest tests/testcase_generator/test_pipeline_generation_config.py tests/testcase_generator/test_priority_risk.py
uv run pytest tests/platform_api/test_case_tree_service.py tests/platform_api/test_case_tree_integration.py tests/testcase_generator/test_audit_export_module_tree.py
uv run pytest tests/testcase_generator/test_generation_convergence.py tests/testcase_generator/test_oracle_guards.py tests/testcase_generator/test_pipeline_generation_config.py tests/testcase_generator/test_priority_risk.py
uv run pytest tests/testcase_generator --ignore=tests/testcase_generator/integration
uv run ruff check src/platform_api/core/settings.py src/testcase_generator/stages/parse/node.py
npm run build
关键词残留扫描：工作区与 HEAD 均无命中。
```

验证缺口：

```bash
npm run lint
```

未通过原因不是新增代码 lint 报错，而是当前 `web/` 缺少 ESLint 配置文件，ESLint 无法启动。这个问题应纳入后续工程卫生/前端重构任务，不应在阶段 A 混入修复。
