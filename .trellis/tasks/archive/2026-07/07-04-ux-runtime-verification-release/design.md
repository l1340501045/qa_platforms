# 阶段 E 技术设计：运行态验收与发布回归

## 设计目标

用真实本地环境证明 UI/UX 重构没有破坏主流程，并形成可审查的发布前报告。

## 验收范围

### 服务

- Docker infra：Postgres、Redis、MinIO。
- API：FastAPI。
- Worker：Celery。
- Frontend：Vite/React。

### 页面

- `/systems`
- `/systems/:systemId/documents`
- `/documents/:documentId`
- `/review`
- `/batches/:batchId`
- `/case-library`
- `/search`
- `/exports`

### 主流程

- 系统列表查看真实统计。
- 上传 PRD，并选择文档类型。
- 文档列表展示类型。
- 批次页面展示状态。
- 澄清弹窗可用。
- 用例审查确认/需修改/删除可用。
- 用例资产树可搜索、折叠、滚动。
- 导出入口可达。

## 证据要求

- 命令输出：
  - 后端测试。
  - 前端 lint/typecheck/build。
  - 健康检查。
- 截图或 Playwright 结果：
  - 每个核心页面一张桌面截图。
  - 至少一个窄屏截图。
- 数据证据：
  - 系统统计接口响应。
  - 上传 `doc_type` 请求/响应。
  - 用例树默认展开状态。

## 不跑昂贵真实批次

如果当前不在公司网络或 LLM 网关不可达，不跑真实 LLM 批次。可以使用已有批次和本地数据验证 UI。

真实跑批需要用户明确批准。

## 批判性 Review 要点

- 哪些验证是强证据，哪些只是冒烟。
- 哪些主流程环节没有验证到。
- 是否因为环境不可用而跳过关键检查。
- 是否存在“测试通过但用户动线仍糟糕”的问题。
