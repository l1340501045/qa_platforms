# 阶段 C 技术设计：用例资产树与共享浏览器

## 设计目标

把工作台和用例库中重复的“用例资产树 + 用例表 + 详情抽屉 + 标签展示”逻辑收敛到共享模型和组件，并支持模块下的递归分支树。

本阶段解决的是结构和复用，不做整体视觉重构。

## 当前证据

- `web/src/components/CaseTreeReview.tsx` 自行实现：
  - `allCasesFromTree`
  - `casesFromDoc`
  - `branchPathKey`
  - `encodeTreePart/decodeTreePart`
  - `SelectedNode`
  - Ant Tree `DataNode` 构建
  - 标签颜色映射和可信度展示
- `web/src/pages/CaseLibrary/index.tsx` 也有一套近似实现。
- 当前后端 `CaseTreeDocument.modules[].branches[]` 将 `branch_path` 表达为数组，但前端渲染成单层分支节点，无法表示模块内多级分支树。

## 共享模型

新增纯模型层，建议路径：

- `web/src/components/case-assets/caseAssetModel.ts`

核心类型：

```ts
export type CaseAssetNodeType = 'root' | 'document' | 'module' | 'branch';

export interface CaseAssetNode {
  key: string;
  type: CaseAssetNodeType;
  title: string;
  count: number;
  children: CaseAssetNode[];
  caseIds: string[];
  meta: {
    documentId?: string;
    moduleName?: string;
    branchPath?: string[];
  };
}
```

核心函数：

- `normalizeCaseTreeDocuments(tree: CaseTreeDocument[], options?): CaseAssetNode`
- `getCasesForNode(nodeKey, root, caseMap): CaseTreeCase[]`
- `filterAssetTree(root, keyword): CaseAssetNode`
- `getDefaultExpandedKeys(root): string[]`
- `toAntTreeData(root): DataNode[]`

## 递归分支规则

输入：

```ts
branch_path: ['账户选择弹窗（批创页）', '分页规则']
```

目标树：

```text
账户授权
  账户选择弹窗（批创页）
    分页规则
      用例列表
```

规则：

- `module_name` 作为模块节点。
- 每个 `branch_path` segment 逐级创建 branch 节点。
- 同一路径复用已有节点，count 聚合。
- 选中模块节点时包含模块下所有分支和模块直属 cases。
- 选中任意 branch 节点时包含该 branch 子树所有 cases。

## 共享展示组件

建议路径：

- `web/src/components/case-assets/CaseAssetTree.tsx`
- `web/src/components/case-assets/CaseAssetTable.tsx`
- `web/src/components/case-assets/CaseAssetBrowser.tsx`
- `web/src/components/case-assets/caseDisplay.tsx`

职责：

- `CaseAssetTree`：树搜索、展开/收起、受控选中、滚动容器。
- `CaseAssetTable`：用例列定义、标签展示、点击详情。
- `CaseAssetBrowser`：组合树和表，按 `mode='review' | 'library'` 控制操作列。
- `caseDisplay`：优先级、bucket、verdict、review status、trust level 的单一展示来源。

## 兼容策略

- 第一版不改后端 `GET /systems/:id/case-tree` 契约。
- 前端共享模型兼容当前 `CaseTreeDocument`。
- `CaseTreeReview` 可以先包一层 `CaseAssetBrowser mode='review'`，保留原 props。
- `CaseLibraryPage` 使用 `CaseAssetBrowser mode='library'`。

## 风险控制

- 先写模型单测，再替换 UI。
- 先替换用例库，再替换工作台；工作台包含审核操作，风险更高。
- 替换工作台时必须保留：
  - 审核确认。
  - 需修改填写意见。
  - 删除确认。
  - 详情抽屉。
  - 自动跳下一条。
  - 父组件 `onAllCasesChange`。

## 批判性 Review 要点

- 是否真的消除了重复模型，而不是多套代码外面套一层壳。
- 是否能表达多级分支，而不是把 `branch_path.join('/')` 换个展示样式。
- 是否保持工作台审核主流程可用。
- 是否把视觉重构提前塞入本阶段。
