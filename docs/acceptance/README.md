# UI/UX 真实验收入口

这个目录用于周一公司网络可用后，验证 `feat/qa-platform-ux-modernization` 是否可以进入 PR / 合 main 准备。

当前结论先说清楚：UI/UX 分支已经是候选交付，但还没有完成真实新批次和首次使用平台的 QA 验收，所以父任务暂不归档。

## 执行顺序

1. 先打开 [验收证据台账](./evidence-ledger.md)，确认这次要补哪些硬证据。
2. 按 [真实跑批 Runbook](./runbook.md) 启动环境、检查分支和确认模型配置。
3. 新建验收系统，上传 [小规模验收 PRD](./ux-small-batch-prd.md)。
4. 在前端选择资料类型为 `PRD`，触发生成，记录 `batch_id`。
5. 批次完成后检查工作台、批次页、用例树、用例资产、搜索和导出。
6. 找一个具备 QA 背景但首次使用本平台的人，按 [观察表](./first-use-observation.md) 做任务演练。
7. 执行 `uv run python scripts/audit_export.py <batch_id> --dump` 生成 `.audit/<batch_id>/`。
8. 按 [跑批后回填模板](./post-batch-report-template.md) 或 [验收证据台账](./evidence-ledger.md) 的最小交付包，把结果发给 Codex 继续审查。

## 判断标准

最终 GO / NO-GO 以 [main 合并准备清单](../../.trellis/tasks/07-04-qa-platform-ux-modernization/main-merge-readiness.md) 为准。

简化版：

| 判定 | 条件 |
|---|---|
| GO | 小规模真实批次通过；首次使用平台的 QA 演练无 P0/P1；新 `.audit` 无 UI/UX 造成的 P0/P1 回归 |
| FIX THEN GO | 只有 P2 UI 问题或文案/布局细节 |
| NO-GO | 上传、生成、批次页、审查、资产、搜索、导出任一主链路断 |
| SPLIT OUT | LLM 网关、生成质量策略、大 PRD 成本问题；转 infra 或 testcase generator |

## 样例 PRD 的边界

[ux-small-batch-prd.md](./ux-small-batch-prd.md) 覆盖权限、字段边界、CSV 上传、异步状态、失败重试、停止、筛选分页和导出，适合证明 UI/UX 主链路是否可用。

[first-use-observation.md](./first-use-observation.md) 用于记录具备 QA 背景但首次使用平台的人，是否能在没有平台操作讲解的情况下独立完成上传、生成、审查和导出。

[evidence-ledger.md](./evidence-ledger.md) 用于区分“已有文档/脚本”和“真正完成的验收证据”，避免把待执行事项误判成已通过。

小规模验收 PRD 不含图片，不能替代视觉模型链路验收；它也不能替代完整大 PRD 的生成质量回归。
