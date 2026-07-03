# 质量门冲突澄清交互改造 — 设计文档

> 状态：设计 v2（brainstorming + 评审修订产出）。下一步：writing-plans 出实施计划。
> 关联：comprehend 质量门 NO_GO 澄清流程；前端 Workbench「质量门澄清」弹窗。
> 产品决策（已与用户确认）：①AI 给推荐裁决但**不预选**（推荐仅提示，用户须主动点）；②本次**只改「冲突类」问题**体验，盲区类保留输入框仅加引导；③实现路径选「**AI 结构化输出 + 前端自动兜底**」。
> v2/v3 修订：依据评审（critic）两轮核对真实代码后修正，详见 §7。

## 1. 背景与目标

### 1.1 现状问题

当 PRD 内部出现同级冲突（典型：同一份 PRD 不同章节自相矛盾），comprehend 质量门判 NO_GO，流水线 `interrupt()` 挂起（`graph.py:interrupt_node`），前端弹「质量门澄清」窗等人工裁决。当前弹窗有三类问题：

1. **红框 context 显示错乱（核心 bug）**：context 行显示 `'未列'(Level 3) 与 '未列'(Level 3) 描述不一致`。经核对代码，根因为：
   - `ComprehensionLLMOutput.identified_conflicts` 是无结构约束的 `List[dict]`（node.py:48），prompt 也未要求 LLM 分项填来源/等级。
   - **「未列」来自 LLM 自身输出，不是代码兜底**：全 `src/` 搜不到「未列」（代码默认是 `lc.get("source_a", "未知")`，node.py:273）。LLM 在「同文档跨章节冲突」场景下，因没有两个独立来源文档，把 `source_a/source_b` 填成「未列」占位串，`trust_level` 缺省落 3。
   - `_build_open_questions`（node.py:303-304）直接用这些占位值拼 context → 「未列(Level 3)」。
   - **更深层**：`SourceConflict` schema 是为「跨文档冲突」设计（靠 trust_level 高低自动仲裁），不适配「同文档跨章节」冲突——无「章节定位」字段，且同文档两方 trust_level 应同为 1。
   - **推论**：必填 `str` 字段挡不住 LLM 继续吐占位串，真正根治靠 **prompt 明确要求填章节号 + 代码校验降级**（占位/空时退安全文案），而非仅加 schema。

2. **富文本框无引导**：一个空 `TextArea` + "请输入回答"，用户不知道该回答什么、什么格式、答案如何被使用。

3. **前后端字段链路未对齐（连带 bug）**：`comprehend_node` 用 `OpenQuestion.model_dump()` 产出 `{question_id, blocking, ...}`（node.py:153），经 interrupt→提取→StageArtifact→`get_batch_status` 全程**透传**到前端；而前端 `OpenQuestion` 期望 `{id, priority, ...}`（types/index.ts:269-274）。后果：
   - `key={q.id}`、`priority` 标签恒 `undefined`；
   - `clarifyAnswers` 以 `q.id`(=`undefined`) 为 key（index.tsx:176,441,443）→ **多问题时共用 `"undefined"` 一个 key、互相覆盖**。
   - 该弹窗历史上几乎从未真正端到端使用，故一直未被发现。

### 1.2 目标

- 冲突类问题：卡片化呈现冲突两方（章节 + 说法 + 等级）、AI 给推荐裁决（提示性，不预选）、三选项裁决（A 方 / B 方 / 自定义）。
- 根治红框：context 正确显示真实章节与等级；LLM 给不出有效章节定位时主动降级到安全文案（不出现「未列/未知/(Level 3)」占位）。
- AI 结构化输出冲突 + 前端兜底降级：AI 不配合时退回纯文字 + 输入框，零崩溃。
- 校准前后端字段链路：多问题各自独立作答不串味，`question_id` 正确回传。
- 盲区类问题：保留输入框，加引导文案与示例（本次不做选项化）。

### 1.3 成功标准

