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

`SplitPane` 可通过 `rightMinWidth` 声明右侧主工作区的最小舒适宽度。树表审查页应优先保证右侧表格可操作；当容器不够宽时应上下堆叠，不要把操作列长期藏在横向滚动深处。

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

## 全局布局 Reset

入口 `web/src/main.tsx` 必须加载 `web/src/global.css`，用于消除浏览器默认 body margin 和统一 `box-sizing`。

约定：

- `html`、`body`、`#root` 的 `margin` 必须为 0，避免弹窗、布局容器或 100vw 场景出现 8px 横向滚动。
- `box-sizing: border-box` 应作用到所有元素及伪元素。
- 页面根节点不应出现横向滚动；数据表格需要横向空间时，应该在表格自身使用 `scroll.x`，不要撑开页面。

## 数据密集页面规则

- 指标条只放页面级摘要，不替代表格。
- 分栏左侧用于树/目录/范围选择，右侧用于主要列表或表格。
- `SplitPane` 已允许窄屏换行；页面不要再写固定宽度撑破容器。
- 入口页空数据使用 `EmptyState`，必须给出下一步动作或恢复路径。
- 表格、树、上传、审查动作继续使用 Ant Design 原生组件和现有 store/service 数据流。

## 项目/系统入口列表

项目/系统 `/systems` 是完整生成链路的第一站，不应只是系统管理卡片墙。

实现约定：

- 默认视图应适合扫描多个系统，优先使用表格/列表，而不是大卡片网格。
- 顶部指标至少暴露系统总数、当前页有资料/批次、待上传资料、已有批次、文档数、批次数。
- 列表应显示系统名称、描述、资料状态、文档数、批次数、最近活动。
- “上传资料 / 发起生成 / 进入知识库”是主流程下一步动作，必须在系统主列或首屏可见；不要只放在横向滚动深处。
- 编辑/删除是管理动作，可以弱化，但仍应在窄屏首屏可见，并保留删除确认弹窗。
- 当前没有后端搜索契约时，搜索/排序只能声明为当前页筛选，不要伪装成全局搜索。
- 页面行点击可以进入知识库，但不能作为唯一入口；必须有可见文字动作。

为什么：

- 具备 QA 背景但首次使用本平台的人，需要先判断“哪个系统还没资料、哪个系统已有批次、下一步该上传还是生成”。
- 企业后台对象多时，卡片墙扫描效率差；表格能承载状态、数量、最近活动和下一步动作。
- 入口页的工作流动作比管理图标更重要，不能让用户从“编辑/删除”推断主流程。

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

- 首次使用本平台的 QA 需要先知道“今天该处理什么”，而不是先理解所有批次状态。
- 生成中/失败/待澄清/待审核是不同工作动作，统一成“去审核”会误导。
- 这种聚合只使用现有 API 查询能力，不影响生成 pipeline。

## 知识库主流程入口

知识库 `/systems/:systemId/documents` 必须把“上传资料 -> 发起生成 -> 去审查”串起来，而不是只做文档仓库。

实现约定：

- 页面顶部提供 3 步主流程提示：上传资料、生成批次、进入审查。
- 文档列表必须有显式“下一步”操作列。
- “生成用例”复用现有 `triggerGeneration(documentId)`，成功后跳转 `/batches/:batchId`。
- 列表里的生成动作必须有确认弹窗，避免误触发生成任务。
- 行点击仍可进入 `/documents/:documentId` 详情；按钮点击要 `stopPropagation()`，避免和行点击冲突。
- 该入口只新增前端动线，不改变生成配置、worker、pipeline 或后端契约。

```tsx
const handleGenerateDocument = (doc: Document, event?: React.MouseEvent) => {
  event?.stopPropagation();
  Modal.confirm({
    title: '生成测试用例',
    onOk: async () => {
      const res = await triggerGeneration(doc.id);
      navigate(`/batches/${res.batch_id}`);
    },
  });
};
```

为什么：

- QA 上传完资料后，下一步应直接可见；不应要求用户猜到“先进入文档详情再生成”。
- 生成成功后进入批次工作台，符合平台主流程和工作台待办设计。
- 保留文档详情入口，满足查看解析详情、知识速查表和关联文档等次级任务。

## 文档详情追溯节点

文档详情 `/documents/:documentId` 是“资料是否可用于生成”的判断页，不应只是数据库字段展示页。

实现约定：

- 页面必须接入 `PageShell` / `PageHeader` / `MetricStrip`，顶部直接暴露文档类型、导入状态、嵌入状态、关联数。
- 顶部主动作必须保留“生成测试用例”，并复用现有 `triggerGeneration(documentId)`；成功后跳转 `/batches/:batchId`。
- 生成动作必须有确认弹窗，避免误触发真实生成批次。
- 保留“添加关联”“知识速查表”“解析详情”等已有能力，不改变 API 契约。
- 关联文档表格需要使用 `scroll.x`，避免长标题或多列在 1024 宽度撑破页面。
- 加载失败或文档为空时使用 `EmptyState` 给出返回路径，不能无限显示 loading。

为什么：

- 首次使用本平台的 QA 从知识库进入详情后，需要知道这份资料的状态、上下文是否齐、下一步能否生成。
- 关联文档是测试资产追溯链的一部分，应与生成动作放在同一工作流里呈现。
- 详情页只改前端动线，不改变文档解析、知识图谱、生成 pipeline 或 worker 逻辑。

## 批次工作台审查执行面

批次工作台 `/batches/:batchId` 是“生成与审查”的执行面，不是单纯的用例列表页。

实现约定：

- 页面顶部必须保留批次状态摘要，至少包含批次状态、阶段进度、用例总数、待审、需修改、待澄清。
- 状态提示必须给出当前下一步：等待 Worker、处理澄清、查看进度、进入审查、重试失败、落库后查看资产。
- 阶段进度需要独立成区，不能只把 `Steps` 混在筛选栏附近。
- 待澄清状态必须有显式“处理澄清”入口；即使自动弹窗被关闭，页面内也要能重新打开。
- 审查态必须保留“触发迭代”和“落库归档”入口；底部操作栏可 sticky，但不能遮挡表格内容。
- 左侧树只负责定位文档/模块/分支，右侧表格负责逐条审查；复用 `CaseTreeReview` + `CaseAssetTree` + `CaseAssetTable`，不得复制树构建逻辑。
- 1024 宽度下树表应上下堆叠或保证右侧表格核心操作列可见；表格需要局部 `scroll.x`，但不能造成页面级横向滚动。
- 加载态不要使用 Ant Design v5 不支持的独立 `Spin tip` 模式；若需要文案，用 `Spin` + 邻近文本。

为什么：

- 具备 QA 背景但首次使用本平台的人，需要先判断“这个批次卡在哪里”和“我现在该做什么”，再进入具体用例审查。
- 质量门、阶段进度、审查动作是同一个工作流的连续节点，拆散后会让主流程变成猜菜单。
- 审查表格的行内操作是核心工作动作，不能只依赖用户发现横向滚动。

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
- 首次使用本平台的 QA 不知道下一步该做什么。

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
- 知识库 `/systems/:systemId/documents` 必须验证三步主流程提示和“生成用例”入口可见。
- 文档详情 `/documents/:documentId` 必须验证状态指标、生成确认弹窗、关联文档表格和空态恢复路径。

当前 `npm run lint` 依赖 ESLint 配置；若仓库没有配置文件，记录为环境/基建缺口，不作为页面改动失败。
