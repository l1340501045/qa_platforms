# platform-web 前端任务清单

## 文档信息

| 属性 | 内容 |
| :--- | :--- |
| **所属变更** | CHG-20260605-001 |
| **模块名称** | platform-web |
| **模块类型** | web-frontend |
| **创建时间** | 2026-06-08 |

---

## 任务格式

```
- [x] T{NNN} [P?] {优先级} 任务描述（含具体文件路径）
  depends: T{NNN}, T{NNN}@{other-module}
```

| 标记 | 含义 |
| :--- | :--- |
| `T{NNN}` | 模块内唯一编号，从 T001 起编 |
| `[P]` | 可并行：操作不同文件、无依赖未完成任务 |
| 优先级 | P0（必须）/ P1（重要）/ P2（可选） |
| `depends:` | 依赖标注（缩进换行）。模块内：`T010`；跨模块：`T020@platform-api`。无依赖则不写此行 |

---

## 阶段 1：环境与基础

**目标**：项目结构、依赖、路由、公共组件就绪

- [x] T001 [P] P0 Vite + React 18 + TypeScript 项目初始化 `vite.config.ts` + `tsconfig.json` + `package.json`
- [x] T002 [P] P0 依赖安装（antd@5, zustand, axios, react-router-dom@6, @ant-design/icons, dayjs, ahooks）
- [x] T003 P0 项目目录结构创建（`src/pages/` `src/components/` `src/stores/` `src/services/` `src/types/` `src/hooks/` `src/utils/`）
  depends: T001
- [x] T004 P0 axios 实例封装 + 请求/响应拦截器（统一错误处理、请求 ID 注入）`src/services/request.ts`
  depends: T003
- [x] T005 P0 React Router v6 路由配置（懒加载 + 嵌套路由，无认证守卫）`src/router/index.tsx` + `src/router/routes.ts`
  depends: T003
- [x] T006 P0 Layout 组件（侧边栏导航 + 顶部栏 + 内容区）`src/components/Layout/index.tsx`
  depends: T003, T002

**✓ 检查点**：`pnpm dev` 启动，空壳页面可访问，路由跳转正常

---

## 阶段 2：数据层

**目标**：TypeScript 类型定义、状态管理、API 对接基础

- [x] T007 [P] P0 TypeScript 类型定义 — 通用响应/分页（对齐 platform-api contracts）`src/types/common.ts`
- [x] T008 [P] P0 TypeScript 类型定义 — 系统/文档/批次/用例/导出 `src/types/system.ts` `src/types/document.ts` `src/types/batch.ts` `src/types/testcase.ts` `src/types/export.ts`
- [x] T009 P0 Zustand knowledgeStore（文档列表/文档树/上传状态）`src/stores/knowledgeStore.ts`
  depends: T008, T004
- [x] T010 P0 Zustand testcaseStore（批次信息/用例列表/生成进度/review 状态）`src/stores/testcaseStore.ts`
  depends: T008, T004
- [x] T011 [P] P0 API service — 系统管理相关 `src/services/systemApi.ts`
  depends: T008, T004
- [x] T012 [P] P0 API service — 文档管理相关 `src/services/documentApi.ts`
  depends: T008, T004
- [x] T013 [P] P0 API service — 批次与用例相关 `src/services/batchApi.ts`
  depends: T008, T004
- [x] T014 [P] P0 API service — 导出相关 `src/services/exportApi.ts`
  depends: T008, T004

**✓ 检查点**：类型定义完整，API 层封装完毕，stores 可正常初始化

---

## 阶段 3：功能实现

**目标**：按页面/用户故事实现核心交互，每个故事独立可测可演示

### 系统列表首页 — US-系统管理 (P0)

**目标**：用户可查看系统列表、创建/编辑/删除系统、配置系统间关联
**独立验证**：访问 /systems → 系统列表展示 → 新建系统 → 配置关联
**对应验收标准**：AC-01 对应前端交互

- [x] T015 P0 系统列表页（卡片/表格切换、搜索、分页）`src/pages/Systems/index.tsx`
  depends: T011, T006
- [x] T016 P0 系统创建/编辑抽屉组件 `src/pages/Systems/components/SystemDrawer.tsx`
  depends: T011
