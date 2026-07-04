# 历史文档类型重标注入口 Review

## 结论

本任务解决了阶段 E 剩余的历史 `other` 文档类型问题：新上传已能按类型入库，历史文档现在也可以由 QA 手动重标注，不需要重新上传文件或直接改数据库。

这符合当前 UI/UX 总目标：具备 QA 背景但首次使用本平台的 QA，在看到历史资料是“其他”时，能理解这不是不可修复状态，并能在原工作流中把资料改成 PRD、技术文档、测试规则等可信类型。

## 自审重点

### 1. 为什么不做自动迁移

自动迁移看似省事，但风险更高。历史文件名、路径、标题都不足以稳定推断真实类型；把历史资料误改成 PRD 或测试规则，反而会让 QA 对生成依据产生错误信任。

因此本次选择人工重标注：系统给出入口和解释，最终类型由 QA 明确选择。这是更稳的产品策略。

### 2. 是否改变生成链路

没有。更新接口只改 `knowledge.documents.doc_type`，不改内容、解析结果、嵌入状态、批次、用例、知识图谱，也不会触发 KB 重新解析或用例生成。

它修的是资料元数据可信度，不是生成算法。

### 3. 后端边界是否足够窄

后端新增 `PATCH /documents/{id}/type`，比通用 `PATCH /documents/{id}` 更窄。这样避免用户误以为可以编辑文档内容，也避免未来完整文档编辑 API 被这次小需求绑死。

服务层校验：

- 非法 `doc_type` 返回 `E4001`。
- 不存在或软删除文档返回 `E4041`。
- 成功后返回更新后的文档对象。

### 4. 前端入口是否过度

知识库列表只对 `other` 文档显示“标注类型”，避免正常文档列表被太多操作淹没。文档详情页提供“修改类型”，因为详情页本来就是确认资料状态和生成前检查的地方，允许 QA 做精确校正。

这比在系统列表或全局搜索里放修改入口更克制。

## 剩余风险

- 修改类型不会重新触发 KB 解析；如果未来解析策略按 doc_type 分支处理，需要单独设计“重标注后是否重新解析”。
- 目前没有操作审计字段，无法追踪谁把类型从 `other` 改成 `prd`。当前项目无鉴权层，这个限制是全局性的。
- 文档类型选项仍在多个前端页面各自维护 map，后续若类型继续增加，应抽出共享常量。

## 验证

| 命令 | 结果 |
|---|---:|
| `uv run pytest tests/platform_api/test_document_service.py` | 6 passed |
| `uv run pytest tests/platform_api` | 71 passed |
| `npm run lint` | passed |
| `npm run typecheck` | passed |
| `npm run build` | passed，仍有既有大 chunk warning |
| `npm run test:ui-models` | 21 passed |
| `uv run ruff check ...` | passed |
| `uv run ruff format --check ...` | passed |
| `git diff --check` | passed |
