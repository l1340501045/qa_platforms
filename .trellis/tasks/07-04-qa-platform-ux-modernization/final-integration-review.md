# QA 平台 UI/UX 重构父任务集成审查

## 结论

当前 `feat/qa-platform-ux-modernization` 父任务下 10 个子任务均已完成并归档。分支已经达到“UI/UX 候选交付、可进入真实小批次验收 / PR review 准备”的状态。

可以成立的结论：

- UI/UX 已从对象管理后台，推进到更接近 QA 日常自动化工作的测试平台：工作台、项目/系统、知识库、批次审查、用例资产、搜索、导出围绕主流程重新组织。
- 已修复用户最初指出的关键问题：系统列表假 0、上传资料类型误落 `other`、目录树默认全展开、模块分支平铺、工作台入口不清晰、错误态伪装空态。
- 当前 UI/UX 分支相对 `checkpoint/architecture-migration-pre-ux` 没有 `src/testcase_generator/**` diff；没有触碰生成算法、LLM 调用策略、case cap、核验策略或 worker 生成逻辑。
- 当前 HEAD 运行态验收已补齐：API、worker、前端在线；核心页面在 1280 和 1024 宽度下无页面级横向溢出、无控制台错误/告警；文档类型标注弹窗告警已修复。
- 已产出真实跑批与首次上手验收脚本，明确周一公司网络可用后如何判定可合 main、需修后合、或不可合。

不能夸大的结论：

- 没有用当前 HEAD 在公司 LLM 网关下跑新的真实批次；不能证明真实生成耗时、网关稳定性和新用例质量。
- 没有让未参与开发的 QA 按脚本完成第一次使用平台的任务演练；“首次使用平台也知道下一步”仍缺真人证据。
- 审查确认、需修改、删除、落库等破坏性 mutation 没有在最终状态下对真实验收批次执行。

因此，当前建议是：**不要立即合 main；先按真实跑批验收脚本跑一个小规模真实批次。若没有 P0/P1 UI 主流程问题，再进入 PR / 合并准备。**

## 分支与范围

- 基线分支：`feat/architecture-migration`
- 回退锚点：`checkpoint/architecture-migration-pre-ux` = `7ccbc7a`
- UI/UX 分支：`feat/qa-platform-ux-modernization`
- 最新收口提交：
  - `0f9cb6a 补齐当前HEAD运行态验收`
  - `1becabc 归档当前HEAD运行态验收任务`
  - `100635a 补齐真实跑批验收脚本`
  - `4605f24 归档真实跑批验收脚本任务`
- 主流程保护证据：`git diff checkpoint/architecture-migration-pre-ux...HEAD --name-only -- src/testcase_generator` 无输出。

这证明本轮 UI/UX 分支没有把测试用例生成核心逻辑混进来。平台 API 和前端有改动，是本任务范围内的系统统计、文档类型、页面动线、资产树和错误态改造。

## 子任务证据矩阵

| 子任务 | 结论 | 关键证据 | 剩余风险 |
|---|---|---|---|
| 阶段 A：分支/脏区治理 | 已完成 UI/UX 分支隔离 | `feat/architecture-migration` 清干净；checkpoint 与 UI/UX 分支创建完成；`.audit`、日志、备份未混入 | 历史提交中存在撤回提交，不在本任务重写历史 |
| 阶段 B：主流程安全快修 | 已解决关键真实 bug | 系统统计返回真实 `document_count/batch_count`；上传可选 `doc_type`；三处树默认不全展开 | 当时 lint 因缺配置不可用，后续已由 lint gate 子任务补齐 |
| 阶段 C：用例资产树 | 已完成递归树和共享基础组件 | `branch_path` 多级路径归一化；工作台和用例库复用模型/树/表格基础列；模型测试通过 | 尚未抽总装 `CaseAssetBrowser`，这是有意克制，避免误伤审查主流程 |
| 阶段 D：信息架构与视觉骨架 | 已显著改善 QA 动线 | 导航改为工作流导向；工作台待办队列；知识库三步流；文档详情追溯；搜索/导出/资产页错误态和恢复路径 | 仍需真实 QA 任务演练验证可理解性 |
| 阶段 E：运行态验收 | 已证明当时无阻断 UI 回归 | 11 个核心页面 Playwright 访问 200；无 console/page/failed request；截图覆盖桌面/窄屏 | 证据已被当前 HEAD 验收任务更新；阶段 E 历史证据不再单独作为最终依据 |
| 前端 ESLint 门禁 | 已补齐 | `npm run lint` 可真实解析 React + TS 并通过 | 目前是基础门禁，未启用 React Compiler 严格规则 |
| 系统删除软删文档 | 已修复阻塞删除的真实 bug | 仅软删除文档不再阻塞系统删除；有有效文档/批次仍阻止删除 | 未来新增外键表仍可能触发兜底 `IntegrityError` |
| 历史文档类型重标注 | 已补齐历史 `other` 修正入口 | 后端 `PATCH /documents/{id}/type`；知识库列表和文档详情支持人工重标注 | 不重新解析、不记录操作者；未来若 doc_type 影响解析需单独设计 |
| 当前 HEAD 运行态验收 | 已补齐最新浏览器证据 | `runtime-acceptance-report.md` 覆盖 API / worker / frontend、8 个核心页面、1280/1024、类型标注弹窗告警修复 | 未跑真实 LLM 新批次；未做破坏性 mutation |
| 真实批次与首次上手验收脚本 | 已补齐合并前执行方法 | `acceptance-runbook.md` 和 `post-batch-report-template.md` 区分小规模 UI 主链路验收与完整 PRD 质量回归 | 这是脚本，不是已通过的真实验收结果 |