- 冲突类问题在弹窗中以「卡片 + 两方并排 + AI 推荐（不预选）+ 三选项」呈现；红框显示正确章节与等级。
- LLM 未给结构化 / 给出占位章节时，弹窗优雅降级为纯文字 + 输入框（不报错、不空白、不显示占位坏值）。
- 多问题场景各自独立作答互不覆盖；提交后流水线正确恢复。
- 既有 GO/CONDITIONAL 路径与不触发冲突的批次行为不变；全量测试通过。

## 2. 范围

**做**：
1. comprehend LLM 结构化冲突输出（`ComprehensionLLMOutput` schema 用显式 `ConflictDetail` + `COMPREHEND_SYSTEM_PROMPT`，要求真实章节号、禁止占位）。
2. schema 扩展（新增**可选**字段，向后兼容）：`ConflictSide`/`ConflictDetail`；`SourceConflict.conflict_detail`；`OpenQuestion` 加 `question_type`/`conflict_detail`/`severity`。
3. `_merge_conflicts`：结构化冲突正确填章节定位与同级 trust_level，**显式 `resolution="unresolved"`**（与 `recommendation` 解耦），挂 `conflict_detail`；占位/空校验降级。
4. `_build_open_questions`：透传 `conflict.conflict_detail` 到 `OpenQuestion`，设 `question_type`，context 正确拼接。
5. 字段链路校准：在 `comprehend_node` 序列化点（node.py:153）显式构造前端契约 dict（补 `id`/`priority`/`question_type`/`conflict_detail`）。
6. 前端弹窗：按 `question_type` 渲染（冲突→卡片或纯文字冲突文案；盲区→输入框 + 引导）；冲突卡片含选项化 + AI 推荐（不预选）+ 自定义降级。
7. 单测（后端解析 / 兜底降级 / context；前端渲染 / 选项转答案 / 多问题独立作答）。

**不做**：
- 改 clarify 提交接口契约主结构、resume 恢复流程、澄清作为 trust_level 3 注入逻辑。
- 盲区类选项化（仅加引导文案）。
- 改 gate 判定阈值 / 逻辑、`SourceConflict` 主字段语义（仅新增可选字段）。

## 3. 设计

### 3.1 数据模型（schema 扩展，向后兼容）

新增结构化冲突描述（`schemas/comprehension_report.py`），**LLM 输出与 `conflict_detail` 复用同一组 schema**：

```python
class ConflictSide(BaseModel):
    """冲突一方"""
    location: str                              # 章节定位，如 "§5.6.1" / "§9.2 表"
    statement: str                             # 该处说法，如 "必填 / ≤50字 / 不支持 emoji"
    trust_level: int = Field(ge=1, le=5)       # 信任等级（同文档跨章节时两方相同）

class ConflictDetail(BaseModel):
    """结构化冲突（供前端选项化渲染；亦作 LLM identified_conflicts 元素）"""
    topic: str                                 # 冲突点标题，如 "角色名称字数上限"
    side_a: ConflictSide
    side_b: ConflictSide
    recommendation: Literal["side_a", "side_b", "neither"]  # AI 推荐方（与 resolution 解耦）
    recommendation_reason: str                 # 推荐理由（一句话）
```

`SourceConflict` 新增可选字段（**承载结构化信息穿过 `_build_open_questions`**，解决 F1）：

```python
conflict_detail: ConflictDetail | None = None  # 结构化时有；规则法/降级时 None
```

`OpenQuestion` 新增可选字段：

```python
question_type: Literal["conflict", "blind_spot"] = "blind_spot"  # 显式判别（解决 F4）
conflict_detail: ConflictDetail | None = None                    # 冲突且结构化时才有
severity: Literal["high", "medium", "low"] = "medium"            # 透传给前端 priority（解决 F5）
```

主字段 `question_id/question/context/blocking` 保留语义不变 → 兜底路径仍可用。

### 3.2 LLM 结构化输出（`stages/comprehend/node.py`）

