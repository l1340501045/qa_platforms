# Implementation Plan

## Phase 0. Context

1. 读取本任务的 `prd.md`、`design.md`、`implement.md`。
2. 读取项目规范：
   - `AGENTS.md`
   - `.trellis/workflow.md`
   - `.trellis/spec/backend/index.md`
   - `.trellis/spec/backend/testing-pattern.md`
   - `.trellis/spec/guides/index.md`
3. 定位现有代码和测试：
   - `src/testcase_generator/schemas/test_case.py`
   - `src/testcase_generator/stages/test_points/`
   - `src/testcase_generator/stages/write_cases/`
   - `src/testcase_generator/stages/verify/`
   - `src/testcase_generator/stages/export/`
   - `scripts/audit_export.py`
   - `tests/testcase_generator/test_verdict_consistency.py`
   - `tests/testcase_generator/test_verify_cross_section.py`
   - `tests/testcase_generator/test_test_points_batching.py`
   - `tests/testcase_generator/test_grounded_provenance.py`
   - `tests/testcase_generator/test_write_cases_split.py`
   - `tests/platform_api/test_export_split.py`

## Phase 1. Failing Tests

先写失败测试，再实现。

至少覆盖：

1. `需求待确认` 不进入 `main`，但保留到 clarification/debt。
2. PRD 只写约束时，具体 toast / HTTP status / payload 不能 `grounded/main`。
3. 无技术方案时，接口契约、表名、worker、cron、轮询频率等技术实现断言不放行。
4. PRD 明确业务级权限、安全、边界、状态用例不被 no-tech-spec guard 误杀。
5. `cross_section_conflict=True` 且 refs 非空时分流并保留冲突证据。
6. 低信任图述/AI caption 不能单独支撑精确布局或文案 oracle。
7. 外部目录不完整时，不生成唯一具体映射断言。
8. 9 个半角字符按规则向上取整为 5。
9. URL query / 宏参数数量断言必须被完整 URL 或同数证据支撑；截断 URL 不可支撑精确数量断言。
10. 任务中心“部分失败”UI 展示文案被业务状态机名“提交完成-有失败”反驳时，应降为 `needs_spec/undefined`，并用负向测试保证真正同层状态机名称冲突仍保留 `to_fix/conflict`。
11. 模板“每条 N 字符”硬上限不能被半角 `0.5 字`显示算法放宽；`200 个半角字符` 不得在 `100 字符`模板上限下留在 `main`，同时用负向测试保证 `100 个半角字符` 和普通标题文案半角规则不被误杀。
12. 中文动作里紧贴的 API endpoint（如 `抓取POST /api/batch/submit请求payload`）必须提取为完整 `POST /api/batch/submit` atom；不得退化成 `POST ` / `/api/` 泛片段，并用有证据负向测试保证完整 endpoint 可被 evidence 支撑。
13. PRD 参数化文案模板（如 `已更新 N 个账户`、`批量修改投放人（已选 N）`、`已创建 N 条广告任务`）必须能支撑具体测试数据实例，同时用负向测试保证非数字占位差异（如 `已删除 5 个账户`）仍被 R2 分流。
14. 投放链接与监测链接是不同测试实体；无 cross-section refs 的 `conflict/to_fix` 不得用监测链接自动绑定规则反驳投放链接空态，也不得用投放链接单选控件反驳监测链接自动绑定。需用负向测试保证同实体投放链接冲突仍保留 `to_fix/conflict`。
15. PRD 明确“每天凌晨/每日/定时/调度 + 遍历/拉取/执行/触发”时，应支撑 `定时任务` oracle；普通“系统自动同步”不得支撑 worker/cron/轮询频率。
16. 非 cross-section 的 `conflict/to_fix` 中，verify 的 `unsupported_assertions` 若包含“数字 + 业务单位”事实，必须锚定在 case 真实断言里；未锚定时降为 `needs_spec/undefined`，并用负向测试保证 case 自身确实断言该数字事实时仍保留 `to_fix/conflict`。
17. 地理位置 UI 勾选上限与接口层地区字符串收录上限不得互相反驳；UI 层 1000 区县选择上限被接口层 200 条收录上限反驳时应降为 `needs_spec/undefined`，并用负向测试保证接口层 1000 vs 200 的同层冲突仍保留 `to_fix/conflict`。
18. Verify 待处理项必须输出结构化审查诊断类型：跨条款有 refs 为 `prd_conflict`，同实体 hard conflict 为 `case_wrong`，同实体/同层级/依据未锚定 guard 撤销的 hard conflict 为 `verify_uncertain`；`summarize()` 必须输出 `by_review_issue_type`。
19. 纯模糊预期（如“页面正常显示/信息正确/符合预期”）不得留在 `grounded/main`；带具体字段、状态、数值、引号文案或副作用的预期不能被误杀。