## 父任务验收逐条核对

| 验收项 | 当前判断 | 证据 |
|---|---|---|
| `feat/architecture-migration` checkpoint 清晰，UI/UX 分支从干净基线创建 | 通过 | checkpoint `7ccbc7a`，当前分支 `feat/qa-platform-ux-modernization` |
| 系统列表不再显示假 0 | 通过 | 阶段 B 运行态报告 + 当前 HEAD 验收；`漫剧批创系统` 已显示真实文档数/批次数 |
| 上传前可选文档类型，上传后列表展示所选类型 | 通过 | `documentApi.batchUploadDocuments(..., docType)` 携带 `doc_type`；后端校验 `DOC_TYPES`；历史 `other` 可重标注 |
| 知识库、工作台、用例库树默认不全展开，支持滚动/搜索 | 通过 | 阶段 B/C review；`CaseAssetTree` 受控展开、内部滚动、搜索、展开/收起 |
| 用例树支持模块下多级分支表达 | 通过 | 阶段 C review：真实路径 `标题包 -> 新建编辑 -> 字数算法` 可递归展示 |
| QA 可从系统进入知识库、触发生成、处理澄清/失败、审查、资产、导出 | 阶段性通过 | 当前 HEAD 浏览器验收覆盖入口和只读页面；真实新批次和 mutation 仍需用户验收 |
| 前端 lint/type/build 通过，后端相关测试通过 | 通过 | 当前 HEAD 验收任务运行 `npm run lint`、`npm run typecheck`、`npm run build`；父任务此前运行 `tests/platform_api`、`test:ui-models` |
| 主流程保护结果明确 | 通过 | `src/testcase_generator` 相对 checkpoint 无 diff |
| 每个子任务有独立 review | 通过 | 10 个子任务均归档；文档型任务也有 `review.md` |
| 父任务最终报告汇总 review 和未解决风险 | 通过 | 本文件更新到当前 10/10 状态 |

## 当前 HEAD 运行态证据摘要

来自 `.trellis/tasks/archive/2026-07/07-04-07-04-ux-current-head-runtime-acceptance/runtime-acceptance-report.md`：

| 检查项 | 结果 |
|---|---|
| API health | `{"status":"ok","version":"0.1.0"}` |
| Frontend | `HTTP/1.1 200 OK` |
| Worker | `celery@LaceyMac: OK pong` |
| 1280 页面巡检 | `/systems`、知识库、文档详情、工作台、批次页、用例资产、搜索、导出均无控制台错误/告警和页面级横向溢出 |
| 1024 页面巡检 | 同一组核心页面均无控制台错误/告警和页面级横向溢出 |
| 本轮发现问题 | Ant Design Form 未连接告警 |
| 修复 | 文档详情和知识库标注类型弹窗改为 `initialValues + key` 初始化 |
| 门禁 | `npm run lint`、`npm run typecheck`、`npm run build` 通过 |

该证据证明“最新 UI 运行态可用”，但不证明“真实新批次生成质量已验证”。

## 真实跑批验收脚本摘要

来自 `.trellis/tasks/archive/2026-07/07-04-ux-real-batch-first-use-acceptance/acceptance-runbook.md`：

