# 阶段②a cheat sheet 领域知识层（后端闭环）Implementation Plan

> **For agentic workers (Claude Code):** 用 superpowers:executing-plans 执行。每个 Task 的 Step 用 `- [ ]` 勾选。**严格按 Chunk 0→4 顺序**，每个 Chunk 末尾「验收红线」不过不进下一个。所有新能力默认灰度关、可字节级回退。

**Goal:** 把阶段① 的实体图谱（1000 实体 / 757 关系）提炼成 **4 类 QA 可审的 cheat sheet（避坑手册）**，审核通过后注入 `write_cases` 当**硬约束**，根治 v5 的 **类A 全局/局部错套（16 P0）+ 类B 概念混淆（11 P0）+ 部分类C 留白编造**。

**范围（决策）：** 本 plan 只做 **②a 后端闭环**——存储 + 提取 + 极简审核 + 注入生成。**精致 Web 审核 UI 作 ②b 单独 plan 后补**（②a 审核先用 REST API + CLI）。

**Architecture（关键决策）:**
1. **后端闭环先行**：cheat sheet 真正影响用例质量优先；Web UI 后补。
2. **分级审核**：高价值类（易混/章节优先级/PRD状态，~100 条）标「必审」；必测清单（量大）标「可批量采纳」。审核状态 pending/approved/rejected。
3. **AI 版 + QA 版分离**（仿 `quality_flywheel` 三元组）：re-parse/re-extract 不丢 QA 裁定。
4. **新建表**（不复用 flywheel/golden_set/stage_artifacts——它们 batch 绑定/无审核态/无双版本）。cheat sheet 以 `knowledge.entities` 为 SSOT 提取，**scope = document_id（文档级，非 batch）**。
5. **注入双层**：审核通过的 cheat sheet 事实进 `write_cases` 的 `user_content`（按 feature 过滤）+ `WRITE_CASES_SYSTEM_PROMPT` 加「如何应用」铁律。`backfill_node` 复用 `generate_cases` 自动继承。
6. **只有 `review_status=approved` 的条目注入**（pending/rejected 不进 prompt）。
7. 灰度开关：`cheat_sheet_extract_enabled` / `cheat_sheet_injection_enabled`，默认关→验收后开。

**Tech Stack:** Python 3.12 · LangGraph · SQLAlchemy(async)+Alembic · Pydantic v2 · pytest · pgvector · OpenAI 兼容网关（视觉模型已配 `LLM_VISION_MODEL=claude-opus-4-6`）。

---

## 前置事实（侦察已确认，Claude Code 无需重新摸底）

### F1. 实体图谱（① 产出，cheat sheet 的原料）
- 表 `knowledge.entities`（`src/platform_api/models/knowledge.py` L83-103 / migration 018）：`id / document_id / system_id / entity_type / name / canonical_key / section_ref / description / source_quote / attributes(jsonb) / created_at`；索引 `(document_id, entity_type)`、`(system_id, canonical_key)`。
- 表 `knowledge.entity_relations`（L106-127）：`id / document_id / source_entity_id / target_entity_id / relation_type / note / source_quote / created_at`；CHECK 自引用禁止；索引 `(source_entity_id)`、`(target_entity_id)`、`(document_id, relation_type)`。
- 枚举（`src/platform_api/models/enums.py` L69-89）：`EntityType{field,section,rule,concept,ui_element,state}`；`EntityRelationType{section_priority,field_defined_in,rule_constrains,mutually_exclusive,unreachable,belongs_to,transitions_to}`。
- `EntityRepository`（`src/knowledge_base/repositories/entity_repo.py`）：`get_entities_by_document(doc_id)` / `get_relations_by_document(doc_id)` / `traverse_entities` / `find_entity_by_name` / `get_entities_by_ids`。
- **漫剧批创 live 规模**（doc `f91a9bef` / sys `26ffd7ba`）：1000 实体 / 757 关系（section_priority14 / mutually_exclusive33 / unreachable52 / transitions_to32 / field_defined_in218 / rule_constrains308 / belongs_to300）。

