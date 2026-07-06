# Design

## Boundary

本任务应优先复用现有结构：

- `src/testcase_generator/schemas/test_case.py`
- `src/testcase_generator/stages/test_points/`
- `src/testcase_generator/stages/write_cases/`
- `src/testcase_generator/stages/verify/`
- `src/testcase_generator/stages/export/`
- `scripts/audit_export.py`

不新增独立审查系统，不新增 DB 表，不新增 API。

## Data Flow

当前链路大致为：

1. parse / source registry 解析 PRD、图述、外部材料并带上 source metadata。
2. test_points 阶段生成测试点和维度。
3. write_cases 阶段生成用例、挂证据、做收敛。
4. verify 阶段给出 verdict / bucket / cross-section conflict。
5. export / audit_export 阶段将主集、澄清、待修正和审查包输出。

本任务的 guard 可以落在多个阶段，但最终契约必须一致：

- `main` 只保留可执行、可判定、证据足够的用例。
- `needs_spec` / clarification 保留需求未定义或 oracle 不足的风险。
- `conflict` / to_fix 保留与 PRD 冲突或 PRD 内部冲突的内容。

## Guard Strategy

### Guard Generalization Boundary

当前 `guards.py` 中已有两类逻辑，后续必须显式区分：

1. **通用质量闸**：不依赖具体业务域，换成电商、CRM、财务 PRD 仍应成立。
2. **领域规则**：依赖当前批创 PRD 的业务实体、状态口径、链路和事实，只能作为批创 rule pack。

短期允许为了修复真实批创批次保留领域规则，但新增规则必须能回答：

- 这是跨 PRD 通用质量规则，还是批创领域规则？
- 如果换成电商 PRD，这条规则是否仍然成立？
- 如果不成立，它的事实来源在哪里，如何替换或关闭？

目标结构：

```text
generic_guard_engine
  - assertion/evidence/oracle quality checks
  - cross-entity / cross-layer conflict hygiene
  - deterministic numeric/state/fact support checks

prd_facts
  - extracted entities
  - states
  - field constraints
  - role permissions
  - critical flows
  - supported technical contracts

domain_rule_pack
  - batch_creation rules
  - ecommerce rules
  - crm rules
```

`guards.py` 不应长期直接认识所有业务词。它可以消费 `prd_facts` 和 `domain_rule_pack`，但通用引擎本身不应硬编码“标题包”“投放链接”“监测链接”“素材评估”等批创实体。

迁移顺序建议：

1. 先在现有代码中用注释/函数边界标记领域规则，防止继续无意识扩散。
2. 把可计算事实抽成 PRD facts 结构，例如实体、状态、数量上限、字段约束、角色权限、主链路。
3. 把批创专属 entity/layer guard 移到 `batch_creation` rule pack。
4. 新 PRD 接入时先生成/校准自己的 facts/rule pack，再启用领域 guard。

### Clarification Guard

输入信号：

- 标题、步骤、预期、rationale、source quote 中出现 `需求待确认`、`待确认`、`PRD未定义`、`无确定断言`。

输出行为：

- bucket 不能是 `main`。
- verdict 可为 `undefined` / `unverified`，具体沿用现有模型。
- 原用例或问题必须保留在 clarification/debt 输出。

### Fake Oracle Guard

识别“高精度 oracle”：

- 精确 toast / 文案
- HTTP 状态码
- API path / payload / response schema
- DB table / field
- worker / MQ / cron / retry count / polling interval
- 精确 UI 布局和折叠策略

若 source evidence 没有直接支持这些 oracle，则不能标为 `grounded/main`。

API endpoint 的 atom 必须是完整 `METHOD /path`，不能退化成 `POST `、`/api/`、`/v1/` 这类碎片。中文动作描述里常见 `抓取POST /api/batch/submit请求payload`，提取时要支持方法名前没有英文空格、方法后路径紧贴中文后缀的形态；unsupported reason 应指向完整 endpoint，方便判断是补技术方案 evidence，还是把用例步骤改成业务可观察口径。

PRD 参数化 UI/toast 文案属于同一 oracle 的测试数据实例化，不应被当成 fake copy。规则只允许证据中独立 `N` 占位替换为数字，且模板其余文字必须逐字一致；例如 `已更新 N 个账户` 可支撑 `已更新 5 个账户`，但不能支撑 `已删除 5 个账户`。模板边界优先来自引号或 markdown 加粗文本，避免从整段 PRD 说明里截出过宽模板。

### No-Tech-Spec Guard

区分：

- 合法业务规则：PRD 明确写出的状态、权限、边界、业务异常。
- 非法实现断言：接口契约、表结构、worker、cron、幂等机制、重试次数、轮询频率。

只禁止后者在无技术方案时进入 `main`。

