# 用例资产浏览模式

> 本文件记录用例资产树与用例表格的真实项目约定。
> 范例文件：`web/src/components/case-assets/caseAssetModel.ts`、`CaseAssetTree.tsx`、`CaseAssetTable.tsx`、`web/src/components/CaseTreeReview.tsx`、`web/src/pages/CaseLibrary/index.tsx`。

## 适用范围

当页面需要展示系统级用例树或用例资产表时，适用本规范：

- 工作台批次审查页。
- 用例库。
- 后续任何“按文档/模块/分支浏览用例”的页面。

## 数据契约

后端 `GET /systems/:id/case-tree` 当前返回：

```typescript
interface CaseTreeDocument {
  document_id: string;
  document_title: string;
  modules: CaseTreeModule[];
}

interface CaseTreeModule {
  module_name: string;
  case_count: number;
  cases: CaseTreeCase[];
  branches?: CaseTreeBranch[];
}

interface CaseTreeBranch {
  branch_name: string;
  branch_path: string[];
  case_count: number;
  cases: CaseTreeCase[];
}
```

重要语义：

- `module.cases` 是模块下全部用例。
- `branches[].cases` 是按 `branch_path` 分组后的重复视图。
- 前端不能把 `module.cases` 与 `branches[].cases` 简单相加，否则会导致计数翻倍。

## 共享模型约定

用例资产树必须先经过 `normalizeCaseTreeDocuments`：

```typescript
const caseAssetTree = normalizeCaseTreeDocuments(treeData, { rootTitle: '全部模块' });
const selectedCases = getCasesForNode(selectedNodeKey, caseAssetTree);
```

模型输出：

```typescript
interface CaseAssetTree {
  root: CaseAssetNode;
  caseMap: Map<string, CaseTreeCase>;
}
```

节点规则：

- root -> document -> module -> branch。
- `branch_path` 每个 segment 都是一级 branch 节点。
- 中间 branch 选中时，右侧列表展示该 branch 子树下所有用例。
- `caseIds` 使用去重聚合，避免重复视图导致计数翻倍。

## 正确与错误

### 错误：页面本地拼 key 与平铺分支

```typescript
const branchNodes = mod.branches.map((branch) => ({
  key: branch.branch_path.join('/'),
  title: branch.branch_name,
  isLeaf: true,
}));
```

问题：

- `['新建编辑', '字数算法']` 会被压成一个平铺节点。
- 工作台和用例库容易各自复制一套 key 解析逻辑。
- 修一个页面时另一个页面可能漂移。

### 正确：共享模型 + 共享树组件

```tsx
<CaseAssetTree
  tree={caseAssetTree}
  selectedKey={selectedNodeKey}
  onSelect={setSelectedNodeKey}
/>
```

## 表格复用约定

基础用例列使用 `CaseAssetTable`：

```tsx
<CaseAssetTable
  cases={selectedCases}
  onOpenCase={setDetailCaseId}
  rowClickToOpen
/>
```

工作台审核动作不得写进通用表格内部，使用 `renderActions` 插槽：

```tsx
<CaseAssetTable
  cases={selectedCases}
  titleAsLink
  showIterationTag
  onOpenCase={setDetailCaseId}
  renderActions={editable ? renderReviewActions : undefined}
/>
```

原因：

- 用例库是只读资产浏览。
- 工作台包含确认、需修改、删除、自动跳下一条等审核动作。
- 共享组件只负责稳定展示结构，业务落库行为留在业务页面。

表格布局约定：

- `CaseAssetTable` 自身负责局部横向滚动，不允许长标题、质量标签或操作列撑出页面级横向滚动。
- 质量桶、核验结论、审查诊断的展示文案必须从 `caseDisplay.tsx` 共享常量取得；页面不得各自硬编码 `grounded/ungrounded/undefined/conflict`、`needs_spec/to_fix` 等内部枚举文案。
- 工作台使用 `renderActions` 时，确认、需修改、删除必须在 1024 宽度下可见；不能把关键操作长期放在横向滚动不可见区域。
- 标题列可以换行换取操作列可见性；QA 审查场景里“能操作”优先于单行标题美观。
- 数据密集资产表的标题应限制在 2 行左右，并通过原生 `title` 或详情抽屉保留完整文本；不能让 20 条分页因为超长标题变成多屏滚动墙。
- `CaseAssetTable` 可通过 `highlightedCaseId` 高亮搜索追溯命中的用例；高亮只负责定位提示，不改变用例审核状态、质量桶或落库语义。
- 树节点标题应单行省略并保留完整 `title`，数量标签必须始终可见；不能让长模块名/分支名挤掉计数或撑宽页面。
- 需要更复杂的工作台动作时，继续通过 `renderActions` 扩展，不把审核业务写进 `CaseAssetTable`。

## 用例详情抽屉字段语义

详情抽屉展示 `steps[].expected_result` 和 `expected_results` 时必须区分语义，不允许两个区域都直出为“预期结果”。

数据契约：

- `steps[].action`：单步操作动作。
- `steps[].input_data`：该步骤使用的输入数据。
- `steps[].expected_result`：该步骤执行后的可观察结果，展示文案使用“步骤预期”。
- `expected_results`：整条用例最终判定口径，展示文案使用“通过标准”。

实现锚点：`web/src/components/CaseDetailDrawer.tsx:602` 展示测试步骤，`web/src/components/CaseDetailDrawer.tsx:656` 展示通过标准。

错误：

```tsx
<Text>测试步骤</Text>
<Steps description={`预期结果：${step.expected_result}`} />

<Text>预期结果</Text>
{expectedResults.map(...)}
```

