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
- 工作台使用 `renderActions` 时，确认、需修改、删除必须在 1024 宽度下可见；不能把关键操作长期放在横向滚动不可见区域。
- 标题列可以换行换取操作列可见性；QA 审查场景里“能操作”优先于单行标题美观。
- 需要更复杂的工作台动作时，继续通过 `renderActions` 扩展，不把审核业务写进 `CaseAssetTable`。

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