### F2. entity_graph_hints（① 已产出但下游零消费）
- `retrieve_entity_graph_hints`（`src/testcase_generator/stages/parse/kb_retriever.py` L49-91）：只取**一跳直接关系**、只过滤 3 类高价值（section_priority/mutually_exclusive/unreachable），输出 dict `{relation_type, source_entity, target_entity, source_name, target_name, note}`。
- 挂在 `parsed_context.entity_graph_hints`（`schemas/parsed_context.py` L75-79），**comprehend/test_points/write_cases 全链路未消费**（grep 确认）。live 99 条。
- ⚠️ hints **不含** `rule`/`rule_constrains`/`field_defined_in`/`transitions_to`，也不含 entity_id/source_quote/entity_type。**②提取必须直接全量查 entity_repo，不能只靠 hints。**

### F3. 注入点（write_cases）
- `write_cases/node.py`：`WRITE_CASES_SYSTEM_PROMPT`（L84-167，已有硬编码避坑反例 L117-151）；`generate_cases()`（L193-462）按 feature 分组、four-layer 注入 `requirement_context`（own/global_default/cross_ref）。
- **注入点**：`_process_feature()` 的 `user_content` 组装（L353-357）——现含 `{test_points, requirement_context}`，② 加 `cheat_sheet`。`full_system_prompt = WRITE_CASES_SYSTEM_PROMPT + few_shot_section`（L351）——② 在 system 加「如何用 cheat_sheet」段。
- `backfill_node`（`stages/review/backfill_node.py` L71-72）复用 `generate_cases()`，自动继承。
- 按 feature 过滤可参考 `context_utils.py` 的 `_tokenize`/`CrossFeatureIndex`（L96-157）、`rule_anchor.py` 的 token 匹配（L33-45）。

### F4. 现状无 cheat sheet 表/服务
- 全仓无 cheat_sheet 实现。不宜复用：`quality_flywheel`（绑 test_case）/ `golden_set_results`（评估报告）/ `stage_artifacts`（batch 绑定）。
- 可借鉴：`ReviewStatus` 枚举（`enums.py` L51-57）模式、飞轮「AI 版/QA 版」双字段、`rule_coverage.py` 的 LLM-as-judge（temperature=0）做审核辅助/去重。
- `section_kind=tbd/mock/future`（`section_classifier.py`，parse 侧）是 testcase_generator **运行时 parse 产物（不落 DB）**——KB 侧 cheat sheet extractor **拿不到**。故 **②a 的 prd_status 不含 section_kind**，只用实体图谱的 `unreachable`+`transitions_to`（自洽）。section_kind 标注作为独立小项后置。

---

## File Structure（创建/修改清单）

**新增**
- `alembic/versions/019_add_cheat_sheets.py`（`knowledge.cheat_sheets` + `knowledge.cheat_sheet_items`；`down_revision` 接当前 head 018，执行前 `alembic heads` 确认）
- `src/platform_api/models/knowledge.py`（+`CheatSheet` + `CheatSheetItem` 模型）
- `src/platform_api/models/enums.py`（+`CheatSheetType` + `CheatSheetReviewStatus`）
- `src/knowledge_base/schemas/cheat_sheet.py`（`CheatSheetItemSchema` 等 Pydantic）
- `src/knowledge_base/repositories/cheat_sheet_repo.py`（CRUD + 按 type/status 查 + get_approved_for_injection）
- `src/knowledge_base/services/cheat_sheet/__init__.py`
- `src/knowledge_base/services/cheat_sheet/extractor.py`（4 类提取 + 分级置信 + 溯源）
- `src/knowledge_base/services/cheat_sheet/review_service.py`（审核状态机 + 分级 + 批量采纳）
- `src/platform_api/api/v1/cheat_sheets.py`（极简 REST：list/get/edit/review/extract，②a）
- `src/platform_api/schemas/cheat_sheet.py`（API request/response）
- `src/testcase_generator/stages/write_cases/cheat_sheet_inject.py`（按 feature 过滤 + 格式化注入）
- 测试：`test_cheat_sheet_repo.py` / `test_cheat_sheet_extractor.py` / `test_cheat_sheet_review.py` / `test_cheat_sheet_inject.py` / `test_write_cases_cheat_sheet.py`