## Phase 2. Implementation

按现有结构最小改动：

1. 优先复用已有 verdict、bucket、source_ref、trust_order、cross_section_conflict 字段。
2. 若需要 helper，放在最靠近现有职责的模块中，不新建大而全服务。
3. guard 应尽量是可测试的纯函数或小函数。
4. 导出层只能兜底，不能成为唯一修复点。
5. 保留原始风险文本和证据，不静默删除。
6. 宏参数 / query 参数数量 guard 放在 verify oracle guard 内，作为 R7 确定性事实校验与 R2 高精度 oracle 缺证据的交叉规则。
7. 状态展示文案 vs 业务状态机名称 guard 放在 verify oracle guard 内、非 main 早返回之前；只处理无 cross-section refs 的 `conflict/to_fix`，撤销硬 conflict 但不直接升回 main。
8. 模板字符硬上限 guard 放在 verify oracle guard 内，作为 R7 确定性事实冲突：模板证据写明 `N 字符`时，超过 `N` 的半角字符不可因显示字数折算而判可保存，分流到 `to_fix/conflict`。
9. API method+path 正则使用 ASCII 标识符边界而非 Unicode `\b`，兼容中文前缀；evidence 侧复用同一提取器做完整 path 精确匹配。
10. 参数化文案支持只落在 R2 evidence 支撑判断中：从 evidence 的引号或 markdown 加粗文本提取含独立 `N` 的模板，仅允许 `N` 替换为数字，模板其余文字必须匹配。
11. 链接实体边界 guard 放在 verify oracle guard 内、非 main 早返回之前；只处理无 cross-section refs 的 `conflict/to_fix`，撤销投放链接/监测链接互相反驳的硬 conflict，但不覆盖已有明确 PRD 跨条款冲突证据。
12. R3 技术断言 evidence 支撑判断增加窄口径定时任务语义：字面支撑之外，只允许明确调度周期/时点 + 执行动作支撑 `定时任务`，不扩展到普通自动同步。
13. conflict basis 锚定 guard 放在 verify oracle guard 内、非 main 早返回之前；只处理无 cross-section refs 的 `conflict/to_fix`，用数字+业务单位原子核对 verify 反驳依据是否真实出现在 case 断言中。
14. 地理位置 UI/API 层级 guard 放在 verify oracle guard 内、非 main 早返回之前；只撤销 UI 勾选上限被接口层收录上限反驳的 hard conflict，不撤销同层接口数量冲突。
15. 在 `CaseVerification` 中新增可选 `review_issue_type`，由 verify 构造、reconcile 和 oracle guard 分流点共同维护；不改变 `verdict`/`bucket` 既有契约，不清理 `conflicting_refs`。
16. 新增断言质量 helper：audit 宽口径统计与 oracle guard 纯模糊分流复用同一模块；hard guard 只在所有预期都缺少具体可观察结果时触发。

## 2026-07-03 记录：guard 通用性与领域硬编码风险

用户提出疑问：`guards.py` 当前很多规则能理解批创 PRD，但如果后续换成电商/CRM 等不同 PRD，硬编码批创实体会不够通用，甚至误杀/漏放。

