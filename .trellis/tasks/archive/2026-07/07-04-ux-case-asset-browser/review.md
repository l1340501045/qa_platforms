# 阶段 C Review：用例资产树与共享浏览器

## 结论

阶段 C 已完成“共享用例资产树模型 + 共享树组件 + 共享表格基础列 + 工作台/用例库复用”的核心目标。多级 `branch_path` 现在会渲染为递归树，例如真实数据中的：

```text
标题包
  新建编辑
    字数算法
```

而不是继续把 `新建编辑 / 字数算法` 平铺成一个分支节点。

## 已完成

- 新增纯模型层 `caseAssetModel.ts`：
  - `normalizeCaseTreeDocuments`
  - `getCasesForNode`
  - `filterCaseAssetTree`
  - `getDefaultExpandedKeys`
  - `collectCaseAssetKeys`
- 新增共享树组件 `CaseAssetTree.tsx`：
  - 搜索
  - 展开全部 / 收起全部
  - 默认只展开 root + 文档层
  - 固定高度与内部滚动
  - 复用同一套递归树数据
- 新增共享展示工具 `caseDisplay.tsx`：
  - 优先级颜色
  - Review 状态标签
  - 质量桶 / verdict / 审查诊断标签
  - 可信度展示
- 新增共享表格组件 `CaseAssetTable.tsx`：
  - 统一标题、优先级、质量、可信度、状态列。
  - 工作台审核操作通过 `renderActions` 插槽注入，不把落库行为藏进通用组件。
  - 用例库保留点击行打开详情；工作台保留标题链接打开详情。
- `CaseTreeReview` 和 `CaseLibrary` 已改为复用共享模型与共享树组件。
- 工作台审核动作仍保留：
  - 确认
  - 需修改
  - 删除
  - 详情抽屉
  - 自动跳下一条
  - `onAllCasesChange`

## 验证证据

- RED：`npm run test:case-assets` 初次失败，原因是 `caseAssetModel.ts` 不存在。
- GREEN：`npm run test:case-assets` 通过，4 个模型测试覆盖：
  - 多级 `branch_path` 递归建树。
  - 选中模块返回全部子树用例。
  - 选中中间 branch 返回子树用例。
  - 搜索命中嵌套用例标题时保留祖先链。
  - 默认展开 root + 文档层，不展开模块/分支子树。
- `npx tsc --noEmit`：通过。
- `npm run build`：通过；仍有既有大 chunk warning。
- `git diff --check`：通过。
- `npm run lint`：失败，原因是项目缺 ESLint 配置文件，ESLint 无法启动；不是本次代码 lint 违规。
- Playwright 运行态验证：
  - `/batches/6f30e1bd-89ad-4e98-878c-4b48014eb1a4` 可展开到 `标题包 -> 新建编辑 -> 字数算法`。
  - 工作台用例表点击标题后详情抽屉可打开。
  - `/case-library` 选择 `漫剧批创系统` 后，可展开到同样的多级树。
  - 用例库选中中间分支 `新建编辑` 后，右侧列表在稳定主集视图下显示 38 条用例，不是空列表。

## 批判性自审

- 这仍不是完整“共享浏览器”终态。当前已经共享了树模型、树组件、标签展示和基础表格列，但还没有抽 `CaseAssetBrowser` 这个总装组件。原因是工作台有审核操作、详情抽屉和自动跳下一条，继续合并到一个大组件前需要更细的回归。
- `module.cases` 与 `branches[].cases` 在后端语义上是重复视图。本次模型用去重 `caseIds` 防止计数翻倍，这是正确的；但如果未来后端改成“模块直属 cases + branches cases”，需要重新审契约。
- 搜索树目前是“节点搜索/用例标题命中保留祖先链”，不会同步过滤右侧表格。工作台原本已有全局标题搜索，本次没有合并两套搜索语义，避免改变审核主流程。后续若做统一浏览器，需要明确“左树搜索”和“右表搜索”的关系。
- `CaseAssetTree` 仍依赖 Ant Design Tree，没有做虚拟化性能专项评估。当前使用 `height` 与内部滚动，能解决页面被撑高，但超大树下还需要阶段 E 或 D 做性能观测。
- 新增测试使用 Node 25 原生 TypeScript type-stripping，没有引入 Vitest。优点是零依赖、能跑；缺点是团队机器如果 Node 版本过低会不兼容。考虑到本地当前 Node 是 v25.8.1，这是阶段 C 可接受折中，但长期前端测试工具链仍应标准化。
- 没有改动 `src/testcase_generator/**`，没有触碰生成算法、LLM 调用、case cap、核验策略或 worker 任务逻辑。

## 回滚性

本阶段可以独立回滚。新增共享目录集中在 `web/src/components/case-assets/`，两处消费方是 `CaseTreeReview` 与 `CaseLibrary`。如果运行态发现共享树问题，可以 revert 本阶段提交，不影响阶段 B 的系统统计、上传类型和树默认折叠快修。

## 后续建议

下一步可以结束阶段 C 或做一个很小的收尾，而不是立刻进入视觉阶段 D：

1. 若继续阶段 C：再考虑 `CaseAssetBrowser` 组合树 + 表 + 详情抽屉，但必须小心工作台审核主流程。
2. 明确左树搜索与右表搜索是否合并，避免用户以为树搜索会过滤表格。
3. 独立处理前端 ESLint 配置缺失，不要把它混进业务 UI 重构提交。