- [x] T017 P0 系统关联配置弹窗（选择目标系统 + 关联类型 + 可视化关系图）`src/pages/Systems/components/AssociationModal.tsx`
  depends: T011
- [x] T018 P1 系统删除确认 + 异常状态处理（有文档时不可删除提示）`src/pages/Systems/components/DeleteConfirm.tsx`
  depends: T015

**✓ 检查点**：系统 CRUD + 关联配置全部可操作

---

### 系统知识库页 — AC-01 (P0)

**目标**：用户可在系统下管理知识文档（文档树展示、文件夹拖拽上传、上传进度、类型标识）
**独立验证**：访问 /systems/:id/knowledge → 文档树展示 → 拖拽 zip 上传 → 进度条 → 文档入库
**对应验收标准**：AC-01

- [x] T019 P0 知识库页面骨架（文档树 + 右侧详情区）`src/pages/Knowledge/index.tsx`
  depends: T012, T009, T006
- [x] T020 P0 文档树组件（树形结构展示、文件夹层级、类型图标、搜索过滤）`src/pages/Knowledge/components/DocTree.tsx`
  depends: T009
- [x] T021 P0 文件夹拖拽上传组件（zip 拖拽 + 点击上传 + 大小校验 100MB + 进度条）`src/pages/Knowledge/components/UploadZone.tsx`
  depends: T012, T009
- [x] T022 P0 上传结果汇总弹窗（成功/跳过/失败统计）`src/pages/Knowledge/components/UploadResult.tsx`
  depends: T021
- [x] T023 P1 文档类型标识与信任等级徽章 `src/components/DocTypeBadge/index.tsx`
  depends: T008

**✓ 检查点**：文档上传、树形浏览、类型标识完整可用

---

### 文档详情页 — AC-06 (P0)

**目标**：用户可预览文档内容、管理关联关系、从文档入口触发用例生成
**独立验证**：访问 /documents/:id → Markdown 预览 → 关联管理 → 点击「生成用例」触发
**对应验收标准**：AC-06

- [x] T024 P0 文档详情页面（Markdown 渲染 + 元信息侧栏 + 操作按钮区）`src/pages/DocumentDetail/index.tsx`
  depends: T012, T009
- [x] T025 P0 Markdown 渲染组件（支持代码高亮、图片展示、目录导航）`src/components/MarkdownViewer/index.tsx`
- [x] T026 P0 文档关联管理面板（当前关联列表 + 添加关联弹窗 + 关联类型选择）`src/pages/DocumentDetail/components/AssociationPanel.tsx`
  depends: T012
- [x] T027 P0 生成入口按钮（触发生成 → 跳转用例工作台）`src/pages/DocumentDetail/components/GenerateButton.tsx`
  depends: T013

**✓ 检查点**：文档预览、关联管理、生成触发全部可操作

---

### 用例工作台 — AC-02, AC-03, AC-04, AC-05 (P0)

**目标**：展示生成进度（6 阶段轮询）、Gate NO_GO 澄清交互、用例列表展示与 review 操作、迭代对比、落库确认
**独立验证**：触发生成 → 进度轮询 → Gate 澄清（如需）→ 用例列表 → review → 迭代 → 落库
**对应验收标准**：AC-02, AC-03, AC-04, AC-05

- [x] T028 P0 用例工作台页面骨架（进度区 + 用例列表区 + 操作栏）`src/pages/Workbench/index.tsx`
  depends: T010, T013, T006
- [x] T029 P0 6 阶段进度组件（Steps 组件 + 实时轮询 + 各阶段状态展示 + 耗时显示）`src/pages/Workbench/components/StageProgress.tsx`
  depends: T010
- [x] T030 P0 进度轮询 hook（定时 GET 批次详情 + 状态驱动 UI 更新 + 完成/失败自动停止）`src/hooks/usePolling.ts`
  depends: T013
- [x] T031 P0 Gate NO_GO 澄清交互组件（问题列表展示 + 答案输入 + 提交恢复）`src/pages/Workbench/components/ClarificationForm.tsx`
  depends: T013, T010