**修改**
- `src/platform_api/api/v1/__init__.py`（注册 cheat_sheets router）
- `src/testcase_generator/stages/write_cases/node.py`（`_process_feature` user_content 加 cheat_sheet + `WRITE_CASES_SYSTEM_PROMPT` 加应用铁律）
- `src/platform_api/core/settings.py`（+`cheat_sheet_extract_enabled: bool=False`、`cheat_sheet_injection_enabled: bool=False`、`cheat_sheet_extract_concurrency: int=4`）
- `src/knowledge_base/services/parse_service.py`（可选：parse 后触发提取，或纯 API 触发）

> **Migration 编号**：执行前 `uv run alembic heads` 确认 head（应为 018），新 migration `down_revision="018"`，裸数字 revision。

---

## 安全保证机制（贯穿全程）

1. **顺序即安全**：C0 建表（零风险）→ C1 提取落库（开关关=不提取）→ C2 分级审核（纯读+状态变更）→ C3 注入（开关关=write_cases 行为不变）→ C4 验收+默认开。
2. **灰度开关 = 字节级回退**：`cheat_sheet_injection_enabled` 关时 `write_cases` 的 user_content/system prompt **与接入前逐字节一致**（须单测断言）。
3. **AI 版 / QA 版分离**：re-extract 只覆盖 `ai_content`，已 approved 的 `qa_content` + 审核状态按**稳定 `dedup_key`（canonical_key 组合，非 LLM 生成的 title）**匹配继承，不丢。
4. **只注入 approved**：`get_approved_for_injection` 只返回 `review_status=approved` 条目；空集时注入 `{}`（等价于不注入）。
5. **回归红线**：C4 对漫剧批创对照 v5——类A/类B P0 应下降；用例数不应暴涨（cheat sheet 是约束非灌水源）。

---

## Chunk 0（零风险）：cheat sheet 存储表

### Task 0.1：migration 019 + 模型 + 枚举

**Files:**
- Create: `alembic/versions/019_add_cheat_sheets.py`
- Modify: `src/platform_api/models/knowledge.py`（+`CheatSheet` + `CheatSheetItem`）
- Modify: `src/platform_api/models/enums.py`（+`CheatSheetType` + `CheatSheetReviewStatus`）

- [ ] **Step 1：写迁移** —
  - `knowledge.cheat_sheets(id uuid pk, document_id uuid fk→documents CASCADE, system_id uuid, version int default 1, status varchar(20) default 'draft', source_entity_count int, source_relation_count int, extracted_at timestamptz, created_at timestamptz)`；**`UNIQUE(document_id, version)`**（防并发撞号 + 保证「取最新 version」单调）。
  - `knowledge.cheat_sheet_items(id uuid pk, sheet_id uuid fk→cheat_sheets CASCADE, sheet_type varchar(30), title varchar(500), dedup_key varchar(200) not null, ai_content jsonb not null, qa_content jsonb null, review_status varchar(20) default 'pending', review_tier varchar(10), review_comment text null, reviewed_by varchar(50) null, reviewed_at timestamptz null, source_entity_ids jsonb null, source_relation_ids jsonb null, source_section_refs jsonb null, sort_order int default 0, created_at timestamptz, updated_at timestamptz)`；索引 `(sheet_id, sheet_type)`、`(sheet_id, review_status)`、`(sheet_id, dedup_key)`。含 `downgrade`。
  - **`dedup_key`（🔴-1 核心）** = 稳定结构化合并键，**绝不用 LLM 生成的 title**，由提取器确定性算出（见 Task 1.1）：confusion_pair/section_priority 用排序后的 `源canonical_key|目标canonical_key|relation_type`；must_test 用 `rule canonical_key|target canonical_key`（同一规则约束多个对象时也不串用 QA 裁定）；prd_status 用 `status_kind|subject canonical_key`。re-extract 时按它匹配继承 QA 裁定。
