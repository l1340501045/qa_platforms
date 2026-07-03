# 阶段 D 技术设计：信息架构与视觉重构

## 设计目标

在阶段 B/C 稳定后，重构整体信息架构和视觉系统，让 QA 新手能按日常工作流完成任务。

本阶段做“工作流和页面骨架重构”，不是营销式改版。

## 目标信息架构

推荐导航从对象名转为工作流：

1. 工作台
   - 待澄清。
   - 待审核。
   - 运行中/失败批次。
   - 最近系统与批次。
2. 项目/系统
   - 系统列表。
   - 文档数/批次数/最近活动。
   - 进入知识库或新建生成。
3. 知识库
   - 文档上传。
   - 文档类型。
   - 解析状态。
   - 文档树。
4. 生成与审查
   - 批次详情。
   - 阶段进度。
   - 澄清。
   - 用例审核。
   - 迭代与落库。
5. 用例资产
   - 稳定主集。
   - 全部资产。
   - 待分类。
6. 导出中心
   - 导出任务。
   - 文件状态。

## 页面组件系统

建议新增：

- `web/src/components/layout/PageShell.tsx`
- `web/src/components/layout/PageHeader.tsx`
- `web/src/components/layout/FilterBar.tsx`
- `web/src/components/layout/MetricStrip.tsx`
- `web/src/components/layout/SplitPane.tsx`
- `web/src/components/common/StatusTag.tsx`
- `web/src/components/common/EmptyState.tsx`

设计要求：

- 不把 page section 做成层层嵌套 card。
- 企业后台保持信息密度和可扫描性。
- 按钮优先用图标 + 清晰文案，破坏性动作显著区分。
- 状态颜色统一，不在每页重新定义。
- 文字不溢出，不遮挡。

## 路由兼容

第一版保留现有路由：

- `/systems`
- `/systems/:systemId/documents`
- `/documents/:documentId`
- `/review`
- `/batches/:batchId`
- `/case-library`
- `/search`
- `/exports`

可以新增 `/dashboard` 或让 `/` 指向工作台，但不能破坏已有深链接。

## 视觉策略

- 使用 Ant Design 5 现有组件，不引入重型 UI 框架。
- 通过 CSS/tokens 统一间距、字号、边框、状态色。
- 不使用大面积渐变、装饰性背景、营销 hero。
- 重点页面是工作台、知识库、批次审查、用例资产。

## 风险控制

- 不在阶段 D 改后端契约，除非是读取已有数据。
- 不在阶段 D 改 case 生成/审核语义。
- 每个页面逐个替换，不做一次性全站 rewrite。
- 保留旧路由和核心按钮，避免主流程入口消失。

## 批判性 Review 要点

- 是否真的让 QA 新手更容易知道下一步。
- 是否只是“换皮”，没有改善任务流。
- 是否保留主流程所有入口。
- 是否引入太多抽象组件导致页面难维护。
- 是否有截图证明视觉和布局没有破版。
