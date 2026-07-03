# QA 平台 UI/UX 重构技术设计

## 设计原则

- 主流程优先：所有改动围绕完整生成测试用例通路，不让视觉重构阻断业务。
- 先契约后界面：凡是展示错误来自 API 缺字段或契约不清，先修接口契约，再修前端。
- 复用优先：工作台和用例库当前存在明显重复实现，本次应抽共享组件/工具，不做两份近似修补。
- 可渐进发布：每个阶段可独立验证、可回滚，避免一次性把页面、接口、样式、树模型全部绑死。
- 批判性 review 优先于进入下一步：任何阶段产物都要先审“是否偏离 QA 工作流、是否保护主流程、是否有足够证据”，再继续。

## 当前架构边界

### 前端

- 技术栈：React 18、Ant Design 5、Zustand、axios、Vite。
- 数据流约定：页面 -> Zustand store -> service -> axios -> API。
- 相关文件：
  - `web/src/layouts/MainLayout.tsx`
  - `web/src/pages/Systems/index.tsx`
  - `web/src/pages/Knowledge/index.tsx`
  - `web/src/pages/Workbench/index.tsx`
  - `web/src/pages/CaseLibrary/index.tsx`
  - `web/src/components/CaseTreeReview.tsx`
  - `web/src/services/systemApi.ts`
  - `web/src/services/documentApi.ts`
  - `web/src/types/index.ts`

### 后端

- 技术栈：FastAPI、SQLAlchemy async、Celery、PostgreSQL。
- API 响应通过统一信封 `{code,message,data}`，前端 axios 拦截器已解包。
- 相关文件：
  - `src/platform_api/api/v1/systems.py`
  - `src/platform_api/services/system_service.py`
  - `src/platform_api/api/v1/documents.py`
  - `src/platform_api/services/document_service.py`
  - `src/platform_api/services/case_tree_service.py`
  - `src/platform_api/repositories/testcase_repo.py`
  - `src/platform_api/models/knowledge.py`
  - `src/platform_api/models/testcase.py`

### 不触碰边界

不修改 `src/testcase_generator` 的生成核心逻辑，除非只是为了读取现有模块分类元数据的展示契约；任何生成算法、LLM prompt、核验策略、case cap 策略都不属于本 UI/UX 任务。

## 数据流与契约设计

### 系统列表统计

现状：

```
GET /systems -> SystemService.list_systems -> public.systems rows
前端 System.document_count/batch_count 缺字段 -> ?? 0
```

目标：

```
public.systems
  left join knowledge.documents where deleted_at is null
  left join testcase.test_batches
-> SystemSummaryResponse
-> SystemsPage 展示真实 count 与最近活动信息
```

建议契约：

```ts
interface SystemSummary {
  id: string;
  name: string;
  description: string | null;
  document_count: number;
  batch_count: number;
  latest_batch_status?: BatchStatus | null;
  latest_batch_id?: string | null;
  latest_activity_at?: string | null;
  created_at: string;
  updated_at: string;
}
```

实现注意：

- 聚合统计必须由后端提供，前端不得用缺字段默认为 0 掩盖接口缺陷。
- 计数要排除软删除文档。
- 批次数是否包含失败/删除历史批次需要显式约定；第一版建议统计所有系统下批次，状态分布后续再扩展。

### 文档上传类型

现状：

```
KnowledgePage.collectFile -> uploadDocuments(systemId, files)
documentApi.batchUploadDocuments 只传 files
POST /systems/:id/documents/batch?doc_type=other
```

目标：

```
用户选择 doc_type
-> store.uploadDocuments(systemId, files, docType)
-> service FormData + query/body doc_type
-> DocumentService.batch_upload(doc_type)
-> documents.doc_type
-> 文档列表 Tag 展示中文标签
```

建议：

- 前端上传面板添加 `Radio.Group` 或 `Select`，默认 `prd`。
- 文件夹上传按钮复用同一个 `selectedDocType`。
- 上传结果 modal 显示每个已上传文档的类型。
- 后端验证 `doc_type` 必须属于 `DocType` 枚举；非法值返回 422/400，而不是静默写入。

### 用例资产树

现状：

后端返回：

```json
[
  {
    "document_id": "...",
    "document_title": "...",
    "modules": [
      {
        "module_name": "...",
        "case_count": 433,
        "cases": [],
        "branches": [
          {"branch_name": "入口与页面预览", "branch_path": ["入口与页面预览"], "cases": []}
        ]
      }
    ]
  }
]
```

问题：

- `branch_path` 是数组，但 API 把所有路径折成 `branches[]` 一层列表。
- 前端只渲染 `文档 -> 模块 -> 分支`，无法表达模块下继续分叉的树。
- `defaultExpandAll` 在大树上造成页面巨大、定位困难、首屏信息噪声高。

目标：

引入共享的前端树归一化层，第一阶段不必破坏后端原有接口：

```ts
interface CaseAssetTreeNode {
  key: string;
  type: 'root' | 'document' | 'module' | 'branch';
  title: string;
  count: number;
  children?: CaseAssetTreeNode[];
  cases?: CaseTreeCase[];
}
```

归一化规则：

- `Document` 节点下是 `Module`。
- 每个 `branch.branch_path` 按 path segment 构建递归子树，而不是只用 `branch_name` 一层。
- 节点 count 从子节点或 cases 聚合，保持与列表数量一致。
- 选中任意节点时，右侧列表展示该节点及其子树下的所有用例。

后端增强建议：

- 第一阶段可以保持接口兼容，只在前端归一化。
- 第二阶段再增加可选字段 `tree_nodes` 或新 endpoint `case-tree-v2`，但不得破坏当前 `CaseTreeDocument` 消费者。