问题：

- Ant Design `Steps` 的 description 默认弱化为灰色说明，长步骤内容会像备注。
- 步骤内预期和整条用例汇总都叫“预期结果”，QA 无法判断哪个是执行脚本、哪个是最终通过标准。

正确：

```tsx
<Text>测试步骤</Text>
<Text>步骤预期</Text>
<div>{step.expected_result}</div>

<Text>通过标准</Text>
{expectedResults.map(...)}
```

为什么：

- 每步预期用于指导执行过程中的检查点。
- 通过标准用于整条用例的最终判定。
- 只改前端展示文案和布局即可对齐语义，不需要迁移后端字段或生成结构。

## 用例资产页工作台约定

用例资产 `/case-library` 是 QA 复用与追溯已沉淀用例的工作台，不应只是“左树右表”的数据展示页。

实现约定：

- 页面顶部必须说明当前页面用于浏览主集候选、全部资产或待处理资产；不要让具备 QA 背景但首次使用本平台的人猜“用例库”和“审核中心”的区别。
- 资产视图使用清晰的三态语义：
  - 主集候选：默认视图，只看进入主集桶的候选用例；是否可复用仍要结合审查状态判断。
  - 全部资产：包含主集候选、重复和待处理资产，用于全量追溯。
  - 待处理资产：聚焦待审、需修改、待澄清或核验不确定资产。
- 筛选项和质量标签必须使用业务语义中文文案，例如“主集候选 / 规格待澄清 / 生成待修正 / 有依据 / 无依据 / 规格未定义 / 与PRD冲突”；内部枚举值只作为接口参数，不直接暴露给 QA。
- 主集候选视图中如果仍存在 `pending` 或 `needs_modification` 用例，页面必须显式提示这批资产仍有待处理债务，并提供“查看待处理资产”和“去工作台审查”等恢复动作；不能只靠指标数字让首次使用本平台的 QA 自己推断。
- 顶部主动作必须有“上传/生成”入口，并跳到当前系统知识库；用例资产页不能成为主流程死路。
- 首次进入且用户尚未选择系统时，默认系统应优先选择已有批次/文档的系统；不要按名称字母序落到一个空系统，让用户误以为资产池为空。统计字段不可用时再回退到系统选项顺序。
- 筛选条应按“系统 -> 资产视图 -> 批次范围 -> 质量筛选”排列，筛选项可以换行，但要保留标签，避免只靠 placeholder 表达含义。
- 批次范围未手动选择时，页面必须说明后端默认语义：按每份文档最新的可见批次聚合。可见批次状态为 `pending_review`、`completed`、`archived`，不包含运行中、失败、挂起或排队中的批次。
- 批次范围列表加载失败时，下拉不可伪装成正常空列表；应禁用或标记 warning，并明确说明资产仍按默认规则展示，不能据此判断没有历史批次，同时提供重试动作。
- 指标条应显示当前视图用例、选中范围、文档数、模块数、分支节点、P0、已确认、待处理、重复标记等资产判断信息。
- 系统列表或用例树加载失败时必须显示页面级错误态和重试动作；指标条不得把失败态显示成 0 条资产。
- 左侧树必须有搜索、展开全部、收起全部，且树容器要有最大高度和局部滚动；不能默认展开所有分支并把页面拉得很长。
- 右侧表格标题必须显示当前选中范围、范围类型、批次范围和资产视图标签。
- 空态必须给出恢复路径：未选系统去系统管理；当前范围无资产时允许重置筛选或去知识库上传/生成。
- 页面只能使用 `normalizeCaseTreeDocuments`、`CaseAssetTree`、`CaseAssetTable`，不得重新复制树构建或表格列逻辑。

为什么：

- 具备 QA 背景但首次使用本平台的人，最需要知道“我现在看的是主集候选、全量候选，还是待处理债务”。
- `view=stable` 当前表达的是主集桶候选，不等同于“已确认可复用”；如果返回用例仍是 `review_status=pending`，前端文案不得称为稳定可复用资产。
- 只把 `pending` 数量放在指标条里仍然不够；当默认视图里混有待审债务时，应主动给出下一步动作，否则专业 QA 第一次进入平台也容易把主集候选误判成可直接交付资产。
- 用例资产是生成链路后的沉淀结果，也必须能回到上传/生成入口，保持完整主流程闭环。
- 默认落到空系统会让“资产页没有资产”的错误印象先入为主；默认选择有生成痕迹的系统更符合工作台入口的任务导向。
- “默认最新可见批次”如果不解释，会被误解成“全系统最新一个批次”或“所有历史批次”；而真实后端规则是按文档取最新可见批次聚合，必须在界面上说清楚。
- 大量模块/分支的系统里，树默认全展开会导致用户必须滚很久才能点到目标模块；局部滚动和默认浅展开更符合数据密集后台实践。

## 搜索约定

- `CaseAssetTree` 的搜索是树节点搜索，支持模块/分支标题，也支持用例标题命中后保留祖先链。
- 工作台已有右侧用例标题搜索，当前不与左树搜索合并。
- 后续若合并搜索语义，必须明确“树搜索是否过滤右表”，避免用户误解。

## 测试要求

修改用例资产模型时必须跑：

```bash
cd web
npm run test:case-assets
```

至少覆盖：

- 多级 `branch_path` 递归建树。
- 选中 module 返回子树全部用例。
- 选中中间 branch 返回子树全部用例。
- 搜索命中嵌套用例标题时保留祖先链。
- 默认展开 root + document 层，不默认展开所有 branch。

生产构建仍使用：

```bash
cd web
npm run build
```
