# 页面骨架与信息架构模式

> 范例文件：`web/src/layouts/MainLayout.tsx`、`web/src/components/layout/*`、`web/src/components/common/EmptyState.tsx`。
> 适用范围：系统列表、知识库、工作台、用例资产、搜索、导出等企业后台页面。

## 目标用户口径

页面应面向“具备 QA 背景、但首次使用本平台的人”，不是零基础教学页。

- 正确：说明当前页面负责什么、下一步动作在哪里、状态意味着什么。
- 错误：用大段教程文案解释 QA 是什么，或把页面做成营销 landing。

## 主导航约定

主导航按 QA 工作流排序，而不是按数据库对象名排序：

1. 工作台：`/review`
2. 项目/系统：`/systems`
3. 用例资产：`/case-library`
4. 全局搜索：`/search`
5. 导出中心：`/exports`

`/batches/:batchId` 归属工作台高亮；`/systems/:systemId/documents` 与 `/documents/:documentId` 归属项目/系统高亮。

首页 `/` 默认跳转工作台，旧路由必须保持可访问。

## 共享组件职责

| 组件 | 职责 | 不应承担 |
|---|---|---|
| `PageShell` | 页面主容器，控制最大宽度与基础文字颜色 | 业务数据加载 |
| `PageHeader` | 页面标题、页面职责说明、顶部操作 | 页面内复杂筛选 |
| `FilterBar` | 横向筛选控件分组，可换行 | 表单提交/校验逻辑 |
| `MetricStrip` | 页面级统计摘要 | 业务明细表格 |
| `SplitPane` | 左导航/右内容的树表分栏，可窄屏换行 | 树节点构建逻辑 |
| `EmptyState` | 空态说明和恢复动作 | 接口错误重试策略 |

## 页面接入模式

```tsx
<PageShell>
  <PageHeader
    eyebrow="工作台"
    title="待处理批次"
    description="优先处理待澄清、失败和待审核批次。"
  />

  <MetricStrip items={metricItems} />

  <FilterBar>
    <Select />
    <Input.Search />
  </FilterBar>

  <SplitPane left={<Tree />} right={<Table />} />
</PageShell>
```

## 数据密集页面规则

- 指标条只放页面级摘要，不替代表格。
- 分栏左侧用于树/目录/范围选择，右侧用于主要列表或表格。
- `SplitPane` 已允许窄屏换行；页面不要再写固定宽度撑破容器。
- 入口页空数据使用 `EmptyState`，必须给出下一步动作或恢复路径。
- 表格、树、上传、审查动作继续使用 Ant Design 原生组件和现有 store/service 数据流。

## 工作台待办队列

工作台 `/review` 不是单纯“审核列表”，必须先暴露 QA 最需要处理的批次队列：

- 待澄清：`status=suspended`
- 失败：`status=failed`
- 生成中：`status=running`
- 待审核：`status=pending_review`

实现约定：

- 使用现有 `listBatches({ status, page: 1, per_page: 3 })` 分状态读取，不为 UI 聚合改后端契约。
- 队列卡片只显示最近少量批次和总数；完整浏览仍由下方表格分页负责。
- 队列卡片的“筛选”按钮只改变下方表格状态筛选，不跳走页面。
- 批次动作文案必须匹配状态，不要所有状态都叫“去审核”。

```tsx
switch (batch.status) {
  case 'suspended':
    return '处理澄清';
  case 'failed':
    return '查看失败';
  case 'running':
    return '查看进度';
  case 'pending_review':
    return '去审核';
}
```

为什么：

- 首次使用平台的 QA 需要先知道“今天该处理什么”，而不是先理解所有批次状态。
- 生成中/失败/待澄清/待审核是不同工作动作，统一成“去审核”会误导。
- 这种聚合只使用现有 API 查询能力，不影响生成 pipeline。

## Wrong vs Correct

### Wrong：页面各自写标题、筛选和空态

```tsx
<div style={{ padding: 24 }}>
  <h2>审核中心</h2>
  <Select />
  {items.length === 0 && <Empty description="暂无数据" />}
</div>
```

问题：

- 页面职责不清。
- 筛选区、空态、间距每页漂移。
- 首次使用平台的人不知道下一步该做什么。

### Correct：共享骨架 + 页面业务内容

```tsx
<PageShell>
  <PageHeader
    eyebrow="工作台"
    title="待处理批次"
    description="从这里进入批次详情完成审查、迭代和落库。"
  />
  <FilterBar>
    <Select placeholder="批次状态" />
  </FilterBar>
  <Table />
</PageShell>
```

## 验证要求

修改页面骨架或关键入口页时至少验证：

- `npm run build`
- 相关共享组件/模型测试，例如 `npm run test:case-assets`
- 1440 宽关键路由无白屏/运行时错误
- 1024 宽关键路由无页面级横向溢出
- 工作台 `/review` 必须验证四个待办队列可见，队列“筛选”按钮能驱动下方表格筛选。

当前 `npm run lint` 依赖 ESLint 配置；若仓库没有配置文件，记录为环境/基建缺口，不作为页面改动失败。
