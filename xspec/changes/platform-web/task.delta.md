# platform-web 任务清单 — CHG-20260609-001

> 基线：xspec/modules/platform-web（无既有 task 基线，全部为新增）
> 交付分段：第一段（信息架构重构+用例库+通知+可观测性+搜索+导出优化+面包屑）+ 第二段（版本历史/差异对比）

---

## 阶段 1：环境与基础

- [ ] T001 P0 新增 TypeScript 类型定义文件 `src/types/notification.ts`（Notification、UnreadCountResponse、NotificationListResponse、MarkReadResponse、MarkAllReadResponse）
- [ ] T002 P0 新增 TypeScript 类型定义文件 `src/types/caseTree.ts`（CaseTreeResponse、TreeNode、CaseSearchResult、SearchResponse）
- [ ] T003 P0 新增 TypeScript 类型定义文件 `src/types/caseVersion.ts`（CaseVersionsResponse、CaseDiffResponse，标注第二段）
- [ ] T004 P0 新增 API Service 文件 `src/services/notificationAPI.ts`（getUnreadCount、getNotifications、markAsRead、markAllAsRead）
  depends: T001
- [ ] T005 P0 新增 API Service 文件 `src/services/caseAPI.ts`（getCaseTree、searchCases、getCaseVersions、getCaseDiff）
  depends: T002, T003
- [ ] T006 P0 扩展 `src/services/batchAPI.ts` 新增方法（getSystemBatches、retryBatch、getBatchOptions）
- [ ] T007 P0 扩展 `src/services/systemAPI.ts` 新增 getSystemOptions 方法
- [ ] T008 P0 新增 Store 文件 `src/stores/notificationStore.ts`（状态定义：unreadCount、notifications[]、loading）
  depends: T001, T004
- [ ] T009 P0 新增 Store 文件 `src/stores/caseTreeStore.ts`（状态定义：tree[]、selectedCase、filters、searchResults）
  depends: T002, T005
- [ ] T010 P0 路由表重构 `src/App.tsx`：新增 /systems/:id/cases、/systems/:id/batches、/cases、/notifications 路由
- [ ] T011 P0 侧边栏菜单扩展 `src/components/Layout/Sidebar.tsx`：新增"用例中心"（/cases）和"通知中心"（/notifications）菜单项

**检查点 CP-1**：所有类型文件通过 tsc 编译无报错；API Service 文件导出正确；Store 骨架可实例化；路由表包含所有新增路由；侧边栏渲染 4 个菜单项。

---

## 阶段 2：数据层

- [ ] T012 P0 实现 `src/stores/notificationStore.ts` 轮询逻辑：10 秒间隔调用 getUnreadCount，visibilitychange 暂停/恢复，乐观更新 markAsRead/markAllAsRead 含回滚
  depends: T008
- [ ] T013 P0 实现 `src/stores/caseTreeStore.ts` 核心方法：fetchTree(systemId, filters)、setSelectedCase、applyFilters（按优先级/review_status/trust_level/batch_id 筛选）
  depends: T009
- [ ] T014 [P] P0 实现 `src/services/notificationAPI.ts` 四个方法的完整请求逻辑（含错误处理策略：轮询静默失败、乐观更新）
  depends: T004
- [ ] T015 [P] P0 实现 `src/services/caseAPI.ts` 搜索方法（searchCases 含 300ms 防抖控制说明）
  depends: T005
- [ ] T016 [P] P1 实现 `src/services/batchAPI.ts` 新增方法（getSystemBatches 含分页、retryBatch 含错误码处理、getBatchOptions）
  depends: T006

**检查点 CP-2**：notificationStore 轮询可在控制台观测到 10 秒间隔请求（mock 环境）；caseTreeStore.fetchTree 可接收 mock 数据并正确设置 tree 状态；页面隐藏时轮询暂停。

---

## 阶段 3：功能实现

### 3.1 系统详情多 Tab + 用例树（AC-09, AC-16）

