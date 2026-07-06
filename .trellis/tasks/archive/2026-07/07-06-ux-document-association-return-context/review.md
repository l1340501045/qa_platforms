# 文档详情关联跳转保留追溯上下文 Review

## 改动摘要

- 新增 `buildAssociatedDocumentUrl`，用于从文档详情打开关联文档时保留来源文档。
- 文档详情页支持 `from=document&document_id=<source>`，返回按钮显示 `返回来源文档`。
- 关联文档表格不再裸跳 `/documents/:id`，而是带上来源文档和上游知识库/搜索上下文。
- 补充 `batchReturn.test.ts`，覆盖普通、知识库来源、搜索来源、旧文档返回能力。

## 批判性自审

### 是否偏离父任务

没有。该改动服务资料追溯动线，让 QA 能从主资料跳到关联资料再回到主资料；不涉及后端关联模型、生成配置或 worker。

### 是否改变主流程

不改变。`triggerGeneration`、批次页、文档关联 API 均未改；只是前端 URL 参数和返回按钮文案变化。

### 是否过度设计

没有做多级链路图、面包屑树或关联可视化，只做一次跳转可返回。多级资料追溯是后续大任务，本次不扩大范围。

### 风险

- URL 参数变长，但只包含已有的搜索/知识库上下文键。
- 关联文档多跳时会回到上一份文档，同时保留最初知识库/搜索来源；这是刻意设计，避免用户沿链路追溯后丢失原入口。

## 验证

- `cd web && npm run test:ui-models`：通过，25 tests。
- `cd web && npm run lint`：通过。
- `cd web && npm run build`：通过，仅有既有 Vite chunk size warning。
- `git diff --check`：通过。
