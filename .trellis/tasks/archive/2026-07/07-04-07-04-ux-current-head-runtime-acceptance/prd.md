# 当前 HEAD UI/UX 运行态验收

## 目标

用当前 `feat/qa-platform-ux-modernization` 最新代码做一次轻量运行态验收，补齐父任务 `final-integration-review.md` 中指出的最大证据缺口：阶段 E 的浏览器证据不是最新 HEAD。

本次 UI/UX 判断口径是：面向“具备 QA 背景、但第一次使用本平台的人”。目标不是把页面做成零基础 QA 教程，而是让 QA 在第一次上手时能清晰判断当前页面负责什么、主流程下一步在哪里、状态是否可继续。

## 范围

- 启动或复用 Docker infra、API、worker、frontend。
- 验证服务健康：
  - `curl http://127.0.0.1:8000/health`
  - `curl -I http://127.0.0.1:3000`
  - Celery inspect ping
- 用浏览器/自动化方式巡检核心页面：
  - `/systems`
  - `/systems/:systemId/documents`
  - `/documents/:documentId?from=knowledge&system_id=:systemId`
  - `/review?status=pending_review`
  - `/batches/:batchId?from=review&status=pending_review`
  - `/case-library`
  - `/search?q=CBO&system_id=:systemId`
  - `/exports`
- 特别关注最后两个改动：
  - 历史 `other` 文档重标注入口是否可见。
  - 系统列表稳定排序后页面仍能展示真实统计。

## 不做

- 不跑真实 LLM 批次。
- 不提交审查确认/需修改/删除等破坏性 mutation。
- 不修改 `src/testcase_generator/**`。
- 不把运行日志、截图缓存、大体积审查产物提交进仓库；只保留精简报告和必要文本证据。

## 验收标准

- API、worker、frontend 至少达到可访问状态，或报告明确说明阻塞原因。
- 核心页面无白屏、无明显页面级横向溢出、无阻断主流程的前端运行错误。
- 页面文本能证明当前信息架构仍围绕 QA 工作流：项目/知识库/生成审查/资产/搜索/导出。
- 报告必须批判性说明：
  - 是否足以支持合入 `main`。
  - 哪些仍需要公司网络下真实 LLM 批次。
- 哪些仍需要真人 QA 首次使用本平台的上手验收。
