# 阶段 B 技术设计：主流程安全 UX 快修

## 设计目标

用最小可回滚改动修复三个已经证实的体验/数据问题：

1. 系统列表统计假 0。
2. 上传文档类型默认落到 `other`。
3. 知识库/工作台/用例库树默认全展开且缺少可控滚动。

本阶段不做整体视觉重构，不抽大型共享组件，不触碰生成核心逻辑。

## 系统统计契约

### 现状

- 前端在 `web/src/pages/Systems/index.tsx` 读取 `system.document_count ?? 0` 和 `system.batch_count ?? 0`。
- 后端 `SystemService.list_systems` 当前只返回 `System` ORM 行，没有聚合统计。
- 本地 DB 只读查询确认 `漫剧批创系统` 实际有 `document_count=1`、`batch_count=3`。

### 目标契约

`GET /systems` 返回分页列表时，每个 item 包含：

```ts
document_count: number;
batch_count: number;
```

计数规则：

- `document_count` 只统计 `knowledge.documents.deleted_at is null`。
- `batch_count` 统计 `testcase.test_batches.system_id = system.id` 的批次数，第一阶段不筛状态。
- 前端正常展示数字；如果字段缺失，显示 `--` 或错误态，而不是静默显示 0。

## 上传文档类型契约

### 现状

- 后端 `POST /systems/:id/documents/batch` 已有 `doc_type: str = Query("other")`。
- 前端 `batchUploadDocuments(systemId, files)` 没有传 `doc_type`。

### 目标契约

- 前端上传区持有 `selectedDocType`，默认 `prd`。
- `uploadDocuments(systemId, files, docType)` 透传到 service。
- `batchUploadDocuments` 通过 query params 传 `doc_type`。
- 后端校验 `doc_type` 属于 `DocType` 枚举；非法值返回明确错误。
- 列表和上传结果使用中文标签展示文档类型。

## 树控件安全改造

### 现状

- `KnowledgePage`、`CaseTreeReview`、`CaseLibraryPage` 都使用 `defaultExpandAll`。
- 树容器缺少最大高度/内部滚动。

### 目标行为

- 默认只展开 root/第一层，不全展开。
- 提供“展开全部 / 收起全部”。
- 提供搜索/过滤或等价定位。
- 树容器固定高度或最大高度，内部滚动。
- 页面主体不被左树撑高。

本阶段可以在三个页面分别做轻量修复；共享抽象留给阶段 C。

## 风险控制

- 聚合统计查询避免 N+1，使用 SQL 聚合或批量 count map。
- 上传类型默认改为 `prd` 后要在 UI 明示当前选择，避免用户误传技术文档。
- 树搜索先做前端过滤即可，不改后端。
- 不在本阶段改 `CaseTreeService` 的树契约。

## 批判性 Review 要点

- 是否真的修了用户看到的问题，而不是只换文案。
- 是否保持所有现有路由和操作可用。
- 是否把阶段 C/D 的大重构提前塞进本阶段。
- 是否有测试或截图证明统计、上传类型、树行为确实改变。