若 PRD 正文自身明确写出技术形态事实，则不需要额外技术方案才能作为 oracle。例如素材评估 PRD 写出“每天凌晨遍历所有已授权账户，逐账户拉取素材评估标签”时，`定时任务` 是被 PRD 直接支撑的调度事实，不应被 R3 误杀。该放行必须保持窄口径：普通“系统自动同步”不能支撑 worker/cron/轮询频率，只有明确周期/调度语义加执行动作的 evidence 才支撑 `定时任务`。

### Conflict Guard

现有 `cross_section_conflict` 不应只作为摘要指标。若有具体 `conflicting_refs`，导出主集时必须分流。

如果现有测试断言“不改写 verdict”，实现者需要更新该测试，并在交付中说明这是业务规则变更。

Verify 输出还必须给待处理项结构化诊断类型，避免报告继续靠人工抽样判断：

- `prd_conflict`：`cross_section_conflict=True` 且有 `conflicting_refs`，说明 PRD 条款自身互斥，需要产品裁决。
- `case_wrong`：无跨条款证据的同实体 `to_fix/conflict`，说明生成用例断言与当前 PRD 明文相反，应修用例/事实表。
- `verify_uncertain`：hard conflict 被同实体、同层级或依据锚定 guard 撤销，说明 verify 比较对象不可靠，应人工复核或补同层证据。

该字段只用于审查归因，不替代 `verdict` / `bucket` / `conflicting_refs`，也不删除原始风险文本。

### Evidence Trust Guard

PRD 正文 > 技术方案 > 流程图 > UI 设计稿 > 原型/AI caption。

低信任 source 不单独支撑高精度 oracle。与高信任 source 冲突时，以高信任 source 为准；无法判断则分流。

### External Mapping Guard

出现“等”“见外部目录”“参考外部目录”时，除非本地 source 中同时存在完整映射表，否则不得生成唯一映射断言。

### Deterministic Boundary Guard

能用规则计算的边界不要交给 LLM 自由判断。字数、数值、集合语义、边界形态都应有纯函数测试。

### Assertion Quality Guard

稳定执行集必须可执行。只有“页面正常显示”“信息正确”“符合预期”“校验正确”这类纯模糊预期的用例，即使 verify 判成 `grounded/main`，也不能进入主执行集。

规则：

- 宽口径模糊信号继续用于 audit 诊断，不能直接作为 hard guard，避免误杀“列表正常显示账户ID，授权状态为已授权”这类有具体可观察细节的预期。
- hard guard 只处理纯模糊预期：所有 expected result 都缺少具体字段、状态、数值、引号文案、写入/回写/任务/接口等可观察结果。
- 命中后分流到 `needs_spec/undefined`，`review_issue_type=case_wrong`，保留原始模糊预期到 `unsupported_assertions`，让后续修生成器或人工重写，不静默删除。
- audit_export 与 verify guard 必须复用同一断言质量 helper，避免报告计数与主集分流口径漂移。

### Deterministic Query Parameter Count Guard

URL query 参数数量、宏参数数量属于可计算事实，不应只由 LLM 判定。

规则：

- 当用例断言出现 `N 个宏参数`、`N 个 query 参数`、`N 个查询参数` 时，必须有可核验证据。
- 若证据中存在完整 URL query，按 query 参数名集合计数；重复参数名只算一次。
- 若证据 URL 被 `...` / `…` 截断，则不视为完整可核验证据，避免截断内容制造假数量。
- 若没有完整 URL，但 PRD 证据明确写出同一数量，可放行。
- 若断言数量与 URL 计数不一致，或数量断言没有完整 URL / 同数声明支撑，该 case 不得留在 `main`。

该规则覆盖本批次 stable 中 `30 个宏参数` 被 `main/grounded` 放行的漏检形态。

### Template Character Limit Guard

模板字符硬上限属于局部字段事实，优先级高于通用半角 `0.5 字`显示/统计算法。

规则：

- 当 PRD 证据明确写出“每条模板 N 字符”这类硬上限时，`N` 约束的是字符数量，不是半角折算后的显示字数。
- 若用例断言模板场景中 `M 个半角字符` 可保存/未超限，且 `M > N`，必须分流到 `to_fix/conflict`。
- 该 guard 只处理模板上下文，不影响普通标题/文案字段的半角字数显示规则。

该规则覆盖“项目名称模板 100 字符上限被解释成 200 个半角字符可通过”的形态。旧批次样例已经被 verify 判为 `to_fix/conflict`，新增 guard 用于防止后续同类 `main/grounded` 变体漏检。

### State Display vs Business State Layer Guard

状态展示文案与业务状态机名称属于不同抽象层，不能仅凭名称不一致直接判 PRD 真冲突。

