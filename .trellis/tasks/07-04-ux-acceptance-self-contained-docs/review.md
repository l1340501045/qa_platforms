# UI 验收资料自包含化自审

## 结论

这次改动是合理的小收口。`docs/acceptance/` 现在包含 README、runbook、回填模板和小规模 PRD 样例，执行者不需要进入 `.trellis/tasks/archive` 才能完成周一验收。

## 价值

- 降低执行摩擦，减少漏步骤。
- 保留 Trellis 归档作为历史记录，同时把实际验收入口放在 `docs/acceptance/`。
- README 使用相对链接，更适合在仓库内浏览。
- 验收对象按用户澄清收敛为“具备 QA 背景但首次使用本平台的人”，不是“QA 新手”。

## 风险

- runbook 和回填模板现在有两份副本：一份在 Trellis 归档，一份在 `docs/acceptance/`。
- 后续若修改验收流程，需要同步两个位置，或明确以 `docs/acceptance/` 为执行版本。

## 是否偏离目标

没有。用户目标要求 UI/UX 重构可被真实探索验证。自包含验收包不是产品 UI，但它让真实验证更顺畅，有助于后续证明是否可以合 main。