`ComprehensionLLMOutput.identified_conflicts` 从 `List[dict]` 改为 `List[ConflictDetail]`（显式 schema）。

`COMPREHEND_SYSTEM_PROMPT` 补充：
- 明确「同文档跨章节冲突」也要识别，两方 `trust_level` 相同（同一文档）。
- 每方 `location` **尽量填真实章节号 / 表名**，**禁止编造「未列」「N/A」「未知」等占位词**；确实定位不到时**仍须上报该冲突**（`location` 留空 / 置 `null`），交由 §3.3 代码降级为纯文字冲突——保证同文档冲突不被静默丢弃、NO_GO 不漏触发（解决 N1）。
- 给出 `recommendation`（side_a/side_b/neither）+ 一句 `recommendation_reason`（依据信任顺序 / 具体性 / 常识）。

### 3.3 冲突合并与问题构建（`node.py`）

- `_merge_conflicts`：
  - 把每个 LLM `ConflictDetail` 映射为 `SourceConflict`：`source_a=side_a.location`、`source_a_trust_level=side_a.trust_level`（side_b 同理）、`description` 取 `topic` + 两方说法摘要、`conflict_detail=<原 ConflictDetail>`。
  - **`resolution` 显式置 `"unresolved"`**（同 trust_level 即同级 → 需人工裁决；与 `recommendation` 完全解耦，避免 F2 的崩溃/NO_GO 不触发）。
  - **校验降级**：抽共享判定 `_is_placeholder(s)`（空 / 命中占位词「未列/未知/N/A」等）；若任一方 `location` 占位，该冲突 `conflict_detail=None`（退化为纯文字冲突），不污染卡片。
  - 规则法 `detector.detect_conflicts` 产出的冲突无结构化信息 → `conflict_detail=None`（保持现状）。
- `_build_open_questions`：
  - 冲突类问题：`question_type="conflict"`，`severity="high"`（冲突比盲区更紧急，避免优先级倒挂，解决 N2），`conflict_detail=conflict.conflict_detail`（可能为 None）；context 用真实章节 + 等级拼接（如 `'§5.6.1'(Level 1) 与 '§9.2 表'(Level 1) 描述不一致`）；**context 是否退安全文案，按 `source_a/source_b` 经 `_is_placeholder()` 判定，不可用 `conflict_detail is None` 触发**（否则规则法冲突的真实文档标题会被误丢，见小注）。
  - 盲区类问题：`question_type="blind_spot"`，`conflict_detail=None`，`severity=blind_spot.severity`。

### 3.4 字段链路校准（转换点 = node.py:153）

后续 interrupt→`_extract_open_questions_from_snapshot`→`on_pipeline_suspended`→`get_batch_status` 全程透传，故只需在**唯一序列化点** `comprehend_node` 返回 `open_questions` 处（node.py:153）显式构造前端契约 dict（`model_dump()` 不会凭空加键，须显式构造，解决 F6）：

```python
"open_questions": [
    {
        "id": q.question_id,                 # 对齐前端 q.id
        "question_id": q.question_id,        # 保留供 resume/审计
        "question": q.question,
        "context": q.context,
        "priority": _severity_to_priority(q),# high/medium/low（severity 优先，缺则 blocking→high/medium）
        "question_type": q.question_type,
        "conflict_detail": q.conflict_detail.model_dump() if q.conflict_detail else None,
        "blocking": q.blocking,
    }
    for q in open_questions
]
```

`ClarifyAnswer`（`{question_id, answer}`）契约不变 → clarify 接口与 resume 注入逻辑不动。

### 3.5 前端弹窗（`web/src/pages/Workbench/index.tsx`）

按 `question_type` 渲染（解决 F4）：

