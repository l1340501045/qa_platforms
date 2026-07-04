# QA 平台 UI/UX 重构执行计划

## 当前状态说明

本文件是父任务早期的阶段化执行计划稿，保留用于追溯原始拆解思路。实际执行已经拆分为子任务完成并归档，当前进度不要以本文件未勾选的历史 checkbox 判断。

当前合并前状态以以下文件为准：

- `main-merge-readiness.md`
- `final-integration-review.md`
- `.trellis/tasks/archive/2026-07/` 下的 UI/UX 子任务归档

截至当前 HEAD，父任务处于“UI/UX 候选交付，等待真实小批次、首次使用平台 QA 演练和新 `.audit` 审查”状态。

## 执行前门禁

- [ ] 不进入实现，直到用户审过 `prd.md`、`design.md`、`implement.md` 并明确同意开始。
- [ ] 当前任务保持 `planning`，不要运行 `task.py start`。
- [ ] 先处理脏工作区：列出所有 dirty files，按“阶段性成果 / UI 重构 / 临时产物 / 不确定”分组。
- [ ] 出提交计划让用户确认；禁止 `git add .`，禁止回滚未识别改动。
- [ ] 将当前阶段性成果固化到 `feat/architecture-migration` 的干净 commit。
- [ ] 从该 commit 建立可回退 checkpoint，建议 `checkpoint/architecture-migration-pre-ux`。
- [ ] 从 checkpoint 创建 `feat/qa-platform-ux-modernization`；不要直接从 `main` 开发。
- [ ] 记录当前 API/worker/frontend 启动方式，确保后续 Playwright 能访问真实页面。
- [ ] 每个阶段结束都做批判性 review；review 未通过时不得进入下一阶段。

## 阶段 A：脏工作区与分支基线治理

1. 读取 `git status --short`、`git diff --stat`、最近提交和分支。
2. 按目录分类：
   - 生成质量与模块树：`src/testcase_generator/**`、相关 tests、docs/spec/plans。
   - 平台 API/前端小修：`src/platform_api/**`、`web/src/**`。
   - 基建：`docker-compose.infra.yml`、`docs/run-infra-docker.md`、启动脚本。
   - Trellis/agent 配置：`.trellis/**`、`.agents/**`、`AGENTS.md`。
   - 运行/审查产物：`.audit/**`、`logs/**`、`.runtime/**`。
3. 对每组给出建议：
   - 应先提交并保留。
   - 应作为 UI/UX 分支内容。
   - 应加入 `.gitignore` 或不提交。
   - 需要用户判断。
4. 用户确认后再执行精确 git add/commit。
5. 确认 `feat/architecture-migration` 干净后创建 checkpoint。
6. 从 checkpoint 创建 UI/UX 分支。

验收：

- `git status --short` 中没有未识别的业务改动混在 UI 分支里。
- UI/UX 分支的 diff 只包含本任务相关内容。

## 阶段 B：关键真实 bug 与低风险 UX 修复

### B1 系统统计

改动点：

- `src/platform_api/services/system_service.py`
- `src/platform_api/schemas/system.py`
- `web/src/types/index.ts`
- `web/src/pages/Systems/index.tsx`
- 后端测试：新增或更新系统列表 API/Service 测试。

要求：

- `list_systems` 返回 `document_count` 和 `batch_count`。
- 计数排除软删除文档。
- 前端如果字段缺失，应显示异常/占位而不是静默 0；正常接口下显示真实值。

验证：

```bash
uv run pytest tests/platform_api -k "system"
```

只读 DB 验证：

```sql
select s.id, s.name,
       count(distinct d.id) filter (where d.deleted_at is null) as document_count,
       count(distinct b.id) as batch_count
from public.systems s
left join knowledge.documents d on d.system_id=s.id
left join testcase.test_batches b on b.system_id=s.id
where s.id='6b0ea53c-f734-4bc9-8506-663d47107b9d'
group by s.id, s.name;
```

### B2 上传文档类型

改动点：

- `web/src/pages/Knowledge/index.tsx`
- `web/src/stores/knowledgeStore.ts`
- `web/src/services/documentApi.ts`
- `src/platform_api/api/v1/documents.py`
- `src/platform_api/services/document_service.py`
- 前后端测试。

要求：

- 上传前可选 `doc_type`，默认 `prd`。
- 上传请求带 `doc_type`。
- 后端校验枚举，非法类型拒绝。
- 上传结果和列表展示中文类型标签。

验证：

```bash
uv run pytest tests/platform_api -k "document"
```

前端验收：

- 上传一个 `.md`，选择 `prd`，列表类型显示 PRD。
- 上传技术文档选择 `tech_doc`，列表类型显示技术文档。

### B3 树默认折叠与滚动

改动点：

- `web/src/pages/Knowledge/index.tsx`
- `web/src/components/CaseTreeReview.tsx`
- `web/src/pages/CaseLibrary/index.tsx`

要求：