- [ ] T017 P0 新增系统详情多 Tab 容器组件 `src/pages/SystemDetail/SystemTabs.tsx`：知识库/用例库/批次历史三个 Tab，默认激活知识库，路由联动
  depends: T010
- [ ] T018 P0 新增用例树页面组件 `src/pages/SystemDetail/CaseTreeView.tsx`：左侧 Ant Tree（三级：PRD 文档→功能模块→用例标题），右侧用例列表区域；树节点显示用例计数；展开/收起全部按钮
  depends: T013, T017
- [ ] T019 P0 用例树筛选栏 `src/pages/SystemDetail/CaseTreeFilter.tsx`：优先级/Review 状态/可信度/批次 四个筛选器，筛选后空节点隐藏
  depends: T018
- [ ] T020 P1 用例树空状态处理 `src/pages/SystemDetail/CaseTreeView.tsx`：无批次时展示"暂无用例，请先在知识库中选择文档生成"；功能模块下全部已删除时节点变灰
  depends: T018

### 3.2 用例详情 Drawer（AC-10）

- [ ] T021 P0 新增用例详情面板组件 `src/components/CaseDetailDrawer/index.tsx`：Ant Drawer 50%-60% 宽度，展示标题栏（标题+优先级 Tag+Review 状态 Tag）、可信度区域、前置条件、测试步骤（编号+操作+输入数据+每步预期）、总体预期结果、测试维度、溯源、操作栏
  depends: T013
- [ ] T022 P0 trust_level 语义修正展示逻辑 `src/components/CaseDetailDrawer/TrustLevelBadge.tsx`：1-2=高可信（绿色）、3-4=中可信（黄色）、5=低可信（红色）；展示 confidence_note；禁止百分比展示
  depends: T021
- [ ] T023 P1 用例详情异常处理：字段缺失时显示"暂无"；steps 超过 20 步折叠展示 `src/components/CaseDetailDrawer/index.tsx`
  depends: T021

### 3.3 通知铃铛 + 通知中心（AC-11）

- [ ] T024 P0 新增通知铃铛组件 `src/components/Layout/NotificationBell.tsx`：Header 右上角 Badge 图标 + 下拉面板（最近 10 条）+ 底部"查看全部"跳转 /notifications
  depends: T012
- [ ] T025 P0 新增通知中心页面 `src/pages/NotificationCenter/index.tsx`：站内消息完整列表，分页（每页 20 条，超 100 条分页），"全部标记已读"按钮
  depends: T012, T010
- [ ] T026 P0 通知消息条目组件 `src/components/NotificationItem.tsx`：图标+标题+时间+点击跳转（按 target_type 跳转对应页面）；点击后标记已读
  depends: T024
- [ ] T027 P1 通知空状态：无消息时下拉面板展示"暂无通知" `src/components/Layout/NotificationBell.tsx`
  depends: T024

### 3.4 StageProgress 增强 + 可观测性面板（AC-12, AC-13）

- [ ] T028 P0 增强 `src/components/StageProgress/index.tsx`：每个 stage 节点下方显示耗时（如"12.3s"）；运行中 stage 旋转动画；完成 stage 绿色勾号；失败 stage 红色叉号 + hover 失败原因 tooltip
  depends: T006
- [ ] T029 P0 失败 stage 旁"重试"按钮逻辑 `src/components/StageProgress/RetryButton.tsx`：点击调用 POST /batches/:id/retry；成功后状态恢复 running 并恢复轮询
  depends: T028, T016

### 3.5 失败重试（AC-14）

- [ ] T030 P1 重试按钮交互完善 `src/components/StageProgress/RetryButton.tsx`：loading 态防重复点击；409 状态码提示"批次正在运行中"；400 提示"当前批次无法重试"；重试后页面自动恢复轮询 batch 状态
  depends: T029

### 3.6 面包屑导航（AC-19）

