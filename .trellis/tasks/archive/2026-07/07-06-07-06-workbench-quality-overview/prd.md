# 批次页质量分流总览稳定化

## 目标

让批次页的“质量分流”成为 QA 进入真实批次后的全批次质量总览，而不是随着当前筛选变化的局部统计。

具备 QA 背景、但首次使用本平台的人进入批次页后，应能先判断：

- 哪些用例属于主集候选，可以继续人工审查。
- 哪些用例属于规格待澄清，不应直接执行。
- 哪些用例属于生成待修正，不应交给 QA 当可执行用例。
- 当前筛选列表只是正在处理的队列，不等于全批次质量结构。

## 背景与证据

真实跑批 `95a00d54-428c-4efa-a29d-de183d491a34` 暴露了质量分流对 QA 动线的重要性：

- `main=1969`，这是默认可继续审查的主集候选。
- `needs_spec=632`，其中部分是真规格缺口，部分可能混入生成错误；不能默认交给 QA 执行。
- `to_fix=59`，应作为生成/核验待修正包，不应混入默认执行集。
- `conflict=36`，需要优先核对。
- 当前审查结论建议默认只发 `bucket=main + verdict=grounded + 非重复 + 排除 _review_required`。

当前代码已经有质量分流初版：

- [Workbench/index.tsx](/Users/echo_lacey/workspace/qa_platforms/web/src/pages/Workbench/index.tsx:471) 从 `allCasesForIterate` 计算 `qualityStats`。
- [Workbench/index.tsx](/Users/echo_lacey/workspace/qa_platforms/web/src/pages/Workbench/index.tsx:603) 点击质量分流按钮会设置 `bucketFilter` / `verdictFilter`。
- [CaseTreeReview.tsx](/Users/echo_lacey/workspace/qa_platforms/web/src/components/CaseTreeReview.tsx:149) `bucketFilter` / `verdictFilter` / `reviewIssueTypeFilter` 会传给后端 `case-tree`。
- [CaseTreeReview.tsx](/Users/echo_lacey/workspace/qa_platforms/web/src/components/CaseTreeReview.tsx:175) `onAllCasesChange` 返回的是当前 case-tree 查询结果，不是无筛选全批结果。

因此一旦用户点击“处理待澄清”或“查看冲突”，`qualityStats` 就会跟随当前筛选后的树变化。业务上这会让“全批总览”变成“当前筛选统计”，首次使用平台的 QA 容易失去整批质量结构。

## 需求

1. 批次页应保留一个稳定的全批次质量总览，不随 `bucketFilter`、`verdictFilter`、`reviewIssueTypeFilter`、`reviewFilter` 或标题搜索变化。
2. 当前筛选列表应继续受现有筛选影响；筛选能力和后端 `case-tree` 参数语义不得改变。
3. 页面必须清楚区分“全批质量结构”和“当前正在查看的队列”：
   - 全批总览用于判断整批能否进入审查/澄清/修正。
   - 当前队列用于逐条处理当前筛选结果。
4. 质量分流快捷按钮应继续驱动现有筛选，而不是新增后端契约。
5. 若全批总览加载失败，不得伪装成 0；应显示不可用状态，同时不阻塞下方当前队列审查。
6. 不改变后端生成逻辑、用例核验逻辑、case-tree 数据契约、批次状态流转和落库行为。

## 验收标准

- [ ] 初次进入批次页时，质量分流显示全批次 `main / needs_spec / to_fix / conflict / ungrounded+undefined` 总览。
- [ ] 点击“处理待澄清”“查看待修正”“查看冲突”等快捷入口后，质量分流总览数字不因当前筛选变成局部统计。
- [ ] 页面能显示当前筛选摘要，例如“当前队列：规格待澄清 / 与PRD冲突 / 待审”，让 QA 知道右侧表格正在看哪一部分。
- [ ] 当前用例树和表格继续使用已有 `bucketFilter`、`verdictFilter`、`reviewIssueTypeFilter`、`reviewFilter`，不改变后端 API 参数。
- [ ] 全批总览加载失败时，页面显示“质量总览暂时不可用”或等价提示，并允许继续审查当前列表。
- [ ] 不改动测试用例生成 pipeline、LLM 配置、worker 逻辑或后端生成侧质量策略。
- [ ] 前端构建/静态检查通过；若抽出纯函数，补充对应单测。

## 不做

- 不新增后端接口。
- 不在本切片修复 `needs_spec` 内部混入 `case_wrong` 的生成质量问题。
- 不在本切片调整 P0 判级、typed numeric oracle、模块归类或 critical flow 统计口径。
- 不把真实跑批 `.audit/` 产物加入提交。

## 批判性 Review

这份 PRD 当前方向成立，因为它直接回应真实跑批报告中的业务风险：`needs_spec/to_fix` 不应混进默认执行集，QA 需要先看整批质量结构再处理队列。

主要风险是过度设计：如果为了全批总览新增后端统计接口，会扩大切片并影响主流程。当前约束明确为“复用现有 case-tree 查询，前端维护全批快照”，风险可控。

另一个风险是把“全批总览”误做成审计报告。这个切片只解决批次页工作流可见性，不解决生成质量本身；typed numeric、P0 过宽、模块误归类仍应在生成/审查质量任务里处理。
