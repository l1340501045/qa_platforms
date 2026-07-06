# 用例质量三小补丁（占位分流 + 图归位 + 边界字数自校验）— 设计文档

> 状态：设计（brainstorming 产出）。下一步：writing-plans 出实施计划（执行交 Claude Code，不走 gpt-review-gate）。
> 来源：批次 `0c9b63e6` 审查（findings/13 占位稀释、findings/10 未定位图影子重复、findings/12 边界值数错）。roadmap 落点 ⑬（占位分流）+ ⑭（图影子重复 + 边界自校验）。
> 线 C（3 线分组之一）：三个**互不依赖**的小补丁，分散在 export / parse / write_cases，打包一个 plan、内部 3 个独立 Chunk。

## 1. 背景与目标（三补丁各自独立）

### 补丁④ 占位用例分流
- 现状：`export_task._execute_export`（:83）导出时只排 `deleted`，**不按 verdict/bucket 过滤** → `undefined`/`needs_spec` 的「待 PM 澄清」占位用例混进主用例集，稀释可执行率（审查：unresolved 72%、素材中心 11 条…）。
- 目标：导出时把 `verdict=undefined`（及 `bucket=needs_spec` 占位）**从主用例集分离**到独立「需求澄清清单」（Excel 单独 sheet / markdown 单独段），主集只留可执行用例。

### 补丁⑤ 未定位图影子重复（图归位匹配修复）
- 现状：`content_injector.py` 已实现「未引用图按 section_hint 归位」，但 **section_hint 是文件名编号（20/30/90），section_line_map 是 PRD 章节号（5.2/5.3/5.9），两套编号对不上**（:67 必然 miss）→ 图全进文末「附：未定位图描述」附录 → 基于附录二次生成 97 条影子重复用例。
- 目标：修复归位匹配——编号匹配失败时用 **caption 语义关键词匹配章节标题**（如 caption 含「漫剧库」→ 匹配标题「5.2 漫剧库」），让图归到真实章节、不再堆附录。

### 补丁⑥ 边界值字数自校验
- 现状：write_cases 生成「输入 N 个字符」类边界用例时，LLM 数中文字数会错（审查：声称 21 字实为 19）→ 照此执行测不到边界。
- 目标：write_cases 后处理，对 step 中「N 字/字符」声明校验 `input_data` 实际字符数，不符则**告警 + 在 confidence_note 标注**（不自动改写，避免误伤），暴露给人工复核。

## 2. 范围
**做**：④export 按 verdict 分流 + 需求澄清清单；⑤content_injector 语义匹配兜底；⑥write_cases 字数校验告警。各带单测。

**不做（YAGNI）**：不改 verify 判定本身（只在 export 用其结果分流）；⑤不引入领域编号映射表（用语义，保持通用）；⑥不自动改写用例（只告警，避免误伤）；不动 dedup/溯源。

## 3. 设计

### 3.1 补丁④：export 占位分流
- `export_task._execute_export`：查询后把 cases 按 `verdict` 分两组——`main_cases`（verdict ∈ {grounded, None, unverified} 或 bucket=main）+ `clarification_cases`（verdict ∈ {undefined, ungrounded} 或 bucket=needs_spec）。
- `_generate_excel`：主用例集一个 sheet「测试用例」，占位另起 sheet「需求澄清清单」（列：标题/所属/verdict/rationale/PRD 依据）。`_generate_markdown` 同理分两段。
- 阈值口径用 `bucket`（main vs needs_spec/to_fix）最稳（bucket 是 verdict 的确定性映射）。
- 兼容：旧批次用例 verdict/bucket 可能为 None → 归主集（行为不变）。

### 3.2 补丁⑤：图归位语义匹配
- `content_injector.inject_captions` 第 2 步：`section_line_map` 除编号外，**同时存「标题纯文本」**（去编号/空格）。
- 未引用图归位顺序：① section_hint 编号命中 → 用；② 否则用 caption 语义匹配——从 `caption.caption_text`（或 `ui_elements`）提取候选词，在各 heading 文本里找包含关系（最长匹配），命中即归位；③ 都不中 → 附录兜底（保留）。
- 通用（不依赖领域编号映射），符合 roadmap 去领域绑定铁律。

### 3.3 补丁⑥：边界字数自校验
- 新增 `write_cases/length_check.py`：`check_step_lengths(steps) -> list[str]`（返回告警），正则匹配 step.action/input_data/expected_result 里的「(\d+)\s*(个)?(字|字符)」声明，对比同 step `input_data` 的实际可见字符数（中文按字符计），偏差 >0 记告警。
- write_cases 构造用例后，若该用例有字数告警 → 追加进 `confidence_note`（如「字数声明与输入不符：声称21实为19」）。不改 input_data。

## 4. 测试与验证
- 单测：
  - ④：mock cases（含 undefined/grounded），`_execute_export` 分流后主集不含 undefined、清单含之；excel 双 sheet。
  - ⑤：构造 content + caption（section_hint 编号对不上但 caption 含章节名），断言图被归到对应章节而非附录。
  - ⑥：`check_step_lengths`（声称20实际16→告警；相符→无告警；无声明→无告警）。
- 真实：对漫剧 PRD 重跑 parse（⑤）看「未定位图」附录是否大幅减少；导出某批次（④）看主集/清单分离。

## 5. 文件改动清单
- **Modify** `src/platform_api/tasks/export_task.py`（④分流 + 双 sheet/段）
- **Modify** `src/knowledge_base/services/image_caption/content_injector.py`（⑤语义匹配）
- **Create** `src/testcase_generator/stages/write_cases/length_check.py`；**Modify** `write_cases/node.py`（⑥接入 confidence_note）
- **Create** `tests/`：`test_export_split.py`、`test_image_relocation.py`、`test_length_check.py`
