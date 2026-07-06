# 文档详情关联跳转保留追溯上下文 Design

## 当前行为

- `DocumentDetailPage` 根据 `from=knowledge` 或 `from=search` 决定返回入口。
- `buildDocumentBatchUrl` 已能把文档详情来源传给批次页。
- `buildDocumentReturnUrl` 已能让批次页从 `from=document&document_id=...` 返回文档详情。
- 关联文档表格当前直接 `<Link to="/documents/:id">`，没有来源参数。

## 设计

在 `web/src/utils/batchReturn.ts` 增加一个前端 URL helper：

```ts
buildAssociatedDocumentUrl(targetDocumentId, sourceDocumentId, sourceParams)
```

它生成：

- 默认：`/documents/<target>?from=document&document_id=<source>`
- 当前来源为知识库：追加 `document_from=knowledge&system_id=<systemId>`
- 当前来源为搜索：追加 `document_from=search` 和搜索上下文
- 当前已经来自另一个文档：沿用上游 `document_from`，避免多跳时把原始知识库/搜索来源丢掉。

`DocumentDetailPage` 读取：

- `from=document` 时返回 label 为 `返回来源文档`
- 返回 URL 使用 `buildDocumentReturnUrl(searchParams)`
- 否则保持当前知识库/搜索/项目系统逻辑。

## 兼容性

- 不改路由表。
- 不改 `triggerGeneration`。
- 不改文档关联 API。
- `buildDocumentReturnUrl` 既用于批次页，也可用于文档详情页，不改变现有参数含义。

## 自审

- 为什么不做完整链路面包屑：多级链路图是更大信息架构任务，本次只保证一次跳转可返回，不扩大范围。
- 为什么 URL 参数复用 `document_from`：批次页已经使用这套语义，复用能减少新概念。
- 为什么加工具测试：返回路径是纯函数契约，页面级测试缺失时必须用 utils 测试兜住。