- [ ] **Step 2：加枚举** — `CheatSheetType{must_test, confusion_pair, section_priority, prd_status}`；`CheatSheetReviewStatus{pending, approved, rejected}`；（`review_tier` 用字符串 `must/sample/batch`，标分级审核档位）。
- [ ] **Step 3：加模型** — `CheatSheet` + `CheatSheetItem` ORM 映射上表。
- [ ] **Step 4：跑迁移** — `uv run alembic upgrade head`；`downgrade -1 && upgrade head` 验可逆。
- [ ] **Step 5：提交** — `git commit -m "feat(db): knowledge.cheat_sheets + cheat_sheet_items（cheat sheet 存储，AI/QA 双版本+审核态）"`

### Task 0.2：cheat_sheet_repo

**Files:**
- Create: `src/knowledge_base/repositories/cheat_sheet_repo.py`
- Create: `src/knowledge_base/schemas/cheat_sheet.py`（`CheatSheetItemSchema` 等）
- Test: `tests/knowledge_base/test_cheat_sheet_repo.py`

- [ ] **Step 1：写失败测试** — `save_sheet(document_id, system_id, items)` 幂等（re-extract 新建 version，旧 approved 条目的 qa_content/review_status 保留——见 Step 3 合并策略）；`list_items(sheet_id, sheet_type?, review_status?)`；`get_approved_for_injection(document_id)` 只返回最新 version 且 `review_status=approved`，按 sheet_type 分组。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — CRUD + 查询。**version 递增**：`save_sheet` 内 `version = max(该 document 现有 version)+1`（同事务取，配合 `UNIQUE(document_id, version)`）。**re-extract 合并策略（用稳定 `dedup_key`，🔴-1 修订，绝不用 LLM title）**：新 version 写入时，对 `dedup_key` 能匹配到旧 approved 条目的，继承其 `qa_content` + `review_status=approved`（QA 裁定不丢）；匹配不到的为新 pending 条目。补一条单测：**同一 dedup_key 在 LLM title 变化时仍能继承 approved**。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): cheat_sheet_repo（幂等保 QA 裁定 + 注入查询）"`

> **Chunk 0 验收**：迁移可逆；repo 单测全绿；`get_approved_for_injection` 空库返回 `{}`（为 C3 注入兜底）。零生成逻辑改动。

---

## Chunk 1（提取）：从实体图谱提 4 类 cheat sheet

### Task 1.1：cheat sheet 提取器

**Files:**
- Create: `src/knowledge_base/services/cheat_sheet/__init__.py`
- Create: `src/knowledge_base/services/cheat_sheet/extractor.py`
- Test: `tests/knowledge_base/test_cheat_sheet_extractor.py`（mock EntityRepository）

