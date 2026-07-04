# QA 平台 UI/UX 重构父任务集成审查

## 结论

当前 `feat/qa-platform-ux-modernization` 的 UI/UX 主体改造、运行态验收、真实验收脚本和验收入口资料已经阶段性收口。分支已经达到“UI/UX 候选交付、可进入真实小批次验收 / PR review 准备”的状态。

可以成立的结论：

- UI/UX 已从对象管理后台，推进到更接近 QA 日常自动化工作的测试平台：工作台、项目/系统、知识库、批次审查、用例资产、搜索、导出围绕主流程重新组织。
- 已修复用户最初指出的关键问题：系统列表假 0、上传资料类型误落 `other`、目录树默认全展开、模块分支平铺、工作台入口不清晰、错误态伪装空态。
- 当前 UI/UX 分支相对 `checkpoint/architecture-migration-pre-ux` 没有 `src/testcase_generator/**` diff；没有触碰生成算法、LLM 调用策略、case cap、核验策略或 worker 生成逻辑。
- 当前 HEAD 运行态验收已补齐：API、worker、前端在线；核心页面在 1280 和 1024 宽度下无页面级横向溢出、无控制台错误/告警；文档类型标注弹窗告警已修复。
- 已产出真实跑批与首次使用平台验收脚本，明确周一公司网络可用后如何判定可合 main、需修后合、或不可合。
- 已补充固定小规模验收 PRD 样例 `docs/acceptance/ux-small-batch-prd.md`，避免周一临时裁剪大 PRD 带来不可控变量。
- 已把真实验收入口收口到 `docs/acceptance/`，执行者不用进入 `.trellis/tasks/archive` 才能找到 runbook、回填模板和样例 PRD。
- 已补充 UI/UX 合并前验收证据台账，明确哪些证据已成立、哪些必须等周一真实跑批和真人演练补齐。
- 已修正 UI/UX 验收前预检与 runbook 的一致性：预检覆盖当前 6 个验收文件，runbook 不再要求固定历史提交必须出现在最近 5 条内。
- 已增强 UI/UX 验收前预检：静态检查真实跑批关键生成配置，确认前端、settings、pipeline 契约中的 merge/cap/P0 quota 配置一致。
- 已补充 UI/UX 验收前预检脚本测试，覆盖前端、pipeline、settings 三类配置解析和不一致失败路径。
- 已清理 UI/UX 验收预检脚本测试输出中的无效 pytest 配置告警，目标单测输出不再夹带 `collect_ignore_glob` warning。
- 已补充 UI 验收前页面 dry-run：在不触发生成的前提下复查工作台、项目/系统、知识库、批次页、用例资产、搜索和导出入口。
- 已补充首次使用平台的 QA 演练观察表，明确任务话术、逐步观察项、目标级/操作级提示规则和 P0/P1/P2 判级。

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
  - `a5cf515 补充小规模跑批验收PRD样例`
  - `c418c94 归档小规模跑批验收PRD样例任务`
  - `8cb395d 补充UI验收入口说明`
  - `e01d5a4 归档UI验收入口说明任务`
  - `c2355d9 补齐UI验收前预检脚本`
  - `e45c3d2 归档UI验收前预检脚本任务`
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
| 真实批次与首次使用平台验收脚本 | 已补齐合并前执行方法 | `docs/acceptance/runbook.md` 和 `docs/acceptance/post-batch-report-template.md` 区分小规模 UI 主链路验收与完整 PRD 质量回归 | 这是脚本，不是已通过的真实验收结果 |
| 小规模真实跑批 PRD 样例 | 已补齐固定验收输入 | `docs/acceptance/ux-small-batch-prd.md` 覆盖权限、字段边界、CSV 上传、异步状态、失败重试、停止、分页和导出 | 不含图片，不能替代视觉模型链路验收；不能替代完整大 PRD 质量回归 |
| UI 验收入口说明 | 已补齐周一执行入口 | `docs/acceptance/README.md` 明确执行顺序、GO / NO-GO 和回填入口 | 仍需真实批次结果回填 |
| UI 验收资料自包含化 | 已补齐可迁移验收包 | `docs/acceptance/runbook.md`、`post-batch-report-template.md`、`ux-small-batch-prd.md` 在同目录内自包含 | runbook 与 Trellis 归档存在副本，后续流程变化要同步 |
| UI 验收前页面 dry-run | 已补齐不触发生成的页面复查 | `dry-run-report.md` 覆盖工作台、项目/系统、知识库、生成弹窗、批次页、用例资产、搜索、导出和 1024 宽度溢出检查 | 未创建真实新批次；不能证明生成质量或真人首次使用表现 |
| 首次使用平台 QA 演练观察表 | 已补齐真人演练记录方式 | `docs/acceptance/first-use-observation.md` 明确任务话术、观察表、提示规则和判级标准 | 观察表不是演练结果；仍需真人执行后回填 |
| 首次使用平台 QA 验收口径校准 | 已补齐验收口径收紧 | 验收对象校准为“具备 QA 背景但首次使用平台的人”，通过条件不再依赖平台操作讲解 | 仍需真人执行后证明该口径成立 |
| UI 验收证据台账 | 已补齐合并前证据总账 | `docs/acceptance/evidence-ledger.md` 列出分支、环境、小批次、首次使用平台 QA 演练和 `.audit` 审查证据 | 台账不是验收结果；仍需周一逐项回填 |
| UI 验收预检与 runbook 一致性 | 已补齐执行一致性修正 | `scripts/ux_acceptance_preflight.py` 覆盖 6 个验收文件；runbook 改为检查固定 HEAD 可追溯，不依赖固定提交出现在最近 5 条 | 仍需周一在公司网络下跑完整预检 |
| UI 验收预检覆盖生成配置 | 已补齐静态配置检查 | `scripts/ux_acceptance_preflight.py` 检查 `existence_merge_enabled=True`、`split_cap_enabled=True`、`cases_per_tp_cap=4`、`p0_quota_enabled=False`，并校验前端、settings、pipeline 契约一致 | 只证明配置静态一致，不证明真实生成质量 |
| UI 验收预检脚本测试补强 | 已补齐测试保护 | `tests/test_ux_acceptance_preflight.py` 覆盖配置解析和 mismatch fail fast；`pytest` 通过 | 目标单测配置告警已在后续清理任务中移除 |
| UI 验收测试输出告警清理 | 已清理测试噪音 | 移除无效 `collect_ignore_glob` pytest ini 配置；目标单测输出不再出现配置告警 | 仅清理测试配置，不改变测试目录结构 |

