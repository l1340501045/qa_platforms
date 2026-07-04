# QA 平台 UI/UX 重构父任务集成审查

## 结论

当前 `feat/qa-platform-ux-modernization` 已经完成父任务拆出的 8 个子任务，达到了“可进入用户验收 / PR review”的状态，但不应直接宣称“可无条件合入 main”。

可以成立的结论：

- UI/UX 已从对象管理后台，推进到更接近 QA 日常工作流的自动化测试工作台。
- 系统列表假 0、上传类型落为 `other`、大树默认全展开、模块分支平铺、工作台入口不清晰、错误态吞掉真实失败等核心问题已被逐项处理。
- 当前 UI/UX 分支相对 `checkpoint/architecture-migration-pre-ux` 没有改动 `src/testcase_generator/**`，没有触碰生成算法、LLM 调用策略、case cap、核验策略或 worker 生成逻辑。
- 当前后端平台测试、前端 lint/type/build/model tests 在本报告前已通过。

不能夸大的结论：

- 阶段 E 的运行态证据发生在历史文档重标注和本轮系统列表稳定排序之前；需要再做一次轻量浏览器验收，覆盖 `/systems`、知识库、文档详情重标注、批次页、用例资产。
- 没有跑新的真实 LLM 批次；因此不能证明公司网关下的真实生成耗时、稳定性和新用例质量。
- 没有让一个未参与开发的 QA 按任务脚本走完整流程；“首次使用本平台也知道下一步”目前仍是专家启发式判断，不是用户测试结论。
- 审查确认/需修改/删除、澄清提交等 mutation 链路没有在最终状态下做破坏性真实提交验收。

## 分支与范围

- 基线分支：`feat/architecture-migration`
- 回退锚点：`checkpoint/architecture-migration-pre-ux` = `7ccbc7a`
- UI/UX 分支：`feat/qa-platform-ux-modernization`
- 当前 UI/UX 分支相对 checkpoint：`git diff --name-only checkpoint/architecture-migration-pre-ux...HEAD -- src/testcase_generator` 无输出。

这证明本轮 UI/UX 分支没有把测试用例生成核心逻辑混进来。平台 API 和前端有改动，是本任务范围内的系统统计、文档类型、页面动线、资产树和错误态改造。

## 子任务证据矩阵

| 子任务 | 结论 | 关键证据 | 剩余风险 |
|---|---|---|---|
| 阶段 A：分支/脏区治理 | 已完成 UI/UX 分支隔离 | `feat/architecture-migration` 清干净；checkpoint 与 UI/UX 分支创建完成；`.audit`、日志、备份未混入 | 历史提交中存在撤回提交，不在本任务重写历史 |
| 阶段 B：主流程安全快修 | 已解决关键真实 bug | 系统统计返回真实 `document_count/batch_count`；上传可选 `doc_type`；三处树默认不全展开 | 当时 lint 因缺配置不可用，后续已由 lint gate 子任务补齐 |
| 阶段 C：用例资产树 | 已完成递归树和共享基础组件 | `branch_path` 多级路径归一化；工作台和用例库复用模型/树/表格基础列；模型测试通过 | 尚未抽总装 `CaseAssetBrowser`，这是有意克制，避免误伤审查主流程 |
| 阶段 D：信息架构与视觉骨架 | 已显著改善 QA 动线 | 导航改为工作流导向；工作台待办队列；知识库三步流；文档详情追溯；搜索/导出/资产页错误态和恢复路径 | 仍需真实 QA 任务演练验证可理解性 |
| 阶段 E：运行态验收 | 已证明当时无阻断 UI 回归 | 11 个核心页面 Playwright 访问 200；无 console/page/failed request；截图覆盖桌面/窄屏 | 不是最新最终状态；未跑真实 LLM 批次；未做破坏性 mutation 验收 |
| 前端 ESLint 门禁 | 已补齐 | `npm run lint` 可真实解析 React + TS 并通过 | 目前是基础门禁，未启用 React Compiler 严格规则 |
| 系统删除软删文档 | 已修复阻塞删除的真实 bug | 仅软删除文档不再阻塞系统删除；有有效文档/批次仍阻止删除 | 未来新增外键表仍可能触发兜底 `IntegrityError` |
| 历史文档类型重标注 | 已补齐历史 `other` 修正入口 | 后端 `PATCH /documents/{id}/type`；知识库列表和文档详情支持人工重标注 | 不重新解析、不记录操作者；未来若 doc_type 影响解析需单独设计 |

## 父任务验收逐条核对