- [ ] **Step 1：写失败测试** — mock entities+relations，断言 4 个提取方法各产出正确条目 + 分级 tier + 溯源 id：
  - `_extract_must_test`：`entity_type=rule` 实体 + `rule_constrains` 出边（rule→约束对象）+ `field_defined_in`（定位章节）→ tier=`sample`（量大）。
  - `_extract_confusion_pairs`：`mutually_exclusive` 关系 → 双实体对 + note + source_quote → tier=`must`（高价值）。
  - `_extract_section_priority`：`section_priority` 关系（局部→全局）+ `field_defined_in` 辅助 → tier=`must`。
  - `_extract_prd_status`：`unreachable` 关系 + `transitions_to`（状态机）→ tier=`must`。（**section_kind=tbd/mock/future 移出 ②a**，见 🔴-2 修订——②a 的 prd_status 只用实体图谱自洽数据。）
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — `CheatSheetExtractorService.extract(document_id) -> list[CheatSheetItem]`：
  - 用 `entity_repo.get_entities_by_document` + `get_relations_by_document` **全量查**（不用 hints，hints 不含 rule/rule_constrains）。
  - 4 个 `_extract_*` 方法按 F1 映射组装 `ai_content`（结构见下）+ **`dedup_key`（稳定键，算法见 Task 0.1）** + `source_entity_ids/source_relation_ids/source_section_refs` 溯源 + `review_tier`。
  - 每条带 `title`（QA 可读，**仅展示、不参与合并匹配**）。全部 `review_status=pending`。
  - `ai_content` 结构：must_test`{rule_text,category,applies_to,section_ref,source_quote,test_hint}` / confusion_pair`{item_a,item_b,distinction,source_quote}` / section_priority`{local_section,global_section,applies_when,resolution}` / prd_status`{status_kind,subject,context,annotation,source_quote}`。
  - **prd_status 只用实体图谱自洽数据（🔴-2 修订）**：`unreachable`（status_kind=unreachable）+ `transitions_to`（status_kind=state_transition）。**`section_kind=tbd/mock/future` 不在 ②a 范围**——它是 testcase_generator parse 运行时产物（`section_classifier`，不落 DB），KB 侧 extractor 拿不到；强行跨模块取数得不偿失，作为独立小项后置（见风险）。
  - **格式自检（🟡补充）**：每类组装后做结构自检（必填字段非空、canonical_key 可解析、dedup_key 唯一），不合格条目记 warn 跳过，避免脏条目落库（呼应 live 发现的 section_priority formatter 问题）。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): cheat sheet 提取器（4 类 + 分级 tier + 溯源）"`

### Task 1.2：提取落库 + 触发入口（开关 cheat_sheet_extract_enabled）

**Files:**
- Modify: `src/knowledge_base/services/cheat_sheet/extractor.py`（落库编排）
- Modify: `src/platform_api/core/settings.py`（+`cheat_sheet_extract_enabled: bool=False`、`cheat_sheet_extract_concurrency`）
- Create: `src/platform_api/api/v1/cheat_sheets.py`（**首次创建**，含 `POST /documents/{id}/cheat-sheets/extract` 触发，202；Task 2.2 再 Modify 补 list/review）
- Test: `tests/knowledge_base/test_cheat_sheet_extractor.py`（落库幂等用例）

- [ ] **Step 1：写失败测试** — extract→save_sheet 落库；重复 extract 新建 version 且保留旧 approved（复用 repo 合并策略）；`cheat_sheet_extract_enabled=False` 时 extract API 返回 disabled 提示不跑。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — extract 编排（查图谱→4 提取→save_sheet）+ 极简触发 API（手动对某文档触发提取）。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): cheat sheet 提取落库 + 触发 API（灰度 cheat_sheet_extract_enabled）"`

### Task 1.3：漫剧批创提取验收

- [ ] **Step 1：开 `cheat_sheet_extract_enabled`，对漫剧批创（doc f91a9bef）触发提取**。
- [ ] **Step 2：统计** — 各 sheet_type 条目数（预期：confusion_pair~33 / section_priority~14 / prd_status~50+ / must_test 数百）。
- [ ] **Step 3：人工抽查** — 每类抽 5-10 条看 ai_content 质量 + 溯源正确。记入基线表。

> **Chunk 1 验收**：4 类 cheat sheet 提取落库；高价值 3 类（confusion/priority/prd_status）条目准确率 ≥80%（抽查）；全部 pending。开关关时不提取。

---

## Chunk 2（分级审核）：审核状态机 + 极简审核入口

**目的**：QA 能审核/编辑 cheat sheet（分级：高价值必审 + 必测清单抽样/批量采纳）。②a 用 REST API + CLI；精致 Web UI 留 ②b。

### Task 2.1：审核 service（状态机 + 分级 + 批量采纳）

**Files:**
- Create: `src/knowledge_base/services/cheat_sheet/review_service.py`
- Test: `tests/knowledge_base/test_cheat_sheet_review.py`

