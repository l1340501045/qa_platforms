# 阶段 B Review：主流程安全 UX 快修

## 结论

阶段 B 的三个目标已完成：系统列表统计不再假 0，知识库上传可选择文档类型且默认 PRD，知识库/工作台/用例库树不再默认全量展开并提供搜索、展开全部、收起全部和内部滚动。

本阶段没有改动 `src/testcase_generator/**`，没有触碰生成算法、LLM 调用、case cap、核验策略或 worker 任务逻辑。

## 已解决的问题

- 系统列表接口现在返回 `document_count` / `batch_count`。
  - 运行态验证：`GET /api/v1/systems?page=1&per_page=5` 中 `漫剧批创系统` 返回 `document_count=1`、`batch_count=3`。
  - 页面验证：`/systems` 卡片展示 `文档数：1`、`批次数：3`。
- 前端不再把缺失统计字段静默显示为 0。
  - 字段缺失时显示 `--`，避免把接口契约缺陷伪装成真实 0。
- 上传文档可选择 `doc_type`。
  - 知识库页新增“上传文档类型”选择器，默认 `PRD`。
  - 上传区显示“当前类型：PRD”。
  - `batchUploadDocuments` 请求携带 `params.doc_type`。
- 后端校验文档类型合法性。
  - 非法类型在 `DocumentService.batch_upload` 入口抛 `ApiError("E4001")`，不会继续处理上传文件。
  - `DOC_TYPES` 改为由 `DocType` 枚举派生，减少拼写漂移。
- 三处树控件从 `defaultExpandAll` 改为受控展开。
  - 知识库：默认只展开根节点；提供文件夹搜索、展开全部、收起全部；树区内部滚动。
  - 工作台批次页：默认展开到文档/模块层，模块下分支不再全铺开；提供模块/分支搜索和展开/收起。
  - 用例库：同工作台，切到 `漫剧批创系统` 后验证树默认不全铺开。

## 验证证据

- `uv run pytest tests/platform_api/test_system_service.py tests/platform_api/test_document_service.py`：3 passed。
- `uv run pytest tests/platform_api -k "system or document"`：6 passed。
- `uv run pytest tests/platform_api`：64 passed。
- `uv run ruff check ...`：All checks passed。
- `uv run ruff format --check ...`：6 files already formatted。
- `npm run build`：TypeScript + Vite build 通过。
- `npm run lint`：未通过，原因是项目没有 ESLint 配置文件，不是本次代码 lint 错误。
- `git diff --check`：通过。
- Chrome 运行态验收：
  - `/systems`：漫剧批创系统展示文档数 1、批次数 3。
  - `/systems/6b0ea53c-f734-4bc9-8506-663d47107b9d/documents`：上传类型选择器默认 PRD，上传区显示当前类型 PRD，左树有搜索/展开/收起。
  - `/batches/6f30e1bd-89ad-4e98-878c-4b48014eb1a4`：左树不再全量展开分支，仍可通过展开全部恢复全展开。
  - `/case-library` 切到漫剧批创系统：用例库树同样默认只展开到模块层。

## 批判性自审

- 这不是完整 UI/UX 现代化，只是阶段 B 快修。导航动线、页面视觉密度、状态/空态/错误态统一仍未完成。
- 用例资产树仍然没有完成“模块 -> 多级分支树”的结构化归一化；本阶段只是避免默认全展开，递归树模型属于阶段 C。
- 工作台和用例库仍有重复逻辑；本阶段只抽了小型 `treeUtils`，没有抽共享 `CaseAssetBrowser`。
- 用例库默认选中第一个系统时可能是空数据，用户需要手动切系统。这是信息架构/默认上下文问题，应进入后续阶段。
- 没有做真实文件上传的浏览器端到端上传，以避免向当前业务库写入新测试文档；后端合法/非法 `doc_type` 已用集成测试覆盖。
- 前端 lint 命令目前不可用，因为仓库缺 ESLint 配置。后续若把 lint 作为门禁，应先补配置而不是把这个失败归因到业务代码。

## 回滚性

本阶段可独立回滚。后端改动集中在系统摘要统计和文档类型校验；前端改动集中在系统列表展示、知识库上传控件、三处树控件受控展开。没有跨入生成核心逻辑。
