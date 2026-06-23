# 切分通用化 · LLM 大纲分段 — 设计文档

> 状态：设计待评审（brainstorming 产出）。下一步：评审 → writing-plans 出实施计划。
> 关联：`progress.md:149`「splitter 通用化」backlog；roadmap 通用性铁律；落点⑧（去领域绑定，同一「LLM 替代死规则」思路）。

## 1. 背景与目标

`_extract_sections` / `_choose_feature_level`（`src/testcase_generator/stages/parse/node.py`）当前**硬性以二级标题 `##` 作为功能点粒度**。对「功能点嵌套在 `## 功能方案` 下的 `###/####`」这类 PRD（实测：自签书、书库管理）会切坏——真功能全折进一个 blob，`## 流程图/原型图/版本信息` 反被当成功能点。

**实测证据**（批次 f41a5ffd，自签书 PRD）：切出 7 个功能点，仅 F-006「6.3 功能方案」一个拿到全部 15 测试点（真功能糊成一团），其余 6 个是元信息/图示伪功能点（0 测试点）。理解覆盖度 0.43、用例分不清功能边界。

**目标**：功能点切分**不再死认某一级标题**，任意结构（功能在 `##`/`###`/`####`）都能正确切；**规整 PRD（漫剧）零回归**。

**成功标准**：
- 开关开：嵌套 PRD（自签书）从「1 blob + 6 伪功能」切成「按真功能（书籍状态/基础信息/作家管理…）正确分功能点」。
- 开关关 / LLM 失败：行为与现状逐字节一致（规则兜底）。
- 规整 PRD（漫剧，`##` 即功能点）：开关开后切分 ≈ 现状（零回归）。

## 2. 范围

**做**：用 LLM 对「标题大纲树」判定功能点边界，替代 `_choose_feature_level` 的死规则；确定性折叠不变。
**不做**：不改下游（test_points/write_cases/verify 等消费功能点的方式不变）；不改向量分块（那是落点④）；不喂全文给 LLM（只喂大纲）。

## 3. 设计（hybrid LLM-over-outline，即 "LLM-regex" 形态）

### 3.1 流程

1. `_extract_sections` 照常用正则把 content 切成 `(level, heading, body)` 三元组（确定性，不变）。
2. **开关开** `settings.feature_seg_llm_enabled`：调 `decide_feature_roots(triples)`（LLM）得到「哪些标题是功能点根」的集合。
3. 折叠执行（复用现有逻辑）：标题是功能点根 → 新功能点边界；其后更深/非根标题 → 折叠进当前功能点；判为 meta/背景/图示的标题及其子树 → 丢弃。
4. **开关关**：`feature_roots=None` → 走现有 `_choose_feature_level` + `_is_meta_heading`（逐字节不变）。

### 3.2 LLM 段（新建 `parse/feature_segmenter.py`）

- **输入**（便宜，只喂大纲、不喂全文）：文档标题 + 大纲列表，每项 `{idx, level, heading, body_chars, body_preview(120字)}`。
- **判定**：对每个标题给一个角色——
  - `feature_root`：一个**可独立测试的业务功能**（LLM 自适应粒度，不固定层级）。
  - `container`：包裹层（如"功能详细说明/功能方案/需求详述"），本身不是功能点，但其子节里找功能点根。
  - `meta`：版本/变更/目录/名词解释/背景/需求范围模板等非功能。
  - `background`：流程图/原型图/示意等。
- **输出 schema**：`{classifications: [{idx, role}]}`，`temperature=0`。
- 返回 `feature_root` 的 idx 集合给调用方。
- **兜底（绝不阻断）**：LLM 异常/空/全非 root → 返回空 → 调用方回退 `_choose_feature_level`。

### 3.3 集成（`parse/node.py`）

- `_extract_sections(result, doc_type, feature_roots: set[int] | None = None)`：新增可选参数。`None` → 现有 `_choose_feature_level` 逻辑；非 None → 用 LLM 根集判定功能点边界 + 用 LLM 角色判断丢弃 meta/background。
- `parse_node`（async）：开关开时，先对每个 source 的 content 跑 `await decide_feature_roots(...)`，把结果传给 `_extract_sections`。
- 误判保护：LLM「拿不准」时倾向判 `feature_root`（宁可多切、不可把真功能丢成 meta）——与现有 classify「拿不准判 spec」一致的从宽原则。

### 3.4 灰度开关

`settings.feature_seg_llm_enabled: bool = False`（默认关，行为不变；env `FEATURE_SEG_LLM_ENABLED` 覆盖）。

## 4. 验证

- **零回归（硬约束）**：漫剧 PRD（规整 `##`）开关开 vs 关，切出的功能点集合一致或等价（功能点数 + 各 heading 对得上）。
- **通用性**：自签书 / 书库 PRD 开关开 → 功能点从「1 blob + N 伪」变为「按真功能正确切」（人工核对功能点清单合理）。
- **兜底**：mock LLM 抛异常 → 回退规则、parse 不崩。
- **对照探针**：复用 `check_features` 思路，dump 开/关两档的功能点清单 before/after。

## 5. 风险与缓解

- **非确定性**：LLM 判断 → 同 PRD 重跑功能点划分可能微变。缓解：`temperature=0` + 灰度 + 规则兜底；规整 PRD 有零回归测试守。
- **LLM 漏判**（把真功能当 meta 丢）：从宽原则（拿不准判 feature_root）+ 零回归测试 + 人工核对清单。
- **延迟/成本**：每文档多一次 LLM 调用（仅大纲、小）。可接受（PRD 高价值低频，解析期一次）。

## 6. 验收标准

- [ ] `settings.feature_seg_llm_enabled` 默认关；关闭时 `_extract_sections` 行为逐字节不变。
- [ ] `parse/feature_segmenter.py`：LLM 大纲判定 + 失败兜底（不抛）。
- [ ] 开关开：自签书 PRD 功能点按真功能切分（不再 1 blob + 6 伪）。
- [ ] 漫剧 PRD 开关开零回归（功能点 ≈ 现状）。
- [ ] 相关文件 ruff 干净；新增/改动有探针或测试佐证。