- [ ] **Step 1：写失败测试** —
  - `approve(item_id, by)` / `reject(item_id, comment, by)` → 改 `review_status` + `reviewed_by/at`。
  - `edit(item_id, qa_content)` → 写 `qa_content`（不动 ai_content），状态保持/转 pending。
  - `batch_approve(sheet_id, sheet_type='must_test', tier='batch')` → 批量把某类/某档全部 pending 置 approved（必测清单批量采纳）。
  - `list_pending_must_review(sheet_id)` → 返回 `review_tier='must'` 的待审条目（QA 优先审这些）。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — review_service 各方法；**注入取数口径**：`get_approved_for_injection` 优先用 `qa_content`（QA 改过的），无则用 `ai_content`。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(kb): cheat sheet 分级审核 service（必审/批量采纳 + AI/QA 版取数）"`

### Task 2.2：极简审核 REST API（②a，非精致 UI）

**Files:**
- Modify: `src/platform_api/api/v1/cheat_sheets.py`（list/get/edit/review/batch-approve）
- Create: `src/platform_api/schemas/cheat_sheet.py`（request/response，对齐 `success()`/`ApiError` 约定）
- Modify: `src/platform_api/api/v1/__init__.py`（注册 router）
- Test: `tests/platform_api/test_cheat_sheets_api.py`（标 `requires_db`——复用 ① 修复D（commit `5452085`）给 platform_api 集成测试建立的 `requires_db` 机制，确认 conftest 位置后沿用，勿重造）

- [ ] **Step 1：写失败测试** — `GET /documents/{id}/cheat-sheets`（分页+type/status 筛选）；`PATCH /cheat-sheets/{id}`（编辑）；`PATCH /cheat-sheets/{id}/review`（approve/reject）；`POST /documents/{id}/cheat-sheets/batch-approve`（必测清单批量）。字段名 review 用 `status`（**避免 v5 那种前后端 action/status 不一致**）。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — router→review_service→repo 分层；遵循 `success()`/`paginated_response()`/`ApiError`。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(api): cheat sheet 极简审核 REST（list/edit/review/batch-approve）"`

### Task 2.3：漫剧批创审核演练

- [ ] **Step 1：对漫剧批创提取的 cheat sheet，按分级审核** — 高价值 3 类（~100 条）逐条 approve/reject/edit；must_test 抽样审 + `batch-approve` 批量采纳。
- [ ] **Step 2：统计** — approved 各类条数；记入基线表（供 C3 注入用）。

> **Chunk 2 验收**：审核 API 可用；分级审核走通（高价值必审 + 必测清单批量）；`get_approved_for_injection(漫剧doc)` 返回非空、按 type 分组。

---

## Chunk 3（核心）：注入 write_cases（把审核通过的 cheat sheet 钉进生成）

**目的**：审核通过的 cheat sheet 注入 `write_cases`——`user_content` 给事实（按 feature 过滤）+ system prompt 给应用铁律。开关 `cheat_sheet_injection_enabled` 默认关。

### Task 3.1：按 feature 过滤 + 格式化注入

**Files:**
- Create: `src/testcase_generator/stages/write_cases/cheat_sheet_inject.py`
- Test: `tests/testcase_generator/test_cheat_sheet_inject.py`

- [ ] **Step 1：写失败测试** — `filter_cheat_sheet_for_feature(feature, approved_by_type) -> dict`：用 `feature.name/description/source_refs` 与条目的章节号/实体名/canonical_key token 匹配，返回该 feature 相关的 cheat sheet（按 type 分组）；全局型条目（如 IAP↔IAA）按规则 fallback（注入相关 feature）。格式化成简洁 prompt 片段。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** — 复用 `context_utils._tokenize` / `rule_anchor` token 匹配；输出结构紧凑（避免 prompt 过长）。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(write-cases): cheat sheet 按 feature 过滤注入器"`