1. 先确认分支、工作区、`src/testcase_generator` 无 diff。
2. 启动 Docker infra、API、worker、frontend。
3. 确认 `.env` 模型配置和前端生成配置：
   - `LLM_PRIMARY_MODEL=claude-opus-4-6`
   - `LLM_VISION_MODEL=claude-opus-4-6`
   - `LLM_VERIFY_MODEL=deepseek-v4-pro-office`
   - `LLM_CONCURRENCY=8`
   - `existence_merge_enabled=true`
   - `split_cap_enabled=true`
   - `cases_per_tp_cap=4`
   - `p0_quota_enabled=false`
4. 新建专门验收系统，跑一个 1-3 模块的小规模真实批次。
5. 验证上传、生成、待澄清/失败/待审核、用例树、用例资产、搜索、导出。
6. 找一个具备 QA 背景但没用过平台的人，只给任务目标，不讲页面操作，观察能否首次上手。
7. 跑完后导出 `.audit/<batch_id>/`，交给 Codex 继续审查新批次用例质量。

## 合 main 判定

### 可以进入 PR / 合 main 准备

满足全部条件：

- 小规模真实批次能完成到待审核或归档。
- UI 没有 P0/P1 主流程卡点。
- 首次使用平台的 QA 能在少量提示内完成上传、生成、审查、导出任务。
- 新批次能导出 `.audit/<batch_id>/` 审查包。
- 生成失败若发生，根因明确是 LLM 网关、模型或生成策略，而不是 UI/UX 主链路。

### 不建议合 main

出现任一情况：

- 上传、生成、批次页、审查、资产、搜索、导出任一主链路断。
- 系统列表统计再次显示假 0。
- 上传资料类型仍误落 `other`。
- 批次状态让首次使用平台的 QA 无法判断下一步。
- 用例树退回 PRD 章节平铺，或默认展开到不可操作。

### 不应归因到 UI/UX 的风险

以下问题需要记录，但应转到 infra 或 testcase generator 任务，而不是直接否定 UI/UX 分支：

- 公司 LLM 网关不可达。
- 模型响应超时或结构化 JSON 截断。
- 大 PRD 跑批耗时过长。
- 新批次用例仍有 P0 失真、needs_spec 过多、assertion 模糊等生成质量问题。

## 批判性自审

### 1. 是否符合“具备 QA 背景但首次使用本平台”的目标

方向已经对齐。当前 UI 不再按数据库对象堆菜单，而是按 QA 工作流组织：工作台处理待办，项目/系统承接资料和生成入口，用例资产沉淀结果，搜索定位历史覆盖，导出服务交付。

但仍缺真人首次上手证据。专家审查能发现明显动线问题，不能代替真实 QA 第一次使用时的理解成本。

### 2. 是否保护完整生成测试用例主流程

当前证据支持“没有改动生成核心”。UI/UX 分支相对 checkpoint 没有 `src/testcase_generator/**` diff。生成入口、批次页、澄清、审查、迭代、落库、导出入口都保留。

但没有跑新的真实 LLM 批次，所以只能说“UI/API 层未发现阻断”，不能说“最新真实生成质量已验证”。

### 3. 是否过度抽象

总体没有。阶段 C 没有强行抽一个大而全的 `CaseAssetBrowser`，而是先共享模型、树、标签和表格基础列，把审查动作留在工作台。这是正确克制。

后续如果继续抽总装组件，需要先列清楚工作台和用例库的差异：审核 mutation、自动跳下一条、详情抽屉、资产筛选、批次范围，不能为了“复用率”牺牲审查效率。

### 4. 现在是否应标记全局目标完成

不应标记完成。

当前已经完成 UI/UX 分支候选交付和验证脚本，但用户原目标要求“探索页面并重构，使其符合 QA 日常自动化最佳动线，并对齐行业最佳实践和系统架构”。这个目标的完成证据必须包括：

- 当前代码运行态通过。
- 真实新批次主流程通过。
- 至少一次首次使用平台的 QA 任务演练通过。
- 对新批次用例质量和模块树的 `.audit` 审查没有发现 P0/P1 回归。

目前只满足第一项，第二到第四项等待公司网络下执行。

## 建议状态

- 代码状态：UI/UX 候选交付。
- Trellis 父任务：可以保留为 planning，等待真实小批次验收结果；暂不归档父任务。
- 全局目标：继续保持 active，不标记 complete。
- 下一步：周一按 `acceptance-runbook.md` 跑小规模真实批次，跑完按 `post-batch-report-template.md` 回填给 Codex。