### 共享组件设计

建议新增：

- `web/src/components/case-assets/CaseAssetBrowser.tsx`
  - 组合左树、右表、筛选/搜索、详情抽屉。
  - `mode='review' | 'library'` 控制是否展示审核操作。
- `web/src/components/case-assets/CaseAssetTree.tsx`
  - 受控 `expandedKeys/selectedKeys`。
  - 默认展开 root + 文档 + 前 N 个高频模块，不全展开。
  - 支持搜索、展开全部、收起全部、定位选中节点。
  - 固定高度，内部滚动；大树优先启用 Ant Design Tree `height`/virtual scroll。
- `web/src/components/case-assets/caseTreeModel.ts`
  - `normalizeCaseTreeDocuments`
  - `getCasesForNode`
  - `getDefaultExpandedKeys`
  - `filterTreeByKeyword`
- `web/src/components/ui/PageHeader.tsx`
- `web/src/components/ui/FilterBar.tsx`
- `web/src/components/ui/MetricStrip.tsx`
- `web/src/components/ui/StatusTag.tsx`

抽象边界：

- 不把 API 请求塞进纯展示组件；数据仍由页面或 store 获取。
- 不让组件直接理解数据库字段；只吃前端 `types/index.ts` 中的契约类型。
- `CaseTreeReview` 可被 `CaseAssetBrowser mode='review'` 替代或变薄封装。
- `CaseLibrary` 使用同一套 `CaseAssetBrowser mode='library'`。

## 信息架构建议

导航建议从“对象管理”转为“QA 工作流”：

1. 工作台：跨系统待处理事项、运行中批次、待澄清、待审查。
2. 项目/系统：系统列表、文档数、批次数、最近活动、进入知识库。
3. 知识库：文档上传、类型、解析状态、文档树。
4. 生成与审查：批次状态、澄清、用例审查、迭代、落库。
5. 用例资产：稳定主集、全部资产、待分类、搜索与筛选。
6. 导出中心：批次/系统导出任务。

为了降低风险，第一阶段可以保留现有路由，只调整导航标签和页面内部动线；第二阶段再把“工作台”设为首页。

## 发布与分支策略

### 前置门禁

- 当前 `feat/architecture-migration` 脏工作区必须先盘点。
- 阶段性成果按用户确认的提交计划固化到 `feat/architecture-migration`。
- 在 `feat/architecture-migration` 干净后创建可回退 checkpoint，建议命名为 `checkpoint/architecture-migration-pre-ux`。
- UI/UX 分支必须从该 checkpoint 创建，不直接从 `main` 创建；`main` 只作为最终集成和发布验收目标。
- 不允许把 `.audit/`、`logs/`、运行缓存、临时截图误提交到 UI/UX 分支。

### 推荐分支

- 阶段成果基线：沿用当前 `feat/architecture-migration`，必要时拆出更小 PR，但不丢失当前成果。
- 可回退锚点：`checkpoint/architecture-migration-pre-ux`，指向用户确认后的干净基线 commit。
- UI/UX 重构分支：从 checkpoint 拉出 `feat/qa-platform-ux-modernization`。
- 最终交付：UI/UX 分支验收通过后，再单独决定如何合入 `main`。

### 推荐阶段

1. 阶段 A：分支/脏区治理，不改业务。
2. 阶段 B：非生成核心的真实 bug 修复：系统统计、上传 doc_type、树默认展开/滚动。
3. 阶段 C：共享用例资产浏览器，替换工作台/用例库重复实现。
4. 阶段 D：导航、页面布局、视觉 token、状态/空态/错误态统一。
5. 阶段 E：Playwright/浏览器全链路验收。

### 批判性 Review 门禁

每个阶段结束时必须产出一段 review，建议写入对应子任务 `review.md` 或阶段报告：

- 产品视角：是否解决真实 QA 动线，而不是只做表面优化。
- 架构视角：是否遵守现有 React + Ant Design + Zustand + FastAPI 分层，不把逻辑散落到页面。
- 主流程视角：上传、生成、澄清、审查、迭代、落库、导出是否仍可达。
- 回滚视角：本阶段是否能独立 revert，不会拖着后续大改一起回滚。
- 证据视角：测试、截图、接口响应、DB 查询是否覆盖对应验收标准。

## 风险与回滚

- 风险：系统统计聚合 SQL 造成分页性能下降。
  - 缓解：先写针对当前数据量的聚合查询，必要时用子查询或批量 count map，不做 N+1。
- 风险：上传类型默认改成 `prd` 后，用户上传技术文档忘记切换。
  - 缓解：上传区显著显示当前类型，上传结果回显类型；后续可做文件名/目录启发式推荐，但第一版不自动误判。
- 风险：递归树前端归一化后，选中节点的用例数和后端 case_count 不一致。
  - 缓解：为 `normalizeCaseTreeDocuments/getCasesForNode` 写单测，覆盖多级 branch_path。
- 风险：工作台/用例库共用组件抽象过大。
  - 缓解：先抽纯模型函数和 TreePanel，再抽 Browser；每一步替换一个页面并回归。
- 风险：视觉重构影响主流程。
  - 缓解：先修数据契约和树控件，再做布局；每阶段都跑主流程冒烟。

## 自审结论

这套方案没有把“好看”放在第一位，而是把 QA 的任务流和数据契约放在第一位，这是对当前问题更稳的方向。最大的风险不是 UI 设计，而是当前 `feat/architecture-migration` 脏工作区和最终 `main` 集成路径不清；如果不先治理分支，大重构会污染阶段成果基线，也会让后续 review 无法判断哪些改动属于质量生成、哪些属于 UI。实施时必须坚持阶段 A 先行。