### Task 3.2：接入 generate_cases + system prompt 铁律（开关控制）

**Files:**
- Modify: `src/testcase_generator/stages/write_cases/node.py`（`_process_feature` user_content + `WRITE_CASES_SYSTEM_PROMPT`）
- Modify: `src/platform_api/core/settings.py`（+`cheat_sheet_injection_enabled: bool=False`）
- Test: `tests/testcase_generator/test_write_cases_cheat_sheet.py`

- [ ] **Step 1：写失败测试** —
  - 开关开：`generate_cases` 的 `user_content` 含 `cheat_sheet` 字段（该 feature 过滤后的 approved 条目）；`full_system_prompt` 含「如何应用 cheat sheet」段。
  - 开关关：user_content / system prompt **与接入前逐字节一致**（回归红线）。
  - 注入数据来自 `get_approved_for_injection`（只 approved）；空集时 `cheat_sheet={}`、行为等价不注入。
- [ ] **Step 2：跑测试确认失败**
- [ ] **Step 3：实现** —
  - **document_id 取数（🟡-4）**：`document_id` 在 `PipelineState`（initial_state 贯穿全程）。`write_cases_node` 从 `state["document_id"]` 取并传入 `generate_cases(...)`（现签名无此参，**需加形参**）；`generate_cases` 入口按 document 拉 `get_approved_for_injection(document_id)`（一次，feature 间复用）；`_process_feature` 调 `filter_cheat_sheet_for_feature` 注入 user_content。
  - `WRITE_CASES_SYSTEM_PROMPT` 末尾加铁律段（开关开时拼接）：① 易混对照——列出的概念**必须区分**、绝不混写；② 章节优先级——局部章节规则**压过**全局默认；③ PRD 状态——标 unreachable/待确认的**只出"待确认"占位，绝不编造确定 oracle**。
  - `backfill_node` 复用 `generate_cases` 自动继承（**注意 backfill 调用处也要把 document_id 传进去**）。
- [ ] **Step 4：跑测试确认通过**
- [ ] **Step 5：提交** — `git commit -m "feat(write-cases): 注入审核通过的 cheat sheet（user_content 事实 + system 铁律，灰度）"`

> **Chunk 3 验收**：开关开时 cheat sheet 进 write_cases prompt；开关关时 write_cases 产物与接入前逐字节一致（单测断言）。`backfill` 自动继承。

---

## Chunk 4（端到端验收）：漫剧批创对照 v5 P0 + 开关默认开

### Task 4.1：端到端 live 验收

- [ ] **Step 1：全开关**（`cheat_sheet_extract_enabled` + `cheat_sheet_injection_enabled` + ① 三开关），对漫剧批创：提取 cheat sheet → 分级审核（已在 C2 做）→ 跑完整生成流水线（新批次）。
- [ ] **Step 2：对照 v5 P0 做 case 级判定（🟡-6 量化，不做泛化「抽样审计」）** — 针对 v5 **具体 P0 锚点**逐条检查新批次对应 feature 的用例是否还出现同样错误断言：
  - 类A（目标 **16→≤5**）：W06 §5.0.3 错套定向包名 / W10 §5.0.4 回滚 / W12 6档错套 / W15 emoji 剔除——查对应 feature 用例是否还按全局规则误断言。
  - 类B（目标 **11→≤3**）：W11 监测链接↔投放链接是否仍混写 / W16 关键行为是否仍被当存在的投放方式。
  - 类C（参考）：W08 §5.4.5 文案误套 / W02 §5.8.2 未定义拒绝行为——查是否仍编造确定 oracle（应出"待确认"占位）。
  - 判定方法：对上述锚点 feature 的新用例**人工逐条核**（约 20-30 条 case），记录"仍错/已纠正"，算消除率。
- [ ] **Step 3：对照"用例数不暴涨"** — cheat sheet 是约束非灌水源，用例数应 **≤ v5 的 1.2 倍**（不应翻倍）。
- [ ] **Step 4：填基线表「②后」列**。