判断：问题成立。当前 guard 中应区分：

- 通用质量闸：证据不足、纯模糊断言、技术派生无依据、数字/状态事实缺证据、跨实体/跨层级 conflict。
- 批创领域规则：投放链接 vs 监测链接、标题包、素材评估、任务状态展示口径、宏参数、批创提交链路。

后续实施任务：

- [ ] 给现有 `guards.py` 中的批创专属规则加清晰边界或迁出入口，避免被当成跨行业通用规则。
- [ ] 设计 `prd_facts` 输入结构：实体、状态、字段约束、角色权限、数量上限、主链路、技术契约。
- [ ] 设计 `domain_rule_pack` 结构，先落批创包，再为电商/CRM 等 PRD 留扩展点。
- [ ] 通用 guard 只消费 facts/rule pack，不直接硬编码“标题包/投放链接/监测链接/素材评估”等批创词。
- [ ] 新增自检要求：每条新增 guard 必须声明 `generic` 或 `domain-specific`，并说明换 PRD 时是否可复用。
- [ ] 后续迁移时保持当前批创批次行为不回退：先加 characterization tests，再拆文件/配置。

非目标：

- 本记录不要求立刻重构整个 guard 架构。
- 不阻塞当前批创系统质量修复。
- 不为了通用化牺牲当前真实批次已验证有效的防误判规则。

## 2026-07-03 增补：R9 纯模糊预期质量闸

文件范围：

- 新增：`src/testcase_generator/services/assertion_quality.py`
- 新增：`tests/testcase_generator/test_assertion_quality.py`
- 修改：`src/testcase_generator/stages/verify/guards.py`
- 修改：`scripts/audit_export.py`
- 修改：`tests/testcase_generator/test_oracle_guards.py`
- 修改：`.audit/6f30e1bd-89ad-4e98-878c-4b48014eb1a4/REPORT.md`

实现清单：

- [x] 把 audit 本地模糊断言正则抽为共享 `has_vague_assertion_signal()`。
- [x] 新增 `is_pure_vague_assertion_case()`，只识别“所有预期均为纯模糊短语”的不可执行用例。
- [x] oracle guard 新增 R9：`grounded/main` 且纯模糊预期时，分流到 `needs_spec/undefined`，`review_issue_type=case_wrong`。
- [x] 宽口径模糊信号和 hard guard 分离，避免误杀带具体字段/状态/数值的预期。
- [x] audit 诊断新增 `pure_vague_expected_count` 与样例，保留原 `vague_expected_count` 宽口径指标。

验证命令：

- [x] `uv run pytest tests/testcase_generator/test_oracle_guards.py -k "vague_only or vague_wording" -q`
- [x] `uv run pytest tests/testcase_generator/test_assertion_quality.py -q`
- [x] `uv run pytest tests/testcase_generator/test_oracle_guards.py -q`
- [x] `uv run pytest tests/testcase_generator/test_audit_export_module_tree.py -q`

## 2026-07-03 增补：review_issue_type 平台审查面闭环

背景：verify 已产出 `review_issue_type=case_wrong/prd_conflict/verify_uncertain`，`summarize()` 也有 `by_review_issue_type`，但平台用例树/API/UI 还只能按 bucket/verdict 看，审查人员仍无法直接筛出“用例错 / PRD 冲突 / 核验不确定”。

文件范围：

- 修改：`src/platform_api/repositories/testcase_repo.py`
- 修改：`src/platform_api/services/case_tree_service.py`
- 修改：`src/platform_api/api/v1/systems.py`
- 修改：`web/src/types/index.ts`
- 修改：`web/src/pages/CaseLibrary/index.tsx`
- 修改：`web/src/pages/Workbench/index.tsx`
- 修改：`web/src/components/CaseTreeReview.tsx`
- 修改：`scripts/audit_export.py`
- 修改：`tests/testcase_generator/test_audit_export_module_tree.py`
- 修改：`tests/platform_api/test_case_tree_service.py`
- 修改：`.audit/6f30e1bd-89ad-4e98-878c-4b48014eb1a4/REPORT.md`

