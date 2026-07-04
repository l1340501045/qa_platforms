# 系统删除忽略软删除文档 Review

## 结论

本任务修复了阶段 E 暴露的真实 UX 缺口：系统下只剩软删除文档时，用户可以删除系统，不会再被不可见 tombstone 外键阻塞。

改动没有触碰测试用例生成链路、批次生成链路或用例落库链路。系统仍有有效文档或任何批次时，仍会拒绝删除，避免误删业务资产。

## 自审重点

### 1. 是否改变了主流程

没有。改动点仅在 `SystemService.delete_system` 的删除前置判断和 tombstone 清理：

- 有效文档：继续阻止删除。
- 批次：继续阻止删除。
- 仅软删除文档：物理清理 tombstone 后删除系统。

生成批次、文档上传、文档软删除本身都没有改变。

### 2. 是否可能误删生成资产

风险较低。系统删除前显式查询 `testcase.test_batches`，只要该系统存在批次就拒绝删除。即使批次引用的文档已经软删除，也会被 `batch_count` 阻止。

这比原先单纯依赖数据库外键报错更清晰，也让错误信息更贴近业务状态。

### 3. 为什么要硬删软删除文档

`knowledge.documents.system_id` 对 `public.systems.id` 使用 `ondelete=RESTRICT`。软删除文档虽然业务上不可见，但数据库外键仍存在。若不硬删 tombstone，系统删除永远无法成功。

这里硬删的前提是：

- 文档已经软删除。
- 系统没有任何批次。
- 系统没有任何有效文档。

因此它更像清理不可见垃圾数据，而不是改变文档删除接口的语义。

### 4. 剩余风险

若未来新增其它表以 `RESTRICT` 指向 `public.systems`，当前代码仍可能在最后删除系统时触发 `IntegrityError`，并返回“仍有关联数据”。这是合理兜底，但不是精细化提示。

后续若要做更完整的系统删除体验，可以把阻塞原因拆成文档、批次、沉淀资产、系统关联等列表，前端展示“去处理”的入口。本任务只修复软删除文档造成的假阻塞。

## 验证

| 命令 | 结果 |
|---|---:|
| `uv run pytest tests/platform_api/test_system_service.py` | 4 passed |
| `uv run pytest tests/platform_api` | 67 passed |
| `uv run ruff check src/platform_api/services/system_service.py tests/platform_api/test_system_service.py` | passed |
| `git diff --check` | passed |
