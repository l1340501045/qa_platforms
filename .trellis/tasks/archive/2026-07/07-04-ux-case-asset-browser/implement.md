# 阶段 C 执行计划

## 前置门禁

- 阶段 A 已完成或用户明确放行。
- 阶段 B 已完成，树默认折叠/滚动的低风险修复已经落地。
- 执行前读取父任务和本任务的 `prd.md/design.md/implement.md`。

## C1 模型层 TDD

1. 新增测试文件，建议：
   - `web/src/components/case-assets/caseAssetModel.test.ts`
2. 覆盖场景：
   - 单文档、单模块、单层分支。
   - 单模块、多级 `branch_path`。
   - 多个分支共享父路径。
   - 选中模块返回全部子树 cases。
   - 选中中间 branch 返回子树 cases。
   - 搜索命中模块/分支/用例标题时保留祖先链。
3. 实现 `caseAssetModel.ts`，直到测试通过。

## C2 抽展示常量与工具

1. 新增 `caseDisplay.tsx` 或 `caseDisplay.ts`。
2. 迁移重复的：
   - `PRIORITY_COLOR`
   - `REVIEW_TAG`
   - `BUCKET_TAG`
   - `VERDICT_COLOR`
   - `REVIEW_ISSUE_TAG`
   - `getTrustDisplay`
3. `CaseTreeReview` 和 `CaseLibraryPage` 先只替换 import，行为不变。

## C3 抽 CaseAssetTree

1. 新增 `CaseAssetTree.tsx`。
2. 支持：
   - `treeRoot`
   - `selectedKey`
   - `expandedKeys`
   - `onSelect`
   - 搜索
   - 展开全部/收起全部
   - 固定高度/滚动
3. 先在 `CaseLibraryPage` 使用。

## C4 抽 CaseAssetTable / Browser

1. 新增 `CaseAssetTable.tsx`，抽用例列定义。
2. 新增 `CaseAssetBrowser.tsx`。
3. 用例库切换到 `CaseAssetBrowser mode='library'`。
4. 工作台切换到 `CaseAssetBrowser mode='review'`，保留原审核 props。

## C5 回归验证

```bash
cd web
npm run lint
npm run typecheck
npm run build
```

必要时运行前端测试命令（若项目已有）。

运行态验收：

- `/case-library` 三种资产视图可切换。
- `/batches/:batchId` 审核确认/需修改/删除可用。
- 多级 branch_path 显示为递归树。
- 搜索后树和右侧列表一致。

## 产物 Review

完成后写 `review.md`，必须说明：

- 重复代码减少在哪里。
- 多级树是否用测试证明。
- 工作台审核主流程是否被完整回归。
- 有哪些视觉问题留给阶段 D。
- 是否可分 commit 回滚。