### Task 4.2：开关默认开

- [ ] **Step 1：`settings.py` `cheat_sheet_extract_enabled` + `cheat_sheet_injection_enabled` 默认 True**。
- [ ] **Step 2：全量单测** — `uv run pytest tests/ -q` 全绿（环境依赖测试 skip 标注）；`ruff check` 无错。
- [ ] **Step 3：提交** — `git commit -m "feat(stage2a): cheat sheet 后端闭环默认启用 + 端到端验收"`

> **②a 最终验收红线**：① cheat sheet 4 类提取+分级审核+注入闭环跑通；② 漫剧批创对照 v5 锚点 case 级判定——**类A 16→≤5、类B 11→≤3**（量化）；③ 用例数 ≤ v5 的 1.2 倍（不暴涨）；④ 全量单测绿。任一不满足不算 ②a 完成。

---

## 风险与取舍（诚实记录）

- **提取依赖实体图谱质量**：① 抽查 ~78%，cheat sheet 提取会继承图谱噪声 → 分级审核（高价值必审）+ QA 编辑是质量闸；rejected 条目不注入。
- **必测清单量大**：rule_constrains 308 条 → must_test 可能数百条。分级审核（批量采纳）+ 注入时按 feature 过滤（不是全塞）控制 prompt 长度。
- **prompt 膨胀**：cheat sheet + 现有 requirement_context 可能让 write_cases user_content 过长 → 按 feature 过滤 + 条目格式化精简；必要时限每 feature 注入条数上限。
- **section_kind 移出 ②a（🔴-2 定案）**：tbd/mock/future 来自 testcase_generator parse 的 `section_classifier`（运行时产物、不落 DB），KB 侧 extractor 跨模块拿不到 → ②a 的 prd_status 明确只用实体图谱 `unreachable`+`transitions_to`；section_kind 标注作为独立小项（需先把 section_kind 持久化或在 ②b/③ 处理），不在本 plan 范围。
- **与现有硬编码反例的关系**：`WRITE_CASES_SYSTEM_PROMPT` L117-151 现有硬编码避坑反例（emoji/投放方式等）→ ② 的 cheat sheet 是**动态数据驱动版**；二者先并存（cheat sheet 补充而非替换），待 ② 稳定后评估是否下线硬编码部分。
- **②b（Web 审核 UI）单独**：本 plan 用 REST API + CLI 审核；精致 UI（CheatSheetReviewPage 复用 Workbench+Systems）作 `docs/plans/2026-06-18-stage2b-cheat-sheet-ui.md` 后补。

---

## 基线表（Chunk 1/2 提取审核 + Chunk 4 回填）

| 指标 | v5 基线 | ②a 后（实测回填） | 红线 |
|---|---|---|---|
| cheat sheet 提取条数（4 类） | — | v4 实测（dedup_key 去重后）：confusion_pair 21 / section_priority 13 / prd_status 66 / must_test 295（source：1000 实体 / 957 关系） | 4 类落库 |
| 高价值类提取准确率（抽查） | — | 抽查 high-value 约 30 条，可审准确率约 90%；发现 section_priority「同一口径」formatter 问题并已修复，复查通过 | ≥80% |
| approved 条目数（分级审核后） | — | 抽样审核演练：confusion_pair 5 / section_priority 5 / prd_status 5 / must_test 5；另 rejected 1；`get_approved_for_injection` 四类非空 | — |
| 类A 全局/局部错套 P0 | 16 | （待填，目标 ≤5） | ≤5 |
| 类B 概念混淆 P0 | 11 | （待填，目标 ≤3） | ≤3 |
| 用例数 | v5≈2176 | （待填，目标 ≤v5×1.2） | ≤2611 |
| 全量单测 | — | 全绿 | 必须绿 |

> **②a 完成标志**：上表「②a 后」列达红线 + 两开关默认开 + 单测绿。达标后 → 写 ②b（Web 审核 UI）+ 进 ③（PRD 迭代）。
