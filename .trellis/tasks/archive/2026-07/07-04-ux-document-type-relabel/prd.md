# 历史文档类型重标注入口

## 目标

为历史 `other` 文档提供手动重标注入口，避免 QA 在文档详情和知识库中误判资料类型。

## 背景

阶段 E 已证明新上传文件可以按前端选择写入 `doc_type=prd`，但历史文档仍会显示为 `other`。如果平台只显示“其他”而不给修正入口，具备 QA 背景但首次使用本平台的 QA 会误以为该资料不会作为 PRD、技术文档或测试规则参与后续生成依据。

盲目自动迁移不安全：历史文件名和内容不一定足以可靠判断类型。本任务采用更稳的做法：提供人工重标注入口，由 QA 明确选择类型。

## 需求

- 后端提供文档类型更新能力，只允许更新为系统已支持的 `DOC_TYPES`。
- 更新已软删除或不存在的文档应返回 404。
- 非法类型应返回 400。
- 前端文档详情页可以修改当前文档类型，并刷新当前详情。
- 知识库列表页应给历史 `other` 文档一个显性的“标注类型”动作，降低误用风险。
- 不改变文档内容、解析状态、批次生成逻辑和用例生成逻辑。

## 验收结果

- [x] 后端测试覆盖成功重标注、非法类型拒绝、已删除文档拒绝。
- [x] HTTP 契约测试覆盖 `PATCH /api/v1/documents/{id}/type`。
- [x] 文档详情页支持类型重标注并成功刷新当前详情。
- [x] 知识库列表页对 `other` 文档提供重标注入口。
- [x] `uv run pytest tests/platform_api/test_document_service.py` 通过。
- [x] `uv run pytest tests/platform_api` 通过。
- [x] `npm run lint` 通过。
- [x] `npm run typecheck` 通过。
- [x] `npm run build` 通过。
- [x] `npm run test:ui-models` 通过。
- [x] `uv run ruff check src/platform_api/api/v1/documents.py src/platform_api/schemas/document.py src/platform_api/services/document_service.py tests/platform_api/test_document_service.py` 通过。
- [x] `uv run ruff format --check src/platform_api/api/v1/documents.py src/platform_api/schemas/document.py src/platform_api/services/document_service.py tests/platform_api/test_document_service.py` 通过。
- [x] `git diff --check` 通过。

## 不做

- 不做历史数据批量迁移。
- 不做自动类型推断。
- 不重新触发 KB 解析或用例生成。
