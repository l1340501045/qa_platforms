# 阶段 E：运行态验收与发布回归 PRD

## 目标

在 UI/UX 重构完成后，启动真实本地环境，用浏览器/Playwright 和测试命令验证主流程、关键页面和可部署性，形成发布前验收报告。

## 前置依赖

- 阶段 A 完成。
- 阶段 B 完成。
- 阶段 C/D 根据用户确认的范围完成。

## 必做

- 启动 Docker infra、API、worker、frontend。
- 验证 `/systems`、`/systems/:id/documents`、`/batches/:id`、`/case-library`、`/review`、`/exports`。
- 验证上传文档类型、树折叠/搜索/滚动、用例审查操作。
- 运行后端测试、前端 lint/type-check/build。
- 产出验收报告，包含截图或 Playwright 证据、失败项、残余风险。

## 不做

- 不跑昂贵真实 LLM 批次，除非用户在公司网络环境明确要求。
- 不把验收报告里的运行数据误提交为业务代码。

## 验收

- 本地从干净仓库可按文档启动。
- 主流程没有阻断性 UI 回归。
- 报告明确说明哪些验证通过、哪些未验证、为什么。