规则：

- 当 verify 产出 `conflict/to_fix`，但没有 `cross_section_conflict` 和 `conflicting_refs` 时，必须检查是否属于同层/同实体误判。
- 对已知任务中心双口径形态：用例断言“列表/执行状态列/mock/partial 显示「部分失败」”，而 PRD 证据只有业务状态机名“提交完成-有失败”时，不得保留为硬 `to_fix/conflict`。
- 该 case 也不能在缺少同层 UI/状态展示证据时直接升回 `main`；应分流到 `needs_spec/undefined`，标记 `conflict_entity_mismatch=True`，保留 unsupported reason，等待同层证据或产品澄清。
- 若用例本身断言的是业务状态机名称应为“部分失败”，则仍是同层状态名冲突，应保留 `to_fix/conflict`。

该规则覆盖本批次 `4a90ae9e-3730-498a-8a0b-bd698fdc2651` 被业务状态机名误反驳的形态。

### Conflict Basis Anchor Guard

非跨条款 hard conflict 的反驳依据必须锚定在 case 的真实断言里，不能由 verify 自己补出不存在的前提。

规则：

- 当 verify 产出 `conflict/to_fix`，但没有 `cross_section_conflict` 和 `conflicting_refs` 时，若 `unsupported_assertions` 中出现“数字 + 业务单位”事实片段，应能在 case 标题/步骤/预期中找到同一数字与同一业务单位。
- 若反驳依据中的关键数字事实没有出现在 case 断言里，不保留 hard conflict；降为 `needs_spec/undefined`，标记 `conflict_entity_mismatch=True`，等待复核。
- 若 case 自身确实包含同一数字事实，则仍保留 `to_fix/conflict`。

该规则覆盖本批次 `b680acb3-041a-4a1a-85ff-6c273b93bc5a` 中 verify 发明“1 个素材”前提的形态。

### Geo Selection vs Interface Payload Layer Guard

地理位置 UI 勾选上限与接口层地区字符串收录上限属于不同抽象层，不能仅凭数量不一致直接判 PRD 真冲突。

规则：

- UI 层：区县选择器最多选 1000 个，第 1001 个起阻止勾选/红框提示。
- 接口层：接口层单次最多收录 200 条地区字符串，超出截断。
- 当 case 侧是 UI 勾选/红框/已选清单语义，而 PRD 反驳证据是接口层收录/截断语义时，不保留 hard conflict；降为 `needs_spec/undefined`，标记 `conflict_entity_mismatch=True`。
- 若 case 自身断言的是接口层可收录 1000 条地区字符串，则仍是同层接口约束冲突，应保留 `to_fix/conflict`。

该规则覆盖本批次 `3d072077-2bb2-4b3c-babc-cc9debc2e6d5` 中地理位置 UI 1000 上限被接口层 200 上限误反驳的形态。

### Link Entity Boundary Guard

投放链接与监测链接虽然都包含“链接”字样，但属于不同测试实体：

- 投放链接：批创表单内按投放方式过滤的可选链接列表，含空态与跳转管理页。
- 监测链接：IAP/IAA 预置宏参数链接，提交时由系统自动绑定。

规则：

- 无 cross-section refs 的 `conflict/to_fix` 中，如果 case 侧是投放链接空态/选择规则，而 PRD 侧反驳证据是监测链接自动绑定/宏参数规则，不得保留硬 conflict。
- 反向也一样：case 侧是监测链接自动绑定，而 PRD 侧反驳证据是投放链接列表单选控件时，不应直接判同实体冲突。
- 处理方式与状态展示层类似：撤销硬 conflict，降为 `needs_spec/undefined`，标记 `conflict_entity_mismatch=True`，等待同实体证据或产品裁决。
- 若 verify 已提供 `conflicting_refs`，说明存在明确 PRD 跨条款冲突证据，仍保留 `to_fix/conflict`，不由实体边界 guard 覆盖。

该规则覆盖本批次 `bc88ae99-ebcc-45b2-92d0-b63af747953d` 中“投放链接空列表”被“监测链接自动绑定”误反驳的形态。

## Compatibility

- 允许主集 case 数下降。
- 允许 `needs_spec` / clarification 数量上升。
- 不把风险静默丢弃。
- 不改变已有数据库结构。
- 不要求重新跑完整批次。

## Risks

- 过严会误杀合法业务异常用例。
- 过松会继续让 fake oracle 进入主集。
- 只在 audit_export 兜底会让前面 pipeline 继续污染数据。

## Review Focus

实现完成后，review 不只看测试绿，还要看：

- 是否靠重命名 bucket 美化指标。
- 是否保留了澄清项和冲突证据。
- 是否把 PRD 明确业务规则误分流。
- 是否新增过度抽象。
