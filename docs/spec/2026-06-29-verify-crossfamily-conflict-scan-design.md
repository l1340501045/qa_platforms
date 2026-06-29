# verify 跨族核验 + 跨条款矛盾扫描 — 设计文档

> 状态：设计（brainstorming 产出，已与用户确认）。下一步：writing-plans 出实施计划（**执行交 Claude Code，本流程不走 gpt-review-gate**）。
> 来源：批次 `0c9b63e6` 用例质量审查（`.audit/0c9b63e6-.../REPORT.md`）+ 行业最佳实践对照（`.audit/0c9b63e6-.../findings/14_行业最佳实践对照.md`）。
> 关联：本设计是「verify 核验关卡」增强（线1）；不涉及 comprehend 冲突召回（线2，并入 clarification 线另行设计）。

## 1. 背景与目标

### 1.1 现状问题（已核对代码与实测）

1. **family bias（自家评自家）**：`.env` 中 `LLM_PRIMARY_MODEL=claude-opus-4-6`，而 verify 走同一 `primary_model`（`llm_client.py:201` `model = ... self.primary_model`；`verifier.py:145` `get_llm_client().generate_structured(...)`）。generator 与 judge 同模型族，业界实证会系统性偏袒同族输出、掩盖退化（见 findings/14 §3）。审查实证：§8.2「关键行为」优化目标偏松判 grounded；多处 `rationale` 自述成立却标 conflict。
2. **cherry-picking（只引支持、忽略矛盾）**：verify 当前逐条判 `grounded/conflict/undefined/ungrounded`，只看「用例断言 vs 它引用的 PRD」，不主动检查「同字段的另一条 PRD 是否与之矛盾」。当 PRD 自相矛盾时（审查实证：标题包名称 `≤50字`(§5.6.1) vs `不限字数`(§9.2首表) vs `30字`(截图)），生成器据不同出处各自产出互斥用例，verify 逐条都判 grounded，**PRD 内部矛盾无人发现**。

### 1.2 目标

- **改①**：verify 换**非 Claude 族**模型（`deepseek-v4-pro-office`）消除 family bias。
- **改②**：verify **复用单次调用**做跨条款矛盾扫描，把「用例被某条款支持、却与另一条款实质互斥」显式标出（`cross_section_conflict` + 两处出处），并汇总成「PRD 矛盾清单」（未来直接喂线2 clarification）。
- **零回归**：`llm_verify_model` 留空 = verify 行为完全不变；②由独立灰度开关控制，可单独回滚。

### 1.3 成功标准（无 gold set，用本次审查「已知答案」回归）

- ② 能把审查已确认的 PRD 矛盾（标题包字数三套、emoji 自动剔除 vs 弹错、定向包重名 弱校验 vs 禁止保存）标为 `cross_section_conflict` 并给出两处出处。
- ① 换族后，§8.2「关键行为」等偏松项不再误判 grounded（或被②的矛盾扫描捕获）。
- `llm_verify_model` 留空、`verify_cross_section_conflict_enabled=false` 时，verify 输出与现状逐条一致（回归脚本零 diff）。

## 2. 范围

**做**：
1. `settings` 加 `llm_verify_model`、`verify_cross_section_conflict_enabled`。
2. `LLMClient.generate_structured` 加可选 `model` 参数（透传已有的 `_call(model=...)`）。
3. `verifier.verify_cases` 用 `llm_verify_model`；`rubric` 加跨条款矛盾检查指令（开关控制注入）。
4. schema：`_CaseVerdict`（verifier 内）与 `CaseVerification`（test_case.py）加 `cross_section_conflict` + `conflicting_refs`。
5. `summarize` 增加 PRD 矛盾清单与计数，进 `verify_summary`。
6. 单测 + 已知矛盾 fixture 端到端回归（并入 `tests/testcase_generator/test_verify_cross_section.py`）。

**不做（YAGNI / 归属其他线）**：
- deepseek 失败回退 claude、ensemble 双判（第一版不做，留空配置即回退 primary）。
- 不接 clarification 消解（线2）；不改 `verdict/bucket` 既有取值与语义；不改其他阶段所用模型；不改前端。

## 3. 设计

### 3.1 改① verify 跨族模型

- `settings.py`：`llm_verify_model: str = ""`（留空 → verify 用 primary，行为不变，天然灰度）。
- `llm_client.py`：`generate_structured(..., model: str | None = None)`；内部 `effective_model = model or (vision if images else primary)`；`_call` 已接收 model，仅需把 `effective_model` 传入并用于日志/重试文案。**其他阶段不传 model，零影响**。
- `verifier.py`：`verify_cases(...)` 调用处传 `model=settings.llm_verify_model or None`。
- 兜底：沿用现状（按 `LLM_MAX_RETRIES` 重试该模型 → 耗尽则该批标 `unverified` 隔离）。不新增 claude 回退。

### 3.2 改② 跨条款矛盾扫描（复用单次调用）

