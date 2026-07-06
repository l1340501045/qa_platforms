# UI 验收预检与 Runbook 一致性修正自审

## 结论

本次修正必要且范围合理。它修的是周一验收执行层面的“假失败”风险：runbook 依赖固定历史提交出现在最近 5 条提交里，这在后续补验收资料后已经不成立。

## 自审问题

### 1. 是否掩盖了真实版本追溯风险

没有。runbook 仍要求当前分支正确、工作区干净、最近提交可追溯、生成核心无 diff。只是去掉了“某两条历史提交必须在最近 5 条里”的脆弱条件。

### 2. 是否让预检过度严格

没有。新增检查的 `evidence-ledger.md` 和 `first-use-observation.md` 已经是当前验收入口依赖的文件；缺失时确实会影响周一执行和证据回填。

### 3. 是否影响主流程

不影响。本次只改 `docs/acceptance/runbook.md`、`scripts/ux_acceptance_preflight.py` 和 Trellis 文档，没有修改前端、API、worker 或 `src/testcase_generator/**`。

## 判定

可以收口。下一步仍是周一按 runbook 跑小规模真实批次，并回填 evidence ledger 所需证据。