- [ ] T031 P0 新增全局面包屑组件 `src/components/Layout/GlobalBreadcrumb.tsx`：基于路由自动生成面包屑路径；每段可点击跳转；当前页名称不可点击（灰色）
  depends: T010
- [ ] T032 P0 面包屑路由配置：系统知识库/用例库/批次列表/文档详情/用例工作台/全局用例中心/通知中心 各页面面包屑数据源 `src/components/Layout/breadcrumbConfig.ts`
  depends: T031
- [ ] T033 P0 集成面包屑到各子页面布局（main 区域顶部）：`src/components/Layout/PageLayout.tsx`
  depends: T031, T032

### 3.7 导出体验优化（AC-17, AC-18）

- [ ] T034 P0 导出中心新建弹窗改造 `src/pages/ExportCenter/CreateExportModal.tsx`：Batch ID / System ID 改为下拉选择器（支持搜索），批次选择器展示"文档标题 - 生成时间 - 状态"，系统选择器展示系统名称
  depends: T007, T016
- [ ] T035 P1 用例工作台快捷导出按钮 `src/pages/BatchWorkbench/ExportButton.tsx`：仅在批次状态 completed/archived 时可用；点击直接创建导出任务，跳转导出中心
  depends: T006
- [ ] T036 P1 导出下拉选择器异常处理：加载失败时展示"加载失败，请重试"并 fallback 手动输入 `src/pages/ExportCenter/CreateExportModal.tsx`
  depends: T034

### 3.8 全局用例中心/搜索页面（AC-15）

- [ ] T037 P1 新增全局用例中心页面 `src/pages/CaseCenter/index.tsx`：顶部搜索栏（关键词+系统筛选+优先级+Review 状态），结果列表（用例卡片），点击跳转所属系统用例详情
  depends: T015, T010
- [ ] T038 P1 搜索输入 300ms 防抖 + 搜索结果分页（每页 20 条） `src/pages/CaseCenter/SearchBar.tsx`
  depends: T037
- [ ] T039 P1 搜索结果高亮渲染：highlight 字段 dangerouslySetInnerHTML 展示 `src/pages/CaseCenter/CaseSearchCard.tsx`
  depends: T037
- [ ] T040 P1 搜索空状态/加载态/错误态处理 `src/pages/CaseCenter/index.tsx`：无结果展示提示；超时展示 loading；失败保持上次结果
  depends: T037

### 3.9 版本历史 + diff 对比视图（AC-20，第二段）

- [ ] T041 P1 新增版本历史时间线组件 `src/components/CaseDetailDrawer/VersionTimeline.tsx`（第二段）：用例详情 Drawer 内"版本历史"区域，展示 v1→v2→v3 时间线，每个节点含版本号/变更原因/变更类型/操作者
  depends: T021, T005
- [ ] T042 P1 新增版本差异对比视图 `src/components/CaseDetailDrawer/VersionDiffView.tsx`（第二段）：使用 jsdiff 库 diffWords/diffLines 对比各字段，红绿高亮展示差异；点击相邻版本触发
  depends: T041
- [ ] T043 P1 安装 jsdiff 依赖 `package.json`（第二段）：npm install diff @types/diff
  depends: T042

### 3.10 needs_human_confirm 人工确认入口 UI

- [ ] T044 P1 批次工作台增加人工确认入口 `src/pages/BatchWorkbench/HumanConfirmBanner.tsx`：当批次 status=suspended 时顶部展示确认横幅，引导用户进入澄清流程
  depends: T028

**检查点 CP-3**：所有新增页面可通过路由正常访问；用例树可展示三级结构并筛选；通知铃铛显示 Badge 数字；StageProgress 展示耗时和状态图标；面包屑在各子页面正确渲染；导出下拉选择器可搜索。

---

## 阶段 4：集成与收尾

- [ ] T045 P0 trust_level 语义修正全局搜索替换：确保所有展示 trust_level 的位置（CaseDetailDrawer、CaseSearchCard、CaseTreeView 节点 tooltip）统一使用档位映射而非百分比
  depends: T022, T039, T018

