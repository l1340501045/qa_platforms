# 阶段 B 执行计划

## 前置门禁

- 阶段 A 已完成，或用户明确允许先做阶段 B。
- 当前工作区已确认不会把 UI 快修与历史脏改混在同一个 commit。
- 执行前读取父任务 `prd.md/design.md/implement.md` 和本任务 `prd.md/design.md/implement.md`。

## B1 系统统计假 0

1. 写后端测试，复现系统有文档/批次但列表缺统计字段的问题。
2. 修改 `SystemService.list_systems`，返回带 `document_count` / `batch_count` 的 dict 或 schema。
3. 更新 `SystemResponse` / 前端 `System` 类型。
4. 修改 `SystemsPage` 展示逻辑：
   - 字段存在时显示真实数字。
   - 字段缺失时显示 `--`，不再默认为 0。
5. 验证 DB 示例系统：
   - `6b0ea53c-f734-4bc9-8506-663d47107b9d`
   - 期望文档数 1、批次数 3。

## B2 上传文档类型

1. 写后端测试：合法 `doc_type=prd` 落库为 prd；非法类型返回错误。
2. 修改后端 `batch_upload_documents` 参数校验。
3. 修改前端类型和 store：
   - `uploadDocuments(systemId, files, docType)`
   - `batchUploadDocuments(systemId, files, docType)`
4. 修改 `KnowledgePage`：
   - 上传区增加文档类型选择。
   - 默认 `prd`。
   - 上传结果展示中文类型。
5. 验证选择 `prd` 上传后列表不再显示 `other`。

## B3 树默认折叠/滚动/定位

1. `KnowledgePage`
   - 移除 `defaultExpandAll`。
   - 增加受控 `expandedKeys`。
   - 增加搜索/展开全部/收起全部。
   - 树容器最大高度和内部滚动。
2. `CaseTreeReview`
   - 同样移除 `defaultExpandAll`。
   - 默认展开 root + 文档层。
   - 左侧 Card 内部滚动，右侧表格不受左树高度影响。
3. `CaseLibraryPage`
   - 同步做轻量修复。

## 验证命令

```bash
uv run pytest tests/platform_api -k "system or document"
```

前端：

```bash
cd web
npm run lint
npm run typecheck
npm run build
```

运行态验收：

- 打开 `/systems`，确认 `漫剧批创系统` 统计不是 0/0。
- 打开 `/systems/6b0ea53c-f734-4bc9-8506-663d47107b9d/documents`，上传区可选文档类型。
- 打开 `/batches/6f30e1bd-89ad-4e98-878c-4b48014eb1a4`，左树默认不全展开，树内部滚动。
- 打开 `/case-library`，用例树默认不全展开。

## 产物 Review

完成后写 `review.md`，必须包含：

- 已解决的问题和证据。
- 未解决的问题和原因。
- 是否触碰生成核心逻辑。
- 是否引入阶段 C/D 范围外的大改。
- 是否可独立回滚。
