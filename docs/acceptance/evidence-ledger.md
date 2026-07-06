# UI/UX 合并前验收证据台账

## 使用方式

这份台账用于判断 `feat/qa-platform-ux-modernization` 是否可以进入 PR / 合 main 准备。

它不是新的执行流程。真正操作仍按 [runbook.md](./runbook.md) 走；这份文件只回答一个问题：**现在手里的证据够不够支撑 GO / NO-GO 判断。**

## 当前结论

截至当前 HEAD，结论仍是：**候选交付，可以进入真实小批次验收，但不能直接合 main。**

原因：

- 本地页面 dry-run、重启后无 LLM 页面巡检、无副作用控件动线巡检、预检脚本、验收文档已经完成。
- 还没有在公司 LLM 网关下跑新的小规模真实批次。
- 还没有让具备 QA 背景但首次使用平台的人完成任务演练。
- 还没有基于新批次 `.audit/<batch_id>/` 审查用例质量和模块树。

## 证据台账

| 证据项 | 怎么取得 | 通过标准 | 当前状态 | 结论影响 |
|---|---|---|---|---|
| 分支正确 | `git status --short --branch` | 当前分支是 `feat/qa-platform-ux-modernization`，工作区干净 | 待周一复核 | 不通过则暂停验收 |
| 生成核心未被 UI 分支污染 | `git diff checkpoint/architecture-migration-pre-ux...HEAD --name-only -- src/testcase_generator` | 无输出 | 本地已多次验证，仍需跑前复核 | 有输出则暂停合并 |
| API / worker / 前端在线 | `uv run python scripts/ux_acceptance_preflight.py` | API、worker、frontend 均通过 | 待周一复核 | 不通过则先修环境 |
| 模型与生成配置正确 | `uv run python scripts/ux_acceptance_preflight.py --skip-runtime` 或完整预检 | 模型、并发、case cap、merge、P0 quota 配置符合 runbook | 待周一复核 | 配置不符会污染跑批结论 |
| 小规模真实批次完成 | 使用 `ux-small-batch-prd.md` 触发生成 | 批次到 `pending_review` 或可归档状态；上传、生成、批次页、审查、资产、搜索、导出主链路不断 | 未完成 | 缺失时不能 GO |
| 文档类型不误落 `other` | 上传前选 `PRD`，上传后看列表和详情 | 上传后显示为 `PRD`，历史 `other` 可人工重标注 | 未完成 | 失败则 NO-GO |
| 用例树可操作 | 新批次页查看左侧树 | 不是 PRD 章节平铺；模块下允许分支；默认不展开到难以操作 | 未完成 | 失败则 NO-GO 或 FIX THEN GO |
| 首次使用平台 QA 演练 | 按 `first-use-observation.md` 找具备 QA 背景但首次使用平台的人 | 不需要平台操作讲解；如有提示，也只需要目标级提示；无 P0/P1 | 未完成 | 缺失时不能 GO |
| `.audit` 审查包 | `uv run python scripts/audit_export.py <batch_id> --dump` | `index.json`、`REPORT.md`、`modules/` 存在 | 未完成 | 缺失时不能 GO |
| 新批次用例质量审查 | Codex 读取 `.audit/<batch_id>/` 审查 | 无 UI/UX 造成的 P0/P1 回归；模块树不退回平铺；资产可追溯 | 未完成 | 失败则回到 UI/UX 或生成策略任务 |

## 给 Codex 的最小交付包

跑完后，把下面内容贴回来即可：

```markdown
## 跑批证据

- 最新提交：
- `git status --short --branch` 输出：
- `uv run python scripts/ux_acceptance_preflight.py` 结果：
- system_id：
- document_id：
- batch_id：
- 最终状态：
- 总用例数：
- 是否出现待澄清：
- 是否出现失败：

## 首次使用平台 QA 演练

- 参与者是否具备 QA 背景：
- 是否第一次使用平台：
- 是否提前接受过平台操作讲解：
- 目标级提示次数：
- 操作级提示次数：
- P0/P1/P2 卡点：
- 最严重卡点：

## 审查包

- `.audit/<batch_id>/` 是否存在：
- `REPORT.md` 前几段：
- 你主观觉得是否仍有灌水：
- 你主观觉得模块树是否符合业务理解：
```

如果已经按 [post-batch-report-template.md](./post-batch-report-template.md) 完整回填，也可以直接贴完整模板。

## GO / NO-GO 判定

| 判定 | 条件 |
|---|---|
| GO | 小规模真实批次通过；首次使用平台 QA 演练无 P0/P1；`.audit` 审查无 UI/UX 造成的 P0/P1 回归 |
| FIX THEN GO | 仅有 P2 UI 问题、文案弱、布局效率低，且主链路不断 |
| NO-GO | 上传、生成、批次页、审查、资产、搜索、导出任一主链路断；文档类型仍误落 `other`；状态明显误导；树退回不可操作 |
| SPLIT OUT | LLM 网关不可达、模型超时、大 PRD 成本、生成策略质量问题；另转 infra 或 testcase generator，不直接否定 UI 分支 |

## 不能当作完成证据的材料

- 只有本地 dry-run，没有真实新批次。
- 只有 runbook 和观察表，没有真人执行结果。
- 只有批次完成截图，没有 `.audit` 审查包。
- 只有旧批次审查结果，没有当前 HEAD 新批次。
- 只有“最后完成了”，但过程依赖按钮、菜单、路径级讲解。

## 审查提醒

- 步骤短不天然是问题；只要可执行、预期可观察、断言清楚，就不应因步骤少而误判。
- 完整大 PRD 批次不是 UI/UX 合并的最小门槛；它更适合验证生成质量、网关稳定性和规模成本。
- 小规模批次如果暴露 UI 主链路问题，必须先修 UI/UX，再考虑大 PRD。