| 验收项 | 当前判断 | 证据 |
|---|---|---|
| `feat/architecture-migration` checkpoint 清晰，UI/UX 分支从干净基线创建 | 通过 | checkpoint `7ccbc7a`，当前分支 `feat/qa-platform-ux-modernization` |
| 系统列表不再显示假 0 | 通过 | 阶段 B 运行态报告证明 `漫剧批创系统` 文档数 1、批次数 3；系统统计后端测试覆盖 |
| 上传前可选文档类型，上传后列表展示所选类型 | 通过 | `documentApi.batchUploadDocuments(..., docType)` 携带 `doc_type`；后端校验 `DOC_TYPES`；历史 `other` 可重标注 |
| 知识库、工作台、用例库树默认不全展开，支持滚动/搜索 | 通过 | 阶段 B/C review；`CaseAssetTree` 受控展开、内部滚动、搜索、展开/收起 |
| 用例树支持模块下多级分支表达 | 通过 | 阶段 C review：真实路径 `标题包 -> 新建编辑 -> 字数算法` 可递归展示 |
| QA 可从系统进入知识库、触发生成、处理澄清/失败、审查、资产、导出 | 阶段性通过 | 阶段 D/E 页面证据覆盖入口和状态；最终 mutation 和真实跑批仍需用户验收 |
| 前端 lint/type/build 通过，后端相关测试通过 | 通过 | 本报告前重新运行：`tests/platform_api` 71 passed；`npm run lint/typecheck/build/test:ui-models` 通过 |
| 主流程保护结果明确 | 通过 | `src/testcase_generator` 相对 checkpoint 无 diff；报告列出改动边界 |
| 每个子任务有独立 review | 通过 | 8 个子任务均归档 review |
| 父任务最终报告汇总 review 和未解决风险 | 当前报告补齐 | 本文件 |

## 本轮最终检查

在父任务收口时发现一个此前被历史数据规模触发的测试稳定性问题：

- 现象：`uv run pytest tests/platform_api` 首次运行时 70 passed / 1 failed。
- 失败点：`test_list_systems_returns_real_document_and_batch_counts` 从 `list_systems(offset=0, limit=100)` 中找刚插入系统，但系统列表查询没有 `order_by`，真实库系统较多时该系统可能不在当前页。
- 根因：分页列表依赖数据库默认顺序，是隐式假设；测试失败只是暴露了真实 UI 分页也可能漂移。
- 修复：`SystemService.list_systems` 增加 `order_by(System.created_at.desc(), System.id.desc())`。
- 规范沉淀：`.trellis/spec/backend/api-route-pattern.md` 新增“分页列表必须有确定性 order_by”。

最终命令结果：

| 命令 | 结果 |
|---|---|
| `uv run pytest tests/platform_api` | 71 passed，1 个既有 pytest config warning |
| `uv run ruff check src/platform_api/services/system_service.py tests/platform_api/test_system_service.py` | passed |
| `uv run ruff format --check src/platform_api/services/system_service.py` | passed |
| `npm run lint` | passed |
| `npm run typecheck` | passed |
| `npm run test:ui-models` | 21 passed |
| `npm run build` | passed，仍有既有 Vite large chunk warning |
| `git diff --check` | passed |

## 批判性自审

### 1. 是否符合“具备 QA 背景但首次使用本平台”的目标

方向是对的。导航、工作台、知识库、文档详情、批次页、用例资产、搜索和导出都围绕“下一步该做什么”组织，而不是仅展示对象列表。

但这仍然需要真实 QA 任务演练确认。专家评审能发现明显动线问题，不能代替真实使用者第一次上手时的理解成本。

### 2. 是否保护完整生成测试用例主流程

当前证据支持“没有改动生成核心”。UI/UX 分支相对 checkpoint 没有 `src/testcase_generator/**` diff。生成入口、批次页、澄清、审查、迭代、落库、导出入口都保留。

但没有跑新的真实 LLM 批次，所以只能说“UI/API 层未发现阻断”，不能说“最新真实生成质量已验证”。

### 3. 是否过度抽象

总体没有。阶段 C 没有强行抽一个大而全的 `CaseAssetBrowser`，而是先共享模型、树、标签和表格基础列，把审查动作留在工作台。这是正确克制。

后续如果继续抽总装组件，需要先列清楚工作台和用例库的差异：审核 mutation、自动跳下一条、详情抽屉、资产筛选、批次范围，不能为了“复用率”牺牲审查效率。

### 4. 是否可以现在合入 main

我的判断：还不建议直接合入 `main`。

更稳的下一步是：

1. 重新启动 API / worker / 前端，用当前最新代码做一次最终浏览器验收。
2. 让用户或另一个 QA 按任务脚本走一遍：建系统、上传 PRD、重标注历史文档、触发生成、进入批次、搜索来源、导出。
3. 在公司网络可用时再跑一次小规模真实 LLM 批次，验证生成链路不是只在旧批次上可浏览。
4. 通过后再开 PR 或准备合并策略。

## 建议状态

- 代码状态：可以作为 UI/UX 分支候选交付继续验收。
- Trellis 父任务：不建议立即归档，除非用户明确接受“未跑真实 LLM 批次 / 未做真实 QA 演练”的风险。
- 目标状态：不要标记全局目标完成；下一步应做最终运行态验收和用户验收脚本。