- 移除 `defaultExpandAll`。
- 默认只展开 root/第一层或按上次状态恢复。
- 树容器有 `maxHeight`/`height` 和内部滚动。
- 提供搜索、展开全部、收起全部。
- 大树不撑高整个页面。

验证：

- 打开旧批次 `6f30e1bd-89ad-4e98-878c-4b48014eb1a4`，左树不再全展开。
- 树很多时只在树区域内滚动。

## 阶段 C：用例资产树与共享组件

1. 新增纯模型函数：
   - `normalizeCaseTreeDocuments`
   - `getCasesForNode`
   - `filterTreeByKeyword`
   - `getDefaultExpandedKeys`
2. 为 `branch_path` 多级路径写单测：
   - 模块 `账户授权`
   - 分支路径 `["账户选择弹窗（批创页）", "分页规则"]`
   - 期望渲染为递归树，不是平铺一个长标题。
3. 抽 `CaseAssetTree`，先替换 `CaseLibrary`。
4. 再替换 `CaseTreeReview` 或让其变成 `CaseAssetBrowser mode='review'`。
5. 确保审核操作、详情抽屉、自动跳下一条、筛选参数都保留。

验证：

```bash
uv run pytest tests/platform_api/test_case_tree_service.py
```

前端：

- 用例库稳定主集/全部资产/待分类视图都能正常切换。
- 工作台审核确认/需修改/删除仍可落库。
- 搜索时右侧列表和左侧树定位一致。

## 阶段 D：整体 UI/UX 重构

1. 重构 `MainLayout`：
   - 导航文案改为工作流导向。
   - 保留当前路由兼容。
   - Header 显示当前系统/批次上下文和通知。
2. 抽页面骨架：
   - `PageHeader`
   - `FilterBar`
   - `MetricStrip`
   - `StatusTag`
   - `SplitTreeTableLayout`
3. 系统列表：
   - 支持卡片/表格切换或更密集卡片。
   - 显示准确统计、最近活动、状态。
4. 知识库：
   - 上传类型选择。
   - 文档列表类型中文化。
   - 文档树搜索/折叠/滚动。
5. 工作台：
   - 阶段进度、澄清、失败重试、审查筛选、用例树布局统一。
   - 关键操作固定在可见区域。
6. 用例库：
   - 强化资产视图：稳定主集、全部资产、待分类。
   - 模块树和表格更适合大批量浏览。

验收：

- 桌面宽度下首屏能看见当前任务、关键状态、下一步操作。
- 文案不依赖用户懂内部 pipeline 名称。
- 不用滚动很久才能操作左树下面的节点。

## 阶段 E：完整验证

后端/生成核心保护：

```bash
uv run pytest tests/platform_api
uv run pytest tests/testcase_generator -k "not integration"
```

前端：

```bash
cd web
npm run lint
npm run typecheck
npm run build
```

运行态：

- 启动 Docker infra、API、worker、frontend。
- Playwright/浏览器验收：
  - `/systems`
  - `/systems/:systemId/documents`
  - `/batches/:batchId`
  - `/case-library`
  - `/review`
  - `/exports`
- 截图验收桌面和窄屏。
- 确认主流程：
  - 上传 PRD。
  - 触发生成。
  - pending/running 状态可见。
  - suspended 可澄清。
  - pending_review 可审查。
  - 可迭代/落库/导出。

## 回滚点

- B1/B2 是后端契约小改，可单独 revert。
- B3 是前端行为小改，可单独 revert。
- C 是共享组件重构，必须在替换第二个页面前保留第一页面可回滚 commit。
- D 是视觉/布局大改，必须最后做，避免和数据契约修复混在同一个 commit。

## Codex Inline 执行约束

本任务由 Codex 主会话按 Trellis inline 流程执行，不派发 implement/check 子代理。真正实施前必须先切到对应子任务并读取该子任务的 `prd.md`、`design.md`（如有）、`implement.md`（如有）以及父任务材料。

固定约束：

- 当前任务必须先处理脏工作区和分支治理，不要直接改 UI。
- 不要 `git add .`，不要回滚未识别改动。
- `main` 只作为最终集成目标；本次 UI/UX 分支从 `feat/architecture-migration` 的干净 checkpoint 拉出。
- UI/UX 重构不得改变 `src/testcase_generator` 生成核心逻辑。
- 所有改动围绕完整生成测试用例主流程，必须保持上传、生成、澄清、审查、迭代、落库、导出通路可用。
- 每个阶段产物都要批判性 review，明确说出“还不够好/证据不足/可能跑偏”的点。

## 自审

- 计划没有直接要求一次性“大换皮”，而是先修真实数据契约和树表可用性，这符合主流程安全。
- 最大风险仍是当前脏工作区，已经把它放在阶段 A。
- 如果用户只想先快速改善体验，可以只做阶段 B；如果要完整现代化，再做 C/D/E。
- 短步骤用例不是本 UI 任务的失败标准，已避免把“步骤数”作为验收硬指标。
