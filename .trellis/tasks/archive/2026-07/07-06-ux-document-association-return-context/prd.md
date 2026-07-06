# 文档详情关联跳转保留追溯上下文

## Goal

让 QA 在文档详情页沿“关联文档”继续追溯资料时，不丢失返回路径：从 A 文档点到关联的 B 文档后，B 文档顶部应能返回 A 文档；如果 A 文档本来来自知识库或搜索，也要继续保留那条上游来源。

这只修改前端 URL 上下文和导航行为，不改变文档关联 API、生成配置、worker、pipeline 或 testcase generator。

## Background

当前文档详情页已经支持：

- 从知识库或搜索进入详情后显示对应返回入口。
- 从文档详情发起生成时，批次页能返回文档详情，并继续保留知识库/搜索来源。
- 关联文档表格能展示直接关联资料。

剩余断点在关联文档跳转：当前关联文档链接是裸 `/documents/:id`。QA 从文档 A 点到关联文档 B 后，B 页不再知道 A 是来源，返回按钮只能回项目/系统入口，追溯链断掉。

## Requirements

1. 文档详情页的关联文档链接必须带上 `from=document&document_id=<currentDocumentId>`。
2. 如果当前文档详情来自知识库，关联文档链接还要保留 `document_from=knowledge&system_id=<systemId>`。
3. 如果当前文档详情来自搜索，关联文档链接还要保留 `document_from=search` 以及搜索关键词、系统、优先级、审核状态、页码等上下文。
4. 文档详情页读取到 `from=document&document_id=<sourceDocumentId>` 时，顶部返回入口必须显示为“返回来源文档”，并跳回该来源文档。
5. 关联跳转只影响前端导航，不改变关联数据、不创建新关联、不触发生成。

## Acceptance Criteria

- [ ] 从普通文档详情打开关联文档，URL 为 `/documents/<target>?from=document&document_id=<source>`。
- [ ] 从知识库进入文档详情后再打开关联文档，URL 保留 `document_from=knowledge&system_id=<systemId>`。
- [ ] 从搜索进入文档详情后再打开关联文档，URL 保留 `document_from=search` 和搜索上下文。
- [ ] 带 `from=document&document_id=<source>` 打开的文档详情，返回按钮文案为 `返回来源文档`。
- [ ] `buildDocumentReturnUrl` 继续支持批次页返回文档详情，不破坏现有批次返回逻辑。
- [ ] 前端 utils 测试、lint、build 通过。

## Out of Scope

- 不新增后端接口。
- 不改变文档关联关系模型。
- 不做关联文档链路图或多级面包屑。
- 不改变生成主流程。

## Planning Review

这是一个轻量但高杠杆的导航修复。它让资料追溯链变得可往返，符合 QA 日常“看主 PRD -> 点技术文档/原型 -> 回主 PRD”的工作方式。风险集中在 URL 参数兼容性，因此必须补 `batchReturn` 工具测试，而不是只改页面 JSX。