实现清单：

- [x] `query_tree_data()` 读取 `TestCase.verification` JSONB，不新增 DB 列。
- [x] `CaseTreeService` 从 `verification.review_issue_type` 透传到 case-tree payload。
- [x] 既有 `GET /systems/{system_id}/case-tree` 增加 `review_issue_type` 查询参数，用于按诊断类型筛选；不新增 endpoint。
- [x] 用例库和工作台审核树都支持审查诊断筛选。
- [x] 表格质量列展示诊断标签：`用例错`、`PRD冲突`、`核验不确定`。
- [x] `.audit/index.json` 输出 `review_issue_type_dist`、`non_duplicate_review_issue_type_dist`。
- [x] `quality_diagnostics.{all,non_duplicate,stable}` 输出 `by_review_issue_type`、`p0_by_review_issue_type` 和样本。

验证命令：

- [x] `uv run pytest tests/platform_api/test_case_tree_service.py -q`
- [x] `uv run pytest tests/platform_api/test_case_tree_integration.py tests/platform_api/test_case_tree_service.py -q`
- [x] `uv run ruff check src/platform_api/services/case_tree_service.py src/platform_api/repositories/testcase_repo.py src/platform_api/api/v1/systems.py tests/platform_api/test_case_tree_service.py`
- [x] `uv run ruff format --check src/platform_api/services/case_tree_service.py src/platform_api/repositories/testcase_repo.py src/platform_api/api/v1/systems.py tests/platform_api/test_case_tree_service.py`
- [x] `uv run pytest tests/testcase_generator/test_audit_export_module_tree.py -k "quality_diagnostics" -q`
- [x] `npm run build`（web）

说明：这不改变生成/verify 的 verdict/bucket 契约，也不回写旧批次 JSONL；它只是把已有 verify 诊断暴露给平台审查和筛选。

## 2026-07-03 增补：PRD facts helper 第一刀

背景：报告后续 P0 项要求建立 PRD facts guard。行业实践上，风险驱动测试和规格驱动测试都要求把测试目标、事实约束和覆盖准则显式化；当前系统已有 query 参数数量、模板字符上限、状态层级等点状事实规则，但“不完整枚举/外部目录 + 唯一具体断言”仍散在 `guards.py`，且只稳定覆盖 ASCII 标识符，中文状态名会漏。

文件范围：

- 新增：`src/testcase_generator/services/prd_facts.py`
- 新增：`tests/testcase_generator/test_prd_facts.py`
- 修改：`src/testcase_generator/stages/verify/guards.py`
- 修改：`tests/testcase_generator/test_oracle_guards.py`
- 修改：`.audit/6f30e1bd-89ad-4e98-878c-4b48014eb1a4/REPORT.md`

实现清单：

- [x] 新增 `has_incomplete_fact_source()`，识别 `等`、`见外部目录`、`见巨量`、`参考第三方目录` 等不完整事实来源。
- [x] 新增 `extract_unique_fact_values()`，提取 `状态显示为「部分失败」`、`优化目标映射到 active_pay` 这类唯一事实值。
- [x] 新增 `unsupported_unique_fact_assertion()`：证据不完整且断言值未直接出现在证据中时，返回不可支撑原因；证据已列明的值放行。
- [x] R6 改为调用 shared PRD facts helper，保留旧 `active_pay` 行为，同时补上中文状态名场景。
- [x] 新增完整枚举 facts：`extract_closed_enum_values()` / `unsupported_closed_enum_assertion()`。PRD 明确完整状态枚举时，枚举外唯一状态值分流到 `to_fix/conflict`；PRD 含 `等` 或外部目录时不当闭集处理。
- [x] 该 helper 是通用质量闸，不依赖批创实体；后续长度、状态名、角色权限、边界值可继续迁入这里或拆成同层 facts module。

验证命令：

