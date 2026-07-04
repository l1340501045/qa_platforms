# main 合并准备清单

## 当前状态

当前 `feat/qa-platform-ux-modernization` 是 UI/UX 候选交付分支，不是已确认可合并分支。

已满足：

- UI/UX 主体改造、运行态验收、真实验收脚本和验收入口资料均已完成阶段性收口。
- 当前 HEAD 运行态验收通过。
- 工作流主导航、知识库、批次工作台、用例资产、搜索、导出已按 QA 日常动线重构。
- `src/testcase_generator/**` 相对 checkpoint 无 diff，生成核心未被 UI 分支污染。
- 真实跑批与首次使用平台验收 runbook 已准备。
- UI/UX 合并前验收证据台账已准备，能区分已有材料、待补硬证据和不能作为完成证明的间接材料。
- UI/UX 验收前预检与 runbook 已对齐：预检覆盖 6 个验收文件，runbook 不再依赖固定历史提交出现在最近 5 条内。
- UI/UX 验收前预检已覆盖真实跑批关键生成配置，能检查前端、settings、pipeline 契约中的 merge/cap/P0 quota 配置是否一致。
- UI/UX 验收前预检脚本已有单测保护，覆盖前端、pipeline、settings 生成配置解析和配置不一致失败路径。
- 不触发生成的页面 dry-run 已复查关键入口、生成弹窗、批次页、资产、搜索、导出和 1024 宽度横向溢出。
- 首次使用平台的 QA 演练观察表已准备，能记录目标级提示、操作级提示、卡点和 P0/P1/P2 判级。

未满足：

- 当前 HEAD 未跑新的真实 LLM 批次。
- 未完成首次使用平台的 QA 任务演练。
- 未基于新批次 `.audit` 审查用例质量和模块树。

## 合并前必须执行

### 1. 分支与环境

```bash
git status --short --branch
git log --oneline -5
git diff checkpoint/architecture-migration-pre-ux...HEAD --name-only -- src/testcase_generator
curl http://127.0.0.1:8000/health
curl -I http://127.0.0.1:3000
uv run celery -A src.platform_api.core.celery_app.celery_app inspect ping --timeout=5
```

通过条件：

- 工作区干净。
- 当前分支是 `feat/qa-platform-ux-modernization`。
- `src/testcase_generator` diff 无输出。
- API / frontend / worker 在线。

### 2. 小规模真实批次

推荐资料：

- 默认使用 [ux-small-batch-prd.md](../../../docs/acceptance/ux-small-batch-prd.md)。
- 这份样例覆盖权限、字段边界、CSV 上传、异步状态、失败重试、停止、筛选分页和导出，适合作为 UI/UX 主链路验收输入。
- 如果要验证图片链路，再额外补一份含图片的小 PRD；不要直接用完整大 PRD 替代最小验收。

执行：

- 新建验收系统。
- 上传 `docs/acceptance/ux-small-batch-prd.md`，或同等规模的 1-3 个模块小 PRD。
- 上传前选择 `PRD` 类型。
- 触发生成。
- 跑到待审核或归档。
- 检查批次页、用例树、用例资产、搜索、导出。

通过条件：

- 主链路没有 P0/P1 UI 卡点。
- 文档类型不误落 `other`。
- 批次状态和下一步动作可理解。
- 用例树是业务模块 + 分支，不是 PRD 章节平铺。

### 3. 首次使用平台的 QA 演练

给参与者唯一任务：

```text
请把这份 PRD 上传到平台，生成测试用例，找到需要审查的批次，抽查几条用例，然后导出结果。
```

通过条件：

- 不需要平台操作讲解就能找到主入口。
- 能理解上传资料类型。
- 上传后知道下一步生成。
- 能理解批次状态。
- 能找到审查、资产、搜索、导出。
- 没有 P0/P1 卡点。
- 如果必须靠按钮、菜单或路径级提示完成上传、生成、审查或导出，不能判为通过。

### 4. 新批次审查包

```bash
uv run python scripts/audit_export.py <batch_id> --dump
```

通过条件：

- `.audit/<batch_id>/index.json` 存在。
- `.audit/<batch_id>/REPORT.md` 存在。
- `.audit/<batch_id>/modules/` 存在。
- Codex 审查没有发现 UI/UX 造成的 P0/P1 回归。

## GO / NO-GO

| 判定 | 条件 |
|---|---|
| GO | 小规模真实批次通过；首次使用平台的 QA 演练无 P0/P1；新 `.audit` 无 UI/UX 造成的 P0/P1 回归 |
| FIX THEN GO | 只有 P2 UI 问题或文案/布局细节；记录后可另开任务 |
| NO-GO | 上传、生成、批次页、审查、资产、搜索、导出任一主链路断；状态误导；文档类型仍错；用例树退回平铺 |
| SPLIT OUT | LLM 网关、生成质量策略、大 PRD 成本问题；转 infra 或 testcase generator，不直接否定 UI 分支 |

## 批判性说明

这份清单有意不要求先跑完整大 PRD 才能合 UI 分支。原因是完整大 PRD 的耗时、网关稳定性和生成质量属于更大范围的质量回归；UI/UX 分支的最小合并门槛应该先证明主流程可用、状态可理解、首次使用平台的 QA 不会迷路。

但如果小规模批次通过后，完整大 PRD 新批次暴露了 UI/UX 导致的模块树错乱、用例资产无法浏览、搜索/导出不可用，那仍然必须回到 UI/UX 分支修复。