- **复用已检索章节**：`verify_node._build_feature_sections` 已为每个 feature 收集了「全局注入 + 跨功能点检索」的相关章节（`verifier.verify_cases` 的 `prd_sections` 即含「相关但用例未必引用」的条款）——**②不新增任何检索**。
- **rubric 指令**（受 `verify_cross_section_conflict_enabled` 控制，关则不注入、行为不变）：在判 verdict 之外，要求模型检查 `prd_sections` 内是否存在与该用例关键断言**实质互斥**的另一条款；**仅在两条 PRD 条款本身互相矛盾（同一字段/行为给出不可同时成立的规定）时报**，并给出两处 `source_ref` + 各自原文。强约束控误报：「未提及 / 更宽泛 / 不同字段」一律不算矛盾。
- **schema**：
  - `verifier._CaseVerdict` 加 `cross_section_conflict: bool = False`、`conflicting_refs: list[_ConflictRef] = []`（`_ConflictRef{ref_a, quote_a, ref_b, quote_b}`）。
  - `test_case.CaseVerification` 加同名两字段（回挂用例；经 `callbacks.py` 的 `verification` dict `model_dump()` **自动落 `test_cases.verification` JSONB，无需迁移**；导出/前端展示「PRD 矛盾清单」属后续线，不在本计划）。
  - **`verdict` 与 `bucket` 保持原判**（矛盾是 PRD 的问题，不是用例错，出口是 PM 澄清而非改用例）。
- **summarize**：`verify_summary` 增加 `cross_section_conflicts`（计数）+ `prd_conflict_list`（去重后的「ref_a×ref_b + 双方原文 + 触发用例数」清单）。

### 3.3 数据流

`verify_node`（不变，已喂 sections）→ `verify_cases`（用 deepseek + 含矛盾检查的 prompt）→ `_VerifyLLMOutput`（每条带 cross_section_conflict）→ 回挂 `CaseVerification` → `summarize` 汇总 PRD 矛盾清单 → `verify_summary`（可观测/落 stage_artifact）。

### 3.4 错误处理与兼容

- deepseek 调用失败：沿用单批隔离（标 `unverified`）。
- LLM 未返回矛盾字段：默认 `cross_section_conflict=false`、`conflicting_refs=[]`，不破坏主流程。
- 开关 `verify_cross_section_conflict_enabled=false`：不注入矛盾指令、不解析矛盾字段 → 与现状逐条一致。

## 4. 测试与验证

- **单测**（mock LLM，`asyncio_mode=auto`）：
  - 返回含 `cross_section_conflict=true` 的输出 → 验证回挂到 `CaseVerification` + `summarize` 产出 `prd_conflict_list` + verdict 不被改写。
  - `model` 参数透传：`generate_structured(model="X")` → `_call` 收到 "X"。
  - 开关关闭 → rubric 不含矛盾指令、矛盾字段不解析。
- **已知矛盾 fixture 端到端测试**（落实成功标准，确定性、并入单测）：
  - 构造本次审查确认的 3 对 PRD 矛盾（标题包字数 / emoji / 定向重名）的 `PrdSection`+`VerifyCase`，调 `verify_cases` 验证「开关开→指令注入→`cross_section_conflict` 召回」因果链 + `summarize` 出清单；开关关则召回 0。
  - **自审修正**：原"离线重跑整批 verify"不可行（需重建 pipeline `ParsedContext` 的 feature→source_refs 映射，DB 无法复原），故不做独立离线脚本。
- **可选人工验证**（不入 CI）：真实 deepseek 对 fixture 跑 smoke 确认识别能力 + JSON 稳定；对 batch `0c9b63e6` 的 §8.2 偏松用例抽样重判看跨族纠偏。

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| deepseek JSON 稳定性弱于 claude | 现有 `_loads_tolerant`/`_salvage_json` 容错 + 留空 `llm_verify_model` 可秒回退 primary |
| 矛盾误报（把"未提及"当矛盾） | rubric 强约束「实质互斥 + 必给两处原文」；②独立开关可关 |
| `conflicting_refs` 结构让 LLM 输出不稳 | 结构精简为 4 个字符串字段；缺失默认空、不阻断 |
| 工作树已有未提交改动（`llm_client.py` 等为 M） | 执行时**每次只 `git add` 本计划涉及文件，严禁 `-A/.`** |

## 6. 文件改动清单

- **Modify** `src/platform_api/core/settings.py`（+`llm_verify_model`、+`verify_cross_section_conflict_enabled`）
- **Modify** `.env`（+`LLM_VERIFY_MODEL=deepseek-v4-pro-office`；执行时由人/Claude Code 添加）
- **Modify** `src/testcase_generator/services/llm_client.py`（`generate_structured` +`model` 参数）
- **Modify** `src/testcase_generator/schemas/test_case.py`（`CaseVerification` +2 字段）
- **Modify** `src/testcase_generator/stages/verify/verifier.py`（`_CaseVerdict`+字段、传 model、解析回挂、`summarize` 加清单）
- **Modify** `src/testcase_generator/stages/verify/rubric.py`（矛盾检查指令，开关控制）
- **Create** `tests/testcase_generator/test_verify_cross_section.py`（单测 + 已知矛盾 fixture 端到端回归）