- **冲突类（`question_type === 'conflict'`）**：
  - 有 `conflict_detail`：卡片——`topic` 标题 + 两方并排（`location`/`statement`）+ AI 推荐提示条（💡 推荐 + 理由，**不预选**）+ 三选项 Radio：「以 {side_a.location} 为准」/「以 {side_b.location} 为准」/「都不对，我来定」；选「我来定」才展开 `TextArea`。`recommendation === 'neither'` 时推荐条提示「AI 倾向：两者均需修正，建议自定」，但仍不预选。
  - 无 `conflict_detail`（规则法/降级）：纯文字展示 `question` + `context`（**冲突语义**文案）+ `TextArea`，不套盲区「请补充说明」文案。
- **盲区类（`question_type === 'blind_spot'`）**：`TextArea` + 引导文案 + 示例 `placeholder`（如「请给出明确结论，例：以 ≤50 字为准」）。
- **提交**：选项 → 转答案文本（如 "以 §5.6.1 为准：必填 / ≤50字"）；自定义/盲区 → 框内容。answer 非空校验同现状；`clarifyAnswers` 改以 `q.id`（已对齐，非 undefined）为 key。
- **低覆盖触发 NO_GO**：open_questions 可能全为盲区（无冲突卡片），天然走盲区渲染，无需特判。

### 3.6 类型与接口

- 前端 `types/index.ts`：`OpenQuestion` 加 `question_type`/`conflict_detail`/`priority` 来源已对齐；新增 `ConflictDetail`/`ConflictSide` 类型。
- `ClarifyAnswer` 结构不变 → clarify 接口契约不变。
- 持久化无迁移：`open_questions`/`clarification_answers` 均存 JSONB，新增可选字段自动透传。

## 4. 验证

- **零回归**：不触发冲突的批次（GO/CONDITIONAL）行为不变；全量 `tests/` 通过。（CONDITIONAL 经 `gate_router`→test_points，不 interrupt、不 suspend，open_questions 永不到前端。）
- **后端单测**（确定性，**mock LLM 注入结构化冲突**，解决 F8）：
  - LLM `ConflictDetail` → `SourceConflict` 正确映射（章节 + 同级 trust_level + `resolution="unresolved"`）。
  - `recommendation` 不污染 `resolution`（NO_GO 仍触发）。
  - **占位/空 location → conflict_detail 降级为 None**，context 走安全文案（**正向断言** context 含真实 `'§x.x'(Level 1)`；**负向断言** 不含「未列」「未知」「(Level 3)」占位）。
  - 规则法冲突 → `question_type="conflict"` 且 `conflict_detail=None`。
- **前端组件测试**：有 `conflict_detail` → 卡片 + 选项；`question_type=conflict` 无 detail → 纯文字冲突文案；`blind_spot` → 输入框；选项选择 → 正确 answer 文本；**多问题各自独立 key 不互相覆盖**；提交 `question_id` 正确。
- **端到端（mock LLM）**：注入同文档跨章节结构化冲突 → 触发 NO_GO → 弹窗卡片 → 选项裁决提交 → 流水线恢复并继续。

## 5. 风险与缓解

- **LLM 不稳定 / 吐占位串** → schema + prompt 双约束 + 代码校验降级（占位→conflict_detail=None 走纯文字），不崩、不显示坏值。
- **字段链路改动影响透传** → 只增不删字段，单一转换点（node.py:153），改动点加测试。
- **推荐裁决误导用户** → 推荐仅提示、不预选，用户必须主动选（产品决策已定）。
- **规则法冲突被误当盲区** → `question_type` 显式判别，规则法冲突仍按冲突语义渲染。
- **范围蔓延** → 盲区类仅加引导不做选项化；不动 gate/clarify/resume 主逻辑。

## 6. 验收标准

