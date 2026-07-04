# 阶段 D 执行计划

## 前置门禁

- 阶段 A 完成。
- 阶段 B 完成。
- 阶段 C 完成，或用户明确决定先跳过 C。
- 执行前读取父任务和本任务材料。

## D1 设计 token 与基础组件

1. 梳理当前 Ant Design 使用方式。
2. 新增轻量布局/通用组件：
   - `PageShell`
   - `PageHeader`
   - `FilterBar`
   - `MetricStrip`
   - `SplitPane`
   - `StatusTag`
   - `EmptyState`
3. 不引入新 UI 框架。

## D2 MainLayout 信息架构

1. 调整导航文案和排序：
   - 工作台。
   - 项目/系统。
   - 知识库入口保留在系统下。
   - 审查。
   - 用例资产。
   - 搜索。
   - 导出。
2. 保持现有 route mapping。
3. Header 显示当前系统/批次上下文和通知。

## D3 页面逐步替换

推荐顺序：

1. `/systems`
   - 系统列表更适合扫描。
   - 显示文档数、批次数、最近活动、下一步动作。
2. `/systems/:systemId/documents`
   - 上传区、类型选择、文档列表、文档树统一布局。
3. `/batches/:batchId`
   - 阶段进度、澄清、筛选、用例浏览器、底部操作栏统一。
4. `/case-library`
   - 资产视图和树表布局强化。
5. `/review`
   - 待处理批次更清晰。
6. `/exports`
   - 状态和下载入口清晰。

## D4 视觉验收

至少检查：

- 桌面宽度：1440px。
- 窄屏：1024px。
- DevTools 半屏场景。
- 长系统名、长模块名、长用例标题。
- 空数据、加载中、失败态。

## 验证命令

```bash
cd web
npm run lint
npm run typecheck
npm run build
```

运行态截图：

- `/systems`
- `/systems/:systemId/documents`
- `/batches/:batchId`
- `/case-library`
- `/review`
- `/exports`

## 产物 Review

完成后写 `review.md`：

- 页面动线是否更符合 QA 工作流。
- 哪些页面仍然旧。
- 是否有主流程入口消失或变难找。
- 是否有视觉破版证据。
- 是否过度抽象。