- [ ] T046 P0 与后端 API 联调（通知接口）：验证 GET /notifications/unread-count、GET /notifications、PATCH /notifications/:id/read、POST /notifications/mark-all-read 接口返回格式匹配前端类型
  depends: T012, T024, T025
  depends: T004@platform-api

- [ ] T047 P0 与后端 API 联调（用例树接口）：验证 GET /systems/:id/case-tree 返回嵌套三级树结构，前端无需 buildTree
  depends: T018
  depends: T005@platform-api

- [ ] T048 P0 与后端 API 联调（搜索/重试/导出选项）：验证 GET /cases/search、POST /batches/:id/retry、GET /batches/options、GET /systems/options 接口
  depends: T037, T029, T034
  depends: T005@platform-api, T006@platform-api

- [ ] T049 P1 虚拟滚动性能优化 `src/pages/SystemDetail/CaseTreeView.tsx`：用例树节点 >200 时启用 Ant Tree height 属性虚拟滚动，验证 500 条用例首次加载 <2 秒
  depends: T018

- [ ] T050 P1 单元测试（Store actions）`src/stores/__tests__/notificationStore.test.ts`：覆盖轮询启停、乐观更新、回滚逻辑
  depends: T012

- [ ] T051 P1 单元测试（Store actions）`src/stores/__tests__/caseTreeStore.test.ts`：覆盖 fetchTree、applyFilters、setSelectedCase
  depends: T013

- [ ] T052 P1 集成测试（页面路由/交互）`src/__tests__/integration/routing.test.tsx`：验证新增路由可达、侧边栏导航、面包屑跳转
  depends: T010, T011, T031

- [ ] T053 P1 集成测试（通知流程）`src/__tests__/integration/notification.test.tsx`：验证铃铛 Badge → 点击消息 → 跳转 → 标记已读完整流程
  depends: T024, T025, T026

- [ ] T054 P1 集成测试（用例树交互）`src/__tests__/integration/caseTree.test.tsx`：验证树展开 → 筛选 → 点击用例 → Drawer 展示详情完整流程
  depends: T018, T019, T021

**检查点 CP-4**：所有 API 联调通过，无 TypeScript 编译错误；trust_level 全部展示为档位标签；虚拟滚动在 500 条数据下渲染流畅；单元测试和集成测试全部通过。

---

## 任务依赖总览

```
阶段 1（基础）: T001-T011（并行度高，类型/Service/Store 骨架可同时进行）
阶段 2（数据层）: T012-T016（依赖阶段 1 的骨架文件）
阶段 3（功能）: T017-T044（依赖阶段 2 的 Store 实现）
阶段 4（收尾）: T045-T054（依赖阶段 3 的组件实现 + 后端 API 就绪）
```

## 跨模块依赖

| 本模块任务 | 依赖模块 | 依赖内容 |
| :--- | :--- | :--- |
| T046 | platform-api | 通知相关 4 个 API 端点就绪 |
| T047 | platform-api | GET /systems/:id/case-tree 返回嵌套树结构 |
| T048 | platform-api | 搜索/重试/选项 API 端点就绪 |
| T041-T043 | platform-api | GET /cases/:id/versions 和 /diff 端点就绪（第二段） |

## 验收标准映射

| AC 编号 | 覆盖任务 |
| :--- | :--- |
| AC-09 | T017, T018, T020 |
| AC-10 | T021, T022, T023 |
| AC-11 | T024, T025, T026, T027 |
| AC-12 | T028 |
| AC-13 | T028, T029 |
| AC-14 | T029, T030 |
| AC-15 | T037, T038, T039, T040 |
| AC-16 | T019 |
| AC-17 | T034, T036 |
| AC-18 | T035 |
| AC-19 | T031, T032, T033 |
| AC-20 | T041, T042, T043（第二段） |
