# 跑批后回填模板

跑完真实批次后，把下面信息贴给 Codex。

```markdown
## 基本信息

- 分支：
- 最近提交：
- 是否工作区干净：
- system_id：
- document_id：
- batch_id：
- PRD 类型：小规模验收 PRD / 完整大 PRD
- 是否含图片：
- 最终状态：pending_review / suspended / failed / archived / other
- 总用例数：
- 开始时间：
- 结束时间：
- 总耗时：

## 环境

- API health：
- worker ping：
- frontend：
- LLM_PRIMARY_MODEL：
- LLM_VISION_MODEL：
- LLM_VERIFY_MODEL：
- LLM_CONCURRENCY：

## UI/UX 观察

- 上传前是否能选资料类型：
- 上传后文档类型是否正确：
- 触发生成是否顺畅：
- 批次状态是否清晰：
- 如果待澄清，澄清问题是否能理解：
- 用例树是否按业务模块/分支组织：
- 左侧树是否默认过度展开：
- 用例资产是否能看到新批次：
- 搜索是否能搜到新用例：
- 导出是否成功：

## 首次使用平台的 QA 观察

- 参与者是否具备 QA 背景：
- 是否第一次使用平台：
- 是否使用 `docs/acceptance/first-use-observation.md`：
- 是否提前接受过平台操作讲解：
- 独立完成步骤数：
- 目标级提示次数：
- 操作级提示次数：
- 是否能独立找到项目/系统：
- 是否能独立完成上传：
- 是否能独立触发生成：
- 是否能理解批次状态：
- 是否能找到审查页：
- 是否能找到导出：
- 需要提示的地方：
- 是否出现按钮、菜单、路径级提示：
- P0/P1/P2 卡点：
- 最严重卡点：
- 是否建议合 main：

## 审查包

- 是否已执行：`uv run python scripts/audit_export.py <batch_id> --dump`
- `.audit/<batch_id>/` 是否存在：
- `index.json` 是否存在：
- `REPORT.md` 是否存在：
- `modules/` 是否存在：
- `image_captions.json` 是否存在：

## 你主观感觉

- 用例是否仍感觉灌水：
- 模块树是否符合业务理解：
- 哪些页面仍别扭：
- 哪些问题你认为必须合 main 前修：
```

## Codex 后续审查动作

收到回填后，Codex 应执行：

1. 读取 `.audit/<batch_id>/index.json` 和 `REPORT.md`。
2. 对比旧批次 `6f30e1bd-89ad-4e98-878c-4b48014eb1a4` 的指标。
3. 抽查 `modules/**/cases.jsonl`，重点看：
   - P0 是否仍滥用。
   - `needs_spec/to_fix` 是否被 stable 主集隔离。
   - 模块树是否符合业务模块，而不是 PRD 章节平铺。
   - 断言是否可观察、可执行、可追溯。
   - 单步用例是否只是原子动作，而不是复杂链路被压扁。
4. 产出是否可合 main 的结论：
   - 可合。
   - 修 P0/P1 后可合。
   - 不可合，需回到 UI/UX 或生成策略任务。