## 父任务验收逐条核对

| 验收项 | 当前判断 | 证据 |
|---|---|---|
| `feat/architecture-migration` checkpoint 清晰，UI/UX 分支从干净基线创建 | 通过 | checkpoint `7ccbc7a`，当前分支 `feat/qa-platform-ux-modernization` |
| 系统列表不再显示假 0 | 通过 | 阶段 B 运行态报告 + 当前 HEAD 验收；`漫剧批创系统` 已显示真实文档数/批次数 |
| 上传前可选文档类型，上传后列表展示所选类型 | 通过 | `documentApi.batchUploadDocuments(..., docType)` 携带 `doc_type`；后端校验 `DOC_TYPES`；历史 `other` 可重标注 |
| 知识库、工作台、用例库树默认不全展开，支持滚动/搜索 | 通过 | 阶段 B/C review；`CaseAssetTree` 受控展开、内部滚动、搜索、展开/收起 |
| 用例树支持模块下多级分支表达 | 通过 | 阶段 C review：真实路径 `标题包 -> 新建编辑 -> 字数算法` 可递归展示 |
| QA 可从系统进入知识库、触发生成、处理澄清/失败、审查、资产、导出 | 阶段性通过 | 当前 HEAD 浏览器验收覆盖入口和只读页面；dry-run 已复查生成弹窗、批次页、资产、搜索和导出；真实新批次和 mutation 仍需用户验收 |
| 前端 lint/type/build 通过，后端相关测试通过 | 通过 | 当前 HEAD 验收任务运行 `npm run lint`、`npm run typecheck`、`npm run build`；父任务此前运行 `tests/platform_api`、`test:ui-models` |
| 主流程保护结果明确 | 通过 | `src/testcase_generator` 相对 checkpoint 无 diff |
| 每个子任务有独立 review | 通过 | 已完成的 UI/UX 子任务均有 `review.md`；验收资料收口任务也补了自审 |
| 父任务最终报告汇总 review 和未解决风险 | 通过 | 本文件更新到当前验收入口收口状态 |

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

来自 `docs/acceptance/runbook.md`：

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
4. 新建专门验收系统，默认上传 `docs/acceptance/ux-small-batch-prd.md` 跑一个小规模真实批次。
5. 验证上传、生成、待澄清/失败/待审核、用例树、用例资产、搜索、导出。
6. 找一个具备 QA 背景但首次使用本平台的人，只给任务目标，不讲页面操作，观察能否按任务目标完成。
7. 跑完后导出 `.audit/<batch_id>/`，交给 Codex 继续审查新批次用例质量。

## 合 main 判定

### 可以进入 PR / 合 main 准备

满足全部条件：

- 小规模真实批次能完成到待审核或归档。
- UI 没有 P0/P1 主流程卡点。
- 首次使用平台的 QA 不需要平台操作讲解；如有提示，也只需要目标级提示，即可完成上传、生成、审查、导出任务。
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

但仍缺真人首次使用平台证据。专家审查能发现明显动线问题，不能代替真实 QA 第一次使用平台时的理解成本。

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

### 5. dry-run 是否改变合 main 结论

不改变。

dry-run 证明页面入口和 runbook 一致性更强，但没有创建真实批次，也没有真人首次使用平台演练。它只支持“可以进入真实小规模验收”，不支持“可以直接合 main”。

### 6. 观察表是否改变合 main 结论

不改变。

观察表只让真人演练证据更可采集、更可审查；它不是演练本身。合 main 仍需要真实参与者按观察表完成任务并回填结果。

## 建议状态

- 代码状态：UI/UX 候选交付。
- Trellis 父任务：可以保留为 planning，等待真实小批次验收结果；暂不归档父任务。
- 全局目标：继续保持 active，不标记 complete。
- 下一步：周一按 `docs/acceptance/runbook.md` 使用 `docs/acceptance/ux-small-batch-prd.md` 跑小规模真实批次，跑完按 `docs/acceptance/post-batch-report-template.md` 回填给 Codex。