- [x] T032 P0 用例列表组件（表格展示 + 优先级/维度筛选 + 可信度标签 + review 状态筛选）`src/pages/Workbench/components/CaseList.tsx`
  depends: T010
- [x] T033 P0 用例详情抽屉（步骤展示 + 原文溯源跳转 + 可信度说明 + review 操作按钮）`src/pages/Workbench/components/CaseDetail.tsx`
  depends: T032
- [x] T034 P0 Review 操作组件（确认/需修改/删除 + 修改意见输入 + 批量操作工具栏）`src/pages/Workbench/components/ReviewActions.tsx`
  depends: T032, T013
- [x] T035 P1 迭代对比组件（当前轮次 vs 上一轮次 diff 展示）`src/pages/Workbench/components/IterationDiff.tsx`
  depends: T032
- [x] T036 P0 落库确认弹窗（统计汇总 + 确认操作 + 成功反馈）`src/pages/Workbench/components/ArchiveConfirm.tsx`
  depends: T013, T010

**✓ 检查点**：生成→轮询→澄清→review→迭代→落库全流程可走通

---

### 导出中心 — AC-07 (P1)

**目标**：用户可触发导出、查看导出状态、下载导出文件
**独立验证**：访问 /exports → 触发导出 → 状态更新 → 下载文件
**对应验收标准**：AC-07

- [x] T037 P1 导出中心页面（导出列表 + 触发导出按钮 + 状态标签）`src/pages/Exports/index.tsx`
  depends: T014, T006
- [x] T038 P1 创建导出弹窗（选择范围 batch/system + 选择格式 markdown/excel）`src/pages/Exports/components/CreateExportModal.tsx`
  depends: T014
- [x] T039 P1 导出状态轮询 + 下载按钮（完成后展示下载链接）`src/pages/Exports/components/ExportStatus.tsx`
  depends: T014, T030

**✓ 检查点**：导出触发、状态查看、文件下载全部可操作

---

## 阶段 4：集成与收尾

**目标**：联调验证、E2E 测试、性能优化、响应式适配

- [x] T040 P0 与 platform-api 联调 — 系统管理流程验证
  depends: T015, T020@platform-api
- [x] T041 P0 与 platform-api 联调 — 文档上传 + 生成 + review + 落库全流程验证
  depends: T024, T028, T024@platform-api, T029@platform-api
- [x] T042 P1 E2E 测试 — 关键路径（创建系统 → 上传文档 → 触发生成 → review → 落库）`tests/e2e/critical-path.spec.ts`
  depends: T040, T041
- [x] T043 [P] P1 性能优化 — 路由级代码分割 + React.lazy `src/router/index.tsx`
  depends: T005
- [x] T044 [P] P1 性能优化 — 大列表虚拟滚动（用例列表超 100 条时）`src/pages/Workbench/components/CaseList.tsx`
  depends: T032
- [x] T045 [P] P1 性能优化 — 图片/资源按需加载 + Vite 分包策略 `vite.config.ts`
  depends: T001
- [x] T046 [P] P1 响应式适配（min 1280px 断点、Ant Design Grid 布局、侧栏折叠）`src/components/Layout/index.tsx`
  depends: T006
- [x] T047 [P] P2 首屏加载优化（骨架屏 + 关键 CSS 内联 + preload 关键资源）确保首屏 < 3s `src/components/Skeleton/index.tsx`
  depends: T006

**✓ 检查点**：全流程联调通过，首屏 < 3s，min 1280px 正常展示

---

## 交付策略

### MVP 优先（仅 P0 页面）
1. 完成阶段 1 + 阶段 2（基础设施）
2. 完成系统列表 → 知识库页 → 文档详情 → 用例工作台
3. 叠加导出中心（P1）和性能优化

### 页面间依赖
- 系统列表：无依赖（可独立交付）
- 知识库页：依赖系统存在
- 文档详情：依赖文档存在
- 用例工作台：依赖生成触发
- 导出中心：依赖已落库数据

---

## 任务统计

| 指标 | 数值 |
| :--- | :--- |
| 总任务数 | 47 |
| P0（必须） | 34 |
| P1（重要） | 11 |
| P2（可选） | 2 |
| 可并行任务 | 12 |
| 预计工时 | 48h |