- [ ] 同文档跨章节冲突触发时，弹窗冲突类问题以「卡片 + 两方并排 + AI 推荐（不预选）+ 三选项」呈现。
- [ ] context **正向**显示真实章节与等级（含 `'§x.x'(Level 1)`）；占位/空 location 时降级安全文案且**不含**「未列/未知/(Level 3)」。
- [ ] AI 未给结构化 / 规则法冲突时，按 `question_type` 走纯文字冲突或盲区输入框，不报错不空白、文案语义正确。
- [ ] 多问题各自独立作答互不覆盖；`question_id` 正确回传，流水线正确恢复。
- [ ] `resolution` 与 `recommendation` 解耦，NO_GO 触发不受影响。
- [ ] GO/CONDITIONAL 与无冲突批次行为不变；全量 `tests/` 通过；改动文件 ruff 干净；前端 lint 干净。
- [ ] 提交仅含本次相关文件（隔离工作树其他未提交改动）。

## 7. 评审修订记录

### v1→v2（首轮评审，依据 critic 对照真实代码）

- **F1（Major）**：`conflict_detail` 原只挂在 `OpenQuestion`，但 `_build_open_questions` 只接收 `list[SourceConflict]` → 拿不到结构化数据、卡片永空。**修**：`SourceConflict` 加可选 `conflict_detail` 承载穿透（§3.1/§3.3）。
- **F2（Major）**：`SourceConflict.resolution` 必填且 gate 靠 `=="unresolved"` 判 NO_GO；新结构化 schema 无 `resolution`，漏填会崩或致 NO_GO 不触发。**修**：`_merge_conflicts` 显式 `resolution="unresolved"`，与 `recommendation` 解耦（§3.3）。
- **F3（Major）**：根因定位错——「未列」非代码默认（默认是「未知」，且「未列」全 `src/` 不存在），实为 LLM 输出；必填 str 挡不住占位串。**修**：根因改为 LLM 占位输出，根治靠 prompt + 校验降级；验收改正向断言 + 负向占位断言（§1.1/§3.2/§3.3/§6）。
- **F4（Major）**：`conflict_detail` 有无 ≠「冲突/盲区」（规则法冲突无 detail 会被当盲区，文案错位）。**修**：加 `question_type` 显式判别，前端按其渲染（§3.1/§3.5）。
- **F5（Minor）**：`priority` 三档凑不出（仅有二值 `blocking`，`severity` 在构建时丢失）。**修**：`OpenQuestion` 透传 `severity`（§3.1/§3.4）。
- **F6（Minor）**：`model_dump()` 不会凭空加 `id/priority` 键。**修**：在 node.py:153 显式构造前端契约 dict（§3.4）。
- **F7（Minor）**：恢复是整体注入、`question_id` 不参与匹配；真 bug 是前端 `q.id`(=undefined) 作 key 致多问题互相覆盖。**修**：成功标准改「多问题独立作答不串味」（§1.3/§3.5）。
- **F8（Minor）**：同文档跨章节冲突仅 LLM 路径可检出，真 LLM 不稳定。**修**：e2e 用 mock LLM 注入（§4）。
- **F9（Minor）**：命名不一（`StructuredConflict` vs `ConflictDetail`）、`trust_level` 缺约束。**修**：统一 `ConflictDetail`（LLM 输出与 detail 复用），`ConflictSide.trust_level` 补 `ge=1,le=5`（§3.1）。

### v2→v3（复审，修正 v2 引入的问题）

- **N1（Major，v2 引入的矛盾）**：§3.2「定位不到则不上报」与 §3.3 占位降级自相矛盾——若 LLM 依指令丢弃定位不清的冲突，降级路径成死代码；且同文档冲突仅 LLM 可检出 → NO_GO 静默漏触发，打脸立项目标。**修**：§3.2 改为「定位不到仍须上报、`location` 留空，由代码降级为纯文字冲突」，使降级成为真实路径。
- **N2（Minor）**：冲突类未赋 `severity` → 恒默认 `medium`、与 high 盲区优先级倒挂、`blocking→high` 成死分支。**修**：§3.3 冲突类显式 `severity="high"`。
- **小注**：占位检测抽共享 `_is_placeholder()` 供 `_merge_conflicts` 与 `_build_open_questions` 复用；context 兜底按 `source_a/source_b` 是否占位判定，**非** `conflict_detail is None`，避免误丢规则法冲突的真实文档标题（§3.3）。