- [x] `uv run pytest tests/testcase_generator/test_prd_facts.py -q`
- [x] `uv run pytest tests/testcase_generator/test_oracle_guards.py -k "closed_enum or r6_etc_marker" -q`

## 2026-07-03 增补：PRD facts 数量上限单位解析修复

背景：`extract_numeric_upper_bounds()` 先匹配量词 `个/条`，导致 `1000个区县`
被解析成 `raw_atom=最多选择1000个`、`unit=""`，`1001个区县仍可提交成功`
的错误诊断也变成 `1001个`，丢失业务单位。这会削弱 R7 确定性事实 guard
的可审查性，并可能让不同业务单位之间误匹配。

文件范围：

- 修改：`src/testcase_generator/services/prd_facts.py`
- 修改：`tests/testcase_generator/test_prd_facts.py`
- 修改：`src/testcase_generator/stages/verify/guards.py`（import 排序）
- 修改：`.trellis/spec/backend/quality-guidelines.md`

实现清单：

- [x] `_UNIT_PATTERN` 支持 `个/条 + 语义单位` 的整体捕获。
- [x] `_canonical_unit()` 去掉前置量词后再归一化业务单位。
- [x] 单位候选按长词优先：`字符` before `字`、`广告任务` before `广告`、`地区字符串` before `地区`、`宏参数` before `参数`。
- [x] 增加回归测试 `test_extract_numeric_upper_bounds_prefers_long_semantic_units`，防止长单位被短前缀截断。
- [x] 更新 backend quality spec，记录 deterministic PRD facts parser 的实现契约与测试要求。

验证命令：

- [x] `uv run pytest tests/testcase_generator/test_prd_facts.py -q` → 12 passed
- [x] `uv run pytest tests/testcase_generator/test_oracle_guards.py tests/testcase_generator/test_prd_facts.py tests/testcase_generator/test_assertion_quality.py -q` → 116 passed
- [x] `uv run ruff check src/testcase_generator/services/prd_facts.py tests/testcase_generator/test_prd_facts.py`
- [x] `uv run ruff check <当前任务 Python 文件集>`
- [x] `uv run ruff format --check <当前任务 Python 文件集>`

## Phase 3. Local Verification

必跑：

```bash
uv run ruff check src/testcase_generator scripts/audit_export.py tests/testcase_generator tests/platform_api/test_export_split.py
uv run ruff format --check src/testcase_generator scripts/audit_export.py tests/testcase_generator tests/platform_api/test_export_split.py
uv run pytest tests/testcase_generator/test_verdict_consistency.py tests/testcase_generator/test_verify_cross_section.py tests/testcase_generator/test_test_points_batching.py tests/testcase_generator/test_grounded_provenance.py tests/testcase_generator/test_write_cases_split.py tests/platform_api/test_export_split.py
```

如果改动影响更广，再跑：

```bash
uv run pytest tests/testcase_generator --ignore=integration
```

不要跑完整真实批次。

## Phase 4. Optional Offline Probe

可用现有审查包做轻量验证：

- `.audit/0627a024-6d63-4d9c-a0a6-0f58dc9af0b5`

目标不是追求主集数量最大，而是确认：

- fake oracle 从 `main` 分流。
- clarification/debt 数量和内容可审查。
- conflict 证据保留。

## Delivery Report

交付时必须说明：

- 改了哪些文件。
- 每个 guard 对应的测试名。
- 测试命令和结果。
- 哪些内容会从 `main` 分流到 `needs_spec` / `conflict`。
- 哪些内容仍应保留为 executable case。
- 仍需产品裁决的 PRD 冲突。

## Critical Self-Review Checklist

提交前逐条自查：

- [ ] 是否只是改了 `.audit` 分类，没有改变生成/验证/导出分流契约？
- [ ] 是否直接删除了不确定用例，导致风险消失？
- [ ] 是否把 PRD 明确业务规则误判成技术派生？
- [ ] 是否把低信任图述当成唯一证据？
- [ ] 是否所有新增规则都有失败优先测试？
- [ ] 是否保留冲突证据和澄清原因？-+
