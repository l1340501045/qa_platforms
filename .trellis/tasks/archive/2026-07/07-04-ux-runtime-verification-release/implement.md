# 阶段 E 执行计划

## 前置门禁

- 阶段 A 完成。
- 阶段 B 完成。
- 阶段 C/D 根据用户批准范围完成。
- 当前工作区无未识别混入改动。

## E1 启动环境

1. 检查 Docker infra：
   - `docker ps`
   - Postgres/Redis/MinIO healthy。
2. 启动 API。
3. 启动 worker。
4. 启动 frontend。
5. 健康检查：
   - `curl http://127.0.0.1:8000/health`
   - `curl http://127.0.0.1:3000`

## E2 自动化/命令验证

后端：

```bash
uv run pytest tests/platform_api
uv run pytest tests/testcase_generator -k "not integration"
```

前端：

```bash
cd web
npm run lint
npm run typecheck
npm run build
```

## E3 浏览器/Playwright 验收

核心页面：

- `/systems`
- `/systems/6b0ea53c-f734-4bc9-8506-663d47107b9d/documents`
- `/batches/6f30e1bd-89ad-4e98-878c-4b48014eb1a4`
- `/case-library`
- `/review`
- `/exports`

检查项：

- 页面无 JS runtime error。
- 系统统计真实。
- 上传类型控件可见。
- 树默认不全展开，内部滚动。
- 用例详情抽屉可打开。
- 审核操作可用或按状态禁用合理。
- 导出入口可达。

## E4 报告

写 `release-verification-report.md`，包含：

- 环境状态。
- 测试命令结果。
- 页面截图/Playwright 结果。
- 主流程通过/失败矩阵。
- 未验证项和原因。
- 发布风险和回滚建议。

## E5 批判性 Review

写 `review.md`：

- 证据是否足够支撑发布。
- 哪些风险仍需用户接受。
- 是否需要回到 B/C/D 修复。
- 是否可以进入最终归档/提交。
